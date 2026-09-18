# scripts/

Five stdlib-only Python 3.10+ tools. All are Windows-safe (UTF-8 file I/O, ASCII output)
and take `--help`.

| Script | Job | Exit code |
|---|---|---|
| `check-image-updates.py` | Reads every `image:` pin in `docker-compose.yml` plus the LiteLLM `FROM` in `litellm/Dockerfile`, asks Docker Hub / GitHub what is newer, and prints a table. Per-image policy keeps major jumps (postgres 16, redis 7, tempo 2.10) as "exists", never "behind". `--json` for tooling, `--github-summary` to append a markdown table to `$GITHUB_STEP_SUMMARY` on a scheduled run, `--compose`/`--dockerfile` to audit another tree. **Reports only, applies nothing.** | always 0 |
| `verify-stack.py` | 15-probe health gate: containers healthy, LiteLLM readiness, catalog size, local routes registered, one chain answers, one restricted key refused, embedding dimension, Prometheus targets UP, Grafana health, dashboards and datasource uids provisioned from disk, Loki labels, Tempo echo, SearXNG JSON, and the TypeSafe pass-through (skips itself when `TYPESAFE_API_KEY` is unset). Every constant is a flag (`--container-prefix`, `--chain-model`, `--embed-model/--embed-dims`, `--restricted-key-var`, URLs). `--no-llm` skips the one paid probe. Secrets come from the process env or `.env` and are never printed. Run it before AND after any bump. | 1 on any FAIL |
| `leak-gate.py` | Blocking leak scan for the public tree against `leak-denylist.txt` (substrings and `re:` regexes). Scans every text file line by line and **every member of every zip-based archive** (xlsx/docx/pptx/...), recursing into nested archives, because references hide in comment and property parts that cell-value scans never see. Also flags `.env*`, `.virtual-keys.env`, `*.pem`, `*.key`, `id_rsa*` by name. Prints `path:line pattern`, never the matching text. `--allow FILE` for reviewed `path:pattern` exceptions, `--self-test` for the seeded-leak regression. | 1 on any hit |

| `probe-typesafe.py` | Proves a TypeSafe Jev key and, with `--via-proxy`, the gateway's `/typesafe` pass-through: lists models, runs one three-question evaluate, asserts on the served model and the answer shape (never the status code), prints latency, tokens and cost. | 1 on any FAIL |
| `jev-bench.py` | Evidence for the Jev decision layer using the exact questions `litellm/jev_gate.py` ships: tier-classifier agreement on 16 labelled prompts (2 adversarial), judge agreement on 15 labelled pairs (2 adversarial), optional `--local <route>` to judge real local-model replies fetched through the gateway. Writes `evidence/jev/jev-bench.{json,md}`. Imports `litellm`, so run it inside the proxy image (`docker cp` + `docker exec`) rather than installing LiteLLM from PyPI on the host. | 0 |

Typical loop: `python scripts/leak-gate.py` before every push; `python scripts/verify-stack.py`
around every change to the running stack; `python scripts/check-image-updates.py` weekly.
