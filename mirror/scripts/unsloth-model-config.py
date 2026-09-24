#!/usr/bin/env python3
"""Per-model configs for Unsloth Desktop (the-array, pc-host). Stdlib only.

Gives each chosen model a pinned, persistent launch config (LM Studio per-model presets, the Unsloth way):
the overrides Unsloth applies whenever a request names the model (auto-switch / API / LiteLLM loads).

  list                         models Unsloth can serve + stored overrides
  inspect MODEL                GGUF header facts: arch, layers, KV cost per token, experts, sizes
  plan MODEL [--reserve MiB]   recommended override for THIS card right now (keeps >= reserve VRAM free)
  apply MODEL --ctx N [--kv q8_0] [--threads 8] [--n-cpu-moe K] [--gpu-layers L>=0] [--parallel P]
                [--no-kv-offload] [--extra ARG ...] [--dry-run]
                (dense model that fits: pass no GPU flags -> Auto -> `-ngl -1 --fit off`;
                 MoE: --n-cpu-moe K -> Manual mode with every layer requested)
  show MODEL                   the override a load of MODEL would apply (Unsloth's own resolver)
  verify MODEL [--runs 3] [--keep] [--ram-floor 3000]
                               load via auto-switch, check argv / VRAM / host RAM / tok/s, then unload; unloads (and
                               kills an in-flight load) if host available RAM stays under the floor for 3 s
  unload                       unload whatever is resident (by the status identifier) and confirm
  remove MODEL                 delete the stored override

MODEL is the Unsloth id with quant, e.g. lmstudio-community/Ministral-3-3B-Instruct-2512-GGUF:Q6_K
(see `list`). The key is read from the-array/.env (UNSLOTH_PC_API_KEY) and never printed.

Facts this tool relies on (OP UNSLOTH ALPHA, 2026-09-23; plan section 6):
- Overrides are keyed "<advertised id>:<QUANT>" (case-folded); auto-switch loads resolve them.
- Default auto-fit left only 661-689 MiB free with ~0.7 GiB spilled to shared memory, and qwen decode swung
  between ~7 and 55 tok/s (the code-read reserve at 0.98 is ~246 MiB of nvidia-smi free): pin context instead.
- Unload works only with model_identifier from /api/inference/status; any other name returns a false "unloaded".
- plan: CPU experts are proposed only when a MoE model does not fit whole. KV is priced like Unsloth's own
  _estimate_kv_cache_bytes (one unified slot): global layers per token, sliding-window layers as a fixed
  window + 512-token micro-batch, shared-KV layers free. apply writes only the flags you pass.
- GPU mode (Unsloth llama_cpp.py): auto_fit = gpu_memory_mode == "manual" and gpu_layers < 0, so Manual with -1
  runs llama.cpp's fitter. Auto with a pinned context that fits launched `-ngl -1 --fit off` (ALPHA, qwen and
  ministral); when Auto cannot prove a fit it spills weight tensors and keeps KV on the GPU. Manual with
  gpu_layers >= 0 emits `--gpu-layers N --fit off` (source-read; check with `verify`).
- Auto proves fits against the global VRAM budget (Settings slider, /api/settings/vram-budget): Unsloth keeps
  max((1 - fraction) x card, min(512, 3% of card)) of nvidia-smi's memory.free, which already leaves out the
  driver's reserved memory (239 MiB on this card; llama_cpp.py _vram_usable_mib). This script counts free as
  total - used, which includes it, so by this script's measure a budget keeps its reserve + 239 MiB:
  0.98 ~485 MiB, 0.95 ~648, 0.904 ~1,025 (the 1 GiB rule), 0.875 ~1,263.
"""
import argparse, json, os, re, struct, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

BASE = os.environ.get("UNSLOTH_BASE", "http://127.0.0.1:8888")
ENV = Path(__file__).resolve().parent.parent / ".env"
HOME = Path(os.environ.get("USERPROFILE", str(Path.home())))
SEARCH_ROOTS = [HOME / ".lmstudio" / "models", HOME / ".cache" / "huggingface" / "hub", HOME / ".unsloth" / "studio" / "models"]
MIB = 1024 * 1024


# ---------------------------------------------------------------- http
def _key() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*UNSLOTH_PC_API_KEY\s*=\s*(.*)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    sys.exit("UNSLOTH_PC_API_KEY not found in .env")


def call(method, path, body=None, timeout=900):
    k = _key()
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + k, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    txt = raw.decode("utf-8", "replace").replace(k, "<KEY>")
    try:
        return status, json.loads(txt)
    except ValueError:
        return status, {"raw": txt[:500]}


def split_model(model: str):
    m = re.match(r"^(.*?):([A-Za-z0-9_.-]+)$", model)
    return (m.group(1), m.group(2)) if m else (model, None)


# ---------------------------------------------------------------- GGUF header (metadata only)
_T = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


def gguf_meta(path: Path) -> dict:
    meta = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(f"not a GGUF file: {path}")
        version, = struct.unpack("<I", f.read(4))
        n_tensors, n_kv = struct.unpack("<QQ", f.read(16))

        def rstr():
            n, = struct.unpack("<Q", f.read(8))
            return f.read(n).decode("utf-8", "replace")

        def rval(t):
            if t == 8:
                return rstr()
            if t == 9:
                at, = struct.unpack("<I", f.read(4))
                cnt, = struct.unpack("<Q", f.read(8))
                if at == 8:  # string arrays (tokenizer vocab): skip contents, keep the length
                    for _ in range(cnt):
                        n, = struct.unpack("<Q", f.read(8)); f.seek(n, 1)
                    return f"<{cnt} strings>"
                fmt = _T[at]; sz = struct.calcsize(fmt)
                if cnt > 4096:
                    f.seek(sz * cnt, 1)
                    return f"<{cnt} values>"
                return [struct.unpack(fmt, f.read(sz))[0] for _ in range(cnt)]
            fmt = _T[t]
            return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]

        for _ in range(n_kv):
            k = rstr()
            t, = struct.unpack("<I", f.read(4))
            meta[k] = rval(t)
    meta["_gguf_version"], meta["_n_tensors"] = version, n_tensors
    return meta


def is_drafter(p: Path) -> bool:
    """A separate MTP drafter, named the way Unsloth's _is_mtp_only_drafter_path matches it (mtp-*.gguf, *-MTP.gguf)."""
    n = p.name.lower()
    return n.startswith("mtp-") or re.sub(r"-\d{5}-of-\d{5}$", "", p.stem.lower()).endswith("-mtp") or p.parent.name.lower() == "mtp"


def find_drafter(model: str):
    """The separate MTP drafter beside a model, if any. Unsloth's auto speculative mode loads it next to the
    weights (Gemma 4 publishes one); a model with the head embedded in its own GGUF has none."""
    w, _, _ = find_files(model)
    return next((c for c in sorted(w.parent.rglob("*.gguf")) if is_drafter(c)), None)


def find_files(model: str):
    """(weights .gguf, mmproj .gguf or None, weights bytes) for an Unsloth id, from LM Studio's folder or the HF cache."""
    repo, quant = split_model(model)
    pub, _, name = repo.partition("/")
    cands = []
    lm = SEARCH_ROOTS[0] / pub / name
    if lm.is_dir():
        cands += list(lm.glob("*.gguf"))
    hf = SEARCH_ROOTS[1] / f"models--{pub}--{name}" / "snapshots"
    if hf.is_dir():
        cands += list(hf.glob("*/**/*.gguf")) + list(hf.glob("*/*.gguf"))
    if not cands:
        sys.exit(f"no local GGUF found for {repo} under {SEARCH_ROOTS[0]} or the HF cache")
    mmproj = next((c for c in cands if "mmproj" in c.name.lower()), None)
    weights = [c for c in cands if "mmproj" not in c.name.lower() and not is_drafter(c)
               and not re.search(r"(^|[._-])imatrix([._-]|$)", c.stem.lower())]
    if quant:
        q = [c for c in weights if quant.lower() in c.name.lower()]
        weights = q or weights
    if len(weights) > 1:
        parts = [c for c in weights if re.search(r"-0000[1-9]-of-", c.name)]
        weights = sorted(parts)[:1] if parts else sorted(weights, key=lambda p: p.stat().st_size)[:1]
    total = sum(p.stat().st_size for p in weights[0].parent.glob(re.sub(r"-0000\d-of-", "-*-of-", weights[0].name)))
    return weights[0], mmproj, total


KV_BPE = {"f16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32}
SWA_PERIOD = {"gemma2": 2, "gemma3": 6, "gemma3n": 5, "gpt-oss": 2, "gpt_oss": 2, "cohere2": 4}  # Unsloth's own defaults
UBATCH = 512


def kv_profile(meta: dict) -> dict:
    """KV cost the way Unsloth's _estimate_kv_cache_bytes prices it for one unified slot.

    Global (full-attention) layers grow per token; sliding-window layers hold a fixed window + one micro-batch,
    padded to 256 cells; the trailing shared_kv_layers (Gemma 3n / Gemma 4) allocate nothing."""
    a = meta.get("general.architecture", "?")
    g = lambda k, d=None: meta.get(f"{a}.{k}", d)
    n_layer = int(g("block_count", 0))
    heads = g("attention.head_count", 0)
    kvh = g("attention.head_count_kv", heads)
    emb = int(g("embedding_length", 0))
    hd_default = emb // (heads if isinstance(heads, int) and heads else 1) if emb else 128
    kl, vl = int(g("attention.key_length", hd_default)), int(g("attention.value_length", hd_default))
    kl_swa, vl_swa = int(g("attention.key_length_swa", kl)), int(g("attention.value_length_swa", vl))
    per_layer_kvh = kvh if isinstance(kvh, list) else [kvh] * n_layer
    shared = int(g("attention.shared_kv_layers", 0) or 0)
    n_kv_layers = max(1, n_layer - shared)
    note = []
    if shared:
        note.append(f"last {shared} layers reuse earlier KV (no cache of their own)")
    swa = int(g("attention.sliding_window", 0) or 0)
    pattern = g("attention.sliding_window_pattern")
    if swa and not isinstance(pattern, list):
        period = SWA_PERIOD.get(a)
        pattern = [(i + 1) % period != 0 for i in range(n_layer)] if period else None
        note.append(f"sliding window {swa}: " + (f"pattern from the {a} default (every {period}th layer global)"
                                                  if pattern else "no pattern known, priced as full attention"))
    interval = g("full_attention_interval")
    glob_elems = swa_elems = 0  # per-token elements on global layers / per-cell elements on SWA layers
    attn_layers = 0
    for i in range(n_kv_layers):
        h = per_layer_kvh[i] if i < len(per_layer_kvh) else per_layer_kvh[-1]
        if not h:
            continue
        if interval and not isinstance(kvh, list) and (i + 1) % int(interval) != 0:
            continue  # recurrent layer of a hybrid: constant state, no KV
        attn_layers += 1
        if swa and pattern and i < len(pattern) and pattern[i]:
            swa_elems += h * (kl_swa + vl_swa)
        else:
            glob_elems += h * (kl + vl)
    if interval and not isinstance(kvh, list):
        note.append(f"hybrid: 1 attention layer per {interval} (recurrent state not counted)")
    swa_cells = ((swa + UBATCH + 255) // 256) * 256 if swa_elems else 0
    return {
        "arch": a, "layers": n_layer, "attention_layers": attn_layers, "kv_heads": per_layer_kvh[:1] if per_layer_kvh else None,
        "key_len": kl, "value_len": vl, "ctx_train": g("context_length"), "experts": g("expert_count"),
        "experts_used": g("expert_used_count"), "vocab": meta.get("tokenizer.ggml.tokens"), "nextn": g("nextn_predict_layers"),
        "kv_bytes_per_token": {t: int(glob_elems * b) for t, b in KV_BPE.items()},
        "kv_fixed_bytes": {t: int(swa_elems * swa_cells * b) for t, b in KV_BPE.items()},
        "notes": note,
    }


# ---------------------------------------------------------------- GPU / process helpers
def vram():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.split(",")
    used, total = int(out[0]), int(out[1])
    return used, total, total - used


def driver_reserved_mib():
    """VRAM the driver reserves (nvidia-smi memory.reserved): outside nvidia-smi's memory.free, which Unsloth
    budgets against, but inside the total - used that vram() reports."""
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.reserved", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip()
    try:
        return int(out.splitlines()[0])
    except (ValueError, IndexError):
        return 0


def host_mem():
    """(available physical MiB, commit % of the commit limit). CPU-MoE and spill rows put weights in host RAM,
    which is shared with the Docker VM: low Available is the Docker-wedge precondition."""
    import ctypes

    class _MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                   [(n, ctypes.c_ulonglong) for n in ("total_phys", "avail_phys", "total_commit", "avail_commit",
                                                     "total_virtual", "avail_virtual", "avail_ext_virtual")]
    s = _MS(); s.dwLength = ctypes.sizeof(_MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s.avail_phys // MIB, round(100 * (s.total_commit - s.avail_commit) / s.total_commit)


def child():
    ps = ("$p=Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | ? { $_.ExecutablePath -like '*\\.unsloth\\*' };"
          "if($p){$s=0;(Get-Counter '\\GPU Process Memory(*)\\Shared Usage' -ErrorAction SilentlyContinue).CounterSamples | ? { $_.InstanceName -like ('pid_'+$p.ProcessId+'_*') } | % { $s+=$_.CookedValue };"
          "$q=Get-Process -Id $p.ProcessId;"
          "@{pid=$p.ProcessId;cmd=$p.CommandLine;shared_mib=[int]($s/1MB);private_mib=[int]($q.PrivateMemorySize64/1MB);ws_mib=[int]($q.WorkingSet64/1MB)} | ConvertTo-Json -Compress}")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    return json.loads(r) if r else None


def unload_resident():
    s, st = call("GET", "/api/inference/status", timeout=30)
    if not st.get("loaded"):
        return "nothing loaded"
    ident = st.get("model_identifier") or st.get("active_model")
    call("POST", "/api/inference/unload", {"model_path": ident}, timeout=120)
    time.sleep(3)
    s, st = call("GET", "/api/inference/status", timeout=30)
    return "unloaded" if not st.get("loaded") else f"STILL LOADED: {st.get('loaded')}"


# ---------------------------------------------------------------- commands
def cmd_list(_):
    s, d = call("GET", "/v1/models", timeout=60)
    for m in d.get("data", []):
        print(f"{m['id']}:{m.get('quant')}".ljust(78), "loaded" if m.get("loaded") else "", m.get("task", ""))
    s, o = call("GET", "/api/settings/openai-auto-switch/overrides", timeout=30)
    print("\nstored overrides:", json.dumps(o.get("overrides", {}), indent=1) if o.get("overrides") else "none")


def cmd_inspect(a):
    w, mm, total = find_files(a.model)
    prof = kv_profile(gguf_meta(w))
    dr = find_drafter(a.model)
    prof.update({"weights_file": str(w), "weights_mib": total // MIB, "mmproj_file": str(mm) if mm else None,
                 "mmproj_mib": mm.stat().st_size // MIB if mm else 0,
                 "drafter_file": str(dr) if dr else None, "drafter_mib": dr.stat().st_size // MIB if dr else 0})
    print(json.dumps(prof, indent=1))
    return prof


def cmd_plan(a):
    w, mm, total = find_files(a.model)
    prof = kv_profile(gguf_meta(w))
    used, cap, free = vram()
    s, st = call("GET", "/api/inference/status", timeout=30)
    if st.get("loaded"):
        print(f"note: {st.get('loaded')} is resident in Unsloth; free VRAM below excludes it, so plan with nothing loaded for accuracy")
    weights, mmp = total // MIB, (mm.stat().st_size // MIB if mm else 0)
    compute = a.compute
    fixed = prof["kv_fixed_bytes"][a.kv] // MIB  # sliding-window cache, independent of context
    dr = find_drafter(a.model)
    # Auto speculative mode loads a separate drafter beside the weights; its own KV comes on top (verify measures it)
    mmp += dr.stat().st_size // MIB if dr else 0
    budget = free - a.reserve - weights - mmp - compute - fixed
    kv = prof["kv_bytes_per_token"][a.kv]
    rec = {"model_id": a.model, "kv_cache_dtype": a.kv, "llama_extra_args": ["--threads", str(a.threads)]}
    lines = [f"card {cap} MiB, used now {used} MiB (desktop + anything resident), free {free} MiB",
             f"weights {weights} MiB + mmproj/drafter {mmp} MiB + compute ~{compute} MiB + reserve {a.reserve} MiB"
             + (f" + sliding-window KV {fixed} MiB" if fixed else "")]
    ctx = min(int(budget * MIB / kv) // 1024 * 1024, int(prof["ctx_train"] or 1 << 20), a.max_ctx) if budget > 0 and kv else 0
    if ctx >= a.min_ctx:  # fits whole with at least the minimum context
        # No GPU-mode fields: Auto with a pinned context launches `-ngl -1 --fit off` when it fits (ALPHA).
        # Manual with gpu_layers -1 would hand placement to llama.cpp's fitter instead (llama_cpp.py auto_fit).
        rec.update({"max_seq_length": ctx})
        lines.append(f"KV {a.kv} = {kv / 1024:.1f} KiB/token -> context {ctx} fits fully on GPU")
    elif prof["experts"]:
        overflow = -budget + a.min_ctx * kv / MIB
        per_layer = weights * 0.9 / max(prof["layers"], 1)  # expert tensors dominate an MoE file
        k = min(prof["layers"], int(overflow / per_layer) + 1)
        # Manual mode, every layer requested (above the block count so the output layer is covered), experts of k on CPU
        rec.update({"max_seq_length": a.min_ctx, "n_cpu_moe": k, "gpu_memory_mode": "manual", "gpu_layers": prof["layers"] + 1})
        lines.append(f"MoE with {prof['experts']} experts: does not fit whole; experts of {k}/{prof['layers']} layers on CPU "
                     f"(estimate), context {a.min_ctx}. Expect host-RAM use of ~{int(k * per_layer)} MiB (mlocked while Keep resident is on)")
    else:
        # Auto, when it cannot prove a fit, spills weight TENSORS and keeps the KV cache on the GPU (llama_cpp.py; the
        # source measured 13.63 vs 1.03 t/s against whole-layer offload on a 27B at 128K). Manual --gpu-layers N moves
        # whole layers, and their KV goes with them. Auto sizes against Unsloth's VRAM budget, so that budget is what
        # decides whether the >= reserve rule holds (see the budget line below).
        per_layer = weights / max(prof["layers"], 1)
        room = free - a.reserve - mmp - compute - fixed - (a.min_ctx * kv / MIB if kv else 0)
        n = max(0, min(prof["layers"], int(room / per_layer)))
        rec.update({"max_seq_length": a.min_ctx})
        lines.append(f"dense model larger than free VRAM: proposing Auto at context {a.min_ctx}, which spills weight tensors "
                     f"and keeps KV on the GPU. Alternative for an exact placement: --gpu-layers {n} (of {prof['layers']}; "
                     f"whole layers and their KV on CPU, slower). A smaller quant that fits whole is usually the better pick")
    s, vb = call("GET", "/api/settings/vram-budget", timeout=30)
    if s == 200:
        # Unsloth's reserve comes off nvidia-smi's memory.free, which excludes the driver-reserved memory;
        # this plan's free is total - used, which includes it, so add it back to compare like with like.
        drv = driver_reserved_mib()
        keep = max((1 - vb["fraction"]) * cap, min(512, (1 - vb["default_fraction"]) * cap)) + drv
        lines.append(f"Unsloth VRAM budget {vb['fraction']} -> its own fits keep ~{int(keep)} MiB free by this plan's measure "
                     f"(its reserve + the driver's {drv} MiB)"
                     + (f"; below this plan's {a.reserve}, a budget of {round(1 - (a.reserve - drv) / cap, 3)} matches it"
                        if keep < a.reserve else ""))
    if dr:
        lines.append(f"separate MTP drafter {dr.name} ({dr.stat().st_size // MIB} MiB) counted above: Unsloth's auto "
                     "speculative mode loads it; its draft KV is extra, so leave margin")
    elif prof["nextn"]:
        lines.append(f"embedded MTP head ({prof['nextn']} layer): auto speculative mode may add a draft context on top")
    print("\n".join(lines))
    for n in prof["notes"]:
        print("note:", n)
    print("\nproposed override (apply with the `apply` command, then `verify`):")
    print(json.dumps(rec, indent=1))
    return rec


def cmd_apply(a):
    body = {"model_id": a.model, "max_seq_length": a.ctx, "kv_cache_dtype": a.kv}
    extra = ["--threads", str(a.threads)] + (["--no-kv-offload"] if a.no_kv_offload else []) + (a.extra or [])
    body["llama_extra_args"] = extra
    # MoE CPU layers need Manual GPU mode. Manual with gpu_layers < 0 hands placement to llama.cpp's fitter
    # (--fit on), so request every layer explicitly instead (999 is above any block count; llama.cpp clamps it).
    if a.gpu_layers is not None and a.gpu_layers < 0:
        sys.exit("--gpu-layers must be >= 0 (Manual mode with -1 turns llama.cpp's fitter on); omit it for Auto")
    if a.n_cpu_moe is not None:
        body.update({"n_cpu_moe": a.n_cpu_moe, "gpu_memory_mode": "manual", "gpu_layers": 999 if a.gpu_layers is None else a.gpu_layers})
        print("note: with Keep resident ON, the experts placed on CPU are mlocked in host RAM. Check host Available and "
              "commit against their size (and LM Studio's residue) before verify.", file=sys.stderr)
    elif a.gpu_layers is not None:
        body.update({"gpu_memory_mode": "manual", "gpu_layers": a.gpu_layers})
    if a.parallel is not None:
        body["n_parallel"] = a.parallel
    print(json.dumps(body, indent=1))
    if a.dry_run:
        return
    s, d = call("PUT", "/api/settings/openai-auto-switch/overrides", body, timeout=30)
    print("HTTP", s, "| stored keys:", list((d.get("overrides") or {}).keys()) if s == 200 else d)
    cmd_show(a)


def cmd_show(a):
    repo, quant = split_model(a.model)
    q = f"?model_id={urllib.request.quote(repo)}&alias_id={urllib.request.quote(repo)}" + (f"&gguf_variant={quant}" if quant else "")
    s, d = call("GET", "/api/settings/openai-auto-switch/overrides" + q, timeout=30)
    print("a load of", a.model, "applies key", d.get("resolved_key"), "->", json.dumps(d.get("resolved"), indent=1))


def _toks(model, runs):
    """Decode tok/s from a streamed response (Unsloth's plain chat path returns no engine timings)."""
    prompt = "Write a detailed, multi-paragraph essay (at least 450 words) on the history of the printing press. Do not use lists."
    rates = []
    for i in range(runs):
        body = {"model": model, "messages": [{"role": "user", "content": prompt + f" ({i})"}], "max_tokens": 400,
                "temperature": 0.7, "stream": True, "stream_options": {"include_usage": True}}
        req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"})
        first = last = None
        n = None
        with urllib.request.urlopen(req, timeout=900) as r:
            for line in r:
                line = line.decode("utf-8", "replace").strip()
                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                    continue
                d = json.loads(line[5:])
                if d.get("usage"):
                    n = d["usage"].get("completion_tokens")
                for ch in d.get("choices") or []:
                    delta = ch.get("delta") or {}
                    if delta.get("content") or delta.get("reasoning_content"):
                        last = time.time()
                        first = first or last
        rates.append(round((n - 1) / (last - first), 1) if n and first and last > first else None)
    return rates


def _ram_watchdog(floor_mib):
    """Background guard for loads that put weights in host RAM: if Available stays under the floor for 3 s, unload
    the resident model, and kill the llama-server child if a load is still in flight (unload cannot cancel a load).
    Returns the Event that stops it."""
    import threading
    stop = threading.Event()

    def watch():
        low = 0
        while not stop.wait(1):
            avail, _ = host_mem()
            low = low + 1 if avail < floor_mib else 0
            if low >= 3:
                res = unload_resident()
                c = child()
                if c:
                    subprocess.run(["taskkill", "/F", "/PID", str(c["pid"])], capture_output=True)
                print(f"RAM FLOOR: host available {avail} MiB < {floor_mib} for 3 s -> unload: {res}"
                      + (f"; killed llama-server {c['pid']}" if c else ""), flush=True)
                stop.set()
    threading.Thread(target=watch, daemon=True).start()
    return stop


def cmd_verify(a):
    b_used, cap, b_free = vram()
    h_avail, h_commit = host_mem()
    print(f"before: VRAM free {b_free} MiB | host available {h_avail} MiB, commit {h_commit}%")
    guard = _ram_watchdog(a.ram_floor) if a.ram_floor else None
    try:
        _verify_body(a, h_avail)
    finally:
        if guard:
            guard.set()


def _verify_body(a, h_avail):
    t0 = time.time()
    # 256, not 12: models that start with reasoning on (Gemma 4) spend a small budget thinking and return empty content
    s, d = call("POST", "/v1/chat/completions", {"model": a.model, "messages": [{"role": "user", "content": "Reply with exactly: CONFIG-OK"}],
                                                 "max_tokens": 256, "temperature": 0}, timeout=900)
    print(f"load+answer: HTTP {s} in {time.time() - t0:.1f}s, model={d.get('model')}, content={((d.get('choices') or [{}])[0].get('message') or {}).get('content')!r}")
    c = child()
    used, cap, free = vram()
    h_avail2, h_commit2 = host_mem()
    if c:
        flags = re.findall(r"(-c \d+|--cache-type-[kv] \S+|-ngl \S+|--gpu-layers \d+|--n-cpu-moe \d+|--threads \d+|--parallel \d+|--mmproj|--no-kv-offload|--fit \S+|--reasoning \S+|--load-mode \S+"
                           r"|--mlock|--no-mmap|--direct-io|--spec-\S+|-md \S+|--model-draft \S+|--cache-ram \d+)", c["cmd"])
        n_ot = len(re.findall(r"(?:^|\s)(?:-ot|--override-tensor)\s", c["cmd"]))
        print("llama-server flags:", " ".join(flags) + (f" (+{n_ot} tensor overrides)" if n_ot else ""))
        print(f"after load: VRAM free {free} MiB, child shared (WDDM spill) {c['shared_mib']} MiB | host available {h_avail2} MiB "
              f"({h_avail2 - h_avail:+d}), commit {h_commit2}%, child private {c['private_mib']} MiB, working set {c['ws_mib']} MiB")
        # Shared GPU memory is not spill by itself: --load-mode none showed ~600 MiB at full speed (ALPHA ab-logs), and
        # gemma-4-E2B + MTP drafter showed 1,916 MiB at 113-130 tok/s with 2.4 GB of VRAM free (09-23). Spill is when
        # dedicated VRAM runs out, so the free figure decides; a large shared figure only matters next to low free VRAM.
        if free < 1024:
            print("WARNING: under 1 GiB free -> lower the context or move experts to CPU")
        elif c["shared_mib"] > 900 and free < 1536:
            print("WARNING: shared GPU memory above 900 MiB with little VRAM headroom -> check tok/s for spill")
        if h_avail2 < 4096:
            print("WARNING: host available RAM under 4 GiB with the model loaded (the Docker-wedge precondition) -> unload, "
                  "check LM Studio residue, or keep fewer weights in host RAM")
    if a.runs:
        print("decode tok/s:", _toks(a.model, a.runs))
    if not a.keep:
        print("unload:", unload_resident())


def cmd_remove(a):
    s, d = call("PUT", "/api/settings/openai-auto-switch/overrides", {"model_id": a.model, "remove": True}, timeout=30)
    print("HTTP", s, "| removed:", d.get("removed_keys"), "| remaining:", list((d.get("overrides") or {}).keys()))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("list")
    sp.add_parser("unload")
    for name in ("inspect", "show", "remove"):
        sp.add_parser(name).add_argument("model")
    pl = sp.add_parser("plan"); pl.add_argument("model")
    pl.add_argument("--reserve", type=int, default=1024, help="MiB of VRAM to leave free (default 1024)")
    pl.add_argument("--compute", type=int, default=512, help="MiB estimate for llama.cpp compute buffers")
    pl.add_argument("--kv", default="q8_0", choices=["f16", "q8_0", "q4_0"])
    pl.add_argument("--threads", type=int, default=8)
    pl.add_argument("--max-ctx", type=int, default=131072)
    pl.add_argument("--min-ctx", type=int, default=8192)
    ap = sp.add_parser("apply"); ap.add_argument("model"); ap.add_argument("--ctx", type=int, required=True)
    ap.add_argument("--kv", default="q8_0", choices=["f16", "q8_0", "q4_0"]); ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--n-cpu-moe", type=int); ap.add_argument("--gpu-layers", type=int); ap.add_argument("--parallel", type=int)
    ap.add_argument("--no-kv-offload", action="store_true"); ap.add_argument("--extra", nargs="*"); ap.add_argument("--dry-run", action="store_true")
    vp = sp.add_parser("verify"); vp.add_argument("model"); vp.add_argument("--runs", type=int, default=3); vp.add_argument("--keep", action="store_true")
    vp.add_argument("--ram-floor", type=int, default=3000,
                    help="MiB of host available RAM that triggers an unload during verify (0 = off); the Docker-wedge guard")
    a = p.parse_args()
    {"list": cmd_list, "inspect": cmd_inspect, "plan": cmd_plan, "apply": cmd_apply, "show": cmd_show,
     "verify": cmd_verify, "remove": cmd_remove, "unload": lambda _: print("unload:", unload_resident())}[a.cmd](a)


if __name__ == "__main__":
    main()
