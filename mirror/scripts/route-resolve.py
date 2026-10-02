#!/usr/bin/env python3
"""
route-resolve.py — does every configured name still resolve to a deployment in the RUNNING router?

WHY THIS EXISTS (2026-10-01, OP CATALOG-CURRENCY): /v1/models and /v1/model/info list a name even when the router holds
no deployment for it. The proxy's model-sync job re-reads litellm_config.yaml about every 30 s and drops every deployment
whose model_name + litellm_params changed on disk, loading nothing new until a restart; a live edit took 76 Venice routes
dark that way while the catalog still listed them. Only a call proves resolution. This makes that call nearly free:

  chat names      POST /v1/chat/completions with an EMPTY message list: the provider rejects it at no cost, or answers
                  one token. An unresolved name answers "There are no healthy deployments for this model".
  local-* names   POST /v1/embeddings: litellm/unsloth_guard.py refuses the call type AFTER the router has picked the
                  deployment, so Unsloth never loads or swaps a model.
  embed names     one real embedding on praxen-embed (CPU, free).

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


def env(key):
    for line in (ROOT / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"{key} not found in .env")


def post(path, body, key):
    req = urllib.request.Request(LITELLM + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        try:
            return e.code, ((json.loads(e.read()).get("error") or {}).get("message") or "")
        except Exception:  # noqa: BLE001
            return e.code, ""
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


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
            st, msg = post("/v1/chat/completions", {"model": name, "messages": [], "max_tokens": 1}, key)
        else:
            st, msg = post("/v1/embeddings", {"model": name, "input": "route-resolve"}, key)
        if DEAD in msg:
            verdict = "UNRESOLVED"
        elif st == 0:
            verdict = "NO ANSWER"
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
