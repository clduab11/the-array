#!/usr/bin/env python3
"""sync-venice-pricing.py — inject/refresh per-entry custom pricing on every
Venice-pinned entry in litellm_config.yaml so venice spend falls under proxy
governance (budgets + SpendLogs + Grafana Spend panels).

WHY: LiteLLM's built-in cost map has no Venice model ids -> spend computes to
$0 for all venice routes. LiteLLM's documented fix is custom pricing on the
entry: litellm_params.input_cost_per_token / output_cost_per_token.

SOURCE OF TRUTH: live https://api.venice.ai/api/v1/models pricing
(model_spec.pricing.{input,output,cache_input,cache_write}.usd, per MILLION
tokens). Venice rotates models AND prices — re-run this script periodically
(it is idempotent: existing pricing lines are updated in place, comments
preserved).

v2 (2026-10-01, config v4.21.0):
  - also injects cache_read_input_token_cost / cache_creation_input_token_cost
    where Venice publishes cache_input / cache_write. Without them LiteLLM
    priced Venice cached tokens at $0 (probed 2026-10-01: a cached call on
    e2ee-glm-5-3-p logged 14% of its real cost).
  - an entry whose upstream id left the live catalog KEEPS its last synced
    price lines (a delisted id can still serve on grace, and stripping its
    price would meter it at $0). It is reported, never deleted.
  - prints every price that moved (old -> new) so a currency pass sees drift.
  - reads/writes UTF-8 with LF endings on every platform.
NOT covered: Venice's `extended` long-context tier (per-model token threshold).

USAGE:  python scripts/sync-venice-pricing.py [--dry-run] [--config litellm_config.yaml.next]
        (reads VENICE_API_KEY from the environment, else from ./.env; never prints it)
        Prefer --config on the staged copy, then swap it in and restart in one command. Without --config this script
        writes the LIVE config, and the running proxy drops every entry whose price lines changed within ~30 s
        (docs/rules/litellm.md): restart AT ONCE, and run `python scripts/route-resolve.py` afterwards.

Text-surgery on purpose: pyyaml round-trip would destroy the config's
comments. Venice no-auto-cull rule: flag, never delete.
"""
import json, os, re, sys, urllib.request
from datetime import date

# --config PATH prices a staged copy (litellm_config.yaml.next) instead of the live file: the staged way (DEPLOY_PLAYBOOK §5).
CONFIG = (sys.argv[sys.argv.index('--config') + 1] if '--config' in sys.argv
          else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'litellm_config.yaml'))
DRY = '--dry-run' in sys.argv
MARK = 'venice-price-sync'
# litellm_params key -> Venice pricing key
FIELDS = (('input_cost_per_token', 'input'), ('output_cost_per_token', 'output'),
          ('cache_read_input_token_cost', 'cache_input'), ('cache_creation_input_token_cost', 'cache_write'))
# Any existing line for a synced key, marked or hand-written: on a matched entry the sync is authoritative, so all of
# them are replaced (four v4.13.5 entries carried unmarked price lines and ended up with duplicate YAML keys).
PRICED = re.compile(r'^      (' + '|'.join(k for k, _ in FIELDS) + r'):\s*([0-9.eE+-]+)')


def venice_key():
    k = os.environ.get('VENICE_API_KEY')
    if k:
        return k
    envp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
    for line in open(envp, encoding='utf-8', errors='replace'):
        if line.startswith('VENICE_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    sys.exit('VENICE_API_KEY not found (env or ./.env)')


def live_pricing():
    req = urllib.request.Request('https://api.venice.ai/api/v1/models',
                                 headers={'Authorization': f'Bearer {venice_key()}'})
    data = json.load(urllib.request.urlopen(req, timeout=30))['data']
    out = {}
    for m in data:
        pr = (m.get('model_spec') or {}).get('pricing') or {}
        row = {vk: (pr.get(vk) or {}).get('usd') for _, vk in FIELDS}
        if row['input'] is not None and row['output'] is not None:
            out[m['id']] = {k: (None if v is None else float(v)) for k, v in row.items()}  # USD per 1M tokens
    return out


def main():
    prices = live_pricing()
    lines = open(CONFIG, encoding='utf-8', newline='').read().split('\n')
    stamp = date.today().isoformat()

    # split into model_list entry blocks; everything before the first entry is the head
    starts = [i for i, ln in enumerate(lines) if re.match(r'^  - model_name:', ln)]
    blocks = [lines[:starts[0]]] + [lines[a:b] for a, b in zip(starts, starts[1:] + [len(lines)])]

    out, priced, kept, moved = list(blocks[0]), [], [], []
    for blk in blocks[1:]:
        name = re.match(r'^  - model_name:\s*"?([^"#\s]+)', blk[0]).group(1)
        upstream, is_venice, key_at = None, False, None
        for j, ln in enumerate(blk):
            mm = re.match(r'^      model: "?openai/(.+?)"?\s*(#.*)?$', ln)
            if mm:
                upstream = mm.group(1)
            if re.match(r'^      api_base: .*api\.venice\.ai', ln):
                is_venice = True
            if re.match(r'^      api_key: os\.environ/VENICE_API_KEY', ln) and key_at is None:
                key_at = j
        if not (is_venice and upstream and key_at is not None):
            out.extend(blk)
            continue
        old = {m.group(1): float(m.group(2)) for m in map(PRICED.match, blk) if m}
        if upstream not in prices:
            kept.append((name, upstream, old))
            out.extend(blk)          # keep the last synced price: a delisted id may still serve on grace
            continue
        new = {lk: prices[upstream][vk] for lk, vk in FIELDS if prices[upstream][vk] is not None}
        inject = [f'      {lk}: {v / 1e6:.12f}   # ${v:g}/M {MARK} {stamp}' for lk, v in new.items()]   # 12 decimals: cache prices go below $0.01/M
        body = [ln for ln in blk if not PRICED.match(ln)]
        at = next(j for j, ln in enumerate(body) if re.match(r'^      api_key: os\.environ/VENICE_API_KEY', ln))
        out.extend(body[:at + 1] + inject + body[at + 1:])
        priced.append(name)
        for lk, v in new.items():
            o = old.get(lk)
            if o is None or abs(o * 1e6 - v) > 1e-4:   # lines written by v1 carried 10 decimals (1e-4 $/M resolution)
                moved.append(f'  {name}: {lk} {"(new)" if o is None else f"${o * 1e6:g}/M"} -> ${v:g}/M')

    print(f'venice entries priced: {len(priced)} | not in live catalog (last synced price kept): {len(kept)}')
    for name, up, old in kept:
        print(f'  DELISTED (flag only): {name} -> {up}  kept {({k: round(v * 1e6, 6) for k, v in old.items()}) or "UNPRICED"}')
    base = [m for m in moved if '(new)' not in m]
    print(f'price lines changed: {len(base)} | cache lines added: {len(moved) - len(base)}')
    for m in base:
        print(m)
    if DRY:
        print('[dry-run] no write')
        return
    with open(CONFIG, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(out))
    import yaml
    yaml.safe_load(open(CONFIG, encoding='utf-8'))
    print('written + YAML parse OK')


if __name__ == '__main__':
    main()
