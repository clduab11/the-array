# mirror/ — sanitized structural backup of the private workspace

This folder is a **failsafe snapshot** of the configuration that runs the stack, taken from the private workspace
and sanitized before it left the machine. It is not the showcase (that is the rest of this repository) and it is
not directly deployable: identity values were replaced, so a restore needs them re-entered by hand.

Generated 2026-10-02 by a private tool; every file passed the leak gate before commit.

## What is here

| Path | What it is |
|---|---|
| `docker-compose.yml`, `prometheus.yml`, `tempo-config.yaml`, `loki-config.yaml`, `alloy-config.alloy`, `searxng_settings.yml` | The stack and its observability configs |
| `litellm_config.yaml`, `litellm/` | The full proxy routing config and its image wrapper and plugins |
| `provision-keys.sh`, `env.template` | Team and key provisioning, and every environment variable the stack reads (names only) |
| `fallback-chains/chains-reference.md` | The fallback chains, generated from the config |
| `scripts/`, `toolbox/` | The live operating scripts and the MCP toolbox sources |
| `vault-contract/` | The agent contract for the notes vault and its sync script |
| `DEPLOY_PLAYBOOK.md` | The restore and operations procedure |

The dashboards are in `../grafana/dashboards/` (sanitized by their own port).

## What was changed on the way out

- **Comments:** removed from the stack's YAML files (compose, the proxy config, Prometheus, Tempo, Loki, SearXNG) and the
  Alloy config (they carried names, clients and figures). `toolbox/toolbox.yaml` is a manifest whose comments and notes are
  its documentation: it keeps them and goes through the same substitutions as every other file.
- **Budgets:** every `max_budget` / `soft_budget` value reads **1.0**, and team and key budgets in
  `provision-keys.sh` read **1**. Set your own before provisioning.
- **Dollar figures** of two or more digits in prose read **$N**.
- **Addresses:** private-range IPs were remapped to documentation ranges (198.51.100.x for the tailnet, 192.0.2.x
  for the LAN, 203.0.113.x and 198.18.0.x for container networks), one per distinct real address.
- **Names:** people, hosts, clients, sibling projects, key families, mailboxes and user paths were replaced with
  neutral placeholders (for example `pc-host`, `~`, `user@example.com`, `front-*`, `legacy-go/*`, `intake-*`).
- **Not copied:** secrets (never in git), the narrative documents (operator notes, state logs, handoffs, rule pages), and
  the local-hosting guide, which records one machine's sign-in and security settings.
  Scripts here cite some of them by path (`docs/rules/...`, `docs/STATE.md`); those paths are not part of this snapshot.

## Restoring from it

1. Clone this repository and copy `mirror/` to the new workspace root.
2. Rename `env.template` to `.env` and fill every value from your password manager.
3. Replace the placeholder budgets, addresses and names you need (search for `1.0`, `198.51.100.`, `192.0.2.`,
   `pc-host`, `user@example.com`, `HUB_PORT`).
4. Follow `DEPLOY_PLAYBOOK.md`: build, seed the embedder's model volume (section 3, step 4a),
   `docker compose --profile observe up -d`, provision keys, then `python scripts/verify-stack.py`.
