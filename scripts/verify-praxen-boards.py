#!/usr/bin/env python3
"""
verify-praxen-boards.py — validation gate for the three example boards (COMMAND / ROUTING / FORENSICS).

Static: JSON parses · expected uid per file · no top-level id · unique panel ids · every datasource uid exists
        on the live Grafana · dashboard links keep time + variables.
Live:   every PromQL / SQL / LogQL / TraceQL target is executed through Grafana's real datasource path
        (POST /api/ds/query) with the dashboard variables set to their defaults (All => `.*`, textboxes empty)
        and reported as HTTP status + frames/rows. Panels that return nothing are listed so an unexpected
        "No data" cannot hide. Also checks provisioned=true per uid and that the two alert rules still load.

USAGE
    python scripts/verify-praxen-boards.py                 # boards under grafana/dashboards
    python scripts/verify-praxen-boards.py --dir <staging> # validate a staged build before landing it
    python scripts/verify-praxen-boards.py --trace <id>    # trace id used for the FORENSICS waterfall probe
Reads GRAFANA_ADMIN_PASSWORD from .env and never prints it. Exit 1 on any FAIL.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAFANA = "http://localhost:3200"
EXPECT = {"praxen-command.json": "praxen-command", "praxen-routing.json": "praxen-routing", "praxen-forensics.json": "praxen-forensics"}
DS_TYPES = {"afimxbo42ap6oe": "prometheus", "praxen-litellm-pg": "grafana-postgresql-datasource", "praxen-loki": "loki", "dfipt8nyznn5sc": "tempo"}


def env(key):
    for line in (ROOT / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def http(url, hdr, data=None, timeout=60):
    req = urllib.request.Request(url, headers=hdr, data=data, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


def interpolate(s: str, trace_id: str) -> str:
    """Dashboard-variable defaults the way the frontend would send them (All => `.*`, textboxes empty)."""
    subs = {
        "${key:regex}": ".*", "${model:regex}": ".*", "${team:regex}": ".*",
        "$key": ".*", "$model": ".*", "$team": ".*",
        # logcontainer has no custom All value: Grafana joins the label values; Loki rejects an empty-compatible matcher
        "$logcontainer": "praxen-.+", "$logq": "", "$severity": ".*", "$call_id": "", "${request_id}": "", "$request_id": "",
        "$trace_id": trace_id, "$interval": "5m", "$__rate_interval": "1m", "$__range": "24h", "$__interval": "1m",
    }
    for k, v in subs.items():
        s = s.replace(k, v)
    return s


def build_query(p, t, trace_id, from_ms, to_ms):
    ds = t.get("datasource") or p.get("datasource")
    uid = ds["uid"]
    q = {"refId": t.get("refId", "A"), "datasource": {"uid": uid, "type": DS_TYPES.get(uid, ds.get("type"))}, "intervalMs": 60000, "maxDataPoints": 500}
    if "expr" in t and DS_TYPES.get(uid) == "prometheus":
        q.update({"expr": interpolate(t["expr"], trace_id), "instant": bool(t.get("instant")), "range": not t.get("instant")})
        if t.get("format"):
            q["format"] = t["format"]
    elif "rawSql" in t:
        q.update({"rawSql": interpolate(t["rawSql"], trace_id), "format": t.get("format", "table"), "rawQuery": True})
    elif "expr" in t and DS_TYPES.get(uid) == "loki":
        q.update({"expr": interpolate(t["expr"], trace_id), "queryType": t.get("queryType", "range")})
    elif DS_TYPES.get(uid) == "tempo" and p["type"] == "traces":
        # the traces panel pastes a bare id into the TraceQL editor; the FRONTEND turns that into a trace lookup.
        # /api/ds/query has no such detection, so probe the same lookup through the backend's traceId query type.
        q.update({"queryType": "traceId", "query": interpolate(t.get("query", ""), trace_id)})
    elif DS_TYPES.get(uid) == "tempo":
        q.update({"queryType": "traceql", "query": interpolate(t.get("query", ""), trace_id), "tableType": t.get("tableType", "traces"), "limit": t.get("limit", 20)})
    else:
        return None
    return q


def frames_summary(res):
    frames = res.get("frames") or []
    rows = 0
    for f in frames:
        vals = (f.get("data") or {}).get("values") or []
        rows = max(rows, len(vals[0]) if vals else 0)
    return len(frames), rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "grafana" / "dashboards"))
    ap.add_argument("--trace", default="", help="trace id for the FORENSICS waterfall probe")
    ap.add_argument("--skip-live", action="store_true")
    a = ap.parse_args()
    d = Path(a.dir)
    hdr = {"Authorization": "Basic " + b64encode(f"admin:{env('GRAFANA_ADMIN_PASSWORD')}".encode()).decode(), "Content-Type": "application/json"}
    fails, warns = [], []

    s, b = http(f"{GRAFANA}/api/datasources", hdr)
    live_ds = {x["uid"] for x in json.loads(b)} if s == 200 else set()
    now = int(time.time() * 1000)
    frm = now - 24 * 3600 * 1000

    for fname, uid in EXPECT.items():
        path = d / fname
        print(f"\n== {fname}")
        try:
            board = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            fails.append(f"{fname}: JSON parse failed: {e}"); continue
        if board.get("uid") != uid: fails.append(f"{fname}: uid {board.get('uid')} != {uid}")
        if "id" in board: fails.append(f"{fname}: top-level id present")
        if board.get("schemaVersion") != 42: fails.append(f"{fname}: schemaVersion {board.get('schemaVersion')}")
        ids = [p["id"] for p in board["panels"]]
        if len(ids) != len(set(ids)): fails.append(f"{fname}: duplicate panel ids {[i for i in ids if ids.count(i) > 1]}")
        for lk in board.get("links", []):
            if lk.get("type") == "link" and lk.get("url", "").startswith("/d/") and not (lk.get("keepTime") and lk.get("includeVars")):
                fails.append(f"{fname}: link {lk.get('title')} lacks keepTime/includeVars")
        used = set()
        for p in board["panels"]:
            for t in p.get("targets", []):
                ds = t.get("datasource") or p.get("datasource")
                if ds: used.add(ds["uid"])
        missing = used - live_ds
        if missing: fails.append(f"{fname}: datasource uids not on live Grafana: {sorted(missing)}")
        print(f"  static: uid={board['uid']} panels={len(ids)} datasources={sorted(used)} links={[l.get('title') for l in board.get('links', [])]}")

        if a.skip_live:
            continue
        # provisioned?
        s, b = http(f"{GRAFANA}/api/dashboards/uid/{uid}", hdr)
        meta = json.loads(b).get("meta", {}) if s == 200 else {}
        print(f"  live: HTTP {s} provisioned={meta.get('provisioned')} externalId={meta.get('provisionedExternalId')} version={meta.get('version')} title={json.loads(b).get('dashboard', {}).get('title') if s == 200 else None}")
        if s != 200 or not meta.get("provisioned"):
            fails.append(f"{fname}: not provisioned on live Grafana (HTTP {s})")

        # execute every target
        for p in board["panels"]:
            if p["type"] in ("row", "text"):
                continue
            for t in p.get("targets", []):
                q = build_query(p, t, a.trace, frm, now)
                if q is None:
                    warns.append(f"{fname} #{p['id']} {t.get('refId')}: unrecognised target shape"); continue
                body = json.dumps({"from": str(frm), "to": str(now), "queries": [q]}).encode()
                st, rb = http(f"{GRAFANA}/api/ds/query", hdr, body, timeout=120)
                try:
                    res = json.loads(rb)["results"][q["refId"]]
                except Exception:  # noqa: BLE001
                    res = {"status": st, "error": rb[:200].decode(errors="replace")}
                nf, nr = frames_summary(res)
                status = res.get("status", st)
                err = res.get("error") or (res.get("errorSource") and res.get("error"))
                tag = "ok " if (status == 200 and not err) else "ERR"
                empty = " (empty)" if nf == 0 or nr == 0 else ""
                print(f"  [{tag}] #{p['id']:<3} {t.get('refId')} {p['type']:<24} {p.get('title', '')[:58]:<58} frames={nf} rows={nr}{empty}")
                if tag == "ERR":
                    fails.append(f"{fname} #{p['id']} {t.get('refId')} ({p.get('title', '')[:40]}): HTTP {status} {str(err)[:160]}")
                elif empty:
                    warns.append(f"{fname} #{p['id']} {t.get('refId')} ({p.get('title', '')[:40]}): no data at defaults")

    if not a.skip_live:
        s, b = http(f"{GRAFANA}/api/v1/provisioning/alert-rules", hdr)
        rules = {r["uid"] for r in json.loads(b)} if s == 200 else set()
        need = {"praxen-key-over-watch", "praxen-total-over-plan"}
        print(f"\n  alert rules: {sorted(rules)}")
        if not need <= rules: fails.append(f"alert rules missing: {sorted(need - rules)}")

    print("\n  WARN (empty at defaults — expected for request-scoped FORENSICS panels, review the rest):")
    for w in warns: print("    -", w)
    print("\n  FAIL:" if fails else "\n  all gates passed")
    for f in fails: print("    -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
