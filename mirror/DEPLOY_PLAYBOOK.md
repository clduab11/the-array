# PRAXEN — the-array Deployment Playbook

**Version: 2.0.0 | 2026-09-10 | Host: pc-host (Win11 Pro, 48GB, RTX 4060 Ti 8GB)**
**Stack epoch at writing:** compose v1.7.8 (tempo 2.9.5 → 2.10.8, 2026-09-10) · LiteLLM base v1.100.1 (`litellm/Dockerfile` pin, bumped 2026-09-10 from v1.100.0 — one-fix patch, no schema change) · litellm_config.yaml v4.13.1 · gate `scripts/verify-stack.py` 14/14 before, between and after the day's bumps (v1.100.1 + tempo 2.10.8)

CHANGELOG
- **2.0.0 (2026-09-10, OP REPO-READY / Phase India rewrite)** — full rewrite for the stack as it runs on pc-host since the Branch B cutover (2026-07-17/18). Replaces the banner-deprecated v1.1.0 (2026-04-09, M1 iMac). Prior file preserved at `backup/ops/DEPLOY_PLAYBOOK.md.bak.pre-india-rewrite-2026-09-10`.
- **1.1.0 (2026-04-09)** — M1 iMac 16GB, Docker 8GB VM, MLflow, init-db.sh, 54-tool MCP wiring. Deprecated 2026-05-24; every phase in it is dead (§10).

---

## §0 — Read me first

- **This file** is the *procedure* layer: how to bring the stack up from nothing, run it daily, change it, bump it, bind clients to it, roll it back, and recognise its known failures. It contains no rulings and no history beyond what a procedure needs.
- **`CLAUDE.md`** is *doctrine + ledger*: `<deployed_state>` (what is live, verified), `<durable_rules>` (rules that survived incidents), `<phase_state>` (closed-op AARs). When a procedure here and a rule there disagree, the rule wins and this file is wrong — fix this file.
- **`ops/STATE.md`** is *continuity*: one page, "what was true at the last session". Session start = read it, then verify the config epoch against the live `litellm_config.yaml` header. **The repo wins on conflict** with either STATE.md or this playbook; dated `handoffs/` docs are the long-form record.
- Every command below is written for **Git Bash on pc-host** unless the block says `# elevated PowerShell`. Dumps and restores are byte-sensitive — run them from Git Bash, not PowerShell (PowerShell redirection re-encodes native output).
- Two identifiers that trip everyone: the compose **service key** is `litellm-proxy`; the **container name** is `praxen-litellm`. `docker compose` takes the service key; `docker exec` / `docker logs` take the container name.

## §1 — Prerequisites

**Host.** Windows 11 Pro on pc-host, 48GB RAM. LM Studio and Docker Desktop share that RAM through the WSL cap — see the wedge signature in §9 before loading large models during any pull/build.

**Docker Desktop 4.90.0** (engine 29.7.2, compose 5.5.1), WSL2 backend, `AutoStart=False` **deliberately** — the operator spins the stack down himself; never propose enabling autostart.
- Settings → Advanced → **"Allow the default Docker socket to be used" stays ON.** `praxen-alloy` bind-mounts `/var/run/docker.sock` for container-log collection; without it the Loki row on the board goes dark.
- Settings → Resources → check Resource Saver after any Desktop bump (4.83 changed it to stop the engine on WSL after idle — a stopped engine after idle is not a wedge).
- New `docker desktop` CLI exists (`status`, `logs`, `update`, `restart`). Do **not** run `docker desktop restart` while the engine is still starting (§9).

**`.wslconfig`** at `~\.wslconfig`: `memory=28GB` (was 35.9GB; cut 2026-08-05 after wedge #2). Rollback copy: `backup/current/wslconfig.bak.2026-08-05-pre-28gb`. This cap is a **shared budget with LM Studio's loaded models**; exceeding host RAM terminates the `docker-desktop` distro.

**LM Studio 0.4.24** on the PC, server on `:1234`, JIT loading ON. From inside the proxy container it is reachable ONLY as `http://host.docker.internal:1234/v1` (§7). A second LM Studio runs on the iMac, reached DIRECT over LAN at `http://192.0.2.10:1234/v1` (router-side DHCP reservation; the PC's own LAN address `192.0.2.11` is NOT reserved — open item).

**Tooling on PATH:** `docker`, `git` (set `core.autocrlf=false` before first checkout — `provision-keys.sh`, YAML and the Alloy River config are LF-sensitive), `python` (3.x; `verify-stack.py` and `check-image-updates.py` are stdlib-only; `extract_chains.py` needs PyYAML), `jq` 1.8.2 (hard dependency of `provision-keys.sh`), `curl`.

**Firewall (Private profile, inbound, elevated PowerShell).** Three published ports are LAN/tailnet-exposed for the iMac; each is gated by a named rule. Create any that are missing:

```bash
# elevated PowerShell
New-NetFirewallRule -DisplayName 'fw-litellm-4000' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 4000 -Profile Private
```

```bash
# elevated PowerShell
New-NetFirewallRule -DisplayName 'fw-grafana-3200' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3200 -Profile Private
```

```bash
# elevated PowerShell
New-NetFirewallRule -DisplayName 'fw-searxng-8080' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8080 -Profile Private
```

Everything else (postgres 5432, redis 6379, prometheus 9090, tempo 3210, parked qdrant 6433, parked n8n 5678) publishes on `127.0.0.1` only; loki, alloy and the renderer publish nothing.

## §2 — Files and directories

| Path | What it is |
|---|---|
| `docker-compose.yml` | v1.7.8. 13 service definitions (12 live + the parked sidecar), every image pinned. Profiles: `core` (postgres, redis, litellm-proxy) ⊂ `observe` (+tempo, loki, alloy, prometheus, grafana, grafana-image-renderer, searxng = **10 containers**); `agents` (core + qdrant, n8n) and `full`/`dev` (observe + qdrant, n8n) — never run; `retired` = the parked Tailscale sidecar. |
| `litellm/Dockerfile` | Tag-lock wrapper: `FROM ghcr.io/berriai/litellm:v1.100.1` + a `RUN` that removes hiredis 3.4.0 (open segfault; the tag still ships it). **The LiteLLM version lives HERE, not in compose.** |
| `litellm_config.yaml` | v4.13.1. Bind-mounted read-only into the proxy. 189 explicit entries, 10 provider wildcards, 82 fallback chains, 23 aliases (`router_settings.model_group_alias`). The ONLY authoritative routing surface (§5). |
| `prometheus.yml` | v1.8.0 scrape config: litellm-proxy, tempo, grafana, loki, alloy, self. Carries Tempo/Loki/Alloy liveness (none of the three defines a healthcheck). |
| `tempo-config.yaml` / `loki-config.yaml` / `alloy-config.alloy` / `searxng_settings.yml` | Runtime bind-mounts. Never move them out of root — compose paths are relative. |
| `grafana/provisioning/dashboards/praxen.yaml` | Dashboard provider: `allowUiUpdates:false`, `disableDeletion:true`, 30s poll. |
| `grafana/provisioning/datasources/praxen-datasources.yaml` | Datasources, `editable:false`. uids `afimxbo42ap6oe` (prometheus), `dfipt8nyznn5sc` (tempo), `praxen-loki`, `praxen-litellm-pg`, `sibling-project-b-infinity` are LOAD-BEARING — never change. |
| `grafana/dashboards/*.json` | The live boards (`praxen-msty` is home). Disk is the only author surface. |
| `provision-keys.sh` | v2.0.0 team + virtual-key minting (§3 step 8). Rebuilds `the virtual-key token file` on every run. |
| `.env` / `the virtual-key token file` / `.env.template` | Secrets + virtual-key tokens (gitignored) / sanitised template. Never `cat` the first two into a transcript. |
| `scripts/verify-stack.py` | 14-probe gate, exit 1 on any FAIL. Run before and after every change. |
| `scripts/check-image-updates.py` | Reports which pins are behind upstream. Reports only, never applies. |
| `scripts/extract_chains.py` / `scripts/sync-venice-pricing.py` | Stdout dumper of aliases/chains/terminal tally (`fallback-chains/chains-reference.md` is authored around it) / re-injects per-entry Venice pricing from the live vendor API — re-run + restart when Venice rotates. |
| `fallback-chains/chains-reference.md` / `docs/litellm-config-changelog-archive.md` | Chain snapshot regenerated at every routing bump / verbatim rolled-out config changelogs (§5). |
| `CLAUDE.md` / `ops/STATE.md` | Doctrine + ledger / continuity page (§0). |
| `tailscale-serve.json` | Sidecar serve config — sidecar retired 2026-07-28, file kept for the parked service. |
| `backup/`, `to-be-deleted/`, `handoffs/` | Rollback ladder / visible soft-delete staging / active handoffs — doctrine below. `deliverables/`, `Claude outputs/`, `.firecrawl/`, `.worktrees/` are gitignored working dirs. |

**backup/ doctrine.** Every destructive pass gets a rung FIRST: `<file>.bak.<stage>` in `backup/<class>/` — `compose/`, `litellm-config/`, `db/` (pg dumps, `grafana.db`), `dashboards/`, `grafana-provisioning/`, `prometheus/`, `claude-md/`, `ops/`, `keys/`, `lmstudio-config/`, `current/<date>/` (full operative snapshots incl. `.env`). `backup/archive-pre-v4.12.0/` is archaeology, not a rollback path. Never delete a rung without an explicit go. The ladder IS the rollback path — git exists but the ladder is what every rollback command below reads.

**to-be-deleted/ doctrine.** Nothing is hard-deleted. Cleanup candidates move to `./to-be-deleted/` (visible, gitignored) with a `MANIFEST.md` line per file (origin path, reason, UTC date), reference-checked first. the operator empties it manually. Never auto-purge.

**handoffs/ doctrine.** Root holds ACTIVE dated handoffs only; executed ones move to `handoffs/archive/`. **Empty root = nothing in flight** (the memory-export dir and `reference-agent-overview-v2.json` are reference material, not handoffs — a rule-protected `hermes*` name, never stage it on the keyword).

## §3 — First bring-up on a fresh box, in order

**1. Port the tree.** `git config --global core.autocrlf false` BEFORE the clone/copy (LF-sensitive files). Secrets, a fresh `pg_dump`, and `the virtual-key token file` travel side-channel — never through the repo or a sync folder.

**2. Create `.env` from the template and fill EVERY variable.** `.env.template` v2.0.0 (2026-09-10) is reconciled to the live file; its v1.1.0 predecessor had drifted 8 names behind for months and anyone following it got a dead stack (no UI login, no renderer token, three provider lanes 401ing, no iMac URL). The consumer map below is authoritative whenever the two disagree again — diff `grep -oE '^[A-Z_]+=' .env .env.template` before every bring-up.

```bash
cp .env.template .env
```

| Variable | Consumed by |
|---|---|
| `COMPOSE_PROJECT_NAME=praxen` | compose itself — locks the project namespace (volume/network names `praxen-*`) independent of the directory name. **Must be exactly `praxen`.** |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `postgres` service; `litellm-proxy` (`DATABASE_URL`); `grafana` (creds for the file-provisioned `litellm-postgres` datasource) |
| `LITELLM_MASTER_KEY` | `litellm-proxy`; `provision-keys.sh`; `verify-stack.py` |
| `UI_USERNAME`, `UI_PASSWORD` | `litellm-proxy` admin UI login at `:4000/ui` |
| `RENDERER_AUTH_TOKEN` | `grafana` (`GF_RENDERING_RENDERER_TOKEN`) + `grafana-image-renderer` (`AUTH_TOKEN`). Grafana 13 **boot-fails** without a non-default value. |
| `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` | `grafana`; `verify-stack.py` |
| `WINDOWS_LM_STUDIO_URL` | `litellm-proxy` — the 7 `local-*` routes. Value MUST be `http://host.docker.internal:1234/v1`. |
| `SECOND_LM_STUDIO_URL` | `litellm-proxy` — the `imac-*` routes. `http://192.0.2.10:1234/v1`. |
| `ANTHROPIC_API_KEY` `OPENAI_API_KEY` `GEMINI_API_KEY` `MISTRAL_API_KEY` `PERPLEXITY_API_KEY` `COHERE_API_KEY` `XAI_API_KEY` `VENICE_API_KEY` `OPENROUTER_API_KEY` | `litellm-proxy` provider credentials |
| `GROQ_API_KEY`, `HUGGINGFACE_API_KEY`, `MERCURY_API_KEY` | `litellm-proxy` (sat orphaned for 14 days once — in `.env` but not in the compose whitelist, so three provider lanes 401'd) |
| `N8N_PASSWORD` (`N8N_USER` optional) | `n8n` — agents/full/dev profiles only, never run |
| `TS_AUTHKEY` | `tailscale-litellm` — `retired` profile, parked; keep the variable, the sidecar reads it if ever revived |
| `VERTEX_API_KEY`, `REDIS_HOST`, `REDIS_PORT` | **NOT consumed by compose.** `litellm_config.yaml` does read `os.environ/REDIS_HOST` + `REDIS_PORT` (cache block, ~line 405), but the container gets those from compose's hardcoded `REDIS_HOST: redis` / `REDIS_PORT: 6379`, never from `.env`; `VERTEX_API_KEY` is referenced by nothing (gemini rides `GEMINI_API_KEY`). FLAG — keep them so `.env` and the template agree; do not delete. A `vertex_ai/*` entry or a Redis relocation means wiring them through the proxy `environment:` block first. |

**Rule that follows from this table:** the proxy has NO `env_file:`. A new provider key added to `.env` is invisible until it is also added to the `litellm-proxy` `environment:` block, and that is a recreate (`up -d`), not a restart.

**3. Docker Desktop settings + `.wslconfig` (§1)** before the first pull — image pulls plus a LiteLLM build against a loaded LM Studio is the wedge precondition.

**4. Build the LiteLLM wrapper.**

```bash
docker compose --profile observe build litellm-proxy
```

**5. Bring up the observe profile.** Bare `docker compose up -d` selects **ZERO** services (everything is profile-gated and `COMPOSE_PROFILES` is not set). Always name the profile.

```bash
docker compose --profile observe up -d
```

**6. Watch Prisma walk the schema on first boot** (161 migrations on v1.100.x against an empty DB — v1.100.1 ships the same migration dir as v1.100.0; proxy healthy in 40-60s; `start_period` is 60s). `ENFORCE_PRISMA_MIGRATION_CHECK` defaults to enforce on this tag, so a failed migration fails the boot loudly.

```bash
docker logs -f praxen-litellm
```

Then confirm the wrapper did its job — this MUST fail with `ModuleNotFoundError`:

```bash
docker exec praxen-litellm python -c "import hiredis"
```

Expected `docker compose ps`: 10 `praxen-*` containers `running`; 7 show `(healthy)`; `praxen-tempo`, `praxen-loki` and `praxen-alloy` show plain `Up` — no healthcheck (tempo and loki are distroless; the alloy service simply defines none), their liveness is the Prometheus `tempo`/`loki`/`alloy` jobs.

**7. Firewall rules (§1)** if this is a new Windows install.

**8. Provision teams + keys — FULL RUN ON A FRESH BOX ONLY.** `provision-keys.sh` is idempotent for teams/keys but **rebuilds `the virtual-key token file` from scratch on every run** (`mv` overwrite — existing keys come back as empty placeholders). NEVER run it on the live box to add one key; add the spec line for the record and mint via direct `/key/generate`. Two facts about the script's roster: it is the 2026-06-20 cut (teams sum $N, six keys, some since deleted) — after a fresh run, reconcile teams (`/team/update`) and keys (`/key/generate`, `/key/delete`) to the live ledger in `CLAUDE.md` `<deployed_state>`; and it does NOT mint `front-go-winpc`, which `verify-stack.py` gate 5 reads from `the virtual-key token file` as `VKEY_MSTY_GO_WINPC`.

```bash
./provision-keys.sh
```

Mint any key outside the script with `budget_duration` set — a key minted without it never resets (the `front-go-imac` lesson):

```bash
curl -sS -X POST http://localhost:4000/key/generate -H "Authorization: Bearer $(grep -E '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)" -H 'Content-Type: application/json' -d '{"key_alias":"<alias>","team_id":"<team>","max_budget":10.0,"budget_duration":"1mo","models":["fast"]}' | jq -r '"VKEY_<ALIAS_UPPER_SNAKE>=" + .key' >> the virtual-key token file && chmod 600 the virtual-key token file
```

The token is returned exactly ONCE by `/key/generate`; the pipe above writes it straight into `the virtual-key token file` (the file the gate reads) without it ever reaching stdout — substitute the real `<ALIAS_UPPER_SNAKE>` before running, and never echo it.

**9. Gate.** Must read **14/14**. Anything less is not a finished bring-up.

```bash
python scripts/verify-stack.py
```

**10. Bind clients (§7), then take the day-0 rungs:** `backup/current/<date>/` snapshot of every operative file and a first `pg_dump` (§6 command).

## §4 — Daily operations

Start (idempotent — recreates only what changed):

```bash
docker compose --profile observe up -d
```

Stop everything, keep data (`down -v` destroys volumes — never without an explicit go):

```bash
docker compose --profile observe down
```

Status: `docker compose --profile observe ps` (10 running; tempo, loki + alloy without a health column). Readiness: `curl -s http://localhost:4000/health/readiness` → `status: healthy`, `db: connected`.

Restart the proxy after a `litellm_config.yaml` edit — the YAML is bind-mounted, a restart is enough:

```bash
docker compose restart litellm-proxy
```

Recreate the proxy after a `.env` or compose `environment:` change — env is baked at container creation; `restart` does NOT pick it up:

```bash
docker compose --profile observe up -d litellm-proxy
```

Logs — the proxy (add `-f` to follow; any other service by compose key: `docker compose --profile observe logs --tail 100 grafana`):

```bash
docker logs --tail 200 praxen-litellm
```

Logs — verbose/historical: Grafana board `praxen-msty`, row **08 VERBOSE LOGS // Loki + Alloy** — `$logcontainer` picks the container, `$logq` is a free regex; Succinct panel = error/warn deduped. Loki keeps 7 days.

**Grafana** `http://localhost:3200` (also `http://198.51.100.10:3200` from the iMac) — `admin` / `GRAFANA_ADMIN_PASSWORD`; root lands on `praxen-msty`. **Dashboards and datasources are file-provisioned: disk is the only author surface.** Edit `grafana/dashboards/*.json`, Grafana re-polls within 30s. UI "Save" is rejected by design (`Cannot save provisioned dashboard`); the API/MCP `update_dashboard` path rejects likewise. New board = drop a JSON with a stable `uid` and NO top-level `id`. Datasource edits = edit the YAML, then recreate grafana (`up -d grafana`); a DB-side datasource save would recreate the exact fossil class §9 warns about. Text panels never use `body.theme-*` classes (Grafana 13 hardcodes `theme-dark` in the served HTML).

**LiteLLM admin UI** `http://localhost:4000/ui` — `UI_USERNAME` / `UI_PASSWORD`. Read-only use. **Never save config through the UI's config-update path**: `STORE_MODEL_IN_DB=True` means a UI save writes `LiteLLM_Config` rows that MERGE over the YAML at every boot and shadow it silently (§9). Keys/teams/budgets DO live in the DB and are edited via `/key/update`, `/team/update` — that is the sanctioned DB-side surface.

Prometheus targets `http://127.0.0.1:9090/targets` (6/6 UP is the baseline); Tempo API on `127.0.0.1:3210`; SearXNG `http://localhost:8080/search?q=test&format=json`.

Image currency audit (report only; `python scripts/verify-stack.py --no-llm` is the free gate without the paid chat probe):

```bash
python scripts/check-image-updates.py
```

## §5 — Config change procedure (`litellm_config.yaml`)

The YAML is the ONLY authoritative routing surface. Every bump follows this order; skipping a step is how the last three silent outages happened.

**1. Rung.** Version bumps use `.bak.pre-v<next>`; named ops use `.bak.pre-<stage>`.

```bash
cp litellm_config.yaml backup/litellm-config/litellm_config.yaml.bak.pre-v4.X.Y
```

**2. Allowlist check BEFORE renaming or removing any `model_name`.** Key allowlists pin model NAMES in `LiteLLM_VerificationToken.models`; a renamed entry silently 403s every client on that key.

```bash
docker exec praxen-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT key_alias, models FROM \"LiteLLM_VerificationToken\" ORDER BY key_alias;"'
```

If the name is pinned: `/key/update` FIRST (swap the name on every key that carries it, DB-verify with the same SELECT), THEN edit the YAML, THEN restart. Reverse order darkens the client between the two steps.

```bash
curl -sS -X POST http://localhost:4000/key/update -H "Authorization: Bearer $(grep -E '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)" -H 'Content-Type: application/json' -d '{"key":"<token>","models":["<full new list>"]}'
```

**3. Edit.** Keep LF line endings — PowerShell edits write CRLF and later string-replace anchors silently miss; normalise after any PowerShell touch. Curated entries (`'/' not in model_name`) and venice entries are immune from bulk culls: flag, never auto-delete. Embedding entries get NO fallback chain. No bare `"*"` wildcard, no `model: openai/*` + `api_base` wildcard. Bump the header `Version:` line.

**4. Parse gate.**

```bash
python -c "import yaml; yaml.safe_load(open('litellm_config.yaml', encoding='utf-8')); print('yaml ok')"
```

**5. Restart and wait for healthy** (30-60s):

```bash
docker compose restart litellm-proxy
```

**6. Probe — assert on the ECHOED model, never the status code.** Three vendors (LM Studio, xAI, Venice) return 200 serving a different model than requested. For LM Studio routes read `system_fingerprint`; for cloud read `model`. Nonce every re-probe: the Redis response cache echoes a byte-identical payload in ~0.1s without touching the upstream.

```bash
curl -sS http://localhost:4000/v1/chat/completions -H "Authorization: Bearer $(grep -E '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)" -H 'Content-Type: application/json' -d "{\"model\":\"<route>\",\"max_tokens\":16,\"messages\":[{\"role\":\"user\",\"content\":\"Reply OK. nonce=$(date +%s)\"}]}" | jq '{model, system_fingerprint, content: .choices[0].message.content}'
```

A removed name must **400/403 loudly** — probe the dead name too. Routable count is upstream-driven; the gate checks ≥500 and that every `local-*`/`imac-*` name is registered, never a fixed number.

**7. Regenerate the chain reference** at every routing change. Rung the old one first (`backup/litellm-config/chains-reference.md.bak.pre-v4.X.Y`); `extract_chains.py` prints to stdout — author the new `fallback-chains/chains-reference.md` around the dump (banner with version/date/backup path + the deltas + the dump). `PYTHONUTF8=1` is required — comments carry non-ASCII.

```bash
PYTHONUTF8=1 python scripts/extract_chains.py > backup/litellm-config/chains-dump.v4.X.Y.txt
```

**8. Changelog rule.** The file header keeps `CHANGELOG - current vX` plus ONE prior. At each bump roll the older block VERBATIM to `docs/litellm-config-changelog-archive.md` under a dated heading, and extend the one-line roll ledger at the end of the in-file history note.

**9. Gate, then ledger.** `verify-stack.py` 14/14 → update the config line in `CLAUDE.md` `<workspace_layout>` + the epoch in `ops/STATE.md` → commit when asked.

## §6 — Image bumps

Order for ANY bump: audit (`check-image-updates.py`, §4) → gate (`verify-stack.py`, §3 step 9) → rung(s) → edit one pin → pull/recreate that one service → gate. One image at a time when host memory is thin.

```bash
cp docker-compose.yml backup/compose/docker-compose.yml.bak.pre-<stage>
```

**Memory precondition** (both wedges happened mid-pull): read LM Studio's working set — if it holds more than `lms ps` shows loaded, restart the app first (`lms unload --all` does NOT release it). If free memory sinks mid-op:

```bash
wsl -d docker-desktop sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
```

**LiteLLM base (`litellm/Dockerfile` FROM line) — pg_dump rung is MANDATORY.** Prisma migrates the schema forward on first boot, and since v1.92.0 stored credentials are re-encrypted (AES-256-GCM, versioned) — a tag revert against a migrated DB is unsupported, not merely incomplete.

```bash
docker exec praxen-postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > backup/db/litellm-db.bak.pre-v<tag>.sql
```

Then edit the `FROM` line, rebuild (§3 step 4) and recreate the proxy (§4 `up -d litellm-proxy`). Watch the migration count in `docker logs -f praxen-litellm`, re-check the hiredis import fails (keep the `RUN` line until an upstream tag ships hiredis ≥3.4.1), check `/metrics` still answers unauthenticated, watch RSS against the 1G limit (v1.100.x baseline ~777MiB). Read the release's migration dir before assuming: v1.100.1 (2026-09-10) changed no schema, so a tag revert alone was a complete rollback for that one bump — the rung (`.pre-v1.100.1.sql`) was taken anyway, because the rule is cheaper than the exception. **PyPI install of LiteLLM is prohibited permanently** — the wrapper is the only install path.

**Grafana MINOR bumps — `grafana.db` rung first** (the DB migrates forward on first boot; dashboards/datasources are file-provisioned and unaffected either way):

```bash
docker cp praxen-grafana:/var/lib/grafana/grafana.db backup/db/grafana.db.bak.pre-<ver>
```

```bash
docker compose --profile observe up -d grafana
```

Post-bump: `provisioned=true` on `praxen-msty`, all datasource uids present (the gate checks both). **Grafana stays 13.1.5 — HELD on structure, not on CVE coverage** (13.1.5 IS a listed fixed version for CVE-2026-19475, advisory `>=13.1.5`, and 13.2.x core was never in the affected range): from 13.2 the postgres/prometheus/tempo/loki datasources become externalized catalog plugins, bundled at build time from an UNPINNED list and re-downloaded from grafana.com on every restart (`preinstall_auto_update=true`) — which collides with pin-everything doctrine — and the standalone postgres plugin's own CVE-2026-19475 fix (plugin 13.0.3) shipped after the 13.2.1 image was built. Preconditions for a future 13.2.x move (compose v1.7.8 changelog): `grafana.db` rung; pin `grafana-postgresql-datasource@13.0.3` and the other externalized datasources in `GF_PLUGINS_PREINSTALL_SYNC`; set `GF_PLUGINS_PREINSTALL_AUTO_UPDATE=false`; verify every provisioned datasource uid (§2) resolves post-boot. The schema-v2 dynamic engine is GA but disk stays classic `schemaVersion 42`.

**Distroless images kill exec-form healthchecks.** Tempo 2.9.4+ and Loki 3.7 ship no shell and no busybox; an in-container probe dies with an OCI exec error and pins the container UNHEALTHY while the service is fine. Their liveness rides the Prometheus scrape jobs. On ANY Grafana-family bump, check whether the image still ships a shell before trusting a `CMD` probe.

**Tempo is on the 2.10 line** (2.10.8 — the LAST 2.x minor, patched to 2027-04-26; keeps `ingester`/`compactor`/local-blocks, so `tempo-config.yaml` was unchanged across the 2.9→2.10 move). 3.x removes those sections and the local-blocks processor, relocates `block_retention`, parses strictly (this config would fail to boot) and has no downgrade path — a gated op with a config rewrite (`tempo-cli migrate config`, target 3.1), never a tag edit. `check-image-updates.py` pins its policy to `^2\.10\.` so 3.x reports as "major exists", never "behind". Rungs from the move: `backup/tempo/tempo-config.yaml.bak.pre-v2.10.8`, `backup/tempo/tempodata.bak.pre-v2.10.8.tgz`, `backup/compose/docker-compose.yml.bak.pre-tempo-2.10.8`.

**Postgres/Redis MAJOR** (16→17, 7→8) is a dump/restore migration, not a tag edit; the checker reports it as INFO. Patch-level bumps within the line are tag edits + `up -d <service>` (postgres: pg_dump rung first anyway; LiteLLM rides a postgres recreate without restart). **Prometheus** tag reverts are valid rollbacks (TSDB format unchanged through v3.14.0) — `docker cp praxen-prometheus:/prometheus backup/prometheus/prom-tsdb.bak.pre-<ver>` only if a release notes a format change. **SearXNG** is rolling (date-tagged): the risk is `settings.yml` schema drift — the gate's `format=json` probe covers it. **Docker Desktop** app bumps: pg_dump rung first (the engine restarts every container); the quiet installer leaves `com.docker.service` Stopped (§9).

```bash
python scripts/verify-stack.py
```

## §7 — Client bindings

- **iMac clients** (Msty Studio/Go on the iMac, dashboards, SearXNG MCP) → the PC's **host tailnet node** `http://198.51.100.10:4000/v1`, Grafana `:3200`, SearXNG `:8080`. MagicDNS is OFF tailnet-wide, so IP bindings, not names. The retired sidecar node (`praxen-litellm` @ `198.51.100.11`) is bound by nothing — expire it in the console when convenient.
- **PC clients** (Msty Studio/Go/Gateway on pc-host, Coder Code) → `http://localhost:4000/v1`.
- **Msty Gateway fronts LiteLLM on ONE key** (`front-gateway-winpc`, deliberately allowlist-free; per-app attribution lives in Gateway client tokens, not LiteLLM). Gateway provider base URL is the BARE root `http://localhost:4000` (`/v1/v1` 404s). Gateway is a CLIENT of the proxy — LiteLLM stays sole vendor-facing egress; no vendor keys in Gateway except the ruled Venice-direct exception. **Coder Code stays on the LiteLLM lane permanently.** Gateway 0.5.x locks legacy admin-role client tokens on Free — tokens must be Inference-role.
- Every client rebind list must cover EVERY service the client touches (`:4000`, `:8080`, `:3200`) — SearXNG was missed at the Branch B cutover and darked the iMac MCP for two weeks.
- Break-glass keys (`front-studio-pc`, `front-go-*`, `coder-code-windows`) bind DIRECT to LiteLLM so a wedged Gateway does not darken every app at once.

**LM Studio `api_base` from inside the proxy netns:**
- `WINDOWS_LM_STUDIO_URL` **MUST be `http://host.docker.internal:1234/v1`.** The PC's Tailscale IP is unreachable from the container (8s timeout) while the host reaches it fine — host-side probes prove nothing. That misbinding killed the terminal local rung of every fallback chain for a week in July 2026 with green healthchecks throughout.
- `SECOND_LM_STUDIO_URL` = `http://192.0.2.10:1234/v1` (LAN, direct). Do NOT swap in the iMac's Tailscale IP (same unreachable class). Never point a `local-*` entry at the iMac URL — its catalog also lists the PC's models over LM Link and the call round-trips back to the PC.
- **Any new LM Studio binding is probed from INSIDE `praxen-litellm` before it is trusted:**

```bash
docker exec praxen-litellm python -c "import urllib.request,time; t=time.time(); r=urllib.request.urlopen('http://host.docker.internal:1234/v1/models', timeout=5); print(r.status, round(time.time()-t,2),'s')"
```

- A 200 from a local route is NOT proof the requested model answered — LM Studio serves whatever is resident under an unresolvable id. Assert on `system_fingerprint`; check `lms ps` before reading any LM Studio 400.

## §8 — Rollback paths

**Compose tag revert** (any service; for postgres/grafana/litellm pair it with the DB restore below):

```bash
cp backup/compose/docker-compose.yml.bak.pre-<stage> docker-compose.yml
```

```bash
docker compose --profile observe up -d <service>
```

**LiteLLM base + Postgres restore** (revert the Dockerfile FROM line first; restore the rung taken BEFORE the bump you are reverting — newest is `.pre-v1.100.1.sql`; `WITH (FORCE)` drops Grafana's open datasource connections):

```bash
docker compose --profile observe stop litellm-proxy
```

```bash
docker exec praxen-postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE);" -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"'
```

```bash
docker exec -i praxen-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backup/db/litellm-db.bak.pre-v<tag>.sql
```

```bash
docker compose --profile observe build litellm-proxy
```

```bash
docker compose --profile observe up -d litellm-proxy
```

**grafana.db restore** (named volume `praxen-grafanadata`; `docker cp` works on a stopped container):

```bash
docker compose --profile observe stop grafana
```

```bash
docker cp backup/db/grafana.db.bak.pre-<ver> praxen-grafana:/var/lib/grafana/grafana.db
```

```bash
docker compose --profile observe up -d grafana
```

**Config rung restore + restart:**

```bash
cp backup/litellm-config/litellm_config.yaml.bak.pre-v4.X.Y litellm_config.yaml
```

```bash
docker compose restart litellm-proxy
```

**Dashboard restore** — copy the `.bak` back into place; Grafana re-polls within 30s, no restart, and `disableDeletion:true` means a deleted file never removes the live board:

```bash
cp backup/dashboards/praxen-msty.json.bak.pre-<stage> grafana/dashboards/praxen-msty.json
```

Three older rungs (`.pre-advised-panel`, `.pre-go-lane`, `.pre-v14-retheme`, all taken on or before 2026-08-05) still sit inside `grafana/dashboards/` — Grafana ignores non-`.json` files there; every rung since (`.pre-tier-detector`, 2026-09-10, onward) lives in `backup/dashboards/` per the §2 doctrine.

**`.env` restore** — from `backup/current/<date>/.env`, then recreate the proxy (`up -d litellm-proxy`, §4). **Datasource YAML restore** — from `backup/grafana-provisioning/`, then `up -d grafana`. **Key/team state** is in Postgres — the pg_dump rung covers it. After every rollback: `verify-stack.py`.

## §9 — Known failure signatures and cures

**Docker Desktop memory wedge.** Signature: engine API 500s, EVERY published port dark (`curl 000`), `wsl -l -v` shows `docker-desktop` Stopped, LM Studio (native Windows) still answers, a direct probe to LM Studio `:1234` succeeds while anything through Docker hangs. Cause: `.wslconfig` cap + loaded models > host RAM (twice: 2026-07-17/18, 2026-08-05). Cure, targeted — `wsl --shutdown` is heavier than needed and takes the Ubuntu distro with it:

```bash
lms unload --all
```

```bash
wsl --terminate docker-desktop
```

```bash
# PowerShell
Stop-Process -Name 'Docker Desktop','com.docker.backend' -Force
```

Relaunch Docker Desktop; engine back in ~10s, `unless-stopped` containers auto-restart, parked ones stay parked. Misdiagnosis trap: the first symptom is often ONE hung request (an embedding call) that reads exactly like a routing regression.

**Quiet-installer upgrade leaves `com.docker.service` Stopped.** Signature after a `winget`/`--quiet` Desktop upgrade: app stalls in `starting` forever, `_ping` 500s, distro Stopped; `docker desktop restart` cannot stop the UI and tears the engine down mid-start. Cure: start the service, then a plain launch of `Docker Desktop.exe`.

```bash
# elevated PowerShell
Start-Service com.docker.service
```

**LM Studio holds ~16GB after unload.** Signature: `lms ps` empty yet the LM Studio process working set is 15+GB; a multi-pull then drives host free memory to ~3GB — the wedge precondition. `lms unload --all` does not release it; only an app restart does. Check before any pull/build op; `drop_caches` (§6) is the safe mid-op relief.

**LM Link half-open.** Signature: PC `lms link status` reads peer `disconnected` while the iMac's own `/api/v0/models` still lists all PC models (up one way, down the other), MLX ids vanish from the PC catalog, `imac-*`-era relay routes 400. Diagnose by comparing BOTH boxes' `/api/v0/models`. Cure: PC-side LM Studio restart. The `imac-*` routes ride direct LAN since v4.12.23 and no longer depend on the link at all; a wedged iMac LM Studio (TCP-open, HTTP-silent on `:1234`) needs an iMac-side restart and costs each `imac-*` rung its full timeout before the fallback catch.

**Dark stack at session start may be a deliberate spin-down.** `AutoStart=False` is intentional. Diagnose first — free memory, `wsl -l -v`, engine log timestamps vs last boot, `docker desktop status` — and CONFIRM with the operator before launching. The wedge runbook applies only when its signature matches, never to a clean Stopped distro with free RAM. Never propose enabling autostart.

**Budget resets fire ~10 minutes after boot on the 1st.** If the stack was down over the 1st, every team/key carries LAST month's spend and `budget_reset_at` until one rescheduler window after boot (observed 12:16 after a 12:06 boot). Design, not defect — never hand-zero spend. Verify:

```bash
docker exec praxen-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT team_id, spend, max_budget, budget_reset_at FROM \"LiteLLM_TeamTable\" ORDER BY team_id;"'
```

**Routing contradicts the YAML → check the `LiteLLM_Config` fossil FIRST**, before theorising about router internals. `STORE_MODEL_IN_DB=True` merges DB rows over YAML at boot; a fossil `router_settings`/`litellm_settings` row shadowed the entire fallback doctrine for weeks in 2026. Expected result on v1.100.x: **no rows** (v1.86.3 used to self-persist one `general_settings` row; any row today — `router_settings`, `litellm_settings`, or `general_settings` — warrants the export/DELETE/restart step).

```bash
docker exec praxen-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT param_name FROM \"LiteLLM_Config\";"'
```

If any row appears: export it to `backup/db/` as a rung, `DELETE` the row(s), restart the proxy. Deleting only the Redis `litellm_config:param:*` cache key does nothing — it regenerates from the DB row.

**Silent substitution (three vendors deep)**: LM Studio, xAI and Venice each return 200 under a substitute model for an unresolvable id; an embedder with an unresolvable id returns whatever embedder is resident. Assert on the echoed model / `system_fingerprint`; verify embedders by DIMENSION (the gate expects `legacy/embed` = 1024). Related green-lies: Grafana multi-query panels timing out while text panels render = memory-starved Grafana (1G since v1.7.2, check RSS first); counter panels reading zero after a restart = `increase()` needs two scraped samples.

## §10 — What this playbook replaced, and what must never return

v1.1.0 (2026-04-09) described a **16GB M1 iMac** running an 8GB Docker VM with MLflow as the trace backend, an `init-db.sh` that created the MLflow database, a `master-playground` directory, and a 54-tool Msty MCP wiring guide. None of it survived: the directory became `the-array` with `COMPOSE_PROJECT_NAME=praxen` locked (2026-05-24); **MLflow was purged** the same day (OTel → Tempo replaced it, `init-db.sh` and the pip install went with it); the **Tailscale sidecar was retired** 2026-07-28 (parked at `profiles: ["retired"]` — the proxy owns its own netns and publishes `:4000` itself, which deleted the netns-cascade gotcha class); and the whole stack moved to pc-host in the **Branch B cutover** (2026-07-17/18) — iMac volumes are a dead cold rollback, 12 iMac-era vendor keys were revoked, every secret was re-minted. The iMac is back only as an LM Studio inference node reached over LAN.

Deprecations that must never return:
- **A bare `local` alias** (as `model_group_alias` key or fallbacks key) — it never registers as a model group; the name is `windows-local`-class local routes called by their `local-*` names. Likewise `localwin-*`, `win-fast`/`win-vision`/`win-titan`, and the three dead iMac MLX entry names.
- **PyPI install of LiteLLM** — permanent prohibition since the March 2026 security incident; `litellm/Dockerfile` tag-lock is the only path.
- **Floating image tags** (`:latest`, `16-alpine`, `7-alpine`) — a moving tag re-resolves only on an explicit `docker pull`; `up -d` reuses the local image, so floating delivered no patches and no rollback target. Pin everything; `check-image-updates.py` is the automated check.
- Also dead: a `venice/*` or `inception/*` wildcard with `api_base` override (phantom-catalog bug — those namespaces stay explicit, `api_base`-pinned per entry); a bare `"*"` catch-all; UI/API-saved Grafana dashboards or datasources; UI-saved LiteLLM config; exec-form healthchecks on distroless images.
