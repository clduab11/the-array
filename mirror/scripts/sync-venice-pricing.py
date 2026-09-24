#!/usr/bin/env python3
"""sync-venice-pricing.py — inject/refresh per-entry custom pricing on every
Venice-pinned entry in litellm_config.yaml so venice spend falls under proxy
governance (budgets + SpendLogs + Grafana Spend panels).

WHY: LiteLLM's built-in cost map has no Venice model ids -> spend computes to
$0 for all venice routes. LiteLLM's documented fix is custom pricing on the
entry: litellm_params.input_cost_per_token / output_cost_per_token.

SOURCE OF TRUTH: live https://api.venice.ai/api/v1/models pricing
(model_spec.pricing.input/output.usd, per MILLION tokens). Venice rotates
models AND prices — re-run this script periodically (it is idempotent:
existing pricing lines are updated in place, comments preserved).

USAGE:  VENICE_API_KEY=... python3 scripts/sync-venice-pricing.py [--dry-run]
        (or run from repo root; reads key from ./.env if env var unset)
Then:   docker compose restart litellm-proxy

Text-surgery on purpose: pyyaml round-trip would destroy the config's
comments. Entries whose upstream id is not in the live catalog are left
unpriced and reported (venice no-auto-cull rule: flag, never delete).
"""
import json, os, re, sys, urllib.request
from datetime import date

CONFIG = os.path.join(os.path.dirname(__file__), '..', 'litellm_config.yaml')
DRY = '--dry-run' in sys.argv

def venice_key():
    k = os.environ.get('VENICE_API_KEY')
    if k:
        return k
    envp = os.path.join(os.path.dirname(__file__), '..', '.env')
    for line in open(envp):
        if line.startswith('VENICE_API_KEY='):
            return line.split('=', 1)[1].strip()
    sys.exit('VENICE_API_KEY not found (env or ./.env)')

def live_pricing():
    req = urllib.request.Request('https://api.venice.ai/api/v1/models',
                                 headers={'Authorization': f'Bearer {venice_key()}'})
    data = json.load(urllib.request.urlopen(req, timeout=30))['data']
    out = {}
    for m in data:
        pr = (m.get('model_spec') or {}).get('pricing') or {}
        i = (pr.get('input') or {}).get('usd')
        o = (pr.get('output') or {}).get('usd')
        if i is not None and o is not None:
            out[m['id']] = (float(i), float(o))  # USD per 1M tokens
    return out

def main():
    prices = live_pricing()
    src = open(CONFIG).read()
    lines = src.split('\n')
    stamp = date.today().isoformat()

    out, cur_upstream, in_venice = [], None, False
    matched, unmatched, updated = [], [], 0
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r'^  - model_name:', ln)
        if m:
            cur_upstream, in_venice = None, False
        mm = re.match(r'^      model: "?openai/(.+?)"?\s*(#.*)?$', ln)
        if mm:
            cur_upstream = mm.group(1)
        if re.match(r'^      api_base: .*api\.venice\.ai', ln):
            in_venice = True
        # replace existing synced pricing lines in place (idempotent re-run)
        if re.match(r'^      (input|output)_cost_per_token:.*venice-price-sync', ln):
            i += 1
            continue
        out.append(ln)
        # inject right after the venice api_key line of a matched entry
        if in_venice and re.match(r'^      api_key: os\.environ/VENICE_API_KEY', ln) and cur_upstream:
            if cur_upstream in prices:
                inp, outp = prices[cur_upstream]
                out.append(f'      input_cost_per_token: {inp/1e6:.10f}   # ${inp}/M venice-price-sync {stamp}')
                out.append(f'      output_cost_per_token: {outp/1e6:.10f}   # ${outp}/M venice-price-sync {stamp}')
                matched.append(cur_upstream)
            else:
                unmatched.append(cur_upstream)
            in_venice = False  # one injection per entry
        i += 1

    print(f'venice entries priced: {len(matched)} | not in live catalog (left unpriced): {len(unmatched)}')
    if unmatched:
        for u in sorted(set(unmatched)):
            print(f'  UNPRICED (rotated out?): {u}')
    if DRY:
        print('[dry-run] no write')
        return
    open(CONFIG, 'w').write('\n'.join(out))
    import yaml
    yaml.safe_load(open(CONFIG))
    print('written + YAML parse OK')

if __name__ == '__main__':
    main()
