"""Render toolbox.yaml into each client's own MCP config format.

    python toolbox/render.py            writes toolbox/out/<client>/...
    python toolbox/render.py --check    renders to a temp folder and only runs the secret scan

The output holds environment-variable REFERENCES in each client's syntax, never values. Nothing here edits a
client's live settings: merge the rendered block by hand (or with that client's own CLI).

Per-client rules come from the 2026-09-16 format research (sources in the PDF):
  Claude Code   .mcp.json "mcpServers"; ${VAR}; Windows stdio via cmd /c npx
  VS Code       mcp.json "servers"; ${env:VAR} for stdio env; ${input:...} for HTTP headers (vscode#336232)
  Zed           "context_servers"; no reference syntax: stdio inherits the user environment, keyed HTTP goes
                through mcp-remote, which expands ${VAR} itself; ALL hosted tools (OAuth and no-auth too) go via
                mcp-remote so Zed's ACP agents get them; commands use the full npx.cmd path (no shell)
  OpenCode      "mcp" (V1 shape); {env:VAR}; command is one array; "environment"
  Coder Code     same as OpenCode, command wrapped in cmd /c, environment mapped explicitly
  Codex         [mcp_servers.<name>]; env_vars / bearer_token_env_var / env_http_headers (names, not values)
  Msty Studio   one JSON per stdio tool for Add New Tool; {MSTY_VAR} from Workspaces > Environments
  Msty Go       manual checklist (no import; npx.cmd; OAuth for remote tools)
"""
import argparse
import json
import pathlib
import re
import shutil
import sys
import tempfile

import yaml

HERE = pathlib.Path(__file__).resolve().parent
CLIENTS = ["claude-code", "vscode", "zed", "opencode", "coder", "codex", "front-studio", "front-go"]
TOKEN_SHAPES = re.compile(r"(sk-[A-Za-z0-9]{12,}|jina_[A-Za-z0-9]{12,}|tvly-[A-Za-z0-9]{8,}|fc-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}"
                          r"|github_pat_[A-Za-z0-9_]{16,}|hf_[A-Za-z0-9]{16,}|lin_api_[A-Za-z0-9]{16,}|ntn_[A-Za-z0-9]{16,}|ctx7sk[A-Za-z0-9-]{8,})")


def camel(name):
    head, *rest = name.split("-")
    return head + "".join(p.title() for p in rest)


def snake(name):
    return name.replace("-", "_")


def secrets_of(tool):
    auth = tool.get("auth") or {}
    names = list(tool.get("secrets_env") or [])
    if auth.get("secret"):
        names.append(auth["secret"])
    return names


def selected(manifest, client):
    """(tool, enabled) pairs for a client: core/role tools only, honouring clients_only and profiles."""
    wanted = set(manifest["clients"][client]["profiles"])
    out = []
    for tool in manifest["tools"]:
        if tool["tier"] not in ("core", "role"):
            continue
        if tool.get("clients_only") and client not in tool["clients_only"]:
            continue
        in_profile = bool(wanted & set(tool["profiles"]))
        enabled = in_profile and tool.get("default_enabled", True)
        if tool.get("setup"):
            enabled = False  # needs a one-time step first (see the tool's setup line)
        out.append((tool, enabled))
    return out


def stdio_parts(tool, runtimes, npx_cmd):
    if tool["runner"] == "npx":
        if tool.get("bin"):  # a package that ships several binaries: name the one to run
            return npx_cmd, ["-y", "-p", tool["package"], tool["bin"], *tool.get("args", [])]
        return npx_cmd, ["-y", tool["package"], *tool.get("args", [])]
    return runtimes["uvx"], list(tool.get("args", []))


# ------------------------------------------------------------------------------------------- renderers
def render_claude_code(manifest, tools):
    on, off = {}, {}
    for tool, enabled in tools:
        env_lit, secrets = dict(tool.get("env") or {}), secrets_of(tool)
        if tool["transport"] == "stdio":
            command, args = stdio_parts(tool, manifest["runtimes"], "npx")
            entry = {"type": "stdio", "command": "cmd", "args": ["/c", command, *args]} if tool["runner"] == "npx" else \
                    {"type": "stdio", "command": command, "args": args}
            env = {**env_lit, **{s: "${%s}" % s for s in secrets}}
            if env:
                entry["env"] = env
        else:
            entry = {"type": "http", "url": tool["url"]}
            headers = http_headers(tool, lambda s: "${%s}" % s)
            if headers:
                entry["headers"] = headers
        (on if enabled else off)[tool["id"]] = entry
    return {".mcp.json": {"mcpServers": on}, "optional.mcp.json": {"mcpServers": off}}


def http_headers(tool, ref):
    auth = tool.get("auth") or {}
    headers = {}
    if auth.get("type") == "bearer":
        headers["Authorization"] = "Bearer " + ref(auth["secret"])
    elif auth.get("type") == "header":
        headers[auth["header"]] = ref(auth["secret"])
    headers.update(tool.get("headers") or {})
    return headers


def render_vscode(manifest, tools):
    on, off, inputs_on, inputs_off = {}, {}, [], []
    for tool, enabled in tools:
        name, inputs = camel(tool["id"]), (inputs_on if enabled else inputs_off)
        if tool["transport"] == "stdio":
            command, args = stdio_parts(tool, manifest["runtimes"], "npx")
            entry = {"type": "stdio", "command": command, "args": args}
            env = {**(tool.get("env") or {}), **{s: "${env:%s}" % s for s in secrets_of(tool)}}
            if env:
                entry["env"] = env
        else:
            entry = {"type": "http", "url": tool["url"]}

            def ref(secret, _inputs=inputs, _tool=tool):
                input_id = secret.lower().replace("_", "-")
                if not any(i["id"] == input_id for i in _inputs):
                    _inputs.append({"type": "promptString", "id": input_id, "description": f"{_tool['name']}: {secret}", "password": True})
                return "${input:%s}" % input_id

            headers = http_headers(tool, ref)
            if headers:
                entry["headers"] = headers
        (on if enabled else off)[name] = entry
    return {"mcp.json": {"inputs": inputs_on, "servers": on}, "optional.mcp.json": {"inputs": inputs_off, "servers": off}}


def render_zed(manifest, tools):
    # Every hosted tool goes through mcp-remote here, never as a bare {"url": ...} entry. Zed hands each
    # context_server to every external ACP agent verbatim (crates/agent_servers/src/acp.rs, mcp_servers_for_project):
    # stdio as command+args+env, HTTP as url+headers only. The OAuth session Zed itself holds is never forwarded and
    # the agent's mcpCapabilities are never consulted, so a {"url"} entry works in Zed's own agent, 401s inside Claude,
    # Codex, OpenCode, Coder, Copilot and Grok (they get the URL without the token), and is dropped by stdio-only agents
    # (Mistral Vibe). mcp-remote is one shape all of them accept, does the OAuth dance itself, and caches the grant in
    # ~/.mcp-auth so one browser sign-in serves Zed and every agent. Verified 2026-09-19 (Zed 1.20.2).
    servers = {}
    for tool, enabled in tools:
        if tool["transport"] == "stdio":
            command, args = stdio_parts(tool, manifest["runtimes"], manifest["runtimes"]["npx"])
            entry = {"command": command, "args": args}  # full npx.cmd path: Zed spawns without a shell, so bare "npx" fails on Windows
            if tool.get("env"):
                entry["env"] = dict(tool["env"])  # literals only; keys come from Zed's inherited user environment
        else:
            args = ["-y", manifest["runtimes"]["mcp_remote"], tool["url"]]
            for header, value in http_headers(tool, lambda s: "${%s}" % s).items():
                args += ["--header", f"{header}:{value}"]
            entry = {"command": manifest["runtimes"]["npx"], "args": args}
        entry["enabled"] = enabled
        servers[tool["id"]] = entry
    return {"context_servers.jsonc": {"context_servers": servers}}


def render_opencode_like(manifest, tools, coder=False):
    servers = {}
    for tool, enabled in tools:
        secrets = secrets_of(tool)
        if tool["transport"] == "stdio":
            command, args = stdio_parts(tool, manifest["runtimes"], "npx")
            full = (["cmd", "/c", command, *args] if coder else [command, *args]) if tool["runner"] == "npx" else [command, *args]
            entry = {"type": "local", "command": full}
            env = {**(tool.get("env") or {}), **{s: "{env:%s}" % s for s in secrets}}
            if env:
                entry["environment"] = env
            entry["timeout"] = 60000
        else:
            entry = {"type": "remote", "url": tool["url"]}
            if (tool.get("auth") or {}).get("type") != "oauth":
                entry["oauth"] = False
            headers = http_headers(tool, lambda s: "{env:%s}" % s)
            if headers:
                entry["headers"] = headers
        entry["enabled"] = enabled
        servers[tool["id"]] = entry
    return {"mcp.jsonc": {"mcp": servers}}


def toml_str(value):
    return json.dumps(value, ensure_ascii=False)


def render_codex(manifest, tools):
    lines = ["# Paste into %USERPROFILE%\\.codex\\config.toml. Keys are passed by NAME; Codex reads them from its own environment.", ""]
    for tool, enabled in tools:
        lines.append(f"[mcp_servers.{snake(tool['id'])}]")
        auth = tool.get("auth") or {}
        if tool["transport"] == "stdio":
            command, args = stdio_parts(tool, manifest["runtimes"], "npx")
            lines.append(f"command = {toml_str(command)}")
            lines.append("args = [" + ", ".join(toml_str(a) for a in args) + "]")
            if tool.get("env"):
                lines.append("env = { " + ", ".join(f"{toml_str(k)} = {toml_str(v)}" for k, v in tool["env"].items()) + " }")
            if secrets_of(tool):
                lines.append("env_vars = [" + ", ".join(toml_str(s) for s in secrets_of(tool)) + "]")
            lines.append("startup_timeout_sec = 60")
        else:
            lines.append(f"url = {toml_str(tool['url'])}")
            if auth.get("type") == "bearer":
                lines.append(f"bearer_token_env_var = {toml_str(auth['secret'])}")
            elif auth.get("type") == "header":
                lines.append(f"env_http_headers = {{ {toml_str(auth['header'])} = {toml_str(auth['secret'])} }}")
            elif auth.get("type") == "oauth":
                lines.append(f"# sign in once: codex mcp login {snake(tool['id'])}")
            if tool.get("headers"):
                lines.append("http_headers = { " + ", ".join(f"{toml_str(k)} = {toml_str(v)}" for k, v in tool["headers"].items()) + " }")
        lines.append(f"enabled = {'true' if enabled else 'false'}")
        lines.append("")
    return {"mcp_servers.toml": "\n".join(lines)}


def render_msty_studio(manifest, tools):
    files, http_rows, env_names = {}, [], set()
    toolsets = {p: [] for p in manifest["clients"]["front-studio"]["profiles"]}
    for tool, enabled in tools:
        for p in tool["profiles"]:
            if p in toolsets:
                toolsets[p].append(tool["name"])
        secrets = secrets_of(tool)
        env_names.update(secrets)
        if tool["transport"] == "stdio":
            command, args = stdio_parts(tool, manifest["runtimes"], "npx.cmd")
            entry = {"command": command, "args": args}
            env = {**(tool.get("env") or {}), **{s: "{MSTY_%s}" % s for s in secrets}}
            if env:
                entry["env"] = env
            files[f"stdio/{tool['id']}.json"] = entry
        else:
            auth = tool.get("auth") or {}
            header_text = "; ".join(f"{k}: {v}" for k, v in http_headers(tool, lambda s: "{MSTY_%s}" % s).items()) or "—"
            how = {"oauth": "OAuth sign-in", "none": "No auth"}.get(auth.get("type"), "Header")
            http_rows.append(f"| {tool['name']} | {tool['url']} | {how} | {header_text} |")
    files["HTTP-TOOLS.md"] = "\n".join([
        "# Msty Studio — HTTP tools (Add New Tool > HTTP)", "",
        "Header values use Msty Environment variables. Confirm in the Tool Console that the placeholder resolves inside a header;",
        "if it does not, paste the key into Msty's header field instead (it stays inside Msty).", "",
        "| Tool | MCP server URL | Auth | Headers |", "|---|---|---|---|", *http_rows, ""])
    files["ENVIRONMENT.md"] = "\n".join([
        "# Msty Studio — Base Environment variables", "",
        "Workspaces > Environments > Base Environment. Msty adds the MSTY_ prefix itself, so create the names without it.", "",
        *[f"- `{n}` (referenced as `{{MSTY_{n}}}`)" for n in sorted(env_names)], ""])
    files["TOOLSETS.md"] = "\n".join(["# Msty Studio — toolsets", "", *[f"- **{p}**: {', '.join(sorted(set(v)))}" for p, v in toolsets.items()], ""])
    return files


def render_msty_go(manifest, tools):
    rows = []
    for tool, enabled in tools:
        named_for_go = "front-go" in (tool.get("clients_only") or [])
        if not enabled and not named_for_go:
            continue
        if tool["transport"] == "stdio":
            command, args = stdio_parts(tool, manifest["runtimes"], "npx.cmd")
            how = f"Local command: `{command}` · arguments `{' '.join(args)}`"
            if not enabled:
                how += " · add it, then leave it switched OFF until a job needs it"
            if secrets_of(tool) or tool.get("env"):
                how += " · environment: " + ", ".join(list(tool.get("env") or {}) + secrets_of(tool))
        else:
            auth = (tool.get("auth") or {}).get("type")
            how = f"Remote URL: `{tool['url']}` · " + ("OAuth" if auth == "oauth" else "no auth" if auth == "none" else
                                                     "OAuth if offered; header auth did not save on Go 0.15.4")
        rows.append(f"- [ ] **{tool['name']}** — {how}")
    return {"CHECKLIST.md": "\n".join(["# Msty Go — tools to add by hand (Settings > Tools)", "",
                                        "Go has no import. Use `npx.cmd`, not `npx`. Type keys into Go's secure fields.", "", *rows, ""])}


def write(root, client, files):
    for rel, content in files.items():
        path = root / client / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")


def secrets_md(manifest):
    rows = [f"| `{name}` | {info['status']} | {info['for']} | {info.get('note', '')} |" for name, info in manifest["secrets"].items()]
    return "\n".join(["# Keys the toolbox reads (names only)", "",
                      "Set each as a Windows **user** environment variable, then fully quit and reopen every app (tray included) so it sees the change.",
                      "Msty Studio reads the same names from Workspaces > Environments instead.", "",
                      "| Variable | Status on 2026-09-16 | Used by | Note |", "|---|---|---|---|", *rows, ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="render to a temp folder and run the secret scan only")
    args = parser.parse_args()
    manifest = yaml.safe_load((HERE / "toolbox.yaml").read_text(encoding="utf-8"))
    root = pathlib.Path(tempfile.mkdtemp()) if args.check else HERE / "out"
    if root.exists() and not args.check:
        shutil.rmtree(root)
    renderers = {"claude-code": render_claude_code, "vscode": render_vscode, "zed": render_zed,
                 "opencode": render_opencode_like, "coder": lambda m, t: render_opencode_like(m, t, coder=True),
                 "codex": render_codex, "front-studio": render_msty_studio, "front-go": render_msty_go}
    for client in CLIENTS:
        tools = selected(manifest, client)
        write(root, client, renderers[client](manifest, tools))
        print(f"{client:12} {sum(e for _, e in tools):2} on, {sum(not e for _, e in tools):2} off")
    (root / "SECRETS.md").write_text(secrets_md(manifest), encoding="utf-8", newline="\n")
    leaks = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and TOKEN_SHAPES.search(p.read_text(encoding="utf-8"))]
    if leaks:
        sys.exit(f"SECRET-SHAPED STRING IN OUTPUT: {leaks}")
    print(f"secret scan clean; output: {root}")
    if args.check:
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
