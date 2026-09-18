# The three boards

`grafana/dashboards/` ships three file-provisioned Grafana boards that split one question each. They are
generated, not hand-drawn: every panel query was executed against a running stack before it was written down,
and `scripts/verify-praxen-boards.py` re-executes every one of them through Grafana's own datasource path.

| Board | uid | Question it answers |
|---|---|---|
| PRAXEN // COMMAND | `praxen-command` | Is anything broken, overspending, degraded or off-policy right now? |
| PRAXEN // ROUTING | `praxen-routing` | Why are traffic, model choice, cost and policy behaving this way? |
| PRAXEN // FORENSICS | `praxen-forensics` | What caused this specific request to fail, slow down, fall back or get judged? |

Every panel's (i) bubble says in plain words what it shows and where the number comes from. The three boards share
the same pickers (KEY, MODEL, TEAM, INTERVAL, LOG CONTAINER, LOG FILTER); the links in the top bar and the row links
in the tables carry the time range and the pickers across.

## COMMAND (fits in about one and a quarter 1440p screens)

Top row: active spend watches (from Grafana's own alert state), route success, provider error rate, end-to-end
P95 latency, fallbacks fired, and off-tier calls (premium-tier billing nobody asked for — a route named `-priority`
or the complexity router choosing a premium lane on purpose counts as opt-in). Second row: UP/DOWN for the gateway,
Tempo, Grafana, Prometheus, Loki and Alloy, month-to-date spend, and that spend as a share of the plan and of the
team hard stops read live from the gateway database. Then the provider→model flow, token throughput, requests and
errors, a per-model table (requests, tokens, latency, first-token time, speed, cost, success) and the last 50
requests with the warn/error and verbose log windows.

## ROUTING

Posture tiles (route success, fallback share, off-tier share, local share, prompt-cache read ratio, Jev refusals
caught), the two Sankeys (provider→model, local↔cloud tokens), per-model telemetry with first-token heatmap and
upstream P95, the billed service-tier table, cost by model, prompt-cache reads/writes/savings (computed from the
price the gateway recorded on each call), advised-route spend, the Jev decision-layer row, the local watchdog and
the team/key envelopes.

## FORENSICS

Paste a spend-ledger `request_id` **or** a `litellm_call_id` into REQUEST / CALL ID. The board derives the call id
(most chat rows store the provider's id as `request_id`, while the judge and the traces key on the call id) and
narrows everything to it: the verbose request table, the correlated Loki window, the Jev judge event, a timeline
built from the row's own timestamps (received, first token, completed), and the exact Tempo trace via
`{ span.litellm.call_id = "…" }` — the LLM span carries `litellm.call_id`, `gen_ai.response.id`,
`litellm.model_group` and the key/team aliases. A trace id loads the waterfall directly.

## Things the telemetry cannot do (so the boards do not pretend)

- No "vs 1 h ago" deltas on range totals; sparklines only where a rate series exists.
- No uptime percentages — Prometheus `up` is the only liveness signal.
- Ordinary proxy log lines carry no request id; only the Jev judge lines do. Correlate the rest by time window.
- Streamed refusal fallbacks do not increment the router's fallback counters.
- The spend ledger keeps one row per request id: a judged-and-replaced call records one leg while the vendor
  bills both.

## A finding worth knowing about Tempo

If TraceQL search only ever returns tiny, constantly re-created traces while `traces_spanmetrics_calls_total`
keeps counting LLM spans, check Tempo's log for `failed to poll tenant blocks … unexpected end of JSON input`. A
single zero-byte block directory on the volume breaks the tenant-index poller; the querier then has no blocklist
and search only sees the ingester's last few minutes — and retention cannot run either. Archive and remove the
empty directory; the next poll rebuilds the index. No config change is involved.
