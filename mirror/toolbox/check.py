"""Handshake every hosted (HTTP) tool in toolbox.yaml and report its real tool count.

    python toolbox/check.py

Keys are read from the Windows user environment inside this process and sent only to the tool's own
server, exactly as an MCP client would. Nothing is printed except status, server name and tool names.
Local (stdio) tools are not launched here, because that would download and run their packages.
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

import yaml

try:
    import winreg
except ImportError:  # not on Windows
    winreg = None

HERE = pathlib.Path(__file__).resolve().parent
UA = "praxen-toolbox-check/1.0"  # Exa's endpoint refuses Python's default user agent


def user_env(name):
    if winreg:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            pass
    return os.environ.get(name)


def post(url, headers, body, session=None):
    head = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18", "User-Agent": UA, **headers}
    if session:
        head["Mcp-Session-Id"] = session
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=head, method="POST")
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read().decode("utf-8", "replace")
        session = response.headers.get("Mcp-Session-Id") or session
        messages = [json.loads(line[5:]) for line in raw.splitlines() if line.startswith("data:") and line[5:].strip().startswith("{")]
        if not messages and raw.strip().startswith("{"):
            messages = [json.loads(raw)]
        reply = next((m for m in messages if m.get("id") == body.get("id")), messages[-1] if messages else {})
        return session, reply


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = yaml.safe_load((HERE / "toolbox.yaml").read_text(encoding="utf-8"))
    failures = 0
    for tool in manifest["tools"]:
        if tool["transport"] != "http" or tool["tier"] not in ("core", "role"):
            continue
        auth = tool.get("auth") or {}
        if auth.get("type") == "oauth" or tool.get("setup"):
            print(f"{tool['id']:18} skipped: needs sign-in or setup")
            continue
        headers = dict(tool.get("headers") or {})
        if auth.get("secret"):
            value = user_env(auth["secret"])
            if not value:
                print(f"{tool['id']:18} skipped: {auth['secret']} is not set")
                continue
            if auth["type"] == "bearer":
                headers["Authorization"] = "Bearer " + value
            else:
                headers[auth["header"]] = value
        try:
            session, init = post(tool["url"], headers, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "praxen-toolbox-check", "version": "1"}}})
            try:
                post(tool["url"], headers, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
            except Exception:  # noqa: BLE001 — some servers answer the notification with 202 and no body
                pass
            _, listing = post(tool["url"], headers, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session)
            names = [t["name"] for t in (listing.get("result") or {}).get("tools", [])]
            server = (init.get("result") or {}).get("serverInfo", {})
            print(f"{tool['id']:18} OK   {server.get('name', '?')} {server.get('version', '')} | {len(names)} tools: {', '.join(names[:8])}")
        except urllib.error.HTTPError as exc:
            failures += 1
            hint = " (key rejected — replace it)" if exc.code in (401, 403) else ""
            print(f"{tool['id']:18} FAIL HTTP {exc.code}{hint}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{tool['id']:18} FAIL {type(exc).__name__}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
