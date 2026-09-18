# Deployment

Bring-up, daily operation, updates and rollback for the reference stack. Every
step below has been run on the reference deployment; where a step encodes a
lesson, the lesson is stated so you can decide whether it applies to you.

## 0. What you are deploying

| Profile   | Services                                                                                          |
|-----------|---------------------------------------------------------------------------------------------------|
| `core`    | postgres, redis, litellm-proxy                                                                     |
| `observe` | everything in `core` plus tempo, loki, alloy, prometheus, grafana, grafana-image-renderer, searxng |
| `agents`  | `core` plus qdrant and n8n (defined, never run on the reference deployment)                        |

Every service is profile-gated. A bare `docker compose up` selects **zero**
services. Use `--profile observe` for the full stack.

The proxy is the only egress to any model vendor. Clients talk to the proxy;
the proxy talks to vendors and to your local model server. That single path is
what makes metering, budgets and the fail-closed private lane possible.

## 1. Prerequisites

- Docker Engine with Compose v2 (Docker Desktop on Windows/macOS, or a Linux
  host). On Docker Desktop enable **Allow the default Docker socket to be
  used** — Alloy tails container logs through `/var/run/docker.sock`.
- Memory headroom. The compose memory limits sum to about 6.5 GB across every
  defined service (less for `observe` alone), but image pulls and a LiteLLM
  image build spike well above that. If a local model server shares the host, unload models
  before pulling images. On WSL2 hosts, size `.wslconfig` memory so the VM
  cap plus your model server's resident set stays under physical RAM; the
  failure mode when it does not is the Docker VM stopping under memory
  pressure while everything native keeps running.
- `python3` (3.10+) for the scripts. They are stdlib-only.
- `curl` and `jq` for `provision-keys.example.sh`.
- A local OpenAI-compatible model server if you want local rungs (LM Studio,
  llama.cpp server, vLLM, Ollama with the OpenAI shim). From inside a
  container the host is `host.docker.internal` on Docker Desktop; on Linux add
  `extra_hosts: ["host.docker.internal:host-gateway"]` to the proxy service.

## 2. First bring-up

1. Copy the environment template and fill every `CHANGE_ME`:

```bash
cp .env.example .env
```

   Provider keys you do not hold can stay `CHANGE_ME`; the matching wildcard
   route will fail at request time, not at startup. Remove such wildcards from
   the config if you want a clean catalog.

2. Review `litellm_config.example.yaml` and save your version as
   `litellm_config.yaml` (the compose file mounts that name). Keep the
   patterns you need; delete the rest. Every provider key referenced as
   `os.environ/NAME` must ALSO be passed through in the `litellm-proxy`
   `environment:` block in `docker-compose.yml` — a key present in `.env` but
   absent from that block is silently orphaned and the provider's routes fail
   auth with no configuration error.

3. Build the proxy wrapper and start the stack:

```bash
docker compose --profile observe build litellm-proxy
```

```bash
docker compose --profile observe up -d
```

   On first boot the proxy runs its database migrations (Prisma). Watch them:

```bash
docker logs -f praxen-litellm
```

4. Run the gate. Nothing else is done until it reads all-pass:

```bash
python scripts/verify-stack.py --no-llm
```

   `--no-llm` skips the one paid probe. Run it without the flag once a key
   with a budget exists. The restricted-key probe reads
   `--restricted-key-var`; until you have a restricted virtual key it reports
   SKIPPED, not FAIL.

5. Mint teams and virtual keys. Edit the example specs in
   `provision-keys.example.sh`, then:

```bash
chmod +x provision-keys.example.sh && ./provision-keys.example.sh
```

   Tokens land in `./.virtual-keys.env`, a chmod-600 file that `.gitignore`
   covers, and are never printed.
   The script is idempotent for teams and keys that already exist and rebuilds
   its output file on every run, so never run it just to add one key — mint
   singles with `POST /key/generate` and append by hand. Give every key a
   `budget_duration`; a key without one never resets.

6. Open Grafana on port 3200 (`admin` / the password in `.env`). Confirm the
   four provisioned datasources exist and open the example dashboard. Saves
   from the UI are rejected by design: the JSON on disk is the only author
   surface and Grafana re-reads it every 30 seconds.

7. Optional: spend alerts by email. The gateway's own warning setting stores
   nothing (see the notes in `litellm_config.example.yaml`), so warnings come
   from Grafana alert rules that query the spend ledger:
   `grafana/provisioning/alerting/spend-watch.yaml`. Set `GRAFANA_SMTP_*` in
   `.env`, replace the address in that file, edit the per-key watch lines to
   your plan, then recreate Grafana so the new variables and mount apply:

```bash
docker compose --profile observe up -d grafana
```

   Confirm the rules appear under Alerting. Rules provisioned from disk cannot
   be edited in the UI; change the file instead.

## 3. Binding a client

Point any OpenAI-compatible client at `http://<host>:4000/v1` with a virtual
key as the bearer token. The proxy's `/v1/models` lists what that key may
call. Then send one request and read it back from the spend ledger:

```bash
docker exec praxen-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT model_group, model, spend, prompt_tokens, completion_tokens FROM \"LiteLLM_SpendLogs\" ORDER BY \"startTime\" DESC LIMIT 5"'
```

Two checks on that row. The `model` column must be the model you expected —
three vendors are known to answer HTTP 200 under a substitute when a model id
is dead, so assert on the echoed model, never on the status code. And `spend`
must be non-zero for a paid model; zero means the price map has no entry and
the route needs an explicit `input_cost_per_token` / `output_cost_per_token`.

**Clients that import the model list.** Some front ends call `/v1/models`
themselves to fill a model picker. LiteLLM builds that list by looking up each
model in turn, so a gateway with around a thousand routes can take half a
minute to answer, and a client with a shorter timeout shows none of the
gateway's models. If the client can register models explicitly, do that
instead of relying on its live import, and repeat it after any change that
adds or removes models.

**A read-only key for dashboards.** A dashboard that shows budgets should not
hold a key that can spend. Create a user with the `internal_user_viewer` role,
add it to each team the dashboard should see (`/team/info` answers team
members only), and mint a key for that user limited to the info endpoints:

```bash
H=(-H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json")
curl -s http://localhost:4000/user/new "${H[@]}" -d '{"user_id": "dashboard-reader", "user_role": "internal_user_viewer", "auto_create_key": false}'
curl -s http://localhost:4000/team/member_add "${H[@]}" -d '{"team_id": "research", "member": [{"role": "user", "user_id": "dashboard-reader"}]}'
curl -s http://localhost:4000/key/generate "${H[@]}" -d '{"user_id": "dashboard-reader", "key_alias": "dashboard-reader", "allowed_routes": ["/key/info", "/team/info", "/user/info"]}'
```

Repeat the `member_add` call for every team. On the reference deployment the
key read every team's spend and budget and got a 403 on model calls, on
`/v1/models` and on key creation. A team added later needs the same member,
or the dashboard never sees it.

## 4. Changing the proxy configuration

1. Back up: `mkdir -p backup && cp litellm_config.yaml backup/litellm_config.yaml.bak.<stage>` (`backup/` is gitignored).
2. Edit. Prefer append-only changes.
3. Restart the proxy service (the compose service key is `litellm-proxy`; the
   container name is `praxen-litellm`):

```bash
docker compose --profile observe restart litellm-proxy
```

4. Probe the route you changed and assert on the echoed model.
5. Run `python scripts/verify-stack.py`.

Before renaming any `model_name`, check whether a virtual key's allow-list
pins it; update the key first (`POST /key/update`), then the YAML, then
restart. A rename with a pinned key still in place breaks that client
silently.

Keep `store_model_in_db` false. A config stored in the database merges over
the YAML at every boot and can shadow it for months; when routing contradicts
the file, query the `LiteLLM_Config` table before theorising about the router.

## 5. Updating images

Run the checker; it reports and never applies:

```bash
python scripts/check-image-updates.py
```

Then bump deliberately, one image at a time, with the gate before and after:

- **LiteLLM base** (`litellm/Dockerfile`): take a database dump first. The
  proxy walks migrations forward on boot, and since the 1.92 line credentials
  are re-encrypted at rest, so a tag revert alone is not a rollback.

```bash
docker exec praxen-postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > backup/litellm-db.bak.pre-<tag>.sql
```

  Then edit `FROM`, rebuild, `up -d litellm-proxy`, confirm
  `import hiredis` still fails inside the container (the wrapper removes it
  on purpose), and gate.
- **Grafana minor bumps**: copy `grafana.db` out of the volume first;
  migrations are forward-only. From 13.2 the core datasources become catalog
  plugins that auto-update from grafana.com on every restart — pin them in
  `GF_PLUGINS_PREINSTALL_SYNC` and set `GF_PLUGINS_PREINSTALL_AUTO_UPDATE=false`
  before moving, or you lose the pin-everything property.
- **Tempo**: stay on the 2.10 line until you rewrite the config. 3.x removes
  the `ingester`, `compactor` and local-blocks sections this config uses and
  has no downgrade path. Before any Tempo minor, boot the new image once
  against your config in a throwaway container and look for `Tempo started`.
- **Postgres / Redis**: a MAJOR version is a dump/restore or a migration
  decision, never a tag edit.
- **Distroless images** (Tempo, Loki): they ship no shell, so an exec-form
  healthcheck fails with an OCI error and the container reads unhealthy while
  the service is fine. Liveness for both rides the Prometheus scrape job.

## 6. Rollback

| What broke              | Rollback                                                                                  |
|-------------------------|-------------------------------------------------------------------------------------------|
| An image bump           | Revert the tag, `docker compose --profile observe up -d <service>`                        |
| LiteLLM base bump       | Revert `FROM`, rebuild, restore the pre-bump dump into a clean database                   |
| Grafana minor bump      | Revert the tag, stop grafana, restore `grafana.db` into the volume, start                 |
| A config edit           | Copy the `.bak` back, restart `litellm-proxy`                                             |
| A dashboard edit        | Copy the `.bak` back; Grafana re-reads within 30 seconds                                  |

Never delete a backup without deciding to. Never hard-delete files during a
cleanup; move candidates to a visible staging directory and purge by hand.

## 7. Failure signatures worth knowing

- **Everything through Docker hangs, the model server still answers.** The
  Docker VM ran out of host memory. Unload models, restart the Docker VM, and
  relaunch; containers come back on their own.
- **A local route returns 200 with the wrong model.** The server substituted
  a resident model for an unresolvable id. Fix the id; the status code will
  never tell you.
- **An embedding route returns vectors of the wrong length.** Same
  substitution class. Verify embedders by dimension, never by name. Embedding
  routes carry no fallback for exactly this reason.
- **A container reads unhealthy after an image bump but serves fine.** The
  image went distroless and the exec-form probe cannot run. Move liveness to
  the scrape job.
- **Routing contradicts the YAML.** Check the database-stored config table
  first (see section 4).
- **Budgets did not reset on the 1st.** Resets fire on the proxy's scheduler
  roughly ten minutes after boot; if the stack was down over the boundary, they
  fire after the next start. Do not zero spend by hand.
- **Spend reads zero on a paid model.** No price-map entry. Add an override
  and re-verify the metered cost against the vendor's rate card.
- **A model returns HTTP 200 with an empty answer.** It declined the request
  (finish_reason `content_filter`), and a refusal does not walk `fallbacks`.
  List the route under `content_policy_fallbacks` and keep
  `litellm/refusal_fallback.py` loaded for streamed calls.
- **Caching looks broken on one model.** Check the probe replies were not
  refusals first: a refused call is billed for the cache write and never reads.
- **A front end shows none of the gateway's models.** It imports `/v1/models`
  live and timed out; see "Clients that import the model list" in section 3.
- **Spend alerts never arrive.** `GRAFANA_SMTP_ENABLED` is still false, or the
  address in `grafana/provisioning/alerting/spend-watch.yaml` was not replaced.

## 8. Optional: the Jev decision layer

`litellm/jev_gate.py` adds two decisions the gateway could not make before and one
pass-through, all backed by TypeSafe AI's Jev (a typed-decision model, not a chat
model). Read `docs/jev-decision-layer.md` first; the short version:

1. Put `TYPESAFE_API_KEY` in `.env` and **recreate** the proxy (the module is a new bind
   mount): `docker compose --profile observe up -d litellm-proxy`. With the key unset
   nothing changes: the judge and the classifier decline and the scorer decides.
2. The judge is already loaded by `callbacks` and acts only on routes listed under
   `content_policy_fallbacks` (plus any in `JEV_JUDGE_GROUPS`); `private*` routes never.
   It rewrites a confident decline to `finish_reason: content_filter`, so the existing
   chain walks. Non-streamed calls only.
3. To let Jev pick tiers on a router, uncomment the four `classifier_*` lines under that
   router's `complexity_router_config`. Every classified prompt goes to the vendor, so do
   not do this on a router that must stay local-only. If Jev fails the built-in scorer decides.
4. To let a script or agent call Jev through the gateway, grant the key:
   `POST /key/update {"key": "...", "metadata": {"allowed_passthrough_routes": ["/typesafe"]}}`
   (merge into the key's existing metadata). Then `python scripts/probe-typesafe.py --via-proxy`.
5. Verify: `python scripts/verify-stack.py` (probe 15), `praxen_jev_*` on `/metrics/`, one
   `jev_gate {...}` JSON line per decision in the proxy log, the Jev row on the dashboard.
6. Roll back: remove `jev_gate.judge_instance` from `callbacks` (judge), re-comment the
   `classifier_*` lines (classifier), or unset the key (everything). Restart the proxy.
