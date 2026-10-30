# the-array: own the front door to your AI

![Every device in the building sends its requests through one dark gateway arch; from there the light splits toward distant cloud servers and toward a small desk machine in the same room, while a ribbon of ledger entries runs to a wall of dashboards. One red strand is the request that was diverted.](docs/images/the-array-hero.jpg)

the-array is a private AI gateway with a local model tier that you run
yourself. Every request from the people and tools you connect passes through
one front door. That front door writes the cost of each call to a ledger and
enforces the budgets and model lists you set. A small referee model checks the
answers, and when a cloud vendor fails, the question goes to a model running
on your own hardware.

This is the build **Praxen Development & Engineering** runs every day. It is
published so prospective clients can see how it works before any
conversation starts. To talk about a deployment of your own, start at
[cld-dev.io](https://cld-dev.io).

If you want a chat model and nothing else, a subscription is the right
product. This is for an organisation that wants to see and control what its
AI use costs, where its text goes, and what happens when a vendor fails.

## Why run AI this way

| What you get | How it works |
|---|---|
| A bill you can read | Every call goes into a ledger: who asked, which model answered, how much text went in and out, and the cost to a fraction of a cent. Local calls go in the same ledger at zero vendor cost, next to the cloud ones. |
| Rules that bind | Each tool can get its own key with a budget and a list of models it may use. A request for a model outside the list is refused. |
| Answers when a vendor is down | Each chat route has a fallback list: if one model fails, the next is tried, and every list ends at a model on your own hardware. Embedding routes and whole-catalog pass-throughs have none, on purpose; they fail loudly instead. |
| A private lane | One route can reach only the vendors you chose for their privacy terms, then your own machine. If both are down, the request is refused, never retried somewhere else. |
| A referee | TypeSafe's Jev, a paid cloud service, catches polite non-answers and rates how hard each question is. A check takes about half a second and costs a few thousandths of a cent. |

## The local tier, and why it holds up

Most local AI setups are one desktop app talking to one model. Nothing checks
whether a reply really answers. A question too hard for the loaded model stays
with it. The local work never appears next to the cloud bill. the-array puts
the local models behind the same front door as the cloud ones. They get the
same ledger, rules and fallbacks, plus the following.

**Unsloth Desktop serves the models.** It runs models in the GGUF format, a
single-file format for running models on your own machine, on llama.cpp, the
open-source engine behind most local AI. It downloads them from its Model
Hub and saves a launch setup for each one. On the reference deployment, each
setup was sized to the machine's full memory, not to whatever happened to be
free at the time. The smaller models sit entirely on the 8 GB graphics card.
The larger ones are built from many specialist parts ("experts"), and only a
few of those work on any one word, so the experts sit in ordinary memory
while the rest stays on the card. A dense model too big for the card keeps
as many layers on it as fit. Each
model's context window (how much text it can hold at once) is set to what was
measured to fit. The difference was measured. Unsloth's automatic setting was
given a long context for a 4-billion-parameter model, and llama.cpp moved part
of the model off the graphics card to make room. It fell to about 20 tokens
per second (a token is roughly three quarters of a word). Pinned whole to the
card, with a slightly smaller context measured to fit, it runs at about 62.

As of 2026-10-29 there are 15 local routes on one 8 GB card and 48 GB of
memory: 14 chat routes, with one model loaded at a time, and an embedding
route. They include a 35-billion-parameter coding model at about 22 tokens
per second that holds 114,688 tokens at once. A 30-billion-parameter model
holds 655,360 tokens and runs at about 14 tokens per second. Those two need
about 20 GB of the 48 GB free, so they load only when other work is stopped.

**Jev chooses, Unsloth answers.** On the local routers, Jev rates each
question by difficulty, and each difficulty level points to a local model:
easy questions go to a fast one, hard ones to a stronger one. Sometimes a
request names a small local model directly and Jev rates the question harder
than that model can handle. The request then moves up to a stronger local
model, never down. Jev also records a verdict on local answers (answered,
refused or non-answer), so the dashboards show which local models dodge which
questions. The next step is already collecting data: a picker that weighs
difficulty, task and content policy across the local roster. For now it
records what it would have chosen and routes nothing, until its records are
reviewed and it is switched on.

Jev runs in TypeSafe's cloud. To rate a question, the gateway sends the
question's text to TypeSafe, and to record a verdict it sends the reply as
well. So on any route where Jev is on, a local answer still involves one
outside service. On the reference deployment Jev is on for most routes,
the local ones included. The private lane never uses it, and without a
TypeSafe key it does nothing at all.

**A guard sits between the apps and the model server.** Unsloth Desktop will
run its built-in tools on your machine whenever a request asks, for anyone
holding its key. A small gateway module (`litellm/unsloth_guard.py`, on by
default in this kit) removes those requests and forces the tools off. No
client can switch them on through the front door, and no app is given the
model server's own address.

**Embeddings stay out of the way.** Embeddings are the step that turns
documents into numbers for search. Unsloth keeps one chat model loaded at a
time, and an embedding call there would unload it. Embeddings therefore run
in a small separate container, and the chat model stays loaded.

**Msty Studio and Msty Nexus sit on the desk.** Msty Studio is the desktop
workspace people use: chat, knowledge stacks (your own documents, indexed for
search) and tools. Msty Nexus sits between the desktop apps and the gateway.
It gives the apps one address and the full list of routes, and it can issue
each app its own token, so one app's access can be revoked without touching
the others. Nexus is a client
of the gateway, not a replacement: the gateway is still where spend is
counted and rules are applied. Coding tools connect the same way, or
straight to the gateway with a key of their own.

**The trade-offs are real.** Only one local model is loaded at a time, and
switching to another takes 10 to 40 seconds. The largest models compete with
everything else for memory. Someone has to run all of it: version pins, price
tables, retired model names and health checks all need regular attention.

## What leaves the building

- **Cloud routes:** the request goes to the vendor that route names, through
  an account you hold.
- **Routes with Jev switched on (most of them on the reference
  deployment):** the question's text goes to TypeSafe, and the reply too
  when Jev records a verdict.
- **The private lane:** only the vendors it lists, then your own machine.
- **Local routes without Jev:** nothing leaves the machine.
- **The ledger, dashboards, traces and logs:** these stay on your machine.

## What has been measured

- **The referee (2026-09-18, small labelled sets).** Jev matched a labelled
  set of answers 15 times out of 15, including two replies written to argue
  for their own grade, and picked the right difficulty tier 16 times out of
  16. The median check took 531 ms, and the whole test cost a tenth of a
  cent. Details: [`docs/jev-decision-layer.md`](docs/jev-decision-layer.md)
  and
  [`docs/why-a-referee-in-front-of-local-models.md`](docs/why-a-referee-in-front-of-local-models.md).
- **What the ledger turned up.** A vendor's default priority tier billed
  every call at between about 1.3 and 2.5 times the standard rate, depending
  on the model family. A price table we wrote ourselves over-counted
  one model five-fold for nine days. A spending cap turned out to be a
  counter that only a restart resets. Refusals arrived looking like empty
  answers. Each story, and what fixed it, is in
  [`docs/field-notes.md`](docs/field-notes.md).
- **What has not been watched yet.** No real vendor outage has yet been seen
  walking a fallback list on live traffic, and no monthly budget has yet been
  seen stopping a real person in the middle of a task. The mechanisms for
  both have been tested.

## How it fits together

```
 people and tools (Msty Studio, editors, agents)
          |
          v
 Msty Nexus  (one address, one token per app)                  optional
          |
          v
 the gateway: LiteLLM + Jev (TypeSafe cloud)
 (ledger, budgets, model lists, fallbacks, referee, Unsloth guard)
          |
   +------+--------------------+----------------------------+
   v                           v                            v
 cloud vendor A          cloud vendor B          Unsloth Desktop on your GPU
   |                           |                            ^
   +-------- on error, walk the fallback list --------------+   <- every chat list ends here

 embeddings ---> a small separate embedding container
 every call ---> ledger ---> Grafana dashboards, budgets, alerts
```

The gateway speaks the OpenAI-compatible API that many AI tools support, so
an existing tool connects to it by changing one address and one key.

## What is in this repository

| Path | What it is |
|---|---|
| `docker-compose.yml` | The whole stack: the LiteLLM gateway, Postgres, Redis, Prometheus, Grafana, Tempo, Loki with Alloy, and SearXNG for private web search. Each component is pinned to an exact version tag; the live deployment also pins the gateway image by digest (`mirror/litellm/Dockerfile`). |
| `litellm_config.example.yaml` | The routing rules as patterns: vendor pass-throughs, a standard route beside an opt-in priority route, a private chain that refuses rather than leaks, local routes, and an embedding route with deliberately no fallback. |
| `litellm/` | The gateway image, the Jev decision layer (`jev_gate.py`: the referee and the difficulty picker), the refusal-fallback module and the Unsloth guard. |
| `grafana/`, [`docs/dashboards.md`](docs/dashboards.md) | Dashboards provisioned from disk: PRAXEN // OVERVIEW (is anything wrong, what needs attention, what it costs; the summary fits one screen and every deeper panel sits in collapsed sections) and FORENSICS (which request), plus the Gateway Overview starter board. |
| `scripts/` | The health gate (`verify-stack.py`), the image-currency report, the leak gate, the dashboard checker, and the Jev probes and benchmark. |
| `toolbox/` | One list of MCP tools (the plug-ins that give AI apps search, files and other abilities) rendered into each client's own config file, with environment-variable references only. |
| `mirror/` | A cleaned-up copy of the live deployment: the current gateway config and compose file, the Jev plugin with the local routing and the recording picker, and the per-model setup tool for Unsloth Desktop. |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | The step-by-step guide: first start-up, connecting a client, changing routes, updating, rolling back. |

## Quick start

[`DEPLOYMENT.md`](DEPLOYMENT.md) has the full procedure. The short version:

1. Copy `.env.example` to `.env`. Fill in the vendor keys you hold, a master
   key for the gateway, and passwords for the database and dashboards.
2. Copy `litellm_config.example.yaml` to `litellm_config.yaml`. Keep the
   patterns you need, and remove any vendor you have no key for.
3. If you run Unsloth Desktop, set `UNSLOTH_PC_URL` and `UNSLOTH_PC_API_KEY`,
   make sure the local route names match the models it serves, and point
   `LOCAL_EMBED_URL` at a separate embedding server. The Unsloth guard is
   already switched on.
4. Start the stack with `docker compose --profile observe up -d`.
5. Run `python scripts/verify-stack.py`, and do not go further until it
   passes.
6. Create one key with a budget, point one tool at the gateway, send one
   request, and read it back from the ledger. If it shows the model you
   expected at a cost above zero, metering works.

## Questions people ask

**Is this a product I can buy?** It is a reference build under the MIT
license. You can run it yourself or adapt it. For help with a deployment of
your own, contact Praxen Development & Engineering at
[cld-dev.io](https://cld-dev.io).

**Do I need my own hardware?** Only for the fallbacks and the private lane.
Metering and budgets work with cloud vendors alone. The reference deployment
runs on one ordinary desktop with a consumer graphics card.

**Will my existing AI tools work with it?** Most tools that let you set a
server address and a key will work. In the tool's settings this is usually
called "OpenAI-compatible" or "custom endpoint".

**What does it cost to run?** The code here is free (MIT). Jev and the cloud
vendors bill per use through accounts you hold. Msty and Unsloth have their
own terms. The local tier needs a machine with a graphics card. The main
cost is the time it takes to run it.

## Terms used here

- **Gateway:** the one program every AI request passes through. Here it is
  LiteLLM.
- **Route:** one entry in the gateway's rules: "a request for this name goes
  there".
- **Fallback list:** the models a route tries next, in order, when one fails.
- **Key:** a password-like code that tells the gateway which tool is asking.
- **Token:** a piece of text about three quarters of a word long. Models are
  priced and measured in tokens.
- **Context window:** how many tokens a model can hold at once.
- **Embeddings:** numbers a model makes from text so the text can be searched
  by meaning.
- **Container:** a packaged program that Docker runs in isolation, one per
  component.
- **Grafana:** the dashboard software. Prometheus, Tempo and Loki store the
  metrics, traces and logs it shows.

## Disclaimer

This project is not affiliated with or endorsed by any vendor named here or
in the configuration. Product names belong to their owners. Prices, speeds
and model names were true on the dates given and will drift.

## License

MIT. See [`LICENSE`](LICENSE).
