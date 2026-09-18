#!/usr/bin/env python3
"""
verify-stack.py -- end-to-end health gate for the stack. Run it BEFORE and AFTER any
image bump, config bump, or compose recreate. Exits 1 on any FAIL.

WHY IT EXISTS
  Every maintenance pass tends to re-derive the same probe set by hand (readiness, a
  routable count, one chain returning 200, one restricted key being refused, embedder
  dimensions, scrape targets UP, provisioned dashboards and datasources, search JSON).
  Hand-derived gates drift and get skipped under time pressure; a script does not.

THE 14 PROBES
   1 containers running/healthy          2 LiteLLM readiness (db connected)
   3 catalog >= --min-routable            4 every local route in YAML is registered
   5 one fallback chain answers 200       6 a restricted key is refused (401/403)
   7 embedding route returns the expected  8 Prometheus targets all UP (via the
     vector dimension                        Grafana datasource proxy)
   9 Grafana health                       10 every dashboard on disk is provisioned
  11 every datasource uid on disk exists  12 Loki answers with the expected label
  13 Tempo echo                           14 SearXNG format=json returns results

  Probe 5 costs a fraction of a cent through a cloud primary: skip it with --no-llm.
  Probe 6 is SKIPPED (not failed) unless --restricted-key-var names an env var that
  holds a virtual key with a model allowlist. Probe 14 is skipped with --no-searxng.
  Probe 7 verifies by DIMENSION, never by the echoed model name: a local model server
  can answer 200 with whatever embedder is resident, and 1024-dim vs 768-dim vectors
  are not interchangeable.

WHAT IT READS FROM DISK (repo root = parent of scripts/, or --root)
  .env                                     LITELLM_MASTER_KEY, GRAFANA_ADMIN_USER,
                                           GRAFANA_ADMIN_PASSWORD (process env wins)
  litellm_config.yaml                      model_name entries starting with --local-prefixes
  grafana/provisioning/datasources/*.yaml  datasource uids and types
  grafana/dashboards/**/*.json             dashboard uids

SECRETS ARE NEVER PRINTED. Only counts, model names, versions and HTTP codes appear.

USAGE
  python scripts/verify-stack.py                              # full gate
  python scripts/verify-stack.py --no-llm                     # skip the paid chat probe
  python scripts/verify-stack.py --restricted-key-var MY_SCOPED_KEY --restricted-model gpt-4.1
  python scripts/verify-stack.py --embed-model local-embed-example --embed-dims 1024
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------------- helpers
def load_env_file(path):
    """KEY=value lines from a dotenv file. Quotes stripped, comments ignored."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def http(url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {}, data=data, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001 -- connection refused, timeout, DNS: all read as 0
        return 0, str(e).encode()


def jbody(b):
    try:
        return json.loads(b)
    except Exception:  # noqa: BLE001
        return None


def datasources_on_disk(root):
    """{uid: type} for every top-level datasource in grafana/provisioning/datasources/*.yaml.

    Deliberately not a YAML parser (stdlib only): a datasource block starts at a
    `- name:` line at the outermost list indent; the first `uid:` / `type:` lines
    deeper than that indent belong to it. Nested `- name:` items (e.g. inside
    tracesToMetrics queries) sit at a deeper indent and are ignored.
    """
    found = {}
    for path in sorted((root / "grafana" / "provisioning" / "datasources").glob("*.y*ml")):
        block_indent, cur = None, None
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            m = re.match(r"^\s*-\s*name:\s*(.+?)\s*$", raw)
            if m and (block_indent is None or indent == block_indent):
                block_indent = indent
                cur = {"uid": None, "type": None}
                continue
            if cur is None or indent <= block_indent:
                continue
            m = re.match(r"^\s*(uid|type):\s*(.+?)\s*$", raw)
            if m and cur[m.group(1)] is None:
                cur[m.group(1)] = m.group(2).strip('"').strip("'")
                if cur["uid"] and cur["type"]:
                    found[cur["uid"]] = cur["type"]
    return found


def dashboards_on_disk(root):
    uids = {}
    for path in sorted((root / "grafana" / "dashboards").rglob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and d.get("uid"):
            uids[d["uid"]] = path.name
    return uids


def local_routes_in_yaml(config_path, prefixes):
    if not config_path.exists():
        return None
    alt = "|".join(re.escape(p) for p in prefixes)
    pat = re.compile(r"^\s*-\s*model_name:\s*[\"']?((?:%s)[\w.\-/]+)" % alt, re.M)
    return sorted(set(pat.findall(config_path.read_text(encoding="utf-8", errors="replace"))))


# ----------------------------------------------------------------------------- gates
results = []


def gate(name, ok, detail="", skipped=False):
    status = "SKIP" if skipped else ("PASS" if ok else "FAIL")
    results.append((name, status, detail))
    print(f"  [{status}] {name:<36} {detail}")


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="14-probe health gate. Exit 1 on any FAIL.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="repo root (default: parent of scripts/)")
    ap.add_argument("--config", default=None, help="litellm_config.yaml (default: <root>/litellm_config.yaml)")
    ap.add_argument("--litellm-url", default=os.environ.get("LITELLM_URL", "http://localhost:4000"))
    ap.add_argument("--grafana-url", default=os.environ.get("GRAFANA_URL", "http://localhost:3200"))
    ap.add_argument("--searxng-url", default=os.environ.get("SEARXNG_URL", "http://localhost:8080"))
    ap.add_argument("--prometheus-url", default=os.environ.get("PROMETHEUS_URL"),
                    help="direct Prometheus URL, used only if no prometheus datasource uid is found on disk")
    ap.add_argument("--container-prefix", default="praxen", help="docker name filter for probe 1")
    ap.add_argument("--min-routable", type=int, default=100,
                    help="probe 3 floor; the real count is upstream-driven, never a fixed target")
    ap.add_argument("--local-prefixes", default="local-",
                    help="comma-separated model_name prefixes that must be registered (probe 4)")
    ap.add_argument("--chain-model", default="fast", help="alias/model for the paid chain probe (probe 5)")
    ap.add_argument("--restricted-key-var", default=None,
                    help="env var (process env or .env) holding a virtual key WITH a model allowlist (probe 6)")
    ap.add_argument("--restricted-model", default="gpt-4.1",
                    help="a model the restricted key must be refused (probe 6)")
    ap.add_argument("--embed-model", default="local-embed-example", help="embedding route (probe 7)")
    ap.add_argument("--embed-dims", type=int, default=1024, help="expected vector dimension (probe 7)")
    ap.add_argument("--loki-label", default="container", help="label Loki must expose (probe 12)")
    ap.add_argument("--no-llm", action="store_true", help="skip the paid chat probe")
    ap.add_argument("--no-searxng", action="store_true", help="skip the SearXNG probe")
    ap.add_argument("--timeout", type=int, default=120, help="seconds for the slow (inference) probes")
    a = ap.parse_args()

    root = Path(a.root).resolve()
    config_path = Path(a.config) if a.config else root / "litellm_config.yaml"
    dotenv = load_env_file(root / ".env")

    def secret(name):
        return os.environ.get(name) or dotenv.get(name)

    master = secret("LITELLM_MASTER_KEY")
    guser = secret("GRAFANA_ADMIN_USER") or "admin"
    gpw = secret("GRAFANA_ADMIN_PASSWORD")
    H = {"Authorization": f"Bearer {master or ''}", "Content-Type": "application/json"}
    G = {"Authorization": "Basic " + b64encode(f"{guser}:{gpw or ''}".encode()).decode()}
    L, GR, SX = a.litellm_url.rstrip("/"), a.grafana_url.rstrip("/"), a.searxng_url.rstrip("/")

    print(f"\nStack gate  (root={root.name}, litellm={L}, grafana={GR})\n")
    if not master:
        print("  note: LITELLM_MASTER_KEY not found in process env or .env -- LiteLLM probes will 401")
    if not gpw:
        print("  note: GRAFANA_ADMIN_PASSWORD not found in process env or .env -- authenticated Grafana probes will 401")

    # 1. containers
    try:
        out = subprocess.run(["docker", "ps", "-a", "--filter", f"name={a.container_prefix}",
                              "--format", "{{.Names}}|{{.State}}|{{.Status}}"],
                             capture_output=True, text=True, timeout=60).stdout.strip().splitlines()
        bad = [l.split("|")[0] for l in out if "|running|" not in l or "unhealthy" in l]
        gate("containers running/healthy", bool(out) and not bad,
             f"{len(out)} {a.container_prefix}* containers" + (f"; BAD: {bad}" if bad else ""))
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        gate("containers running/healthy", False, f"docker not available: {type(e).__name__}")

    # 2. litellm readiness
    s, b = http(f"{L}/health/readiness")
    d = jbody(b) or {}
    db_ok = d.get("db") in (None, "connected")
    gate("litellm readiness", s == 200 and d.get("status") == "healthy" and db_ok,
         f"HTTP {s} status={d.get('status')} db={d.get('db')}")

    # 3 + 4. routable catalog, every local route registered
    s, b = http(f"{L}/v1/models", H)
    ids = {m.get("id") for m in (jbody(b) or {}).get("data", []) if isinstance(m, dict)}
    gate("catalog routable", s == 200 and len(ids) >= a.min_routable,
         f"HTTP {s} {len(ids)} routable (floor {a.min_routable}; count is upstream-driven)")
    prefixes = [p.strip() for p in a.local_prefixes.split(",") if p.strip()]
    yaml_locals = local_routes_in_yaml(config_path, prefixes)
    if yaml_locals is None:
        gate("local routes registered", False, f"config not found: {config_path.name}")
    else:
        missing = [m for m in yaml_locals if m not in ids]
        gate("local routes registered", not missing,
             f"{len(yaml_locals)} in YAML with prefix {prefixes}" + (f"; MISSING {missing}" if missing else ""))

    # 5. chain probe (paid, tiny)
    if a.no_llm:
        gate(f"chain probe ({a.chain_model}) 200", True, "SKIPPED (--no-llm)", skipped=True)
    else:
        nonce = int(time.time())  # defeat any response cache so the probe reaches a real backend
        body = json.dumps({"model": a.chain_model, "max_tokens": 8,
                           "messages": [{"role": "user", "content": f"Reply with the word OK. nonce={nonce}"}]}).encode()
        t = time.time()
        s, b = http(f"{L}/v1/chat/completions", H, body, timeout=a.timeout)
        d = jbody(b) or {}
        gate(f"chain probe ({a.chain_model}) 200", s == 200 and bool(d.get("choices")),
             f"HTTP {s} in {time.time() - t:.1f}s served_by={d.get('model')}")

    # 6. allowlist enforcement: a scoped key must be refused a model outside its list
    if not a.restricted_key_var:
        gate("restricted key refused", True, "SKIPPED (no --restricted-key-var)", skipped=True)
    else:
        rk = secret(a.restricted_key_var)
        if not rk:
            gate("restricted key refused", False, f"env var {a.restricted_key_var} is empty/unset")
        else:
            body = json.dumps({"model": a.restricted_model, "max_tokens": 1,
                               "messages": [{"role": "user", "content": "x"}]}).encode()
            s, b = http(f"{L}/v1/chat/completions",
                        {"Authorization": f"Bearer {rk}", "Content-Type": "application/json"}, body, timeout=30)
            gate("restricted key refused", s in (401, 403), f"HTTP {s} for {a.restricted_model} (want 401/403)")

    # 7. embedding dimension -- assert on the vector, never on the echoed model name
    body = json.dumps({"model": a.embed_model, "input": "dimension probe"}).encode()
    t = time.time()
    s, b = http(f"{L}/v1/embeddings", H, body, timeout=a.timeout)
    d = jbody(b) or {}
    first = (d.get("data") or [{}])[0] if isinstance(d.get("data"), list) else {}
    dims = len(first.get("embedding", []) if isinstance(first, dict) else [])
    gate(f"embed {a.embed_model} = {a.embed_dims} dims", s == 200 and dims == a.embed_dims,
         f"HTTP {s} dims={dims} in {time.time() - t:.1f}s")

    # 7b. TypeSafe Jev pass-through (optional; docs/jev-decision-layer.md). Skips unless the key is configured.
    ts_key = os.environ.get("TYPESAFE_API_KEY") or ""
    env_path = root / ".env"
    if not ts_key and env_path.exists():
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.startswith("TYPESAFE_API_KEY=") and raw.split("=", 1)[1].strip().strip('"') not in ("", "CHANGE_ME"):
                ts_key = "set"
    if not ts_key or ts_key == "CHANGE_ME":
        gate("typesafe pass-through (/typesafe/v1/models)", True, "SKIPPED (TYPESAFE_API_KEY not set)", skipped=True)
    else:
        t = time.time()
        s, b = http(f"{L}/typesafe/v1/models", H, timeout=30)
        d = jbody(b) or {}
        names = [x.get("name") or x.get("id") for x in (d.get("models") or d.get("data") or [])]
        gate("typesafe pass-through (/typesafe/v1/models)", s == 200 and any(str(n).startswith("jev") for n in names),
             f"HTTP {s} models={names} in {time.time() - t:.1f}s")

    # datasource / dashboard inventory from disk
    ds_disk = datasources_on_disk(root)
    by_type = {}
    for uid, typ in ds_disk.items():
        by_type.setdefault(typ, uid)
    prom_uid, loki_uid, tempo_uid = by_type.get("prometheus"), by_type.get("loki"), by_type.get("tempo")

    # 8. prometheus targets (via grafana proxy, else direct URL, else skip)
    if prom_uid and gpw:
        s, b = http(f"{GR}/api/datasources/proxy/uid/{prom_uid}/api/v1/targets", G)
        via = f"grafana proxy uid={prom_uid}"
    elif a.prometheus_url:
        s, b = http(f"{a.prometheus_url.rstrip('/')}/api/v1/targets")
        via = "direct"
    else:
        s, b, via = None, b"", ""
    if s is None:
        gate("prometheus targets all UP", True, "SKIPPED (no prometheus datasource on disk and no --prometheus-url)", skipped=True)
    else:
        tg = ((jbody(b) or {}).get("data") or {}).get("activeTargets", [])
        down = [f"{t.get('labels', {}).get('job')}:{t.get('lastError', '')[:40]}" for t in tg if t.get("health") != "up"]
        gate("prometheus targets all UP", s == 200 and bool(tg) and not down,
             f"{len(tg) - len(down)}/{len(tg)} up via {via}" + (f"; DOWN {down}" if down else ""))

    # 9. grafana health (unauthenticated)
    s, b = http(f"{GR}/api/health")
    d = jbody(b) or {}
    gate("grafana health", s == 200 and d.get("database") == "ok", f"HTTP {s} version={d.get('version')}")

    # 10. dashboards on disk are provisioned
    dash_disk = dashboards_on_disk(root)
    s, b = http(f"{GR}/api/search?type=dash-db&limit=500", G)
    dash_live = {x.get("uid") for x in (jbody(b) or []) if isinstance(x, dict)}
    missing = sorted(u for u in dash_disk if u not in dash_live)
    gate("dashboards provisioned", s == 200 and bool(dash_disk) and not missing,
         f"HTTP {s} {len(dash_disk)} on disk" + (f"; MISSING {missing}" if missing else "; all present")
         if dash_disk else "no grafana/dashboards/*.json on disk")

    # 11. datasource uids on disk exist in grafana
    s, b = http(f"{GR}/api/datasources", G)
    ds_live = {x.get("uid") for x in (jbody(b) or []) if isinstance(x, dict)}
    missing = sorted(u for u in ds_disk if u not in ds_live)
    gate("datasource uids present", s == 200 and bool(ds_disk) and not missing,
         f"HTTP {s} {len(ds_disk)} on disk ({', '.join(sorted(set(ds_disk.values())))})" + (f"; MISSING {missing}" if missing else "")
         if ds_disk else "no grafana/provisioning/datasources/*.yaml on disk")

    # 12. loki labels
    if loki_uid:
        s, b = http(f"{GR}/api/datasources/proxy/uid/{loki_uid}/loki/api/v1/labels", G)
        labels = (jbody(b) or {}).get("data", []) or []
        gate(f"loki label '{a.loki_label}'", s == 200 and a.loki_label in labels, f"HTTP {s} labels={labels[:6]}")
    else:
        gate(f"loki label '{a.loki_label}'", True, "SKIPPED (no loki datasource on disk)", skipped=True)

    # 13. tempo echo
    if tempo_uid:
        s, b = http(f"{GR}/api/datasources/proxy/uid/{tempo_uid}/api/echo", G)
        gate("tempo echo", s == 200 and b.strip() == b"echo", f"HTTP {s}")
    else:
        gate("tempo echo", True, "SKIPPED (no tempo datasource on disk)", skipped=True)

    # 14. searxng json (an MCP search tool typically rides this path)
    if a.no_searxng:
        gate("searxng format=json", True, "SKIPPED (--no-searxng)", skipped=True)
    else:
        s, b = http(f"{SX}/search?q=grafana+release+notes&format=json", timeout=40)
        n = len((jbody(b) or {}).get("results", []) or [])
        gate("searxng format=json", s == 200 and n > 0, f"HTTP {s} {n} results")

    fails = [r[0] for r in results if r[1] == "FAIL"]
    skips = sum(1 for r in results if r[1] == "SKIP")
    print(f"\n  {len(results) - len(fails)}/{len(results)} gates passed"
          + (f" ({skips} skipped)" if skips else "")
          + (f" -- FAIL: {fails}" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
