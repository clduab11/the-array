# Praxen master toolbox

One list of MCP tools (`toolbox.yaml`), rendered into every app's own config. Keys never live in these files —
each config names a Windows user environment variable, in that app's own syntax.

| File | What it is |
|---|---|
| `toolbox.yaml` | The list: every kept tool with its profile, address or package, and key name; every dropped tool with what replaces it. |
| `render.py` | Writes `out/<app>/` for Windows and WSL clients, Paperclip, Grok, Hermes, and the existing desktop apps. It fails if anything key-shaped appears in the output and refuses to delete stale generated files. |
| `check.py` | Connects to every hosted tool with your keys and reports its real tool count. |
| `dbhub.toml.example` | Read-only config for the one database tool (the LiteLLM spend ledger). |
| `out/SECRETS.md` | The key names to set, and which are missing. |

## Use it

```bash
python toolbox/render.py
```

```bash
python toolbox/check.py
```

Then merge the rendered block into each app. None of these steps edits an app for you:

| App | Merge this | Into |
|---|---|---|
| Zed | `out/zed/context_servers.jsonc` | `%APPDATA%\Zed\settings.json` (`context_servers` key) |
| OpenCode | `out/opencode/mcp.jsonc` | `%USERPROFILE%\.config\opencode\opencode.jsonc` (`mcp` key; keep `$schema`) |
| Coder Code | `out/coder/mcp.jsonc` | `%USERPROFILE%\.config\coder\coder.jsonc` (`mcp` key) |
| VS Code | `out/vscode/mcp.json` | `%APPDATA%\Code\User\mcp.json` |
| Codex | `out/codex/mcp_servers.toml` | `%USERPROFILE%\.codex\config.toml` |
| Claude Code | `out/claude-code/.mcp.json` | a repo root, or `claude mcp add-json` per server |
| Claude Code WSL | `out/claude-code-wsl/.mcp.json` | a WSL repo root, or `claude mcp add-json` per server |
| Msty Studio | `out/front-studio/` | Add New Tool, one pasted JSON per local tool; HTTP tools by hand; set keys under Workspaces > Environments |
| Msty Go | `out/front-go/CHECKLIST.md` | Settings > Tools, by hand |
| Codex WSL | `out/codex-wsl/mcp_servers.toml` | `~/.codex/config.toml` |
| OpenCode WSL | `out/opencode-wsl/mcp.jsonc` | `~/.config/opencode/opencode.jsonc` (`mcp` key) |
| Grok Build | `out/grok/mcpServers.json` | merge `mcpServers` into WSL `~/.claude.json` |
| Paperclip | `out/paperclip/CONNECTORS.md` | reference only; managed through Paperclip's Connectors UI and approved templates |
| Hermes | `out/hermes/mcp-servers.yaml` | merge into `~/.hermes/config.yaml` only after the container-to-hub 403 is resolved; MemPalace stays disabled and query-only |

MemPalace uses the full MCP server for Claude and the compact server for other local harnesses. The compact server still exposes write tools; Paperclip uses its separate approved `mempalace-read` template with `palace_query` only. Hermes uses the remote endpoint with an explicit query-only filter, left disabled while its Docker route returns 403.

After changing a Windows environment variable, fully quit each app (tray included) and reopen it.

## Change it

Edit `toolbox.yaml`, run `render.py`, re-merge. Pin versions; never `@latest`. A tool with a `setup:` line
renders switched off until that step is done. Regeneration writes atomically and refuses stale files; back them up and soft-stage them with a manifest before changing the generated file set.
