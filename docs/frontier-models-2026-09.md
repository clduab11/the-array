# Frontier model wiring (2026-09-22/23)

Staged by Rook from weekday digest handoffs. Prefer direct provider routes over OpenRouter while `openrouter/*` enforces `zdr: true`.

| Model | LiteLLM id | List price (short ctx) | Notes |
| --- | --- | --- | --- |
| Claude Opus 5.5 | `anthropic/claude-opus-5-5` | $4 / $20 / cache read $0.20 per 1M | Thinking always on; default effort `medium`. Fast mode Anthropic-only (`speed: fast`, 2x). |
| GPT-6 Sol | `openai/gpt-6-sol` | $2 / $10 | Replaces GPT-5.6 Sol-class curated traffic. |
| GPT-6 Luna | `openai/gpt-6-luna` | $0.10 / $0.50 | High-volume; use `reasoning_effort: none` if you need `temperature`. |
| Grok 4.7 | `xai/grok-4.7` | $2 / $6 | Same as 4.6 list. |

## Reload cost map (required for accurate metering)

On LiteLLM `v1.76.0+` with the **remote** cost map: Admin UI → Models + Endpoints → Price Data → **Reload Price Data**, or `POST /reload/model_cost_map` as proxy admin.

If `LITELLM_LOCAL_MODEL_COST_MAP=true`, Reload does nothing — rebuild/pull an image that includes the cost-map PRs (#42489 Opus 5.5, #42515 GPT-6 Sol/Luna, Grok 4.7 day-0).

## Live checklist (needs Chris GO)

1. Confirm live YAML wildcards `openai/*`, `anthropic/*`, `xai/*` (or curated entries).
2. Reload cost map or bump image.
3. Probe each id; assert echoed `model` and non-zero spend (never trust HTTP 200 alone).
4. Do **not** change production without GO.
