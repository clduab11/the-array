# Master MCP toolbox

One list of MCP tools (`toolbox.yaml`), rendered into every client's own config. Keys never live in these
files: each config names an environment variable, in that client's own syntax.

| File | What it is |
|---|---|
| `toolbox.yaml` | The list: every kept tool with its profile, address or package, and key name; every dropped tool with what replaces it. Edit this, never the rendered files. |
| `render.py` | Writes `out/<client>/` for Claude Code, VS Code, Zed, OpenCode and Codex. Fails if anything key-shaped appears in the output. |
| `check.py` | Connects to every hosted tool with your keys and reports its real tool count. |
| `dbhub.toml.example` | Read-only config for the one database tool (the gateway's spend ledger). |
| `out/SECRETS.md` | The key names to set, and which are missing (generated). |

## Use it

```bash
python toolbox/render.py
```

```bash
python toolbox/check.py
```

Then merge the rendered block into each client. None of these steps edits a client for you:

| Client | Merge this | Into |
|---|---|---|
| Zed | `out/zed/context_servers.jsonc` | Zed `settings.json` (`context_servers` key) |
| OpenCode | `out/opencode/mcp.jsonc` | `~/.config/opencode/opencode.jsonc` (`mcp` key; keep `$schema`) |
| VS Code | `out/vscode/mcp.json` | the user-level `mcp.json` |
| Codex | `out/codex/mcp_servers.toml` | `~/.codex/config.toml` |
| Claude Code | `out/claude-code/.mcp.json` | a repo root, or `claude mcp add-json` per server |

After changing an environment variable, fully quit each client and reopen it.

## Why one list

- Every tool is pinned to a version, and a bump is a one-line edit followed by a re-render.
- Every key is referenced by name, so no client config ever holds a secret, and rotating a key touches one
  place.
- Tools are grouped by profile (build-code, rnd-researcher, biz-ops, plan-triage). A client carries only
  the profiles it needs, and tools outside them render switched off where the client has an on/off flag.
- Clients that send every tool schema with every request pay for each tool in context. Chrome DevTools
  (~26 tools) and Firecrawl (~25) therefore ship switched off; turn them on for the task.

## Change it

Edit `toolbox.yaml`, run `render.py`, re-merge. Pin versions; never `@latest`. A tool with a `setup:` line
renders switched off until that step is done.
