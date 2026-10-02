#!/usr/bin/env python3
"""probe-typesafe.py - probe the TypeSafe AI (Jev) System One API, direct or through the proxy.

Reads TYPESAFE_API_KEY (and LITELLM_MASTER_KEY for --via-proxy) from ./.env. Never prints a key.
Exit 1 on any failed assertion. Stdlib only.

  python scripts/probe-typesafe.py            # direct: GET /v1/models + one 3-question evaluate
  python scripts/probe-typesafe.py --via-proxy  # same request through http://localhost:4000/typesafe/...
                                                #   (needs a LiteLLM image with the TypeSafe pass-through,
                                                #    first shipped in v1.103.0-dev.2 / PR #41607 - v1.100.1 404s)

Assertions follow the durable rule: assert on the RESPONSE MODEL and shape, never on the status code.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRECT_BASE = "https://api.typesafe.ai"
PROXY_BASE = "http://localhost:4000/typesafe"
INPUT_USD_PER_TOKEN = 0.042 / 1_000_000   # docs.typesafe.ai/models (2026-09-17): $0.042/Mtok in, output free

PROBE_REQUEST = {
    "model": "jev-latest",
    "state": {
        "ticket": {
            "subject": "Duplicate charge",
            "message": "I was charged twice for order A-104 three days ago and nobody has replied. "
                       "Please refund the duplicate today or I am disputing it with my bank.",
        }
    },
    "questions": {
        "department": {
            "type": "choice",
            "instructions": "Which team should handle `ticket`?",
            "criteria": {
                "billing": "Payments, invoicing, refunds, duplicate charges",
                "technical": "Bugs, outages, integrations",
                "sales": "Pricing, upgrades, new accounts",
            },
        },
        "frustration": {
            "type": "score",
            "instructions": "How frustrated is the author of `ticket.message`?",
            "criteria": ["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"],
        },
        "is_urgent": {
            "type": "noul",
            "instructions": "Does `ticket.message` convey urgency or a deadline?",
        },
    },
}


def env(key):
    path = os.path.join(ROOT, ".env")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return os.environ.get(key)


def call(method, url, token, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw": raw[:400].decode(errors="replace")}
        return e.code, parsed, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--via-proxy", action="store_true", help="route through the LiteLLM /typesafe pass-through")
    args = ap.parse_args()

    if args.via_proxy:
        token = env("LITELLM_MASTER_KEY")
        base = PROXY_BASE
        who = "LITELLM_MASTER_KEY"
    else:
        token = env("TYPESAFE_API_KEY")
        base = DIRECT_BASE
        who = "TYPESAFE_API_KEY"
    if not token:
        print(f"[FAIL] {who} not present in .env or environment")
        return 1

    failed = False

    status, models, dt = call("GET", f"{base}/v1/models", token)
    if status == 404 and args.via_proxy:
        print("[FAIL] proxy /typesafe/v1/models -> 404: this LiteLLM image has no TypeSafe pass-through "
              "(needs >= v1.103.0-dev.2 / PR #41607).")
        return 1
    names = [m.get("id") or m.get("name") for m in (models.get("data") or models.get("models") or [])] \
        if isinstance(models, dict) else []
    ok = status == 200 and any(n and n.startswith("jev") for n in names)
    print(f"[{'PASS' if ok else 'FAIL'}] GET /v1/models  HTTP {status}  {dt*1000:.0f} ms  models={names or models}")
    failed |= not ok

    status, out, dt = call("POST", f"{base}/v1/systemone", token, PROBE_REQUEST)
    answers = out.get("answers", {}) if isinstance(out, dict) else {}
    served = out.get("model") if isinstance(out, dict) else None
    usage = out.get("usage", {}) if isinstance(out, dict) else {}
    shape_ok = (
        isinstance(served, str) and served.startswith("jev-")
        and set(answers) == set(PROBE_REQUEST["questions"])
        and answers.get("department", {}).get("type") == "choice"
        and answers.get("department", {}).get("choice") in PROBE_REQUEST["questions"]["department"]["criteria"]
        and abs(sum(answers.get("department", {}).get("probabilities", {}).values()) - 1.0) < 0.01
        and answers.get("frustration", {}).get("type") == "score"
        and answers.get("is_urgent", {}).get("type") == "noul"
        and 0.0 <= answers.get("is_urgent", {}).get("noul", -1) <= 1.0
        and isinstance(usage.get("input_tokens"), int)
    )
    print(f"[{'PASS' if shape_ok else 'FAIL'}] POST /v1/systemone  HTTP {status}  {dt*1000:.0f} ms  served_model={served}")
    if shape_ok:
        d = answers["department"]
        print(f"       department = {d['choice']}  p={ {k: round(v, 3) for k, v in d['probabilities'].items()} }  "
              f"confidence={d.get('confidence')}")
        print(f"       frustration = {answers['frustration'].get('score')}  confidence={answers['frustration'].get('confidence')}")
        print(f"       is_urgent   = {answers['is_urgent'].get('noul')}")
        cost = usage.get("input_tokens", 0) * INPUT_USD_PER_TOKEN
        print(f"       usage       = {usage}   -> ${cost:.8f} at $0.042/Mtok (output free)")
        # Semantic sanity on this state: billing should win, urgency should be high.
        sem_ok = d["choice"] == "billing" and answers["is_urgent"]["noul"] >= 0.5
        print(f"[{'PASS' if sem_ok else 'WARN'}] semantic sanity (billing + urgent expected)")
    else:
        print("       body:", json.dumps(out)[:600])
    failed |= not shape_ok

    print("\nRESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
