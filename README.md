# the-array

A self-hosted AI gateway. One proxy sits in front of every model vendor you
use and in front of the models running on your own hardware, and everything
that passes through it is metered, budgeted and graphed by software you run
yourself. The parts are deliberately ordinary: a LiteLLM proxy, Postgres for
the spend ledger, Redis for caching, Prometheus for metrics, Grafana for
dashboards, Tempo for traces, Loki and Alloy for logs, and a local model
server such as LM Studio for the models that never leave the building.

This README makes the case for owning that layer, argued from this stack's
own numbers rather than from principle. Some of the numbers are unflattering.
That is why they are persuasive.

## Why own it

### 1. Governance you can see

When one proxy is the only way out to any vendor, every call is metered,
attributed to a key, and stopped by a budget. That sounds like bookkeeping
until it catches something.

It caught this. A bare request to the OpenAI API, with no service tier
specified, came back tagged `service_tier: priority` and was billed at
roughly twice the standard rate. Nothing in the stack had asked for that. It
was a default set on the vendor side, at the project level in the account
settings, applied to every call that did not say otherwise.

You cannot find that inside a subscription. There is no invoice line that
says "priority tier, 2x". The only reason it surfaced here is that the proxy
records the billed tier per call in its cost breakdown, and someone looked.

The fix was one configuration key, `service_tier: default`, on every
OpenAI-direct model entry, plus a single opt-in priority route with its own
budget for the rare prompt that genuinely needs the fast lane. Verified after
the change: the priority lane cost exactly 2.0x the standard lane on identical
tokens, so the tier served is the tier billed. One more detail worth knowing:
requesting `priority` is echoed back as `fast`. They are one server-side tier
under two names.

### 2. Prices move under you, both ways

Vendors reprice. On 2026-07-30 OpenAI cut prices across the GPT-5.6 family,
one model by 80 percent and another by 20 percent. If your metering is a
table you copied once, it is now wrong, and nothing tells you.

This stack got it wrong in both directions. A stale price override that had
been written by hand over-metered one model 5x for nine days after the cut.
Separately, a stale price bundled with the proxy software over-metered a
Gemini flash model 2x on live traffic for weeks, until an explicit override
corrected it. One error came from a number we wrote; the other came from a
number we inherited.

The argument is not that owning the config prevents mistakes. It is that
owning the config lets you be wrong and then measurably right. The spend
ledger shows the drift, the fix is a text edit, and the next probe checks
the metered cost against the vendor's published rate card.

### 3. It never goes dark

Every fallback chain in the configuration terminates at a local model on
hardware in the room. When a vendor returns an error, the request walks down
the chain and the answer degrades instead of disappearing. A cheaper cloud
model first, then a local one, and the caller gets a response either way.

The configuration behind this README carries 82 such chains across 189
explicit model entries and 10 provider wildcards. At last measurement the
proxy could route about 1,069 model ids; that number is driven by upstream
catalogs and is never a fixed target.

### 4. Privacy is a routing decision, not a policy promise

A vendor's privacy policy is a promise. A route is a mechanism.

The `private` lane in this configuration fails closed. Its chain contains
only confidential-class rungs, ending at a local model. If the confidential
path is down, the request is refused. It is never quietly retried against a
vendor that logs prompts, because no such vendor is in the chain to retry
against. Whether a request can reach a logging vendor is decided by the
shape of a list in a YAML file, and you can read the list.

## What it costs you

This is the part a pitch would leave out.

It took months. Not the first `docker compose up`, which is an afternoon, but
the part where the metering is correct, the fallbacks are real, and the
dashboards say true things. Every finding above was preceded by a period in
which the stack was confidently wrong.

It breaks in ways a subscription does not. A subscription's failure mode is
"the service is down". A self-hosted gateway's failure modes include a
database migration on an image bump, a healthcheck that lies, a Docker engine
that wedges under memory pressure, and a fallback chain whose last rung
silently pointed at a model that had been deleted from disk.

Dead model ids do not reliably return errors. Three separate vendors, a local
model server, a frontier API vendor and a privacy-focused inference reseller,
have each returned HTTP 200 while serving a different model than the one
requested. The status code, the response shape and the content were all
indistinguishable from success. The rule this stack runs on is: assert on the
echoed model name, never on the status code. That rule exists because the
alternative was learned the expensive way.

Some failures cannot be caught by a fallback at all. Embedding routes here
carry no fallback on purpose. A 1024-dimension embedder and a 768-dimension
embedder are not interchangeable, and a silent failover between them writes
incompatible vectors into the same store, corrupting retrieval without ever
raising an error. Failing closed is the only safe behavior.

Maintenance is real and recurring: image pins to review, price maps to
re-verify against rate cards, model ids that vendors retire without notice,
and healthchecks to re-validate whenever a base image changes. A distroless
image bump silently kills any healthcheck that expects a shell in the
container, which is why Tempo and Loki liveness here rides the Prometheus
scrape job rather than an in-container probe.

If you want a model and nothing else, buy a subscription. If you want to
know what you are paying for, where your prompts go, and what happens when a
vendor is down, this is the price of finding out.

## What is in this repository

Sanitized infrastructure. Everything here is a template or a tool, built to
be read and adapted.

- A pinned Docker Compose stack. Every image is pinned to an exact tag:
  LiteLLM on a pinned base image with a small custom wrapper (the wrapper
  removes the hiredis 3.4.0 extension from the image), Postgres
  16.15-alpine, Redis 7.4.11-alpine, Grafana 13.1.5, grafana-image-renderer
  v5.12.3, Prometheus v3.14.0, Loki 3.7.7, Tempo 2.10.8, Alloy v1.19.2,
  SearXNG 2026.9.8-3fdc6d753. The `observe` profile brings up 10 containers.
  Qdrant v1.15.4 and n8n 2.23.3 are defined under separate profiles and have
  never been run in the reference deployment.
- Observability configuration for Prometheus, Tempo, Loki and Alloy,
  including the scrape-job liveness pattern described above.
- File-provisioned Grafana provisioning for datasources and dashboards, plus
  one example dashboard. Dashboards and datasources are authored on disk
  only. Saves from the Grafana UI are rejected by design, so the files in
  this tree are the single source of truth.
- `litellm_config.example.yaml`, an example LiteLLM configuration that shows
  the patterns without the maintainer's routes: provider wildcards, a standard-tier OpenAI entry next
  to an opt-in priority lane with its own budget, a fail-closed private
  chain, fallback chains that terminate at local model rungs, and an
  embedding route with deliberately no fallback.
- `scripts/check-image-updates.py`, which reports which pinned images are
  behind upstream and never applies anything.
- `scripts/verify-stack.py`, a 14-probe gate that exits non-zero on any
  failure. It read 14 of 14 on the reference deployment on the day this
  README was written.
- `scripts/leak-gate.py`, a leak gate that scans the tree, including the
  raw members of zip-based files, against a denylist before anything is
  pushed, so the public copy stays public. The list that ships here is
  generic; a private, identity-bearing list is layered on with `--denylist`
  and never published, because publishing a denylist publishes what it denies.
- `DEPLOYMENT.md`, the step-by-step bring-up guide.

What is not here, and will not be: the maintainer's live model
configuration, any API keys or virtual keys, real budget figures, and any
dashboard that carries real spend. This repository is a reference for how to
build the thing, not a copy of the thing.

## Quick start

`DEPLOYMENT.md` has the full procedure and the decisions behind each step.
The short version:

1. Copy `.env.example` to `.env` and fill in the vendor API keys you hold,
   a master key for the proxy, and passwords for Postgres and Grafana.
2. Copy `litellm_config.example.yaml` to `litellm_config.yaml`, keep the
   patterns you need, and remove any vendor you do not have a key for. A wildcard for a vendor without a key will fail at
   request time, not at startup.
3. If you run a local model server, point the local model entries at it and
   confirm the served model ids match what the server actually loads.
4. Bring up the stack with `docker compose --profile observe up -d`. A bare
   `docker compose up` selects no services, because every service is
   profile-gated.
5. Run `python scripts/verify-stack.py`. Do not proceed until it passes.
6. Open Grafana, confirm the provisioned datasources are present, and open
   the example dashboard.
7. Create a virtual key with a budget through the proxy, and bind one client
   to the proxy's OpenAI-compatible endpoint using that key.
8. Send a request, then confirm it appears in the spend ledger with a
   non-zero cost and the model you expected. If the cost is zero, the price
   for that model is missing and needs an override.

## How updates work here

Every image is pinned on purpose. A floating tag such as `postgres:16-alpine`
does not keep you patched, because Docker only re-resolves a moving tag on an
explicit `docker pull`, and `compose up` reuses whatever image is already
local. A floating tag buys unpredictable update timing and no rollback
target. Pinning everything and automating the check is the alternative.

`scripts/check-image-updates.py` reads every `image:` line in the compose
file, plus the proxy's base image from its Dockerfile, queries the upstream
registries, and prints what is behind. It never applies an update. That is a
rule, not a limitation: a database engine must not restart itself, and a
proxy image bump walks database migrations forward, which needs a backup
first. On the day this README was written the checker reported, before that day's
bumps, three live images behind: the LiteLLM base one patch release behind,
Grafana 13.2.1, and SearXNG, which is a rolling tag. One of the three, the
LiteLLM base, was bumped the same day after its rollback rung was taken;
SearXNG's rolling tag was left two days old; Grafana was held on purpose
(`DEPLOYMENT.md` explains why 13.2 changes how datasources are pinned). A
held image is a decision the checker keeps surfacing, which is the point.
Tempo also moved that day, 2.9.5 to 2.10.8, and it was NOT one of the three
reported: the checker's version-line policy was pinned to 2.9 and hid the
2.10 line entirely. That is what a checker under-reporting looks like; the
policy was corrected the same day.

Dependabot and GitHub Actions open pull requests. A human merges them. The
continuous integration in this repository cannot reach a live stack, so it
only lints, parses and validates: compose file syntax, YAML and JSON
validity, script syntax, and the leak gate.

One honest note on scope. This public repository carries templates and
tooling. A live deployment does not update from here; it updates from its
own private tree, with its own configuration and its own backups, using the
same checker and the same gate.

## Status and disclaimer

This is a reference stack, maintained by one operator, published so that the
patterns and the findings are available to anyone building the same thing.
There is no support promise and no release schedule. Pull requests that fix
something real are welcome; issues that describe a real failure are more
useful than issues that ask for features.

Nothing here is affiliated with, endorsed by, or supported by any vendor
named in this document or in the configuration. Product names belong to
their owners. Prices, tiers and model ids cited above were true on the dates
given and will drift, which is rather the point.

## License

To be chosen before publication. No `LICENSE` file ships yet; until one is
added, no license is granted.
