# The boards

`grafana/dashboards/` ships two file-provisioned PRAXEN boards: OVERVIEW, which puts the everyday questions on one
screen and keeps every deeper panel one click away, and FORENSICS for a single request. (`gateway-overview.json`,
titled "Gateway Overview", is a separate starter board.) The PRAXEN boards are generated, not hand-drawn: every panel
query was executed against a running stack before it was written down, and `scripts/verify-praxen-boards.py`
re-executes every one of them through Grafana's own datasource path, including the panels inside collapsed sections.

| Board | uid | Question it answers |
|---|---|---|
| PRAXEN // OVERVIEW | `praxen-command` | Is anything broken, what needs attention, what is it costing, is local inference used? |
| PRAXEN // FORENSICS | `praxen-forensics` | What caused this specific request to fail, slow down, fall back or get judged? |

A third file, `praxen-routing.json`, is a signpost page that links to OVERVIEW, so bookmarks to the former ROUTING
board still land somewhere useful.

"Spend ledger" below means the gateway's `LiteLLM_SpendLogs` table (one row per request), which the panel bubbles
call SpendLogs. Every panel's (i) bubble says in plain words what it shows and where the number comes from; ratio
and money panels also name their window and denominator. The boards share the same pickers (TRAFFIC, KEY, MODEL,
TEAM, INTERVAL, LOG CONTAINER, LOG FILTER). TRAFFIC defaults to client traffic: it leaves out calls made with the
master key, calls tagged `health-gate`, and the `sandbox-probe` example key; choose `all` to see them.
The links in the top bar and the row links in the tables carry the time range and the pickers across.

## OVERVIEW

The summary panels (everything above the collapsed sections) fit one 1080p screen; the section headers start just
below them. Colour means one thing: green only for verified healthy, amber for needs a look, red for broken, grey
for idle ("idle · no requests" is not the same as healthy), and steel for no data (a source that did not answer).

- **Top:** a service strip (Prometheus `up` per job) and FRESHNESS (age of the newest spend-ledger row and of the
  newest scrape: amber after 6 hours for the ledger, after one minute for the scrape, so stale data never reads as
  quiet).
- **Eight tiles:** SERVICE (answered ÷ routed; requests refused before routing are not service failures), REJECTED
  (auth, allowlist, rate and budget refusals), FALLBACK (answered by a backup model instead of the one asked for),
  LATENCY (P95/P50 of answered requests over the window), MTD $ with a month-end estimate at the last week's pace,
  WINDOW $, LOCAL (share answered by local models) and ALERTS.
- **NEEDS ATTENTION:** checks on the spend ledger over the window (the key watch-line check is month to date),
  ranked BROKEN (failed after routing, out of credit) → LOOK (rejected, answered by a backup model, off-tier
  billing, a key past its watch line) → INFO (unauthenticated management calls); one VERIFIED row when nothing
  matches. A row click opens FORENSICS with the same window and pickers.
- **Two trends:** requests by outcome and estimated cost by provider.
- **Collapsed sections** (a collapsed section runs no queries until opened): models and local models (the per-model
  table is built on the spend ledger: routed, success, fallback, tokens, P50/P95, first-token time and speed on
  streamed answers, cost), flow, latency, cost/tier/cache, three Jev sections (decisions that changed routing,
  observe-only recordings, operations), client key lanes, teams and routing posture, and logs with the last 50
  requests.

Money is the gateway's own estimate from its price map for logged requests, not a provider bill. Request counts
come from the spend ledger; the Prometheus panels show rates, latency and throughput, and their counts can run a
little low, because the gateway's counters restart from zero when the gateway restarts.

Some panel bubbles describe routes and services of the live deployment copied in `mirror/` (the embedding
container, the Go lanes, the `array/*` routers, the Jev Decisions classifier). On the example config those panels
read empty; nothing is broken.

**Changing the plan.** The monthly plan ($40) and the four example watch lines live in
`grafana/provisioning/alerting/spend-watch.yaml`, and the boards repeat them: the MTD $ tile's amber/red lines and
its "plan $40" label, the SPEND MTD and "vs PLAN" panels in the cost section, and the watch-line lists inside the
NEEDS ATTENTION and key-lanes queries. Change all of them together, or the boards and the alerts will disagree.

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
