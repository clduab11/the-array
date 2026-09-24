# Praxen master toolbox

One list of MCP tools (`toolbox.yaml`), rendered into every app's own config. Keys never live in these files —
each config names a Windows user environment variable, in that app's own syntax.

| File | What it is |
|---|---|
| `toolbox.yaml` | The list: every kept tool with its profile, address or package, and key name; every dropped tool with what replaces it. |
| `render.py` | Writes `out/<app>/` for Claude Code, VS Code, Zed, OpenCode, Coder Code, Codex, Msty Studio and Msty Go. Fails if anything key-shaped appears in the output. |
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
| Msty Studio | `out/front-studio/` | Add New Tool, one pasted JSON per local tool; HTTP tools by hand; set keys under Workspaces > Environments |
| Msty Go | `out/front-go/CHECKLIST.md` | Settings > Tools, by hand |

After changing a Windows environment variable, fully quit each app (tray included) and reopen it.

## Change it

Edit `toolbox.yaml`, run `render.py`, re-merge. Pin versions; never `@latest`. A tool with a `setup:` line
renders switched off until that step is done.
