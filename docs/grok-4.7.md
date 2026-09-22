# Grok 4.7 on the-array

Added 2026-09-22 (Rook). Upstream: https://x.ai/news/grok-4-7 · LiteLLM day-0: https://docs.litellm.ai/blog/grok_4_7

## Route

- Direct (preferred while OpenRouter ZDR is on): `xai/grok-4.7` via the existing `xai/*` wildcard, or a curated entry `model: xai/grok-4.7`.
- OpenRouter: `openrouter/x-ai/grok-4.7` (bundled map ~$1.60/$4.80) — avoid if `openrouter/*` forces `zdr: true` and you need SpaceXAI ZDR nuances separately.

## Pricing (verify on vendor page before overrides)

Same as Grok 4.6 list: $2 / $6 per 1M input/output under 200k tokens; $4 / $12 at or above 200k. Cache read $0.50 / $1.0 per 1M. Do **not** inject `input_cost_per_token` unless LiteLLM's map is wrong.

## Example curated block

```yaml
  - model_name: grok-coding-example
    litellm_params:
      model: xai/grok-4.7
      api_key: os.environ/XAI_API_KEY
      max_budget: 40.0
      budget_duration: 1mo
```

Fallback companion (under `litellm_settings.fallbacks`):

```yaml
    - grok-coding-example: [claude-cached-example, local-chat-example]
```

Probe: call the gateway with that model name and assert the echoed `model` is `grok-4.7` (or the vendor echo) and spend is non-zero. A HTTP 200 alone is not proof.
