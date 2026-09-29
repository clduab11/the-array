# PRAXEN LiteLLM — Chain Reference

**Snapshot:** config **v4.18.0** · **2026-09-29** — REGENERATED from the live config via
`PYTHONUTF8=1 python scripts/extract_chains.py` (backup of the v4.17.0 snapshot at
`backup/litellm-config/chains-reference.md.bak.pre-v4.18.0`). Delta notes keep CURRENT + ONE prior; older ones live in
the backup rungs and git history.

**Chain deltas at v4.18.0 — the operator's rulings: Sonnet 5.5 promoted, MiMo V2.6 Flash for go/coding-lite (2026-09-29)**

- **Sonnet 5.5 takes Sonnet 5's duty.** Alias primaries `reasoning` / `array/reasoning` / `praxen/reasoning` / `go/reasoning` /
  `legacy-go/reasoning` and the `array/auto` COMPLEX tier now resolve to `claude-sonnet-5-5`. `claude-sonnet-5` becomes the
  FIRST rung of those five chains (it answers when Sonnet 5.5 400s a forced `tool_choice` or is down, at the same price):
  `reasoning: [claude-sonnet-5, grok-4.5, gemini-3.1-pro, local-gemma4-uncensored]` ·
  `go/reasoning: [claude-sonnet-5, gemini-3.1-pro, grok-4.5, gpt-5.6-terra, local-gemma4-uncensored]`.
  It stays first in `array/auto`'s chain and keeps its catch duty for `claude-sonnet-4-6` and `claude-sonnet-5-advised`.
- **House-workhorse rungs → `claude-sonnet-5-5`:** `go/coding-heavy` (+legacy-go), `praxen/openai-router`,
  `array/auto-openai`, `grok-4.7`.
- **`go/coding-lite` (+legacy-go) → `mimo-v2.6-flash`**, and its chain gains `glm-5.3-flash` (ZDR) as the first rung:
  `[glm-5.3-flash, gemini-3.6-flash, laguna-s-2.1, local-granite-4.1, imac-gemma4-12b-qat, local-qwen3.5-4b]`. GLM 5.3
  Prime and Qwen 3.8 Max Prime were NOT added (no zero-retention endpoint). **+1 regular chain:** `mimo-v2.6-flash` carries
  the same shape as its catch chain.
- Every change applies to both `fallbacks` and `content_policy_fallbacks` (mirrors stay identical).
- Counts: 209 entries · 114 regular chains · 45 content-policy chains.

**Chain deltas at v4.17.0 (prior) — OP ADVISOR-PAIRS: Claude Sonnet 5.5 and two advised pairs (2026-09-29)**

- **+3 regular chains, 110 → 113; +3 content-policy chains, 42 → 45.** Each new group mirrors its regular chain exactly under
  `content_policy_fallbacks` (all three executors run refusal classifiers). Zero duty in any alias, router or other chain:
  `claude-sonnet-5-5: [claude-sonnet-5, claude-sonnet-4-6, gpt-5.5, local-gemma4-uncensored]` ·
  `claude-sonnet-5-5-advised-opus: [claude-sonnet-5-5, claude-sonnet-5, local-gemma4-uncensored]` ·
  `claude-opus-5-5-advised-fable: [claude-opus-5-5, claude-opus-4-8, local-gemma4-uncensored]`.
- **Advised routes degrade to their plain executor** (the advisor is lost on fallback), then a plaintext-era rung, then the
  local floor — the `claude-sonnet-5-advised` pattern.
- **Probed behaviour worth knowing when reading these chains:** LiteLLM walks chains RECURSIVELY (`max_fallbacks` 5), so a
  400 caused by the request's own shape keeps descending until some model accepts the request. `tool_choice: "required"` on `claude-sonnet-5-5`
  400s upstream and `claude-sonnet-5` answers; a client that ANSWERS the advisor's tool call on an advised route 400s and the
  nested chains served that turn from `gpt-5.4` (cross-vendor).
- Counts: 208 entries · 113 regular chains · 45 content-policy chains.

```
===== A. ALIASES (model_group_alias) — alias -> PRIMARY target =====
count: 39
  reasoning            -> {'model': 'claude-sonnet-5-5', 'hidden': True}
  array/reasoning      -> claude-sonnet-5-5
  praxen/reasoning     -> {'model': 'claude-sonnet-5-5', 'hidden': True}
  deep-reasoning       -> {'model': 'claude-fable-5', 'hidden': True}
  array/deep-reasoning -> claude-fable-5
  praxen/deep-reasoning -> {'model': 'claude-fable-5', 'hidden': True}
  fast                 -> {'model': 'gemini-3.1-flash-lite', 'hidden': True}
  array/fast           -> gemini-3.1-flash-lite
  praxen/fast          -> {'model': 'gemini-3.1-flash-lite', 'hidden': True}
  coding               -> {'model': 'grok-code', 'hidden': True}
  array/coding         -> grok-code
  praxen/coding        -> {'model': 'grok-code', 'hidden': True}
  private              -> {'model': 'venice/e2ee-glm-5-3-p', 'hidden': True}
  array/private        -> venice/e2ee-glm-5-3-p
  praxen/private       -> {'model': 'venice/e2ee-glm-5-3-p', 'hidden': True}
  private-uncensored   -> {'model': 'qwen-3.6-plus-venice', 'hidden': True}
  array/private-uncensored -> qwen-3.6-plus-venice
  praxen/private-uncensored -> {'model': 'qwen-3.6-plus-venice', 'hidden': True}
  vision               -> {'model': 'gemini-3.6-flash', 'hidden': True}
  array/vision         -> gemini-3.6-flash
  praxen/vision        -> {'model': 'gemini-3.6-flash', 'hidden': True}
  array/embed          -> local-embed-qwen3
  legacy/embed         -> {'model': 'local-embed-qwen3', 'hidden': True}
  go/coding-lite       -> mimo-v2.6-flash
  legacy-go/coding-lite -> {'model': 'mimo-v2.6-flash', 'hidden': True}
  go/coding-balanced   -> grok-code
  legacy-go/coding-balanced -> {'model': 'grok-code', 'hidden': True}
  go/coding-heavy      -> kimi-k3
  legacy-go/coding-heavy -> {'model': 'kimi-k3', 'hidden': True}
  go/fast              -> grok-4.3
  legacy-go/fast       -> {'model': 'grok-4.3', 'hidden': True}
  go/reasoning         -> claude-sonnet-5-5
  legacy-go/reasoning  -> {'model': 'claude-sonnet-5-5', 'hidden': True}
  go/private           -> venice/e2ee-glm-5-3-p
  legacy-go/private    -> {'model': 'venice/e2ee-glm-5-3-p', 'hidden': True}
  go/uncensored        -> glm-4.7-heretic
  legacy-go/uncensored -> {'model': 'glm-4.7-heretic', 'hidden': True}
  go/vision            -> gemini-3.6-flash
  legacy-go/vision     -> {'model': 'gemini-3.6-flash', 'hidden': True}

===== B. FALLBACK CHAINS — total 114 =====

--- B1. Alias-named chains (37) ---
  reasoning: claude-sonnet-5 -> grok-4.5 -> gemini-3.1-pro -> local-gemma4-uncensored
  deep-reasoning: venice/openai-gpt-56-sol-pro -> gpt-5.5-pro -> claude-opus-4-8 -> local-gemma4-uncensored
  fast: gpt-5.4-mini -> gpt-5.6-luna -> mercury-2 -> mercury-2.5 -> grok-4.3 -> gemini-3.5-flash -> local-ministral-3b
  coding: kimi-k2.7-code -> mimo-v2.5 -> venice-qwen3-coder -> codestral -> local-granite-4.1 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  private: venice/e2ee-glm-5-3-flash -> venice/e2ee-glm-5-2-p -> venice/e2ee-deepseek-v4-flash -> venice/e2ee-qwen3-6-35b-a3b -> local-gemma4-uncensored -> local-qwen3.5-4b
  private-uncensored: venice/e2ee-gemma-4-26b-a4b-uncensored-p -> venice-uncensored-1.1 -> glm-4.7-heretic -> local-gemma4-uncensored -> local-qwen3.5-4b
  vision: grok-4.5 -> local-ministral-3b -> local-qwen3.5-4b
  praxen/reasoning: claude-sonnet-5 -> grok-4.5 -> gemini-3.1-pro -> local-gemma4-uncensored
  array/reasoning: claude-sonnet-5 -> grok-4.5 -> gemini-3.1-pro -> local-gemma4-uncensored
  praxen/deep-reasoning: venice/openai-gpt-56-sol-pro -> gpt-5.5-pro -> claude-opus-4-8 -> local-gemma4-uncensored
  array/deep-reasoning: venice/openai-gpt-56-sol-pro -> gpt-5.5-pro -> claude-opus-4-8 -> local-gemma4-uncensored
  praxen/fast: gpt-5.4-mini -> gpt-5.6-luna -> mercury-2 -> mercury-2.5 -> grok-4.3 -> gemini-3.5-flash -> local-ministral-3b
  array/fast: gpt-5.4-mini -> gpt-5.6-luna -> mercury-2 -> mercury-2.5 -> grok-4.3 -> gemini-3.5-flash -> local-ministral-3b
  praxen/coding: kimi-k2.7-code -> mimo-v2.5 -> venice-qwen3-coder -> codestral -> local-granite-4.1 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  array/coding: kimi-k2.7-code -> mimo-v2.5 -> venice-qwen3-coder -> codestral -> local-granite-4.1 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  praxen/private: venice/e2ee-glm-5-3-flash -> venice/e2ee-glm-5-2-p -> venice/e2ee-deepseek-v4-flash -> venice/e2ee-qwen3-6-35b-a3b -> local-gemma4-uncensored -> local-qwen3.5-4b
  array/private: venice/e2ee-glm-5-3-flash -> venice/e2ee-glm-5-2-p -> venice/e2ee-deepseek-v4-flash -> venice/e2ee-qwen3-6-35b-a3b -> local-gemma4-uncensored -> local-qwen3.5-4b
  praxen/private-uncensored: venice/e2ee-gemma-4-26b-a4b-uncensored-p -> venice-uncensored-1.1 -> glm-4.7-heretic -> local-gemma4-uncensored -> local-qwen3.5-4b
  array/private-uncensored: venice/e2ee-gemma-4-26b-a4b-uncensored-p -> venice-uncensored-1.1 -> glm-4.7-heretic -> local-gemma4-uncensored -> local-qwen3.5-4b
  legacy-go/coding-lite: glm-5.3-flash -> gemini-3.6-flash -> laguna-s-2.1 -> local-granite-4.1 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  go/coding-lite: glm-5.3-flash -> gemini-3.6-flash -> laguna-s-2.1 -> local-granite-4.1 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  legacy-go/coding-balanced: minimax-m3 -> kimi-k3 -> venice/e2ee-glm-5-2-p -> local-granite-4.1 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  go/coding-balanced: minimax-m3 -> kimi-k3 -> venice/e2ee-glm-5-2-p -> local-granite-4.1 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  legacy-go/coding-heavy: claude-fable-5 -> claude-opus-5 -> gpt-5.6-sol-pro -> claude-sonnet-5-5 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  go/coding-heavy: claude-fable-5 -> claude-opus-5 -> gpt-5.6-sol-pro -> claude-sonnet-5-5 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  legacy-go/fast: grok-4.5 -> gpt-5.6-luna -> gemini-3.6-flash -> mercury-2 -> mercury-2.5 -> local-ministral-3b
  go/fast: grok-4.5 -> gpt-5.6-luna -> gemini-3.6-flash -> mercury-2 -> mercury-2.5 -> local-ministral-3b
  legacy-go/reasoning: claude-sonnet-5 -> gemini-3.1-pro -> grok-4.5 -> gpt-5.6-terra -> local-gemma4-uncensored
  go/reasoning: claude-sonnet-5 -> gemini-3.1-pro -> grok-4.5 -> gpt-5.6-terra -> local-gemma4-uncensored
  legacy-go/private: venice/e2ee-glm-5-2-p -> venice/e2ee-deepseek-v4-flash -> venice/e2ee-qwen3-6-35b-a3b -> local-gemma4-uncensored -> local-qwen3.5-4b
  go/private: venice/e2ee-glm-5-2-p -> venice/e2ee-deepseek-v4-flash -> venice/e2ee-qwen3-6-35b-a3b -> local-gemma4-uncensored -> local-qwen3.5-4b
  legacy-go/uncensored: venice/aion-labs-aion-3-0 -> qwen-3.6-plus-venice -> venice/gemma-4-uncensored -> local-gemma4-uncensored -> local-qwen3.5-4b
  go/uncensored: venice/aion-labs-aion-3-0 -> qwen-3.6-plus-venice -> venice/gemma-4-uncensored -> local-gemma4-uncensored -> local-qwen3.5-4b
  legacy-go/vision: grok-4.5 -> local-ministral-3b -> local-qwen3.5-4b
  go/vision: grok-4.5 -> local-ministral-3b -> local-qwen3.5-4b
  praxen/vision: grok-4.5 -> local-ministral-3b -> local-qwen3.5-4b
  array/vision: grok-4.5 -> local-ministral-3b -> local-qwen3.5-4b

--- B2. Per-model chains (77) ---
  praxen/local-router: local-gemma4-uncensored -> local-qwen3.5-4b
  array/auto-local: local-gemma4-uncensored -> local-qwen3.5-4b
  legacy-go/local: local-qwen3.5-4b
  go/local: local-qwen3.5-4b
  praxen/openai-router: gpt-5.5 -> gpt-5.6-sol -> claude-sonnet-5-5 -> local-gemma4-uncensored
  array/auto-openai: gpt-5.5 -> gpt-5.6-sol -> claude-sonnet-5-5 -> local-gemma4-uncensored
  gpt-5.6-sol-priority: gpt-5.6-sol -> gpt-5.5 -> claude-opus-4-8 -> local-gemma4-uncensored
  gpt-5.5-priority: gpt-5.5 -> gpt-5.6-sol -> claude-opus-4-8 -> local-gemma4-uncensored
  claude-opus-4-8: claude-fable-5[1m] -> gemini-3.1-pro -> claude-opus-4-6 -> local-gemma4-uncensored
  claude-fable-5[1m]: claude-opus-4-8 -> claude-opus-4-6 -> gpt-5.4-pro -> local-gemma4-uncensored
  claude-fable-5: claude-opus-4-8 -> claude-opus-4-6 -> gpt-5.4-pro -> local-gemma4-uncensored
  claude-fable-5-1: claude-opus-4-8 -> claude-opus-4-6 -> gpt-5.4-pro -> local-gemma4-uncensored
  claude-opus-4-6: claude-opus-4-8 -> gemini-3.1-pro -> gpt-5.4-pro -> local-gemma4-uncensored
  claude-opus-4-7: claude-opus-4-8 -> claude-opus-4-6 -> gemini-3.1-pro -> local-gemma4-uncensored
  gpt-5.4-pro: claude-opus-4-8 -> gemini-3.1-pro -> local-gemma4-uncensored
  gpt-5.5-pro: claude-opus-4-8 -> gemini-3.1-pro -> local-gemma4-uncensored
  gpt-5.6-sol: claude-opus-4-8 -> gpt-5.5 -> gemini-3.1-pro -> local-gemma4-uncensored
  gemini-3.1-pro: claude-opus-4-8 -> gpt-5.4-pro -> local-gemma4-uncensored
  claude-mythos-5: claude-opus-4-8 -> claude-fable-5 -> local-gemma4-uncensored
  claude-opus-5-5: claude-opus-5 -> claude-opus-4-8 -> gpt-5.4-pro -> local-gemma4-uncensored
  claude-opus-5-5-advised-fable: claude-opus-5-5 -> claude-opus-4-8 -> local-gemma4-uncensored
  claude-opus-5: claude-opus-4-8 -> claude-opus-4-6 -> gpt-5.4-pro -> local-gemma4-uncensored
  gpt-6-sol: gpt-5.6-sol -> gpt-5.5 -> claude-opus-4-8 -> local-gemma4-uncensored
  claude-sonnet-5: claude-sonnet-4-6 -> gpt-5.5 -> gpt-5.4 -> local-gemma4-uncensored
  claude-sonnet-5-advised: claude-sonnet-5 -> claude-sonnet-4-6 -> local-gemma4-uncensored
  claude-sonnet-5-5: claude-sonnet-5 -> claude-sonnet-4-6 -> gpt-5.5 -> local-gemma4-uncensored
  claude-sonnet-5-5-advised-opus: claude-sonnet-5-5 -> claude-sonnet-5 -> local-gemma4-uncensored
  claude-sonnet-4-6: claude-sonnet-5 -> gpt-5.4 -> grok-4.3 -> gemini-3.1-pro -> local-gemma4-uncensored
  gpt-5.4: claude-sonnet-4-6 -> grok-4.3 -> local-gemma4-uncensored
  gpt-5.5: claude-sonnet-4-6 -> gpt-5.4 -> gemini-3.1-pro -> local-gemma4-uncensored
  gpt-5.6-terra: gpt-5.5 -> claude-sonnet-4-6 -> gpt-5.4 -> local-gemma4-uncensored
  gpt-4.1: claude-sonnet-4-6 -> gpt-5.4 -> local-gemma4-uncensored
  grok-4.3: claude-sonnet-4-6 -> gpt-5.4 -> local-gemma4-uncensored
  grok-4.5: grok-4.3 -> claude-sonnet-4-6 -> gpt-5.4 -> local-gemma4-uncensored
  grok-4.20: grok-4.5 -> claude-sonnet-4-6 -> gpt-5.4 -> local-gemma4-uncensored
  grok-4.7: grok-4.6 -> grok-4.5 -> claude-sonnet-5-5 -> local-gemma4-uncensored
  mistral-large-3: claude-sonnet-4-6 -> gpt-5.4 -> local-gemma4-uncensored
  mistral-medium-latest: claude-sonnet-4-6 -> gpt-5.5 -> local-gemma4-uncensored
  mistral-small-4: gpt-4.1-mini -> gemini-3.5-flash -> local-ministral-3b
  magistral: claude-sonnet-4-6 -> gpt-5.4 -> local-gemma4-uncensored
  gemini-3-flash: gemini-3.5-flash -> gpt-5.4-mini -> local-ministral-3b
  gemini-2.5-flash: gemini-3-flash -> gpt-5.4-mini -> local-ministral-3b
  gemini-3.5-flash: gemini-3.1-flash-lite -> gpt-5.4-mini -> local-ministral-3b
  gemini-3.6-flash: gemini-3.5-flash -> gpt-5.4-mini -> local-ministral-3b
  gemini-3.1-flash-lite: gpt-5.4-mini -> mercury-2 -> grok-4.3 -> gemini-3.5-flash -> local-ministral-3b
  gpt-5.4-mini: gemini-3.5-flash -> claude-haiku-4-5 -> local-ministral-3b
  gpt-5.4-nano: gemini-3.1-flash-lite -> gemini-3.5-flash -> local-ministral-3b
  gpt-5.6-luna: gpt-5.4-mini -> gemini-3.5-flash -> local-ministral-3b
  gpt-6-luna: gpt-5.6-luna -> gpt-5.4-mini -> local-ministral-3b
  gpt-4.1-mini: gemini-3.5-flash -> gpt-5.4-mini -> local-ministral-3b
  gpt-4.1-nano: gpt-4.1-mini -> gemini-3.1-flash-lite -> local-ministral-3b
  claude-haiku-4-5: gpt-5.4-mini -> gemini-3.5-flash -> local-ministral-3b
  claude-haiku-4-5-advised-opus: claude-haiku-4-5 -> gpt-5.4-mini -> local-ministral-3b
  claude-haiku-4-5-advised-sonnet: claude-haiku-4-5 -> gpt-5.4-mini -> local-ministral-3b
  intake-extract: claude-haiku-4-5 -> gpt-5.4-mini -> local-ministral-3b
  mistral-small: gpt-4.1-mini -> gemini-3.5-flash -> local-ministral-3b
  command-r7b: gpt-5.4-nano -> gemini-3.1-flash-lite -> local-ministral-3b
  mercury-2: gpt-5.4-mini -> gemini-3.5-flash -> local-ministral-3b
  codestral: grok-code -> kimi-k2.7-code -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  devstral-2: codestral -> grok-code -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  grok-code: kimi-k2.7-code -> mimo-v2.5 -> venice-qwen3-coder -> local-granite-4.1 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  kimi-k2.7-code: mimo-v2.5 -> grok-code -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  mimo-v2.5: kimi-k2.7-code -> grok-code -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  mimo-v2.6-flash: glm-5.3-flash -> gemini-3.6-flash -> laguna-s-2.1 -> local-granite-4.1 -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  venice-qwen3-coder: venice-glm-5.1 -> codestral -> imac-gemma4-12b-qat -> local-qwen3.5-4b
  gemini-2.5-pro: gemini-3.1-pro -> claude-opus-4-6 -> local-gemma4-uncensored
  venice/e2ee-glm-5-3-p: venice/e2ee-glm-5-2-p -> venice/e2ee-deepseek-v4-flash -> venice/e2ee-qwen3-6-35b-a3b -> local-gemma4-uncensored -> local-qwen3.5-4b
  venice/e2ee-glm-5-2-p: venice/e2ee-deepseek-v4-flash -> venice/e2ee-qwen3-6-35b-a3b -> local-gemma4-uncensored -> local-qwen3.5-4b
  venice-glm-5.1: venice-qwen3-235b-thinking -> venice-llama-3.3-70b -> venice-nemotron-cascade-2 -> local-gemma4-uncensored
  venice-qwen3-235b-thinking: venice-glm-5.1 -> venice-llama-3.3-70b -> venice-nemotron-cascade-2 -> local-gemma4-uncensored
  venice-llama-3.3-70b: venice-glm-5.1 -> venice-nemotron-cascade-2 -> local-gemma4-uncensored
  venice-nemotron-cascade-2: venice-llama-3.3-70b -> venice-qwen3-235b-thinking -> local-gemma4-uncensored
  qwen-3.6-plus-venice: venice/e2ee-gemma-4-26b-a4b-uncensored-p -> venice-uncensored-1.1 -> glm-4.7-heretic -> local-gemma4-uncensored -> local-qwen3.5-4b
  glm-4.7-heretic: qwen-3.6-plus-venice -> venice-rp-uncensored -> venice-uncensored-1.1 -> local-gemma4-uncensored -> local-qwen3.5-4b
  venice-rp-uncensored: glm-4.7-heretic -> qwen-3.6-plus-venice -> venice-uncensored-1.1 -> local-gemma4-uncensored -> local-qwen3.5-4b
  venice-uncensored-1.1: glm-4.7-heretic -> venice-rp-uncensored -> local-gemma4-uncensored -> local-qwen3.5-4b
  array/auto: claude-sonnet-5 -> gpt-5.6-terra -> grok-4.5 -> local-gemma4-uncensored

===== C. default_fallbacks: None =====

===== D. TERMINAL-RUNG TALLY (last model in each chain) =====
  local-gemma4-uncensored    terminal for 49 chains
  local-qwen3.5-4b           terminal for 41 chains
  local-ministral-3b         terminal for 24 chains
```
