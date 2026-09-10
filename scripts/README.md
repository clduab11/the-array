# scripts/

Three stdlib-only Python 3.10+ tools. All are Windows-safe (UTF-8 file I/O, ASCII output)
and take `--help`.

| Script | Job | Exit code |
|---|---|---|
| `check-image-updates.py` | Reads every `image:` pin in `docker-compose.yml` plus the LiteLLM `FROM` in `litellm/Dockerfile`, asks Docker Hub / GitHub what is newer, and prints a table. Per-image policy keeps major jumps (postgres 16, redis 7, tempo 2.10) as "exists", never "behind". `--json` for tooling, `--github-summary` to append a markdown table to `$GITHUB_STEP_SUMMARY` on a scheduled run, `--compose`/`--dockerfile` to audit another tree. **Reports only, applies nothing.** | always 0 |
| `verify-stack.py` | 14-probe health gate: containers healthy, LiteLLM readiness, catalog size, local routes registered, one chain answers, one restricted key refused, embedding dimension, Prometheus targets UP, Grafana health, dashboards and datasource uids provisioned from disk, Loki labels, Tempo echo, SearXNG JSON. Every constant is a flag (`--container-prefix`, `--chain-model`, `--embed-model/--embed-dims`, `--restricted-key-var`, URLs). `--no-llm` skips the one paid probe. Secrets come from the process env or `.env` and are never printed. Run it before AND after any bump. | 1 on any FAIL |
| `leak-gate.py` | Blocking leak scan for the public tree against `leak-denylist.txt` (substrings and `re:` regexes). Scans every text file line by line and **every member of every zip-based archive** (xlsx/docx/pptx/...), recursing into nested archives, because references hide in comment and property parts that cell-value scans never see. Also flags `.env*`, `.virtual-keys.env`, `*.pem`, `*.key`, `id_rsa*` by name. Prints `path:line pattern`, never the matching text. `--allow FILE` for reviewed `path:pattern` exceptions, `--self-test` for the seeded-leak regression. | 1 on any hit |

Typical loop: `python scripts/leak-gate.py` before every push; `python scripts/verify-stack.py`
around every change to the running stack; `python scripts/check-image-updates.py` weekly.
