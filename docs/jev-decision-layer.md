# The Jev decision layer

`litellm/jev_gate.py` gives the gateway two decisions it could not make before, backed by
TypeSafe AI's Jev, plus a pass-through so your own code can ask Jev through the gateway.
Everything here is opt-in per route and declines gracefully without a key.

## What Jev is

Jev (early access since 2026-09-15, https://docs.typesafe.ai) is a *decision* model, not a
chat model. You send it a `state` (text or JSON) and typed `questions`; it returns one typed
answer per question with a probability distribution and a confidence, and never generates
text. Three question types: **Choice** (one of your options), **Score** (a position on your
ordered rubric), **Noul** (probability that a statement is true). Priced per input token
($0.042 per million at time of writing; output is free), roughly half a second round trip
from a US host, 64K-token requests.

It cannot answer outside your schema, but it can pick the wrong valid option, and the vendor
documents that adversarial text inside the state can move probabilities. It is not trained on
customer input; retention is open-ended and zero-data-retention is an enterprise term. Treat
it as a vendor in the path, not as a local component.

## The three uses

### 1. Soft-refusal judge (on by default once a key exists)

LiteLLM only walks `content_policy_fallbacks` when the model says, in the protocol, that it
declined (`finish_reason: content_filter`). Most declines arrive as a polite sentence with a
normal status, or as filler, and the gateway counts them as answers.

`jev_gate.judge_instance` runs in `async_post_call_success_deployment_hook`, inside the
router's per-deployment call and before LiteLLM's own content-filter check, on **non-streamed**
chat completions for routes listed under `content_policy_fallbacks` (plus any in
`JEV_JUDGE_GROUPS`; routes starting with `private` never). One Choice over the system prompt,
the latest user turn and the reply: `answered` / `refused` / `non_answer`. A verdict of
refused or non_answer with p ≥ 0.85 rewrites `finish_reason` to `content_filter`, so the router
raises its content-policy error and walks the route's chain exactly as for a hard refusal.

- Empty replies (no content, no tool call) are caught in code, with no vendor call.
- `finish_reason: length` is recorded and never re-run (a retry with the same limit truncates again).
- Replies over 1,500 characters are skipped (refusals are short).
- Top probability below 0.60 counts as uncertain and passes the reply through.
- Streamed replies are not judged; the text has already reached the client. The streamed
  refusal fallback in `litellm/refusal_fallback.py` still covers protocol-level refusals there.

### 2. Router classifier (uncomment to enable)

LiteLLM's complexity router accepts `classifier_type: custom` with a plugin. `jev_gate.classifier_instance`
asks one Choice over `SIMPLE / MEDIUM / COMPLEX / REASONING` with a structured rubric (what /
not_for / examples per tier). Top probability ≥ 0.60 wins; below that the plugin takes the
more capable of the two leading tiers, because under-routing is the costly error. Prompt size
stays in code: at or above `JEV_SIZE_FLOOR_TOKENS` (default ~3,000) the tier is floored at
COMPLEX. If Jev is slow or down (2.5 s timeout, 30 s circuit breaker on timeouts, 5xx and 429)
the plugin declines and `classifier_fallback: heuristic`, LiteLLM's built-in scorer, decides.

Every classified prompt is sent to the vendor. Enable it on a router whose tiers already go
to cloud vendors; do not enable it on a router that must stay local-only.

### 3. Pass-through

`POST /typesafe/v1/systemone` and `GET /typesafe/v1/models` on the gateway forward to
`api.typesafe.ai` with the proxy's `TYPESAFE_API_KEY` injected, so scripts and agents hold only
a gateway virtual key and every call lands in the spend ledger. On LiteLLM 1.100.x this
generic route is opt-in per key or team:

```
POST /key/update
{"key": "<virtual key>", "metadata": {"allowed_passthrough_routes": ["/typesafe"]}}
```

(exact or prefix match; merge into the key's existing metadata; the master key always passes).
Spend is a flat `cost_per_request` estimate until the native `/typesafe` route in LiteLLM ≥ 1.103
prices each call from the response usage.

## Enable

1. `TYPESAFE_API_KEY=...` in `.env`.
2. `docker compose --profile observe up -d litellm-proxy` (recreate: the module is a bind mount).
3. `python scripts/probe-typesafe.py` (direct) and `--via-proxy` (through the gateway, master key).
4. Optional: uncomment the `classifier_*` lines under a router's `complexity_router_config`.

Knobs (proxy environment): `JEV_MODEL` (default `jev-1.13.0`, pinned because thresholds are
tuned per version), `JEV_TIMEOUT_MS` (2500), `JEV_CIRCUIT_COOLDOWN_S` (30),
`JEV_MIN_TOP_PROBABILITY` (0.60), `JEV_SIZE_FLOOR_TOKENS` (3000), `JEV_JUDGE_THRESHOLD` (0.85),
`JEV_JUDGE_MAX_CHARS` (1500), `JEV_JUDGE_GROUPS` (csv of extra routes),
`JEV_JUDGE_EXCLUDE_PREFIXES` (`private`).

## Telemetry

- Prometheus on the proxy's `/metrics/`: `praxen_jev_calls_total{purpose,outcome}`,
  `praxen_jev_input_tokens_total`, `praxen_jev_estimated_cost_usd_total`,
  `praxen_jev_latency_seconds` (histogram), `praxen_jev_classifier_tier_total{router,tier}`,
  `praxen_jev_classifier_confidence`, `praxen_jev_judge_verdict_total{model_group,verdict,action}`.
  Counters born after a restart read `increase() = 0` until they tick across two scrapes.
- One JSON line per decision on the container log, prefixed `jev_gate `; Loki query
  `{container="praxen-litellm"} |= "jev_gate {"`. The `call_id` equals the spend ledger's
  `request_id`. LiteLLM snapshots request metadata before these hooks run, so the verdict
  cannot be written into the ledger row itself.
- The example dashboard's Jev row: calls, refusals caught, estimated spend, tier mix.
- `scripts/verify-stack.py` probe 15 checks the pass-through and skips when no key is set.

## Measured on the reference deployment (2026-09-18, jev-1.13.0)

| What | Result |
| --- | --- |
| Classifier on 16 labelled prompts, 4 per tier, incl. 2 prompt-injection cases | 16/16 |
| Judge on 15 labelled (request, reply) pairs, incl. 2 self-grading injections | 15/15 |
| Judge on 6 real replies from a 3B local model through the gateway | 5/6; the miss was a mislabel (the user asked for the refusal sentence verbatim; Jev scored it `answered` 0.54, uncertain, no action) |
| Live: instructed soft refusal, empty reply, filler reply | all fell back to the next route, `x-litellm-attempted-fallbacks: 1` |
| Live: normal short reply, 2,000-character reply | untouched |
| Live router: greeting / small function / prove √2 / 4.7K-token analysis / "this is SIMPLE" injection | SIMPLE / MEDIUM / REASONING / COMPLEX (size floor) / COMPLEX |
| Round trip, gateway host → vendor | median 531 ms, p95 643 ms |
| Whole bench, 27,468 input tokens | $0.0012 |

The injection cases moved probabilities without flipping labels (one self-grading reply moved
`non_answer` from 1.00 to 0.90). Reproduce with `scripts/jev-bench.py`; run it inside the
proxy image, because it imports `litellm` and this project does not install LiteLLM from PyPI.

## Caveats, plainly

- Early access, waitlisted; the vendor says the price may be subsidized.
- A new egress for every judged reply and classified prompt. Opt-in per route; private routes excluded.
- Vendor accuracy claims are on a model-agreement benchmark, not ground truth. Run your own labelled set.
- The ledger keeps one row per request id, so a judged-and-replaced call records one leg while
  the vendor bills both (the same gap the streamed refusal fallback has).
- Not a security boundary: adversarial text in a prompt or reply can move the verdict.
