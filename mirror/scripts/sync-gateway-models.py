"""Register LiteLLM's full model list on a Msty Gateway provider record explicitly.

Why: Gateway auto-import (autoProxyModels) fetches LiteLLM's /v1/models live, and LiteLLM v1.100.1 builds that list by calling
get_model_info once per model — 25-35 s for ~1,100 models. Gateway times out first, so the record showed zero models
(2026-09-16: Gateway listed 51 models while the front-gateway-winpc key could see 1,092).
This script turns auto-import off on the record (PUT without `credential` keeps the stored key — verified on a throwaway
provider) and registers each model id, so the list no longer depends on LiteLLM answering quickly.

Re-run after every LiteLLM config change that adds or removes models:
    python scripts/sync-gateway-models.py              # provider openai-compatible, key VKEY_MSTY_GATEWAY_WINPC
    python scripts/sync-gateway-models.py --prune      # also delete registrations LiteLLM no longer serves
    python scripts/sync-gateway-models.py --dry-run
Secrets are read from .env / .virtual-keys.env inside the script and never printed.
"""
import argparse, json, pathlib, sys, time, urllib.parse, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = "http://127.0.0.1:3939"
LITELLM = "http://localhost:4000"
RESPONSES_ONLY = {"pplx-sonar", "pplx-pro-search"}  # /v1/responses routes (config v4.13.1)


def dotenv(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def http(method, url, headers, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read()[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openai-compatible")
    ap.add_argument("--key-var", default="VKEY_MSTY_GATEWAY_WINPC", help="the LiteLLM key this Gateway record uses (.virtual-keys.env)")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    env, keys = dotenv(ROOT / ".env"), dotenv(ROOT / ".virtual-keys.env")
    nx = {"X-front-Gateway-Token": env["GATEWAY_ADMIN_TOKEN"]}

    st, prov = http("GET", f"{GATEWAY}/v1/providers/{a.provider}", nx)
    if st != 200:
        sys.exit(f"provider {a.provider}: HTTP {st}")
    print(f"provider {a.provider}: baseUrl={prov['baseUrl']} enabled={prov['enabled']} autoProxyModels={prov['autoProxyModels']} credentialConfigured={prov['credentialConfigured']}")

    t0 = time.time()
    st, lm = http("GET", f"{LITELLM}/v1/models", {"Authorization": f"Bearer {keys[a.key_var]}"}, timeout=240)
    if st != 200:
        sys.exit(f"LiteLLM /v1/models: HTTP {st}")
    # wildcard route names are not callable models (Gateway rejects "*"), and Gateway's openai-compatible provider kind
    # cannot carry /v1/responses-only routes ("Model endpoint family is not supported by provider kind").
    # OpenRouter's "~vendor/model-latest" alias slugs (seen 2026-09-23) 400 in Gateway: "Model ID must use path-safe
    # model segments" — skipped too; they stay callable through the proxy by name.
    want = sorted({m["id"] for m in lm["data"] if "*" not in m["id"] and "/~" not in m["id"] and m["id"] not in RESPONSES_ONLY})
    print(f"LiteLLM lists {len(want)} registrable models for {a.key_var} ({time.time() - t0:.1f}s); skipped wildcard routes, OpenRouter ~ aliases and {sorted(RESPONSES_ONLY)}")

    if prov["autoProxyModels"]:
        body = {k: prov[k] for k in ("name", "kind", "scope", "baseUrl", "enabled")} | {"autoProxyModels": False}
        print("switching the record to an explicit model list (credential untouched)" + (" [dry run]" if a.dry_run else ""))
        if not a.dry_run:
            st, after = http("PUT", f"{GATEWAY}/v1/providers/{a.provider}", nx, body)
            if st not in (200, 201) or not after.get("credentialConfigured"):
                sys.exit(f"provider update failed or lost its credential: HTTP {st} {after}")

    st, listing = http("GET", f"{GATEWAY}/v1/models", nx, timeout=120)
    have = {m["msty_model"]["name"] for m in listing.get("data", []) if m.get("msty_model", {}).get("providerId") == a.provider}
    missing, stale = [m for m in want if m not in have], sorted(have - set(want))
    print(f"Gateway already lists {len(have)} for {a.provider}; registering {len(missing)}; stale {len(stale)}" + (" (pruning)" if a.prune else ""))

    fails = 0
    for mid in missing:
        body = {"providerId": a.provider, "name": mid, "metadata": {"upstreamModelId": mid},
                "endpointFamilies": ["openai.chat_completions"]}
        if a.dry_run:
            continue
        st, _ = http("PUT", f"{GATEWAY}/v1/models/{a.provider}/{urllib.parse.quote(mid, safe='/')}", nx, body)
        fails += st not in (200, 201)
    if a.prune and not a.dry_run:
        for mid in stale:
            st, _ = http("DELETE", f"{GATEWAY}/v1/models/{a.provider}/{urllib.parse.quote(mid, safe='/')}", nx)
            fails += st not in (200, 204)

    st, listing = http("GET", f"{GATEWAY}/v1/models", nx, timeout=120)
    per = {}
    for m in listing.get("data", []):
        pid = m.get("msty_model", {}).get("providerId", "?")
        per[pid] = per.get(pid, 0) + 1
    print(f"done: {fails} failures; Gateway now lists {sum(per.values())} models: {per}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
