# Frontier models, September 2026: Opus 5.5, GPT-6 Sol and Luna, Grok 4.7

Drafted by an agent from release digests on 2026-09-22/23, then checked against each vendor's own docs and probed
through a LiteLLM v1.100.1 proxy on 2026-09-23. The example config wires all four.

| Model | Route in the example | Price per 1M tokens | Notes |
| --- | --- | --- | --- |
| Claude Opus 5.5 | `anthropic/claude-opus-5-5` | $4 in / $20 out · cache read $0.20 · cache write $5 (5-minute TTL) | GA 2026-09-22. 1M context, 128K output, 512-token cache minimum. Thinking is always on; effort defaults to `medium`. Rejects non-default temperature/top_p/top_k, forced `tool_choice` and assistant prefill. Fast mode ($8 / $40) is a research preview behind a beta header and an access request. |
| GPT-6 Sol | `openai/responses/gpt-6-sol` | $2 / $10 · cached $0.20 · cache write $2.50 · above 272K input: $4 / $15 | GA 2026-09-22. `gpt-priority-example` is the same model at the priority tier (2x). |
| GPT-6 Luna | `openai/responses/gpt-6-luna` | $0.10 / $0.50 · cached $0.01 · cache write $0.125 · above 272K input: $0.20 / $0.75 | GA 2026-09-22. |
| Grok 4.7 | `xai/grok-4.7` | $2 / $6 · cached $0.50 · at or above 200K prompt tokens: $4 / $12, cached $1 | Released 2026-09-21. 500K context. Reasoning effort low to xhigh; it cannot be turned off. |

## Three things that break on LiteLLM v1.100.1 without the example's settings

1. **GPT-6 tool calls.** Over `/v1/chat/completions`, every GPT-6 model returns 400 on function tools while reasoning
   is on ("Function tools with reasoning_effort are not supported ... use /v1/responses"), and reasoning is on by
   default. Before v1.101.0, LiteLLM routes that case to the Responses API automatically only for `gpt-5` names. The
   `openai/responses/` prefix does it explicitly. The bridge maps `max_tokens` to `max_output_tokens` but forwards
   `temperature` and `top_p`, which GPT-6 rejects unless `reasoning_effort` is `none`, so those are dropped. The
   Responses API stores conversations by default, so `store: false` keeps Chat Completions behaviour. On v1.101.0
   and later a plain `openai/gpt-6-sol` entry handles this itself.
2. **Grok penalties.** Every current xAI model returns 400 on `presence_penalty` and `logit_bias`, and LiteLLM
   forwards both (it already strips `stop` and `frequency_penalty` for grok-4 names). The example drops them.
3. **Opus 5.5 refusals.** Its cyber, bio and reasoning-extraction classifiers return HTTP 200 with an empty answer.
   Listing the route under `content_policy_fallbacks` makes a refusal walk the fallback chain instead.

## Pricing

Unless `LITELLM_LOCAL_MODEL_COST_MAP` is set, LiteLLM downloads its model price map from GitHub `main` at every
startup and uses it instead of the copy in the image. These models reached `main` in PRs #42489 (Opus 5.5), #42515
(GPT-6 Sol and Luna) and #42264 (Grok 4.7); no stable image tag carries them yet, so a proxy started after those
merges prices them from the download. Check `GET /model/cost_map/source` (expect `remote`), reload with
`POST /reload/model_cost_map`, or schedule `POST /schedule/model_cost_map_reload?hours=24` so price changes arrive
without a restart. If you force the local map, add per-token overrides — and remember an override freezes the price.

Two cost effects worth knowing:

- GPT-6 writes a long prompt to cache the first time it sees it and bills that write at 1.25x the input rate (a
  371K-token Luna request billed 371,307 cache-write tokens at the above-272K rate).
- xAI prepends its own prompt to Grok 4.7 calls: a one-line message bills about 1,250 prompt tokens, most of them
  served from cache.

## OpenRouter and zero data retention

The example's `openrouter/*` wildcard requires zero-data-retention providers. A model whose only provider retains
prompts has no endpoint under that policy and returns 404 "No endpoints found matching your data policy".
`poolside/laguna-s-2.1` is one: its provider retains prompts but does not train on them. If logging without training
is acceptable for that model, give it its own entry with `data_collection: "deny"` and no `zdr` flag.

## After deploying

1. `GET /model/cost_map/source` returns `remote`.
2. Call each route and assert the echoed `model` and a non-zero spend. HTTP 200 alone proves nothing.
3. Send one tool call to each GPT-6 route and expect `finish_reason: tool_calls`.
4. Compare the spend-log cost against the table above.

## Sources

- Anthropic pricing and the Opus 5.5 release notes: platform.claude.com/docs/en/about-claude/pricing,
  platform.claude.com/docs/en/models/opus-5-5/whats-new-opus-5-5
- OpenAI pricing and the GPT-6 guide: developers.openai.com/api/docs/pricing,
  developers.openai.com/api/docs/guides/latest-model
- xAI pricing and the Grok 4.7 model page: docs.x.ai/developers/pricing, docs.x.ai/developers/models/grok-4.7
- LiteLLM: BerriAI/litellm PRs #42489, #42515 and #42264 (cost map), #39631 (GPT-6 handled like GPT-5 from v1.101.0)
