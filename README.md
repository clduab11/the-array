# the-array: Own the front door to your AI.


![Every device in the building sends its requests through one dark gateway arch; from there the light splits toward distant cloud servers and toward a small desk machine in the same room, while a ribbon of ledger entries runs to a wall of dashboards. One red strand is the request that was diverted.](docs/images/the-array-hero.jpg)

the-array is a front door you run for all the AI your business uses. Every
request passes through it and is written to a ledger with its cost, and the
front door is built to enforce whatever rules you set about who may spend
what. This repository is the reference build: a worked example you copy and
adapt. It is published so the patterns, and the mistakes, are available to
anyone who wants the same thing.

If you have never run a server, read the first three sections and the
questions at the end. If you have, skip to "What is in this repository".

## The short version

A seat subscription works like cable television: a fixed fee per person, a
fixed menu, one number on the bill, and no way to see what happened between
"I typed a question" and "I got an answer".

the-array replaces that with something closer to owning the front door.
Every request from every person and every tool in your organisation passes
through one gateway you run. A gateway is the front door in software terms,
the one place every request goes in and every answer comes out. It decides
which AI model answers (a model is one AI engine, the kind of thing behind the
chat assistants you already know) and records exactly what the answer cost.
It is built to refuse further requests once a budget is used up, and when
the outside vendor is unavailable it is built to hand the question to a model
running on a machine in your own office so the answer can still arrive. Which
parts of that have been seen working on real traffic is set out below.

The AI companies still get paid, per use instead of per seat, through
accounts you hold. What you own is the front door. Whether per-use comes to
less than seats depends on how much your people use. Vendors price by the
volume of text that goes in and comes out, the way a print shop charges by
the page, so a one-line question costs pennies at most and a long document
pasted in costs more. Light users usually pay less per use than a seat costs.
A team asking questions all day can pay more. This README gives no figure of
its own; after a month behind the gateway the ledger replaces any estimate
with the real one. The software is free and the vendors are paid per use. A
computer in your office for the local model is optional. Somebody's time to
run it all is the one cost you cannot skip. A seat subscription never exposed
you to any of the hazards described below; they come with paying per use, and
the gateway is what makes them visible once you do.

The bill is the first thing that changes. Every call is recorded: who made
it, which model answered, how many words went in and out, and the cost to a
fraction of a cent.

Each tool then gets its own key, a password-like code the gateway uses to
know who is asking. A key can have a budget and a short list of models it
may use; anything outside the list is refused. A private lane can be limited
to vendors you chose for their privacy terms plus the machine in your office.
Cheap questions can go to a cheap model. The gateway can only count a model
it knows the price of, so the budget is only as accurate as that price
table. The section on prices below shows what happens
when the table is wrong.

Vendors also reprice, retire models and go down. Behind one gateway, moving a
route to a different vendor is a small edit to one file once you hold an
account there. A route is one line in the gateway's rulebook: when a tool
asks for this, send it there, and if that fails, try these. When a vendor is
down, the answer is meant to still arrive from further down that list. The
next section says what has and has not been watched working.

The price of all this is that it is yours to run. That part gets its own
section.

## What you can see from behind your own gateway

Once you pay per use, each vendor sends one monthly total. Everything below
sat underneath one of those totals and was invisible until the gateway's own
ledger was laid beside it. Each of these happened on the reference deployment.

### The double charge nobody asked for

A vendor account was billing roughly double on every request through a
"priority" processing tier that nothing in this system had requested. It was
a default, set on the vendor's side, applied to every call that did not say
otherwise.

A monthly total does not tell you this. It surfaced during a routine check of
the vendor's endpoints: a request sent with no tier at all came back tagged
"priority". The gateway's per-call ledger then showed which routes had been
paying the premium, and it showed something worse. On three routes a price
override we had written ourselves was recording only half of what the vendor
actually charged. The vendor was charging double; our ledger was recording
standard.

The fix was one line of configuration on every route to that vendor, plus a
few deliberately separate "priority" routes with their own small budgets for
the rare prompt that needs the fast lane. After the change, the gateway
confirmed the standard route was billed at the standard rate and the priority
route at the premium, on identical inputs. The ledger now records the tier on
every call, and the dashboard flags any premium-tier call on a route that did
not ask for it. The premium varies by model family, so the dashboard shows the
ratio per route.

### Prices move under you, in both directions

Vendors reprice constantly. On 2026-07-30 one vendor cut prices across a whole model family, one model by 80 percent and another by 20 percent. A price table you copied once can change in a day, and nothing tells you. The vendor's invoice was right both times; it was our own ledger that was wrong, and that matters because budgets stop spending based on the ledger. A price override written by hand over-counted one model five-fold for nine days after the cut. One mistake was a number we wrote; the other was a number we inherited. The ledger shows the drift, and the fix is a text edit checked against the vendor's published rate card.

### A rule saying no

A rule only counts if it binds. On the reference deployment an access key
limited to a short list of models was asked for a model outside that list.
The gateway refused, and the same key's own list kept answering. No monthly
budget has yet been reached on real traffic here, so the budget stop has not
been watched firing on a real person mid-task. It is the same mechanism, a
key the gateway turns away, applied to a running total instead of a list.

### The answer still arrives when the vendor is down

When a vendor returns an error, the request walks down a list of
alternatives, a cheaper cloud model first, then a local one, and the person
who asked still gets an answer. That list is called a fallback chain, and
every fallback chain in this configuration ends at a model running on
hardware in the room. Routes that pass a vendor's whole catalog straight
through have no chain of their own and fail loudly instead. The reference
configuration has more than 80 fallback chains across roughly 190 named
routes and 10 vendor-wide pass-throughs, and can currently reach about 1,070
model ids. That last figure moves with the vendors' catalogs.

So far the only thing watched walking the list is a refusal. A vendor said no
to a newly released model this account could not yet use, and the next model
on the list answered; the ledger showed which one. An outage walks the same
list. One has not yet been watched happening on real traffic.

### Privacy is a routing decision

The private lane is a list, and the list is the whole guarantee. The lane
still begins at a vendor; what the route guarantees is the set of places a
request can ever go. In this configuration that set is: vendors chosen for
their privacy terms, then your own machine. If the chosen vendor is down the
question is answered locally, and if that is down too the request is refused.
It is never quietly retried against a vendor that logs prompts, because no
such vendor is on the list. The list lives in `litellm_config.example.yaml`
under the private chain, where anyone can read it.

## What it costs you

The first start-up is an afternoon. Getting the metering right took months;
the fallbacks and the dashboards took about as long. Every finding above was
preceded by a period in which the system was confidently wrong.

A subscription's failure mode is "the service is down". A self-run gateway
has more of them. A software update can break the database. The "all good"
light can be wrong. The thing that runs the components can freeze when the
machine runs out of memory. A fallback can end at a model someone deleted
from disk. The technical names for those are in `DEPLOYMENT.md`, with the
fixes.

Dead models do not reliably say so. Three separate vendors, a local model
server, a frontier API vendor and a privacy-focused reseller, have each
returned a normal-looking success while serving a different model than the
one requested. Status code and reply looked exactly like success. The rule
this deployment runs on is to check the name of the model that actually
answered; the success code proves nothing.

Some failures cannot be caught by a fallback at all. One kind of AI request
turns your documents into numbers so they can be searched. Two different
models produce numbers of different shapes that cannot be mixed, so those
routes deliberately have no fallback. Swapping models silently would corrupt
the search without any error. Refusing is the only safe behaviour.

There is also the recurring maintenance: version pins to review, price
tables to re-check against rate cards, model ids that vendors retire without
notice, and health checks to re-validate whenever a component changes.

If you want a model and nothing else, a subscription is the right product. If
you want to lay the vendor's monthly total beside your own ledger and see what
is underneath it, this is the price of finding out.

---

## Questions people ask

**Is this a product I can buy?** 
- *No. It is a reference build under an open license. You can run it or adapt it, or pay someone to.*

**Do I need my own hardware?** 
- *Only for the "still answers when a vendor is down" and "private lane" properties. Metering and budgets work with cloud vendors alone; the local model is what makes the fallback and the closed private lane possible. On the reference deployment that hardware is an ordinary desktop computer with a consumer graphics card. Without it the gateway still meters and caps, but the last step of every fallback list would have to be a cloud model or a refusal.*

**Will my existing AI tools work with it?** 
- *Most tools that let you type in a server address and a key will work. In the tool's settings this is usually labelled "OpenAI-compatible" or "custom endpoint". Many desktop AI assistants and coding tools have that setting; check yours before assuming.*

**How much does the gateway itself cost to run?** 
- *The software is free. You still pay the AI vendors for usage; that is the bill the gateway meters and caps. The reference deployment runs on one workstation, and the components together are limited to a few gigabytes of memory. The rest of the cost is the time described above.*

**Will it warn me before a budget runs out?** 
- *Only if you connect a chat webhook; alerting ships switched off in the example configuration. The budget itself is built to refuse requests whether or not a webhook is connected. "A rule saying
no" above says what has and has not been observed.*

**Who maintains this?** 
- *One operator, for the operator's own use, published as-is. There is no support promise and no release schedule. Issues that describe a real failure are more useful than issues that ask for features.*

---

## What is in this repository

Everything here is a template or a tool, built to be read and adapted. It is
the reference build with the operator's specifics removed.

| Piece | What it is |
|---|---|
| `docker-compose.yml` | The whole stack as one file: the gateway (LiteLLM), its database (Postgres) and cache (Redis), metrics (Prometheus), dashboards (Grafana), traces (Tempo), logs (Loki and Alloy), and a private web-search engine (SearXNG). Every component is pinned to an exact version. |
| `litellm/Dockerfile` | The gateway's image, pinned to one release, with one deliberate change explained in the file. |
| `litellm_config.example.yaml` | The routing rules shown as patterns: vendor pass-throughs, a standard-rate route beside an opt-in priority route with its own budget, a privacy-preserving route pinned to its endpoint, local models, a fail-closed private chain, and an embedding route with deliberately no fallback. |
| `prometheus.yml`, `tempo-config.yaml`, `loki-config.yaml`, `alloy-config.alloy` | The observability configuration, including the liveness pattern for components that ship without a shell. |
| `grafana/` | Dashboards and data sources provisioned from disk. Edits made in the Grafana web interface are rejected by design, so these files are the single source of truth. The example dashboard includes the billed-tier detector described above. |
| `provision-keys.example.sh` | Creates teams and per-tool access keys with budgets that reset monthly. |
| `scripts/check-image-updates.py` | Reports which pinned components are behind upstream. It applies nothing. |
| `scripts/verify-stack.py` | A health gate that checks 14 specific things and stops at the first one that fails. It read 14 of 14 on the reference deployment on the day this was written. |
| `scripts/leak-gate.py` | Scans the tree, including the insides of spreadsheets and documents, for anything that must not be published. |
| `DEPLOYMENT.md` | The step-by-step guide: first start-up, connecting a client, changing routes, updating components, rolling back. |
| `.github/` | Automation that opens pull requests and files reports. A human merges. |

What is not here, and will not be: the operator's live routing
configuration, any API keys or access tokens, real budget figures, and any
dashboard that shows real spend.

## How it fits together

```
 people and tools ---> the gateway (one front door, one key per tool, one budget per key)
                            |
              +-------------+------------------+
              v             v                  v
        cloud vendor A  cloud vendor B   local model server (your hardware)
              |             |                  ^
              +---- on error, walk the list ---+   <- every fallback list ends here

        every call ---> spend ledger ---> dashboards and budgets (alerts optional)
```

The gateway speaks the same protocol most AI tools already use, so existing
applications connect to it by changing one address and one key. Nothing about
the tools has to change.

## Quick start

`DEPLOYMENT.md` has the full procedure and the reasoning behind each step.
The short version, for someone comfortable with a terminal:

1. Copy `.env.example` to `.env` and fill in the vendor API keys you hold, a
   master key for the gateway, and passwords for the database and dashboards.
2. Copy `litellm_config.example.yaml` to `litellm_config.yaml`, keep the
   patterns you need, and remove any vendor you do not have a key for.
3. If you run a local model server, point the local routes at it and confirm
   the model names match what the server actually loads.
4. Start the stack with `docker compose --profile observe up -d`. A bare
   `docker compose up` starts nothing, because every component sits behind a
   named profile.
5. Run `python scripts/verify-stack.py`. Do not continue until it passes.
6. Open the dashboards, confirm the data sources are present, and open the
   example dashboard.
7. Create one access key with a budget, point one tool at the gateway with
   that key, and send one request.
8. Read that request back from the spend ledger. Confirm the model named
   there is the one you expected and the cost is not zero. If the cost is
   zero, the price for that model is missing and needs an override.

Not comfortable with a terminal? That is normal. This is a build guide. Hand
it to whoever runs your computers, or to whoever you would hire to.

## How updates work here

Every component is pinned to an exact version. A floating tag such as
`postgres:16-alpine` does not keep you patched: the engine only re-checks a
moving tag when explicitly asked, and a routine restart reuses whatever is
already downloaded. Floating buys unpredictable timing and no way back.

`scripts/check-image-updates.py` reads every pinned version and asks the
upstream registries what is newer. It prints a table and applies nothing. A
database must not restart itself, and a gateway update walks database
migrations forward, which needs a backup first. On the day this README was
written the checker reported, before that day's updates, three components
behind: the gateway one patch release behind, the dashboard software one
minor version behind, and the search engine two days behind its latest
date-stamped build. The gateway was updated after its database backup was
taken. The search engine was left alone, since no advisory stood against the
build it runs. The dashboard software was held on purpose; `DEPLOYMENT.md`
explains why that version changes how data sources are pinned. The same run
exposed a bug in the checker itself: a version-line policy had been hiding an
entire minor line of the trace store and reporting it current. The policy was
fixed and the trace store updated the same day. Policy lines get reviewed for
that reason.

Dependabot opens pull requests; the scheduled image-currency workflow files a
rolling issue. A human merges and updates. The automation in this repository
cannot reach a live stack, so it only checks that the files parse, the compose
file renders, the scripts compile and the leak gate is clean.

This public repository has templates and tooling. A live deployment updates
from its own private configuration, with its own backups, using the same
checker and the same gate.

## Disclaimer

This project is not affiliated with or endorsed by any vendor named in this
document or in the configuration. Product names belong to their owners. The
prices and model ids cited above were true on the dates given and will
drift.

## License

MIT. See `LICENSE`.
