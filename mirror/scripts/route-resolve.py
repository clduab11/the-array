#!/usr/bin/env python3
"""
route-resolve.py — does every configured name still resolve to a deployment in the RUNNING router?

WHY THIS EXISTS (2026-10-01, OP CATALOG-CURRENCY): /v1/models and /v1/model/info list a name even when the router holds
no deployment for it. The proxy's model-sync job re-reads litellm_config.yaml about every 30 s and drops every deployment
whose model_name + litellm_params changed on disk, loading nothing new until a restart; a live edit took 76 Venice routes
dark that way while the catalog still listed them. Only a call proves resolution. This makes that call nearly free:

  chat names      POST /v1/chat/completions with an EMPTY message list and `disable_fallbacks: true`: the provider rejects
                  it at no cost, or answers one token. An unresolved name answers "There are no healthy deployments for
                  this model". Without `disable_fallbacks` (until 2026-10-05) the provider's 400 walked the name's chain:
                  a rung that answers an empty request (Gemini does) returned 200 and would have masked a primary with no
                  deployment, and every sweep logged ~600 fallbacks under the master key, nearly all of the proxy's
                  fallback and failure counters for the week.
  local-* names   POST /v1/embeddings: litellm/unsloth_guard.py refuses the call type AFTER the router has picked the
                  deployment, so Unsloth never loads or swaps a model.
  embed names     one real embedding on praxen-embed (CPU, free).
  non-chat names  the /v1/responses-only Perplexity routes and the image_generation entries get the same empty chat
                  call: the provider's rejection ("Invalid model", 503 "No available capacity") still proves the router
                  picked a deployment, at no cost. A native-shape call could bill unmetered (Perplexity's search fee, an
                  image), so none is made (2026-10-07).

Every call carries `x-litellm-tags: health-gate`, so its SpendLogs row says it is gate traffic (the boards' TRAFFIC
picker leaves it out). A rejection by the proxy itself (bad key, budget, model access) is a FAIL (AUTH): the call never
reached the router, so it proves nothing; an upstream 401/403 on a routed call still proves the name resolved.
Run it after every proxy restart and after any edit to the live YAML. Reads the master key from .env and never prints it.

USAGE
  python scripts/route-resolve.py            # every model_name and alias; exit 1 if any is unresolved
  python scripts/route-resolve.py NAME ...   # only these names, verbose
"""
import json, sys, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LITELLM = "http://localhost:4000"
DEAD = "no healthy deployments"
GATE_TAG = "health-gate"   # SpendLogs request_tags marker; the same tag scripts/verify-stack.py sends
# The proxy's OWN rejections (litellm/proxy/_types.py ProxyErrorTypes, v1.104.0): the call stopped before the router. An
# upstream 401/403 on a routed call carries an OpenAI-style type (authentication_error, permission_error) and still proves
# the name resolved, as before.
PROXY_REJECTIONS = {"auth_error", "expired_key", "token_not_found_in_db", "budget_exceeded", "auth_provider_unavailable",
                    "key_model_access_denied", "team_model_access_denied", "user_model_access_denied",
                    "org_model_access_denied", "project_model_access_denied", "agent_model_access_denied"}


def env(key):
    for line in (ROOT / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"{key} not found in .env")


def post(path, body, key):
    req = urllib.request.Request(LITELLM + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "x-litellm-tags": GATE_TAG})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, "", ""
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error") or {}
            return e.code, (err.get("message") or ""), str(err.get("type") or "")
        except Exception:  # noqa: BLE001
            return e.code, "", ""
    except Exception as e:  # noqa: BLE001
        return 0, str(e), ""


def main():
    key = env("LITELLM_MASTER_KEY")
    cfg = yaml.safe_load((ROOT / "litellm_config.yaml").read_text(encoding="utf-8"))
    entries = {e["model_name"]: e["litellm_params"] for e in cfg["model_list"] if "*" not in e["model_name"]}
    aliases = cfg["router_settings"].get("model_group_alias") or {}
    target = {a: (t["model"] if isinstance(t, dict) else t) for a, t in aliases.items()}

    def kind(name):
        p = entries.get(target.get(name, name)) or {}
        if "praxen-embed" in str(p.get("api_base", "")):
            return "embed"
        return "local" if "UNSLOTH" in str(p.get("api_base", "")) else "chat"

    def probe(name):
        k = kind(name)
        if k == "chat":
            st, msg, etype = post("/v1/chat/completions", {"model": name, "messages": [], "max_tokens": 1, "disable_fallbacks": True}, key)
        else:
            st, msg, etype = post("/v1/embeddings", {"model": name, "input": "route-resolve"}, key)
        if DEAD in msg:
            verdict = "UNRESOLVED"
        elif st == 0:
            verdict = "NO ANSWER"
        elif etype in PROXY_REJECTIONS:
            verdict = "AUTH"       # the proxy refused the key before routing: the name was never tried
        elif k == "local" and "unsloth_guard" not in msg:
            verdict = "CHECK"      # resolved, but the guard did not refuse the call type
        elif k == "embed" and st != 200:
            verdict = "CHECK"
        else:
            verdict = "ok"
        return name, k, st, verdict, msg[:150].replace("\n", " ")

    names = list(entries) + list(aliases)
    only = sys.argv[1:]
    if only:
        names = [n for n in names if n in only]
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(probe, names))
    bad = [r for r in rows if r[3] != "ok"]
    for name, k, st, verdict, msg in rows:
        if only or verdict != "ok":
            print(f"  [{verdict}] {name:<48} {k:<5} HTTP {st}  {msg}")
    print(f"\n  {len(rows) - len(bad)}/{len(rows)} names resolve" + (f" — NOT OK: {[r[0] for r in bad]}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
