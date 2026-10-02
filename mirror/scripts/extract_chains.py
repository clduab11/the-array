import yaml
from collections import Counter

d = yaml.safe_load(open('litellm_config.yaml'))
alias = d['router_settings'].get('model_group_alias', {})
fb = d['litellm_settings'].get('fallbacks', [])
deff = d['litellm_settings'].get('default_fallbacks')

print("===== A. ALIASES (model_group_alias) — alias -> PRIMARY target =====")
print(f"count: {len(alias)}")
for k, v in alias.items():
    print(f"  {k:<20} -> {v}")

aliaskeys = set(alias.keys())
alias_chains, model_chains = [], []
for entry in fb:
    for name, chain in entry.items():
        (alias_chains if name in aliaskeys else model_chains).append((name, chain))

print(f"\n===== B. FALLBACK CHAINS — total {len(fb)} =====")
print(f"\n--- B1. Alias-named chains ({len(alias_chains)}) ---")
for name, chain in alias_chains:
    print(f"  {name}: {' -> '.join(chain)}")
print(f"\n--- B2. Per-model chains ({len(model_chains)}) ---")
for name, chain in model_chains:
    print(f"  {name}: {' -> '.join(chain)}")

print(f"\n===== C. default_fallbacks: {deff} =====")

terms = Counter(chain[-1] for entry in fb for chain in entry.values() if chain)
print("\n===== D. TERMINAL-RUNG TALLY (last model in each chain) =====")
for m, c in terms.most_common():
    print(f"  {m:<26} terminal for {c} chains")
