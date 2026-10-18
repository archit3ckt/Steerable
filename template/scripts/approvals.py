"""Approvals for tools that change things in the owner's services.

The chat runs Claude Code headless, so nobody is there to answer a permission prompt. This file
is the one who answers: an MCP server (stdio) that Claude Code calls through
--permission-prompt-tool for every tool call no rule settles. It decides at once, never waits:

- tools that only read (their server says so; for claude.ai connectors, by their name) run;
- tools the owner chose to always allow run, and so does the exact call they allowed once;
- anything else becomes a decision on the owner's dashboard, and the COO is told it's waiting.
- tools that aren't MCP tools are refused: the chat's own rules already say what it may do.

When the owner allows it, the agent API starts a turn that makes the same call, which then
matches its grant. Steerable Cloud's connected services don't come here: its gateway holds those
changes for the owner itself.

    Claude Code: --permission-prompt-tool mcp__approvals__ask   (integrations.claude_mcp_args)
    OpenCode:    python scripts/approvals.py check mcp__<server>__<tool>  < input.json
                 (from the plugin opencode_approvals.js, before each call to those servers)
"""
import fcntl
import hashlib
import json
import re
import sys
import time
from contextlib import contextmanager

from common import CACHE, env, now_iso

STORE = CACHE / "approvals.json"
SERVER = "approvals"
TOOL = f"mcp__{SERVER}__ask"
GRANT_MINUTES = 30
CONNECTOR = "claude_ai_"  # Claude Code names claude.ai connectors mcp__claude_ai_<Name>__<tool>
READ_VERBS = ("get", "list", "search", "read", "find", "fetch", "query", "describe", "view", "lookup",
              "retrieve", "count", "download", "check", "preview")
DESTRUCTIVE = re.compile(r"delete|trash|remove|destroy|cancel|refund|void|archive|purge|revoke", re.I)


@contextmanager
def _store():
    CACHE.mkdir(exist_ok=True)
    with (CACHE / "approvals.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(STORE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data.setdefault("pending", {})
        data.setdefault("always", [])
        data.setdefault("grants", [])
        yield data
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.chmod(0o600)
        tmp.replace(STORE)


def split(tool_name: str) -> tuple[str, str]:
    """mcp__<server>__<tool> -> (server, tool)."""
    server, _, tool = tool_name.removeprefix("mcp__").partition("__")
    return server, tool


def service_name(server: str) -> str:
    if server.startswith(CONNECTOR):
        return server[len(CONNECTOR):].replace("_", " ")
    own = _own(server)
    return own["name"] if own else server


def human(tool: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_-]+", " ", tool)).strip().lower()


def _fingerprint(tool_name: str, tool_input) -> str:
    return hashlib.sha256(json.dumps([tool_name, tool_input], sort_keys=True).encode()).hexdigest()


def _own(server: str) -> dict | None:
    try:
        import tools
        return next((c for c in tools.connected() if tools.slug(c["id"]) == server), None)
    except Exception:
        return None


def reads_only(server: str, tool: str) -> bool:
    own = _own(server)
    if own is not None:
        return tool in own["readOnly"]
    if server.startswith(CONNECTOR):
        first = re.split(r"[_\-]", tool.lower(), maxsplit=1)[0]
        return first in READ_VERBS
    return False


def destructive(server: str, tool: str) -> bool:
    own = _own(server)
    return bool(DESTRUCTIVE.search(tool)) or (own is not None and tool in own["destructive"])


def check(tool_name: str, tool_input) -> dict:
    """The answer Claude Code expects: {"behavior": "allow", "updatedInput": ...} or
    {"behavior": "deny", "message": ...}."""
    allow = {"behavior": "allow", "updatedInput": tool_input if isinstance(tool_input, dict) else {}}
    if tool_name == "Bash":  # say how it would be allowed, so the COO can do it the right way
        return {"behavior": "deny", "message": (
            "Not allowed in that form. Run one script per command, on its own: .venv/bin/python scripts/<name>.py "
            "with plain arguments (put text in quotes; no ;, &&, |, heredocs or $(...)), or read-only git commands. "
            "Inline Python and other commands aren't allowed.")}
    if not tool_name.startswith("mcp__") or tool_name.startswith(f"mcp__{SERVER}__"):
        return {"behavior": "deny", "message": "That isn't allowed here."}
    server, tool = split(tool_name)
    if reads_only(server, tool):
        return allow
    if env("STEERABLE_DRY_RUN") == "1":
        return {"behavior": "deny", "message": f"Dry run: {human(tool)} in {service_name(server)} changes something, so it isn't run while testing."}
    fp = _fingerprint(tool_name, tool_input)
    with _store() as data:
        if tool_name in data["always"]:
            return allow
        now = time.time()
        data["grants"] = [g for g in data["grants"] if g["until"] > now]
        grant = next((g for g in data["grants"] if g["fp"] == fp), None)
        if grant:
            data["grants"].remove(grant)
            return allow
        pid = next((k for k, p in data["pending"].items() if p["fp"] == fp), None)
        if not pid:
            pid = fp[:12]
            data["pending"][pid] = {"tool": tool_name, "input": tool_input, "fp": fp, "at": now_iso()}
    return {"behavior": "deny", "message": (
        f"Waiting for the owner's OK: {human(tool)} in {service_name(server)} is in their Decisions now. "
        "Tell them in a sentence and don't retry; once they allow it, you'll be asked to do it.")}


# ---------- the owner's side (agent API) ----------

def pending() -> list[dict]:
    with _store() as data:
        return [{"id": k, **v} for k, v in data["pending"].items()]


def resolve(pid: str, choice: str) -> dict | None:
    """The owner's answer: "once", "always" or "decline". Returns the pending call, or None if
    it's no longer waiting. For once and always, the next identical call is allowed."""
    with _store() as data:
        p = data["pending"].pop(pid, None)
        if not p:
            return None
        if choice in ("once", "always"):
            data["grants"].append({"fp": p["fp"], "until": time.time() + GRANT_MINUTES * 60})
        if choice == "always" and p["tool"] not in data["always"] and not destructive(*split(p["tool"])):
            data["always"].append(p["tool"])
    return p


def always_allowed() -> list[str]:
    with _store() as data:
        return list(data["always"])


def stop_always(tool_name: str) -> None:
    with _store() as data:
        data["always"] = [t for t in data["always"] if t != tool_name]


# ---------- the MCP server ----------

ASK_TOOL = {
    "name": "ask",
    "description": "Decides whether a tool call may run (for Claude Code's --permission-prompt-tool).",
    "inputSchema": {"type": "object", "properties": {"tool_name": {"type": "string"}, "input": {"type": "object"},
                                                     "tool_use_id": {"type": "string"}}, "required": ["tool_name"]},
}


def answer(m: dict) -> dict | None:
    method = m.get("method")
    if method == "initialize":
        result = {"protocolVersion": (m.get("params") or {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "steerable-approvals", "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [ASK_TOOL]}
    elif method == "tools/call" and (m.get("params") or {}).get("name") == "ask":
        args = m["params"].get("arguments") or {}
        try:
            decision = check(str(args.get("tool_name", "")), args.get("input") or {})
        except Exception as e:  # never leave Claude Code hanging
            decision = {"behavior": "deny", "message": f"Couldn't check that: {e}"}
        result = {"content": [{"type": "text", "text": json.dumps(decision)}]}
    else:
        return {"jsonrpc": "2.0", "id": m.get("id"), "error": {"code": -32601, "message": f"Unknown: {method}"}}
    return {"jsonrpc": "2.0", "id": m.get("id"), "result": result}


def serve() -> None:
    for line in sys.stdin:
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(m, dict) or "id" not in m:
            continue  # notifications
        sys.stdout.write(json.dumps(answer(m)) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "check":
        # OpenCode's way in (opencode_approvals.js): the call's input on stdin, the answer printed.
        try:
            print(json.dumps(check(sys.argv[2], json.loads(sys.stdin.read() or "{}"))))
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"behavior": "deny", "message": f"Couldn't check that: {e}"}))
    else:
        serve()
