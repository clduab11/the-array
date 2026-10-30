# Field notes from behind the gateway

These are the findings the reference deployment turned up once every request went through its own front door,
written in September and October 2026 and kept as written. Counts, prices and settings were true on the day
given and have drifted since; the README has the current picture. The short version of the
project is in the [README](../README.md).

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

### The same default, at a second vendor, by a different road

Fixing the first vendor is what turned up the second one. This time nothing
on the vendor's side was misconfigured. The gateway software itself was doing
the translating: a neutral "choose for me" value, which sounds like a
reasonable default, is converted on the way out into *that* vendor's premium
tier. Nobody wrote "premium" anywhere. It was the honest reading of a word
that means something different at each vendor.

That lane had been running unpinned for months, and it is the one behind the
everyday image-and-document route, so it saw real traffic. The fix was the
same one line, on eleven routes and the catch-all beneath them, and a probe
afterward confirmed the vendor now reports the standard tier back. The general
lesson is worth more than the fix: words like "auto", "priority" and "fast"
do not survive translation between vendors, and a gateway that speaks to all
of them has to pin the meaning at every door.

### Prices move under you, in both directions

Vendors reprice constantly. On 2026-07-30 one vendor cut prices across a whole model family, one model by 80 percent and another by 20 percent. A price table you copied once can change in a day, and nothing tells you. The vendor's invoice was right both times; it was our own ledger that was wrong, and that matters because budgets stop spending based on the ledger. A price override written by hand over-counted one model five-fold for nine days after the cut. One mistake was a number we wrote; the other was a number we inherited. The ledger shows the drift, and the fix is a text edit checked against the vendor's published rate card.

### The ceiling that isn't one

There is a single setting that reads like the obvious way to cap monthly
spend, and it is the wrong place to put your real number. Reading the
gateway's source at the pinned version, and again at its current code, shows
what it arms: a counter that lives in the running process and is reset by
nothing but a restart. Set it to the figure you actually intend to spend and,
some weeks later, the gateway simply stops serving — with no month boundary
to release it.

The companion setting, the one that is supposed to warn instead of block,
turned out to do nothing at all. It accepts the value, reports success, and
stores none of it.

So the working arrangement puts the real limits on the team budgets, which do
reset each month, leaves the global figure far above anything intended as a
runaway backstop, and moves the warning to the dashboard, where a query over
the gateway's own ledger emails when a lane passes its share. A number that
looks like a ceiling, a number that silently isn't a warning, and a reset that
only a restart performs — none of that is visible from the setting names.

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
configuration then had more than 80 fallback chains across roughly 190 named
routes and 10 vendor-wide pass-throughs, and could reach about 1,070 model
ids. By late October 2026 it had 164 chains across 217 entries; the model-id
count moves with the vendors' catalogs.

So far the only failure watched walking the list on real traffic is an account
being turned away. A vendor said no
to a newly released model this account could not yet use, and the next model
on the list answered; the ledger showed which one. An outage walks the same
list. One has not yet been watched happening on real traffic.

### A refusal that looks like an empty answer

Models sometimes decline a request. The gateway treated that as a success: it
returned a normal-looking reply with nothing in it and did not try the next
model on the list. A route built to fall back to a second model simply went
quiet.

The same behavior hid a second problem for ten weeks. A test of the discount
vendors give for re-sending the same instructions showed one model paying the
surcharge for storing them and never receiving the discount, so the feature
was switched off for that model. The test prompts had been declined. A
declined request still pays to store the instructions and never reads them
back, which looks exactly like a discount that does not work. On ordinary text
it worked, and it was switched back on.

The configuration now names the routes that should move on when a model
declines, and a small module in `litellm/` does the same for replies that
arrive word by word. In testing, both kinds of reply moved to the next model
and normal answers were untouched; it has not yet been watched happening on
real traffic. One gap remains in the ledger: a declined request and the answer
that replaced it share an identifier, and the ledger keeps one row per
identifier, so one of the two calls goes unrecorded while the vendor bills
both.

### A referee that costs less than the reply

The fix above only fires when the model says, in the protocol, that it
declined. Most declines do not arrive that way. They arrive as a polite
sentence with a normal status, or as filler, and the gateway counts them as
answers. So the reference build now asks a second, much smaller model to
referee. TypeSafe's Jev is not a chat model: it takes the request and the reply
and returns one typed verdict, answered, refused or non-answer, with a
probability, in about half a second, for a few hundredths of a cent. A
confident decline is then treated exactly like a protocol-level refusal and the
gateway moves to the next model on the list. Empty replies are caught without
asking anyone. The same model can pick the tier on the cost-aware router, with
a rule in code that long prompts never get the cheapest model; when the referee
is unreachable the built-in scorer decides, as it did before.

On the reference deployment the referee agreed with a labelled set 15 times out
of 15, including two replies written to argue for their own grade, and the tier
picker 16 of 16; the median round trip was 531 ms and the whole test cost a
tenth of a cent. It is a paid, early-access service with open-ended retention,
so the private routes are excluded and every use was opt-in per route (the
reference deployment has since switched it on for most routes). Knobs,
access rules and the caveats are in `docs/jev-decision-layer.md`.

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

## How updates work here

Every component is pinned to an exact version. A floating tag such as
`postgres:16-alpine` does not keep you patched: the engine only re-checks a
moving tag when explicitly asked, and a routine restart reuses whatever is
already downloaded. Floating buys unpredictable timing and no way back.

`scripts/check-image-updates.py` reads every pinned version and asks the
upstream registries what is newer. It prints a table and applies nothing. A
database must not restart itself, and a gateway update walks database
migrations forward, which needs a backup first. On the day this note was
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
