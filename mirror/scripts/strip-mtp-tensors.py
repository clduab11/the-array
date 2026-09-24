#!/usr/bin/env python3
"""
strip-mtp-tensors.py — remove `mtp.*` (multi-token-prediction draft-head) tensors from an
MLX safetensors repo whose strict engine loader refuses them.

BORN 2026-08-08 for imac-qwen3.5-9b (qwen3.5-9b-optiq): the OptiQ export ships qwen3.5 MTP
draft-head tensors (mtp.layers.0.*, mtp.norm, ...) and LM Studio's MLX engine — CONFIRMED
CURRENT at v1.11.0 — still rejects them in strict load_weights on the mlx_vlm path (the repo
declares a vision config, which forces that path). MTP is a self-speculative-decode head; it
is INFERENCE-INERT under an engine that can't map it, so stripping loses nothing that works
today. (A future engine that learns qwen3.5 MTP would want the original back — re-pull from
HF to restore; this script also keeps .bak files until you delete them.)

RUN ON THE BOX THAT HOLDS THE REPO (for the 9B: the iMac — LM Link does not carry file ops):

    lms unload --all                       # free memory first (models unloaded, not deleted)
    pip3 install mlx                       # if not already present (Apple silicon)
    python3 strip-mtp-tensors.py ~/.lmstudio/models/<publisher>/<repo-dir>
    # dry run first (default). Then apply:
    python3 strip-mtp-tensors.py ~/.lmstudio/models/<publisher>/<repo-dir> --apply

Needs free disk >= the largest shard (stripped copy is written alongside before the atomic
swap; originals stay as *.bak.pre-mtp-strip until you delete them after a verified load).
Subdirectories (e.g. an optiq/ vision-tower dir) are untouched — top-level shards only.
After --apply: reload the model (lms load <id>, or one probe from the proxy) to verify,
then delete the .bak files. If config.json declares MTP layers (any key containing 'mtp'
or 'nextn'), the loader may EXPECT the tensors — the script reports such keys and removes
them only with --fix-config (config.json gets its own .bak first).
"""

import argparse
import json
import sys
from pathlib import Path

PREFIX = "mtp."


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def main() -> int:
    ap = argparse.ArgumentParser(description="Strip mtp.* tensors from an MLX safetensors repo")
    ap.add_argument("repo", help="Path to the model repo dir (holds *.safetensors + config.json)")
    ap.add_argument("--apply", action="store_true", help="Actually write changes (default: dry run)")
    ap.add_argument("--fix-config", action="store_true",
                    help="Also remove mtp/nextn keys from config.json (backed up first)")
    args = ap.parse_args()

    try:
        import mlx.core as mx  # noqa: deferred so --help works anywhere
    except ImportError:
        print("ERROR: mlx not installed. Run: pip3 install mlx  (Apple silicon only)")
        return 2

    root = Path(args.repo).expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}")
        return 2

    shards = sorted(p for p in root.glob("*.safetensors"))  # top-level only, subdirs untouched
    if not shards:
        print(f"ERROR: no *.safetensors at top level of {root}")
        return 2

    total_stripped = 0
    stripped_keys: list[str] = []

    for shard in shards:
        weights, metadata = mx.load(str(shard), return_metadata=True)
        bad = sorted(k for k in weights if k.startswith(PREFIX))
        if not bad:
            print(f"[skip] {shard.name}: no {PREFIX}* tensors")
            continue
        bad_bytes = sum(weights[k].nbytes for k in bad)
        total_stripped += bad_bytes
        stripped_keys.extend(bad)
        print(f"[hit]  {shard.name}: {len(bad)} {PREFIX}* tensors, {human(bad_bytes)}")
        if args.apply:
            kept = {k: v for k, v in weights.items() if not k.startswith(PREFIX)}
            tmp = shard.with_name(shard.name + ".stripped")
            mx.save_safetensors(str(tmp), kept, metadata=metadata or {})
            bak = shard.with_name(shard.name + ".bak.pre-mtp-strip")
            shard.rename(bak)
            tmp.rename(shard)
            print(f"       -> rewritten; original kept as {bak.name}")

    if not stripped_keys:
        print("Nothing to strip — repo is already clean.")
        return 0

    index = root / "model.safetensors.index.json"
    if index.exists():
        idx = json.loads(index.read_text())
        wm = idx.get("weight_map", {})
        gone = [k for k in wm if k.startswith(PREFIX)]
        print(f"[idx]  {index.name}: {len(gone)} weight_map entries to drop")
        if args.apply and gone:
            for k in gone:
                del wm[k]
            if "metadata" in idx and "total_size" in idx["metadata"]:
                idx["metadata"]["total_size"] = max(0, idx["metadata"]["total_size"] - total_stripped)
            bak = index.with_name(index.name + ".bak.pre-mtp-strip")
            index.rename(bak)
            index.write_text(json.dumps(idx, indent=2))
            print(f"       -> rewritten; original kept as {bak.name}")

    cfg = root / "config.json"
    if cfg.exists():
        conf = json.loads(cfg.read_text())
        suspect = [k for k in conf if "mtp" in k.lower() or "nextn" in k.lower()]
        if suspect:
            print(f"[cfg]  config.json declares MTP-ish keys: {suspect}")
            if args.apply and args.fix_config:
                for k in suspect:
                    del conf[k]
                bak = cfg.with_name("config.json.bak.pre-mtp-strip")
                cfg.rename(bak)
                cfg.write_text(json.dumps(conf, indent=2))
                print(f"       -> removed; original kept as {bak.name}")
            elif suspect:
                print("       (left in place — rerun with --apply --fix-config if the load still fails)")
        else:
            print("[cfg]  config.json: no mtp/nextn keys — good")

    mode = "APPLIED" if args.apply else "DRY RUN (rerun with --apply)"
    print(f"\n{mode}: {len(stripped_keys)} tensors / {human(total_stripped)} across {len(shards)} shard(s).")
    if args.apply:
        print("Next: reload the model (lms load <id> or one proxy probe); after a clean load,")
        print("delete the *.bak.pre-mtp-strip files to reclaim disk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
