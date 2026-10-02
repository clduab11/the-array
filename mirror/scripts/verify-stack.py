#!/usr/bin/env python3
"""
verify-stack.py — end-to-end health gate for the praxen stack. Run BEFORE and AFTER any
image bump, config bump, or compose recreate. Exit 1 on any FAIL.

WHY THIS EXISTS (2026-09-09 currency sweep): every prior op re-derived the same probe set
by hand (readiness, routable count, a chain 200, an allowlist 403, embedder dims,
6/6 prometheus targets, provisioned dashboards/datasources, searxng json). Hand-derived
gates drift and get skipped under time pressure; a script does not. Reads secrets from
.env / .virtual-keys.env and NEVER prints them.

USAGE
  python scripts/verify-stack.py            # full gate
  python scripts/verify-stack.py --no-llm   # skip the paid chat probe (keeps the free gates)
  python scripts/verify-stack.py --no-local # skip the Unsloth G-SEC probe (it loads a small model in Unsloth)
  python scripts/verify-stack.py --no-routes # skip the name-resolution sweep (about 240 near-free calls, 1-3 minutes)
"""
import argparse, json, re, subprocess, sys, time, urllib.error, urllib.request
from base64 import b64encode
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LITELLM = "http://localhost:4000"
GRAFANA = "http://localhost:3200"
SEARXNG = "http://localhost:8080"
PROM_UID, TEMPO_UID, LOKI_UID, PG_UID = "afimxbo42ap6oe", "dfipt8nyznn5sc", "praxen-loki", "praxen-litellm-pg"

def env(path, key):
    for line in (ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None

def http(url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {}, data=data, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()

def jbody(b):
    try:
        return json.loads(b)
    except Exception:  # noqa: BLE001
        return None

results = []
def gate(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<34} {detail}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="skip the paid chat probe")
    ap.add_argument("--no-local", action="store_true", help="skip the Unsloth G-SEC probe (loads a small model in Unsloth)")
    ap.add_argument("--no-routes", action="store_true", help="skip the name-resolution sweep (scripts/route-resolve.py)")
    a = ap.parse_args()

    master = env(".env", "LITELLM_MASTER_KEY")
    gpw = env(".env", "GRAFANA_ADMIN_PASSWORD")
    go_key = env(".virtual-keys.env", "VKEY_MSTY_GO_WINPC") if (ROOT / ".virtual-keys.env").exists() else None
    H = {"Authorization": f"Bearer {master}", "Content-Type": "application/json"}
    G = {"Authorization": "Basic " + b64encode(f"admin:{gpw}".encode()).decode()}

    print("\nPRAXEN stack gate\n")

    # 1. containers
    out = subprocess.run(["docker", "ps", "-a", "--filter", "name=praxen", "--format", "{{.Names}}|{{.State}}|{{.Status}}"],
                         capture_output=True, text=True).stdout.strip().splitlines()
    bad = [l for l in out if "|running|" not in l or "unhealthy" in l]
    gate("containers running/healthy", bool(out) and not bad, f"{len(out)} praxen-* containers" + (f"; BAD: {bad}" if bad else ""))

    # 2. litellm readiness
    s, b = http(f"{LITELLM}/health/readiness")
    d = jbody(b) or {}
    gate("litellm readiness", s == 200 and d.get("status") == "healthy" and d.get("db") == "connected", f"status={d.get('status')} db={d.get('db')}")

    # 2b. price map: v1.100.1 downloads LiteLLM main's cost map at boot and v4.16.1 prices most routes from it (injected
    # overrides removed so vendor changes flow through). A failed download falls back to the bundled map, where the
    # newest models are ABSENT and meter $0 - so a "local" source is a FAIL. Cure: POST /reload/model_cost_map.
    s, b = http(f"{LITELLM}/model/cost_map/source", H)
    cm = jbody(b) or {}
    s2, b2 = http(f"{LITELLM}/schedule/model_cost_map_reload/status", H)
    rl = jbody(b2) or {}
    gate("cost map remote + daily reload", s == 200 and cm.get("source") == "remote" and bool(rl.get("scheduled")),
         f"source={cm.get('source')} models={cm.get('model_count')} reload_every_h={rl.get('interval_hours')}")

    # 3. routable catalog + every local-*/imac-* registered
    s, b = http(f"{LITELLM}/v1/models", H)
    ids = {m["id"] for m in (jbody(b) or {}).get("data", [])}
    yaml_locals = sorted(set(re.findall(r"^\s*-\s*model_name:\s*((?:local|imac)-[\w.\-]+)", (ROOT / "litellm_config.yaml").read_text(encoding="utf-8"), re.M)))
    missing = [m for m in yaml_locals if m not in ids]
    gate("catalog routable", s == 200 and len(ids) >= 500, f"{len(ids)} routable (count is upstream-driven, never a fixed target)")
    gate("local/imac routes registered", not missing, f"{len(yaml_locals)} in YAML" + (f"; MISSING {missing}" if missing else ""))

    # 3a. Every model_name and alias resolves to a live deployment (config v4.22.0, the operator 2026-10-02). /v1/models above lists
    #     a name even when the router no longer holds it: the proxy's model-sync job drops every entry whose params changed in
    #     the mounted YAML until a restart (2026-10-01: 76 Venice routes for 13 minutes while the catalog still listed them).
    #     scripts/route-resolve.py sends each name an empty message list, so the sweep costs next to nothing.
    if a.no_routes:
        gate("every name resolves (route-resolve)", True, "SKIPPED (--no-routes)")
    else:
        t = time.time()
        rr = subprocess.run([sys.executable, str(ROOT / "scripts" / "route-resolve.py")], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        tail = (rr.stdout.strip().splitlines() or ["no output"])[-1].strip()
        gate("every name resolves (route-resolve)", rr.returncode == 0, f"{tail[:150]} in {time.time()-t:.0f}s")

    # 3b. OP UNSLOTH CHARLIE (config v4.19.0): G-SEC. A server-side-tool bait sent THROUGH the proxy to the Unsloth probe
    #     route must not make Unsloth run a tool: litellm/unsloth_guard.py strips enable_tools & co. per deployment. Proof is
    #     the absence of any new execute_tool line in Unsloth's tauri.log (ALPHA p12 saw two before the guard existed).
    tlog = Path.home() / ".unsloth" / "studio" / "tauri.log"
    if a.no_local:
        gate("unsloth G-SEC (no server tool ran)", True, "SKIPPED (--no-local)")
    elif not tlog.exists():
        gate("unsloth G-SEC (no server tool ran)", False, f"{tlog} not found")
    else:
        start = tlog.stat().st_size
        bait = {"enable_tools": True, "enabled_tools": ["python"], "run_tools_locally": True, "bypass_permissions": True}
        body = json.dumps({"model": "gsec-unsloth-probe", "temperature": 0, "max_tokens": 200, **bait, "extra_body": dict(bait),
                           "messages": [{"role": "user", "content": f"Use your python tool to run print('GATE-TOOL-MARK', {int(time.time())}) and report its output."}]}).encode()
        t = time.time(); s, b = http(f"{LITELLM}/v1/chat/completions", H, body, timeout=600)
        time.sleep(2)
        with tlog.open("rb") as fh:
            fh.seek(start)
            ran = [l for l in fh.read().decode("utf-8", "replace").splitlines() if "execute_tool" in l]
        gate("unsloth G-SEC (no server tool ran)", s == 200 and not ran, f"HTTP {s} in {time.time()-t:.1f}s execute_tool lines={len(ran)}")

    # 4. chain 200 (fast alias -> cloud primary; ~$0.0001)
    if not a.no_llm:
        nonce = int(time.time())
        body = json.dumps({"model": "fast", "max_tokens": 8, "messages": [{"role": "user", "content": f"Reply with the word OK. nonce={nonce}"}]}).encode()
        t = time.time(); s, b = http(f"{LITELLM}/v1/chat/completions", H, body, timeout=120)
        d = jbody(b) or {}
        gate("chain probe (fast) 200", s == 200 and bool(d.get("choices")), f"HTTP {s} in {time.time()-t:.1f}s served_by={d.get('model')}")
    else:
        gate("chain probe (fast) 200", True, "SKIPPED (--no-llm)")

    # 5. allowlist enforcement (Go key must be refused a frontier model)
    if go_key:
        body = json.dumps({"model": "claude-opus-4-8", "max_tokens": 1, "messages": [{"role": "user", "content": "x"}]}).encode()
        s, b = http(f"{LITELLM}/v1/chat/completions", {"Authorization": f"Bearer {go_key}", "Content-Type": "application/json"}, body, timeout=30)
        gate("allowlist 403 (front-go-winpc)", s in (401, 403), f"HTTP {s}")
    else:
        gate("allowlist 403 (front-go-winpc)", False, ".virtual-keys.env / VKEY_MSTY_GO_WINPC not found")

    # 6. embedder dimension (verify by DIMENSION, never by echoed name)
    body = json.dumps({"model": "legacy/embed", "input": "dimension probe"}).encode()
    t = time.time(); s, b = http(f"{LITELLM}/v1/embeddings", H, body, timeout=120)
    d = jbody(b) or {}
    dims = len((d.get("data") or [{}])[0].get("embedding", []))
    gate("embed legacy/embed = 1024 dims", s == 200 and dims == 1024, f"HTTP {s} dims={dims} in {time.time()-t:.1f}s")

    # 6b. TypeSafe Jev pass-through (config v4.14.0): the generic /typesafe route forwards to api.typesafe.ai with the
    #     proxy's TYPESAFE_API_KEY injected; a jev-* name proves key + route + upstream in one probe.
    t = time.time(); s, b = http(f"{LITELLM}/typesafe/v1/models", H, timeout=30)
    names = [m.get("name") or m.get("id") for m in ((jbody(b) or {}).get("models") or (jbody(b) or {}).get("data") or [])]
    gate("typesafe pass-through (/typesafe/v1/models)", s == 200 and any(str(n).startswith("jev") for n in names), f"HTTP {s} models={names} in {time.time()-t:.1f}s")

    # 6c. Jev v2 (config v4.15.0, OP JEV pt2): the classifier plugin must be registered on EVERY complexity router (the two local
    #     routers joined at v4.15.0), and the array/* + go/* namespaces must list. /v1/model/info exposes each deployment's
    #     litellm_params, so this is a config-truth probe with no LLM call.
    t = time.time(); s, b = http(f"{LITELLM}/v1/model/info", H, timeout=180)
    infos = (jbody(b) or {}).get("data") or []
    routers = {m.get("model_name"): ((m.get("litellm_params") or {}).get("complexity_router_config") or {}) for m in infos
               if str((m.get("litellm_params") or {}).get("model", "")).startswith("auto_router/complexity_router")}
    # /v1/model/info serialises the resolved plugin OBJECT as {} (probed 2026-09-18), so the plugin NAME is read from the
    # YAML on disk (config truth) and the live endpoint proves classifier_type/fallback + that the router is registered.
    ytxt = (ROOT / "litellm_config.yaml").read_text(encoding="utf-8", errors="replace")
    yaml_routers = {}
    blocks = re.split(r"(?m)^  - model_name: ", ytxt)[1:]
    for blk in blocks:
        name = blk.split("\n", 1)[0].split("#", 1)[0].strip().strip('"')
        body = blk.split("\n", 1)[1] if "\n" in blk else ""
        if "auto_router/complexity_router" in body:
            yaml_routers[name] = "jev_gate.classifier_instance" in body
    not_jev = sorted(n for n, c in routers.items()
                     if c.get("classifier_type") != "custom" or c.get("classifier_fallback") != "heuristic" or not yaml_routers.get(n, False))
    not_jev += sorted(n for n, ok in yaml_routers.items() if n not in routers)  # in YAML but not registered live
    gate("jev classifier on every router", s == 200 and bool(routers) and not not_jev,
         f"{len(routers)} routers in {time.time()-t:.1f}s" + (f"; NOT JEV: {not_jev}" if not_jev else f": {sorted(routers)}"))
    need = {"array/auto", "array/fast", "array/reasoning", "go/fast", "array/auto-local", "go/local"}
    missing_ns = sorted(need - set(ids))
    gate("array/* + go/* namespaces listed", not missing_ns, f"missing={missing_ns}" if missing_ns else "array/auto · array/fast · array/reasoning · go/fast · array/auto-local · go/local")

    # 6d. Jev decides the tier and the tier map holds (config v4.22.0, the operator 2026-10-02: put the Jev classifier to work in the
    #     routing check). One exemplar per tier goes through array/auto. The assertion is CONSISTENCY, never Jev's taste:
    #     whichever tier Jev's own counter (praxen_jev_classifier_tier_total) records for the call, the deployment that
    #     answered (x-litellm-model-name) must be that tier's model in the RUNNING router, and the decision must be Jev's:
    #     "declined" means Jev was unreachable and LiteLLM's heuristic is routing. --no-local skips the SIMPLE exemplar,
    #     which lands on a local model.
    if a.no_llm:
        gate("jev routes each tier (array/auto)", True, "SKIPPED (--no-llm)")
    else:
        tier_map = (routers.get("array/auto") or {}).get("tiers") or {}
        upstream = {m.get("model_name"): (m.get("litellm_params") or {}).get("model") for m in infos}

        def jev_counts():
            _, raw = http(f"{LITELLM}/metrics/", timeout=30)
            tiers, decisions = {}, {}
            for line in raw.decode("utf-8", "replace").splitlines():
                m = re.match(r"praxen_jev_classifier_(tier|decision)_total\{([^}]*)\}\s+([0-9.eE+-]+)", line)
                if m and 'router="array/auto"' in m.group(2):
                    key = re.search(r'(?:tier|decision)="([^"]+)"', m.group(2)).group(1)
                    (tiers if m.group(1) == "tier" else decisions)[key] = float(m.group(3))
            return tiers, decisions

        exemplars = [("SIMPLE", "What is the capital of France?"),
                     ("MEDIUM", "Rewrite this sentence in a friendlier tone: Your request was denied."),
                     ("COMPLEX", "Design a zero-downtime migration plan for a 4 TB Postgres cluster with three read replicas: cutover, rollback and validation."),
                     ("REASONING", "Prove that the square root of 2 is irrational.")]
        notes, bad = [], []
        t = time.time()
        for want, text in exemplars:
            if want == "SIMPLE" and a.no_local:
                continue
            t0, d0 = jev_counts()
            req = urllib.request.Request(f"{LITELLM}/v1/chat/completions", headers=H, method="POST", data=json.dumps(
                {"model": "array/auto", "max_tokens": 48, "messages": [{"role": "user", "content": f"{text} (gate {int(time.time())})"}]}).encode())
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    s, served = r.status, r.headers.get("x-litellm-model-name")
            except urllib.error.HTTPError as e:
                s, served = e.code, None
            except Exception:  # noqa: BLE001
                s, served = 0, None
            t1, d1 = jev_counts()
            moved = [k for k in t1 if t1[k] - t0.get(k, 0) >= 1]
            declined = d1.get("declined", 0) - d0.get("declined", 0) >= 1
            ok = s == 200 and not declined and any(upstream.get(tier_map.get(k)) == served for k in moved)
            notes.append(f"{want}->{'/'.join(moved) or ('DECLINED' if declined else 'no verdict')}:{(served or f'HTTP {s}').rsplit('/', 1)[-1][:24]}")
            if not ok:
                bad.append(want)
        gate("jev routes each tier (array/auto)", bool(tier_map) and bool(notes) and not bad,
             f"{' · '.join(notes)} in {time.time()-t:.0f}s" + (f"; MISMATCH on {bad}" if bad else ""))

    # 7. prometheus targets via grafana datasource proxy
    s, b = http(f"{GRAFANA}/api/datasources/proxy/uid/{PROM_UID}/api/v1/targets", G)
    tg = ((jbody(b) or {}).get("data") or {}).get("activeTargets", [])
    down = [f"{t['labels'].get('job')}:{t.get('lastError','')[:40]}" for t in tg if t["health"] != "up"]
    gate("prometheus targets all UP", s == 200 and tg and not down, f"{len(tg)-len(down)}/{len(tg)} up" + (f"; DOWN {down}" if down else ""))

    # 8. grafana health + provisioning
    s, b = http(f"{GRAFANA}/api/health"); d = jbody(b) or {}
    gate("grafana health", s == 200 and d.get("database") == "ok", f"version={d.get('version')}")
    s, b = http(f"{GRAFANA}/api/search?type=dash-db", G)
    dash = {x["uid"] for x in (jbody(b) or [])}
    gate("dashboard praxen-command provisioned", "praxen-command" in dash, f"uids={sorted(dash)}")
    s, b = http(f"{GRAFANA}/api/datasources", G)
    ds = {x["uid"] for x in (jbody(b) or [])}
    need = {PROM_UID, TEMPO_UID, LOKI_UID, PG_UID}
    gate("datasource uids intact", need <= ds, f"missing={sorted(need - ds)}" if need - ds else "prom/tempo/loki/pg present")

    # 9. loki + tempo answer through grafana
    s, b = http(f"{GRAFANA}/api/datasources/proxy/uid/{LOKI_UID}/loki/api/v1/labels", G)
    labels = (jbody(b) or {}).get("data", [])
    gate("loki labels (container)", s == 200 and "container" in labels, f"labels={labels[:6]}")
    s, b = http(f"{GRAFANA}/api/datasources/proxy/uid/{TEMPO_UID}/api/echo", G)
    gate("tempo echo", s == 200 and b.strip() == b"echo", f"HTTP {s}")

    # 10. searxng json path (Msty SearXNG MCP rides this)
    s, b = http(f"{SEARXNG}/search?q=grafana+release+notes&format=json", timeout=40)
    n = len((jbody(b) or {}).get("results", []))
    gate("searxng format=json", s == 200 and n > 0, f"{n} results")

    fails = [r for r in results if not r[1]]
    print(f"\n  {len(results)-len(fails)}/{len(results)} gates passed" + (f" — FAIL: {[f[0] for f in fails]}" if fails else ""))
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
