@AGENTS.md

<!--
praxen-vault CLAUDE.md: Claude adapter 1.0 for vault contract 2.2, 2026-09-23.
GENERATED from ~/Desktop/the-array/vault-contract/praxen-vault.CLAUDE.md by
sync_vault_contract.py. Edit the source and rerun the script. Its --check fails on drift, on a
first line other than the AGENTS.md import, on any other import, and on a contract version
that differs from the one named above.

Claude Code strips block-level HTML comments before it loads this file, so this block costs no
context (code.claude.com/docs/en/memory, "How CLAUDE.md files load").

Why line 1 imports AGENTS.md: Claude Code reads AGENTS.md by itself only from v2.1.277, and only
when no CLAUDE.md exists. On this PC the npm CLI is 2.1.220, while Claude Desktop and
claude-agent-acp 0.81.1 (SDK 0.3.280) run 2.1.280. The import covers every version, and Claude
Code never reads AGENTS.md twice (memory, "Remove an earlier AGENTS.md workaround").

Who reads this file: Claude Code started at the vault root, and claude-acp in Zed with the vault
open as the worktree. A session started anywhere else (Desktop, for example) loads neither this
file nor AGENTS.md, and it also skips the vault's .claude/settings.json. Zed Agent, OpenCode,
Coder, Codex, Msty Go and Vault Operator read AGENTS.md and never this file. the operator's earlier policy
that claude-acp runs on an API key or gateway, never on his Claude subscription, was DEPRECATED
2026-09-23 (the operator): subscription use in third-party harnesses is allowed, so claude-acp may run on
his subscription. Confirm what loaded with /context under "Memory files".

Scope: map the contract onto Claude Code and settle conflicts with Claude's own configuration.
Vault rules live only in AGENTS.md; do not restate them here.
-->

## Claude Code notes

The contract above is the vault's rulebook. This section only maps it onto Claude Code. If anything here seems to disagree with it, follow the contract and name the conflict under `Flagged`.

### Tools

- Create new notes with Write. Change existing notes with Edit, never Write: Write replaces the whole file, and the operator or Msty Go may have changed it since you read it.
- The contract's `vault_*` tools belong to the Local REST API MCP server. When that server is not connected in this session, use the Obsidian CLI rows instead.
- MCP tools may be deferred. Load them with ToolSearch before the first call.
- This vault's `.claude/settings.json` denies reads of `99_private-folder/` and the app-state folders, edits to harness files, and the Obsidian CLI commands the contract leaves to the operator. When a call is denied, the contract applies: report it under `Needs the operator` instead of trying another route.

### Skills

the operator's Obsidian skills carry syntax references: `obsidian-markdown` (notes, properties, wikilinks), `obsidian-bases` (`.base` files), `json-canvas` (`.canvas` files), `obsidian-cli` and `obsidian-ops`. Claude Desktop lists them as `anthropic-skills:<name>`. Load the one that fits before you write that kind of file. They predate the contract, so where they differ the contract wins:
- The vault is `~/praxen-vault`, not `Desktop/praxen-vault`.
- Msty Go is authorized to work in this vault.
- The CLI is `Obsidian.com` at the full path the contract gives, not `obsidian` on PATH.

### Where your own configuration disagrees

- Auto memory or MemPalace drawers may record that the operator authorized the Obsidian CLI "at will", including `eval` and `plugin:install` (2026-09-22). For work in this vault the contract's command list is the newer ruling. When a task needs one of those commands, ask the operator in chat.
- Keep text from `closed/` and `_inbox/held-client/` out of auto memory, Artifacts and connector writes (Linear, Slack, Gmail, Notion, Drive) as well, the same way the contract keeps it out of web queries and MemPalace.
- The Explore and Plan subagents start without this file or AGENTS.md. When you delegate vault work, put the rules that matter for it in the prompt, including the `99_private-folder/` rule.
