"""
praxen-host-exporter (OP GRAFANA Phase 2, the operator 2026-10-30): what the host and Unsloth Desktop are doing, as Prometheus metrics.

Source: Unsloth Desktop's READ-ONLY status API on the Windows host (GET /api/system, GET /api/inference/status), reached from
the container as host.docker.internal:8888 with UNSLOTH_PC_API_KEY, the same two calls litellm/jev_gate.py already makes. No
inference, no model loads, nothing written. /api/system reports host-wide RAM (probed 2026-10-30: within 0.1 GB of Windows'
GlobalMemoryStatusEx), CPU, disk and per-GPU VRAM / utilisation / temperature / power; /api/inference/status the loaded model.
Not visible from here: Windows commit charge and per-process memory (the overview labels them NOT INSTRUMENTED).

Phase 3 (2026-10-30, the operator "Phase 3 is a go"): which client APP sent each Gateway request. LiteLLM sees one key per Gateway lane
(desktop chat app, web chat app and Go share `openai-compatible` = key front-gateway-winpc), so the split lives only in Gateway's own
usage_events table (one row per request, with the pairing/client token that made it). GATEWAY_DB_DIR is a READ-ONLY bind mount of
%APPDATA%\\gateway app Runtime; every GATEWAY_TTL seconds the exporter copies gateway.db + its WAL into /tmp and reads the copy, never
the live file (Gateway is the only writer, and SQLite's shared-memory index does not work across the Windows/VM boundary). Only
names, counts and token sums leave the copy; token hashes and credential refs are never selected.

Every scrape reports praxen_exporter_source_up{source} so the overview can tell "the source did not answer" (unknown, steel)
from "the host is fine" (green). Standard library only; serves :9488/metrics on praxen-network (no published port).
"""
import http.server
import json
import os
import shutil
import sqlite3
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = os.environ.get("UNSLOTH_PC_URL", "http://host.docker.internal:8888").rstrip("/")
BASE = BASE[:-3] if BASE.endswith("/v1") else BASE
KEY = os.environ.get("UNSLOTH_PC_API_KEY", "")
PORT = int(os.environ.get("EXPORTER_PORT", "9488"))
TTL = 10          # seconds a reading is reused (Prometheus scrapes every 15 s)
GIB = 1024 ** 3   # Unsloth reports *_gb in GiB (47.75 total on this 48 GiB host)
_lock, _cache = threading.Lock(), {"t": 0.0, "body": ""}
GATEWAY_DIR = os.environ.get("GATEWAY_DB_DIR", "")   # empty = the Gateway collector is off
GATEWAY_TTL = 60                                   # usage is per request; a minute-old copy is fresh enough
GATEWAY_WORK = "/tmp/gateway-snapshot"
_gateway = {"t": 0.0, "lines": []}


def fetch(path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {KEY}"} if KEY else {})
    with urllib.request.urlopen(req, timeout=3) as r:   # 3 s, both calls in parallel: well inside Prometheus' 10 s scrape
        return json.loads(r.read())


def fetch_or_none(path):
    try:
        return fetch(path)
    except Exception:  # noqa: BLE001 — any failure is reported as source_up 0, never as a healthy zero
        return None


def num(v, scale=1.0):
    try:
        return float(v) * scale
    except (TypeError, ValueError):
        return None


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")[:120]


def emit(out, name, help_, samples, typ="gauge"):
    out.append(f"# HELP {name} {help_}")
    out.append(f"# TYPE {name} {typ}")
    for labels, value in samples:
        if value is None:
            continue
        value = round(value, 6) if isinstance(value, float) else value
        lbl = ",".join(f'{k}="{esc(v)}"' for k, v in labels.items())
        out.append(f"{name}{{{lbl}}} {value}" if lbl else f"{name} {value}")


def app_of(name, token_id):
    """The app behind a Gateway client token. Every Studio re-pair mints a new pairing token under the same name, so the name
    (not the id) carries the app; a deleted token keeps its usage rows but loses its name."""
    if name is None:
        return "bootstrap token" if (token_id or "").startswith("bootstrap") else "deleted token"
    n = name.lower()
    if "web-chat-app" in n or "web chat app" in n:
        return "Web chat app"
    if n.startswith(("desktop chat app", "front-studio")):
        return "Desktop chat app"
    if n.startswith(("task app", "front-go")):
        return "Task app"
    if n.startswith("coder"):
        return "Coder"
    if "paperclip" in n or "hermes" in n:
        return "Paperclip"
    return name


def via_of(provider_id, base_urls):
    """`litellm` when the Gateway lane fronts the proxy (metered, in SpendLogs), `direct` when Gateway served it elsewhere (Studio's
    llama.cpp, Gateway's own runtimes, a second proxy): those requests never reach LiteLLM's ledger."""
    url = base_urls.get(provider_id)
    if url is None:  # a deleted lane: its id says whether it fronted LiteLLM
        return "litellm" if (provider_id or "").startswith("litellm") else "direct"
    return "litellm" if ":4000" in url else "direct"


def gateway_copy():
    """Copy the WAL, then the database, into GATEWAY_WORK; retry when the WAL changed meanwhile (a checkpoint ran). The -shm index
    is not copied: SQLite rebuilds it from the WAL when the copy opens."""
    src = lambda n: os.path.join(GATEWAY_DIR, n)  # noqa: E731
    dst = lambda n: os.path.join(GATEWAY_WORK, n)  # noqa: E731
    sig = lambda: (os.stat(src("gateway.db-wal")).st_size, os.stat(src("gateway.db-wal")).st_mtime) if os.path.exists(src("gateway.db-wal")) else None  # noqa: E731
    os.makedirs(GATEWAY_WORK, exist_ok=True)
    for _ in range(3):
        for n in ("gateway.db", "gateway.db-wal", "gateway.db-shm"):
            if os.path.exists(dst(n)):
                os.remove(dst(n))
        before = sig()
        if before:
            shutil.copyfile(src("gateway.db-wal"), dst("gateway.db-wal"))
        shutil.copyfile(src("gateway.db"), dst("gateway.db"))
        if sig() == before:
            break
    return sqlite3.connect(dst("gateway.db"))


def gateway_read():
    """Per-app Gateway usage as metric lines, or None when the copy could not be read (reported as source_up 0)."""
    t0 = time.time()
    con = gateway_copy()
    try:
        urls = dict(con.execute("SELECT id, base_url FROM providers"))
        month = datetime.now(timezone.utc).strftime("%Y-%m-01T00:00:00")
        rows = con.execute(
            "SELECT t.name, u.token_id, u.provider_id, u.success, count(*), sum(COALESCE(u.input_tokens, 0)), "
            "sum(COALESCE(u.output_tokens, 0)), max(u.created_at), sum(u.created_at >= ?), "
            "sum(CASE WHEN u.created_at >= ? THEN COALESCE(u.input_tokens, 0) ELSE 0 END), "
            "sum(CASE WHEN u.created_at >= ? THEN COALESCE(u.output_tokens, 0) ELSE 0 END) "
            "FROM usage_events u LEFT JOIN gateway_tokens t ON t.id = u.token_id GROUP BY 1, 2, 3, 4", (month,) * 3).fetchall()
    finally:
        con.close()
    req, tok, mreq, mtok, last, total = {}, {}, {}, {}, {}, 0
    add = lambda d, k, v: d.__setitem__(k, d.get(k, 0) + (v or 0))  # noqa: E731
    for name, tid, prov, ok, n, tin, tout, newest, m_n, m_in, m_out in rows:
        app, via, lane = app_of(name, tid), via_of(prov, urls), prov or "?"
        total += n
        add(req, (app, name or app, lane, via, "success" if ok else "failure"), n)
        add(tok, (app, lane, via, "input"), tin)
        add(tok, (app, lane, via, "output"), tout)
        if m_n:
            add(mreq, (app, lane, via), m_n)
            add(mtok, (app, lane, via, "input"), m_in)
            add(mtok, (app, lane, via, "output"), m_out)
        if newest:
            ts = datetime.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            last[(app, lane, via)] = max(ts, last.get((app, lane, via), 0))
    lab = lambda k, names: dict(zip(names, k))  # noqa: E731
    out = []
    emit(out, "praxen_gateway_requests_total", "Requests Gateway logged, by app (client token family), client token, lane (Gateway provider), "
         "via (litellm = metered through the proxy, direct = never reached LiteLLM) and outcome. Totals of Gateway's usage_events table.",
         [(lab(k, ("app", "client", "lane", "via", "outcome")), v) for k, v in sorted(req.items())], "counter")
    emit(out, "praxen_gateway_tokens_total", "Input and output tokens Gateway logged, by app, lane, via and direction.",
         [(lab(k, ("app", "lane", "via", "direction")), v) for k, v in sorted(tok.items())], "counter")
    emit(out, "praxen_gateway_mtd_requests", "Requests this calendar month (UTC), by app, lane and via. Apps with none this month are absent.",
         [(lab(k, ("app", "lane", "via")), v) for k, v in sorted(mreq.items())])
    emit(out, "praxen_gateway_mtd_tokens", "Tokens this calendar month (UTC), by app, lane, via and direction.",
         [(lab(k, ("app", "lane", "via", "direction")), v) for k, v in sorted(mtok.items())])
    emit(out, "praxen_gateway_last_request_timestamp_seconds", "Newest Gateway request per app, lane and via (Unix seconds, UTC).",
         [(lab(k, ("app", "lane", "via")), v) for k, v in sorted(last.items())])
    emit(out, "praxen_gateway_events", "Rows in Gateway's usage_events table (a drop means Gateway pruned history).", [({}, total)])
    emit(out, "praxen_gateway_read_seconds", "Time spent copying and reading gateway.db.", [({}, round(time.time() - t0, 3))])
    return out


def render():
    out = []
    metric = lambda *a, **k: emit(out, *a, **k)  # noqa: E731

    t0 = time.time()
    sources = (("unsloth_system", "/api/system"), ("unsloth_status", "/api/inference/status"))
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:   # parallel: a hung Unsloth costs 3 s, not 2 x 3 s
        got = dict(zip((s for s, _ in sources), pool.map(fetch_or_none, (p for _, p in sources))))
    up = {s: got[s] is not None for s in got}
    if GATEWAY_DIR:
        if time.time() - _gateway["t"] > GATEWAY_TTL:
            try:
                _gateway["lines"] = gateway_read()
            except Exception:  # noqa: BLE001 — unreadable copy: report the source down, keep no stale numbers
                _gateway["lines"] = None
            _gateway["t"] = time.time()
        up["gateway_db"] = _gateway["lines"] is not None
    metric("praxen_exporter_source_up", "1 when the source answered this scrape, 0 when it did not (the metrics below are then absent).",
           [({"source": s}, 1 if ok else 0) for s, ok in up.items()])
    metric("praxen_exporter_fetch_seconds", "Time spent reading both sources.", [({}, round(time.time() - t0, 3))])
    out.extend(_gateway["lines"] or [])

    s = got["unsloth_system"]
    if s:
        mem, cpu, disk = s.get("memory") or {}, s.get("cpu") or {}, s.get("disk") or {}
        metric("praxen_host_memory_total_bytes", "Host physical memory.", [({}, num(mem.get("total_gb"), GIB))])
        metric("praxen_host_memory_available_bytes", "Host physical memory available (Windows' own counter, via Unsloth).",
               [({}, num(mem.get("available_gb"), GIB))])
        metric("praxen_host_memory_used_ratio", "Share of host physical memory in use.", [({}, num(mem.get("percent_used"), 0.01))])
        metric("praxen_host_cpu_usage_ratio", "Host CPU utilisation (instantaneous sample).", [({}, num(cpu.get("usage_percent"), 0.01))])
        metric("praxen_host_disk_total_bytes", "Disk holding Unsloth's data.", [({}, num(disk.get("total_gb"), GIB))])
        metric("praxen_host_disk_free_bytes", "Free space on that disk.", [({}, num(disk.get("free_gb"), GIB))])
        metric("praxen_unsloth_process_tree_bytes", "Memory held by Unsloth Desktop and its child processes (llama-server).",
               [({}, num(mem.get("process_tree_used_mb"), 1024 ** 2))])
        metric("praxen_unsloth_uptime_seconds", "Unsloth Desktop backend uptime.", [({}, num(s.get("uptime_seconds")))])
        devs = (s.get("gpu") or {}).get("devices") or []
        lab = lambda d: {"gpu": str(d.get("index", "")), "name": d.get("name", "")}  # noqa: E731
        metric("praxen_gpu_memory_total_bytes", "GPU memory.", [(lab(d), num(d.get("memory_total_gb"), GIB)) for d in devs])
        metric("praxen_gpu_memory_used_bytes", "GPU memory in use.", [(lab(d), num(d.get("vram_used_gb"), GIB)) for d in devs])
        metric("praxen_gpu_memory_free_bytes", "GPU memory free.", [(lab(d), num(d.get("vram_free_gb"), GIB)) for d in devs])
        metric("praxen_gpu_utilization_ratio", "GPU compute utilisation.", [(lab(d), num(d.get("gpu_utilization_pct"), 0.01)) for d in devs])
        metric("praxen_gpu_temperature_celsius", "GPU temperature.", [(lab(d), num(d.get("temperature_c"))) for d in devs])
        metric("praxen_gpu_power_watts", "GPU power draw.", [(lab(d), num(d.get("power_draw_w"))) for d in devs])
        metric("praxen_gpu_power_limit_watts", "GPU power limit.", [(lab(d), num(d.get("power_limit_w"))) for d in devs])

    st = got["unsloth_status"]
    if st:
        loaded = st.get("loaded") or []
        model = st.get("active_model") or (loaded[0] if loaded else "")
        variant = st.get("gguf_variant") or ""
        metric("praxen_unsloth_models_loaded", "Models Unsloth Desktop holds loaded (0 = nothing resident).", [({}, len(loaded))])
        metric("praxen_unsloth_models_loading", "Models Unsloth Desktop is loading right now.", [({}, len(st.get("loading") or []))])
        metric("praxen_unsloth_model_info", "The resident model (value 1; the labels carry its name).",
               [({"model": model, "variant": variant}, 1)] if model else [])
        metric("praxen_unsloth_context_tokens", "Context length the resident model was loaded with.",
               [({"model": model}, num(st.get("context_length")))] if model else [])
    return "\n".join(out) + "\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] != "/metrics":
            self.send_response(200); self.end_headers()
            self.wfile.write(b"praxen-host-exporter: see /metrics\n"); return
        with _lock:
            if time.time() - _cache["t"] > TTL:
                _cache["body"], _cache["t"] = render(), time.time()
            body = _cache["body"].encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # quiet: Prometheus scrapes every 15 s
        pass


if __name__ == "__main__":
    print(f"praxen-host-exporter on :{PORT}, source {BASE}", flush=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
