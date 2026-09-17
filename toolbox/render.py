"""Render toolbox.yaml into each client's own MCP config format.

    python toolbox/render.py            writes toolbox/out/<client>/...
    python toolbox/render.py --check    renders to a temp folder and only runs the secret scan

The output holds environment-variable REFERENCES in each client's syntax, never values. Nothing here edits a
client's live settings: merge the rendered block by hand (or with that client's own CLI).

Per-client rules (verified against each client's documentation):
  Claude Code   .mcp.json "mcpServers"; ${VAR}; Windows stdio via cmd /c npx
  VS Code       mcp.json "servers"; ${env:VAR} for stdio env; ${input:...} for HTTP headers (vscode#336232)
  Zed           "context_servers"; no reference syntax: stdio inherits the user environment, keyed HTTP goes
                through mcp-remote, which expands ${VAR} itself; commands use the runtimes.npx path (no shell)
  OpenCode      "mcp" (V1 shape); {env:VAR}; command is one array; "environment"
  Codex         [mcp_servers.<name>]; env_vars / bearer_token_env_var / env_http_headers (names, not values)
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
CLIENTS = ["claude-code", "vscode", "zed", "opencode", "codex"]
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
    servers = {}
    for tool, enabled in tools:
        if tool["transport"] == "stdio":
            command, args = stdio_parts(tool, manifest["runtimes"], manifest["runtimes"]["npx"])
            entry = {"command": command, "args": args}  # full npx path (npx.cmd on Windows): Zed spawns without a shell
            if tool.get("env"):
                entry["env"] = dict(tool["env"])  # literals only; keys come from Zed's inherited user environment
        elif (tool.get("auth") or {}).get("type") in ("bearer", "header"):
            args = ["-y", manifest["runtimes"]["mcp_remote"], tool["url"]]
            for header, value in http_headers(tool, lambda s: "${%s}" % s).items():
                args += ["--header", f"{header}:{value}"]
            entry = {"command": manifest["runtimes"]["npx"], "args": args}
        else:
            entry = {"url": tool["url"]}
        entry["enabled"] = enabled
        servers[tool["id"]] = entry
    return {"context_servers.jsonc": {"context_servers": servers}}


def render_opencode(manifest, tools):
    servers = {}
    for tool, enabled in tools:
        secrets = secrets_of(tool)
        if tool["transport"] == "stdio":
            command, args = stdio_parts(tool, manifest["runtimes"], "npx")
            full = [command, *args]
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
    lines = ["# Paste into ~/.codex/config.toml. Keys are passed by NAME; Codex reads them from its own environment.", ""]
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


def write(root, client, files):
    for rel, content in files.items():
        path = root / client / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")


def secrets_md(manifest):
    rows = [f"| `{name}` | {info['status']} | {info['for']} | {info.get('note', '')} |" for name, info in manifest["secrets"].items()]
    return "\n".join(["# Keys the toolbox reads (names only)", "",
                      "Set each as a user environment variable (Windows: setx; macOS/Linux: your shell profile), then fully quit and",
                      "reopen every client so it sees the change.", "",
                      "| Variable | Status | Used by | Note |", "|---|---|---|---|", *rows, ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="render to a temp folder and run the secret scan only")
    args = parser.parse_args()
    manifest = yaml.safe_load((HERE / "toolbox.yaml").read_text(encoding="utf-8"))
    root = pathlib.Path(tempfile.mkdtemp()) if args.check else HERE / "out"
    if root.exists() and not args.check:
        shutil.rmtree(root)
    renderers = {"claude-code": render_claude_code, "vscode": render_vscode, "zed": render_zed,
                 "opencode": render_opencode, "codex": render_codex}
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
