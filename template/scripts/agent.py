"""The AI the engine runs, in one place, so the coding agent and the model can change without
touching the scripts that use it.

Two kinds of call:

    agent.run(prompt, budget_usd="0.50", allow=[...], live=path)   # an agent with tools: the chat,
                                                                    # building and fixing routines,
                                                                    # studying a book, learning
    agent.complete(prompt, schema=..., source="decide")             # one question, one answer

Models are asked for by tier, never by name:

    STEERABLE_MODEL_SMART   the chat, builds, fixes, reviews       (default: sonnet)
    STEERABLE_MODEL_FAST    small decisions, flow charts, titles   (default: haiku)

A tier's value is any name: an alias Claude Code knows (sonnet, haiku, opus), a full model id, or a
name the gateway routes to another provider (Steerable Cloud's AI_MODELS: GLM, Kimi, GPT, Gemini...).

The coding agent, STEERABLE_AGENT:

    claude     Claude Code (the default). Works with a Claude account or an API key / the gateway.
    opencode   OpenCode (needs an API key or the gateway; no Claude account). This file runs it
               itself and prints Claude Code's stream-json, so everything downstream (results,
               the live activity in the app, cost) reads the same either way. Changes in the
               owner's services still wait for their OK (opencode_approvals.js).

Permissions are written the Claude Code way ("Read(./**)", "Edit(//abs/path/**)", "Bash(git -C x *)",
"mcp__server"); each agent translates them. What isn't allowed is refused: neither agent has anyone
to ask in a headless run.

    python scripts/agent.py opencode <spec.json>     # what an OpenCode run executes (in a burst Job too)
"""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from common import CACHE, ROOT, env

AGENTS = ("claude", "opencode")
TIERS = {"smart": ("STEERABLE_MODEL_SMART", "sonnet"), "fast": ("STEERABLE_MODEL_FAST", "haiku")}
FULL = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-4-5", "opus": "claude-opus-5-5"}
SPECS = CACHE / "agent"


def which() -> str:
    """The coding agent this engine runs (STEERABLE_AGENT)."""
    name = (env("STEERABLE_AGENT") or "claude").strip().lower()
    if name not in AGENTS:
        raise ValueError(f"STEERABLE_AGENT must be one of {AGENTS}, not {name!r}")
    return name


def model(tier: str = "smart") -> str:
    """The model for a tier, as configured (an alias, a full id, or a name the gateway routes)."""
    var, default = TIERS[tier]
    return env(var) or default


def api_model(tier: str = "smart") -> str:
    """The model for a tier as the Messages API wants it: aliases become full ids."""
    name = model(tier).removeprefix("anthropic/")
    return FULL.get(name, name)


@dataclass
class Result:
    ok: bool = False                # an answer came back at all
    text: str = ""
    structured: dict | None = None  # the JSON asked for with `schema`
    cost: float = 0.0
    session_id: str | None = None
    is_error: bool = False
    model: str = ""
    stdout: str = ""
    stderr: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def error(self) -> str:
        return (self.stderr or self.stdout)[-1500:]


def parse(stdout: str, schema: bool = False) -> Result:
    """The result of a run, printed as one JSON object or as stream-json events (the last one with
    a result wins)."""
    found: dict = {}
    for line in (stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and ("result" in event or "structured_output" in event or event.get("type") == "result"):
            found = event
    if not found:
        return Result(stdout=stdout or "")
    structured = found.get("structured_output")
    if schema and not isinstance(structured, dict):
        structured = _json_in(found.get("result") or "")
    return Result(ok=True, text=found.get("result") or "", structured=structured,
                  cost=float(found.get("total_cost_usd") or 0), session_id=found.get("session_id"),
                  is_error=bool(found.get("is_error")), stdout=stdout, raw=found)


def _json_in(text: str) -> dict | None:
    """A JSON object in an answer: the whole of it, or the last {...} in it (a fenced block too)."""
    text = text.strip()
    candidates = [text] + re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if "{" in text:
        candidates.append(text[text.index("{"):text.rindex("}") + 1] if "}" in text else "")
    for c in candidates:
        try:
            value = json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


# ---------- an agent with tools ----------

def run(prompt: str, *, budget_usd: str | float, tier: str = "smart", allow=(), deny=(),
        schema: dict | None = None, system: str | None = None, resume: str | None = None,
        permission_mode: str | None = None, add_dirs=(), mcp: str | None = None,
        max_turns: int | None = None, live: Path | str | None = None, timeout: float = 900,
        cwd: Path | str = ROOT, extra_env: dict | None = None, burst: bool = True,
        prompt_on_stdin: bool = False) -> Result:
    """One agent run to completion.

    allow / deny   permission rules, Claude Code's syntax
    schema         a JSON schema the final answer must follow (Result.structured)
    system         added to the agent's system prompt
    resume         a session id from an earlier Result, to continue that conversation
    mcp            "live" or "dry": the company's connected services as tools (dry: nothing changes)
    live           a file in the company folder: the run's events land there as they happen
    burst          run in a burst Job when the platform has them (else here, like subprocess.run)
    """
    spec = dict(prompt=prompt, model=model(tier), budget_usd=str(budget_usd), allow=list(allow), deny=list(deny),
                schema=schema, system=system, resume=resume, permission_mode=permission_mode,
                add_dirs=[str(d) for d in add_dirs], mcp=mcp, max_turns=max_turns, live=bool(live), cwd=str(cwd),
                tier=tier)
    agent = which()
    if agent == "opencode":
        if resume and not resume.startswith("ses_"):
            spec["resume"] = None  # a Claude Code session: OpenCode can't continue it
        SPECS.mkdir(parents=True, exist_ok=True)
        path = SPECS / f"{uuid.uuid4().hex[:16]}.json"
        path.write_text(json.dumps(spec))
        cmd = [sys.executable, str(Path(__file__).resolve()), "opencode", str(path)]
        prompt_on_stdin = False
    else:
        if resume and resume.startswith("ses_"):
            spec["resume"] = None  # an OpenCode session
        cmd = _claude_command(spec, prompt_on_stdin)
    environment = {**os.environ, **extra_env} if extra_env else None
    try:
        if burst:
            import burst as jobs

            proc = jobs.run(cmd, kind="claude", timeout=timeout, cwd=cwd, env=environment, stream=live)
        elif prompt_on_stdin:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                                  env=environment)
        else:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout,
                                  cwd=cwd, env=environment)
    finally:
        if agent == "opencode":
            path.unlink(missing_ok=True)
    result = parse(proc.stdout, schema=bool(schema))
    result.stderr, result.model = proc.stderr or "", spec["model"]
    return result


def _claude_command(spec: dict, prompt_on_stdin: bool = False) -> list[str]:
    cmd = ["claude", "-p", *([] if prompt_on_stdin else [spec["prompt"]])]
    cmd += ["--output-format", "stream-json", "--verbose"] if spec["live"] else ["--output-format", "json"]
    cmd += ["--model", spec["model"].removeprefix("anthropic/"), "--max-budget-usd", spec["budget_usd"]]
    if spec["schema"]:
        cmd += ["--json-schema", json.dumps(spec["schema"])]
    if spec["system"]:
        cmd += ["--append-system-prompt", spec["system"]]
    if spec["permission_mode"]:
        cmd += ["--permission-mode", spec["permission_mode"]]
    mcp_args, mcp_rules = [], []
    if spec["mcp"]:
        import integrations

        mcp_args, mcp_rules = integrations.claude_mcp_args(dry_run=spec["mcp"] == "dry")
    cmd += mcp_args
    for d in spec["add_dirs"]:
        cmd += ["--add-dir", d]
    if spec["max_turns"]:
        cmd += ["--max-turns", str(spec["max_turns"])]
    if spec["allow"] or mcp_rules:
        cmd += ["--allowedTools", *mcp_rules, *spec["allow"]]
    if spec["deny"]:
        cmd += ["--disallowedTools", *spec["deny"]]
    if spec["resume"]:
        cmd += ["--resume", spec["resume"]]
    return cmd


# ---------- one question, one answer ----------

def complete(prompt: str, *, source: str, tier: str = "fast", schema: dict | None = None,
             images=(), max_tokens: int = 1024, budget_usd: str = "0.10"):
    """One question to the model, with pictures if given. Returns the JSON asked for (with
    `schema`), else the text. Through the Messages API when there's a key (the gateway in
    Steerable Cloud, which routes the model to whichever provider), else through the coding agent
    (an engine signed in with a Claude account), from a neutral folder so it doesn't load the
    company's CLAUDE.md for one small question. Raises RuntimeError when no answer comes."""
    from budget import record, record_usage

    if env("ANTHROPIC_API_KEY"):
        import base64

        name = api_model(tier)
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(Path(p).read_bytes()).decode()}}
                   for p in images]
        content.append({"type": "text", "text": prompt})
        body = {"model": name, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
        if schema:
            body["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        response = _messages(body)
        usage = response.get("usage") or {}
        record_usage(source, name, SimpleNamespace(
            input_tokens=usage.get("input_tokens") or 0, output_tokens=usage.get("output_tokens") or 0,
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens") or 0,
            cache_read_input_tokens=usage.get("cache_read_input_tokens") or 0))
        text = "".join(b.get("text", "") for b in response.get("content") or [] if b.get("type") == "text")
        if not schema:
            return text
        data = _json_in(text)
        if data is None:
            raise RuntimeError(f"No answer: {text[-200:]}")
        return data
    where = ""
    if images:
        where = "\n\nLook at these pictures first (Read them): " + ", ".join(str(p) for p in images)
    result = run(prompt + where, tier=tier, budget_usd=budget_usd, schema=schema,
                 allow=[f"Read({p})" for p in images], cwd=tempfile.gettempdir(), burst=False, timeout=300)
    if not result.ok or (schema and result.structured is None):
        raise RuntimeError(f"No answer: {result.error[-200:]}")
    record(source, result.cost, model(tier), note="claude account")
    return result.structured if schema else result.text


def _messages(body: dict, timeout: float = 180) -> dict:
    """POST a Messages API request: to ANTHROPIC_BASE_URL (the gateway in Steerable Cloud, which may
    send it to any provider) or Anthropic. Plain HTTP, so it needs no SDK."""
    import urllib.error
    import urllib.request

    base = (env("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
    req = urllib.request.Request(f"{base}/v1/messages", data=json.dumps(body).encode(), method="POST", headers={
        "content-type": "application/json", "anthropic-version": "2023-06-01", "x-api-key": env("ANTHROPIC_API_KEY")})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"The AI answered {e.code}: {detail}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"Couldn't reach the AI: {e}") from None


# ---------- OpenCode ----------
# Verified with OpenCode 1.19 against a fake Messages API: in a headless run a rule that would ask
# is refused; a tool every rule refuses isn't offered at all; the last matching rule wins; chained
# commands are checked part by part (a leading `cd dir &&` is not a part); paths inside the folder
# are matched relative to it, others through external_directory; CLAUDE.md, .claude/skills and
# extra instruction files are read; any model name works once listed under its provider; its folder
# comes from PWD (so it's set, with --dir).

TOOLS = {"Read": "read", "Edit": "edit", "Write": "edit", "MultiEdit": "edit", "NotebookEdit": "edit",
         "Glob": "glob", "Grep": "grep", "LS": "list", "WebFetch": "webfetch", "WebSearch": "websearch",
         "Bash": "bash", "TodoWrite": "todowrite"}
PATH_TOOLS = {"read", "edit", "glob", "grep", "list"}
# Allowed unless a rule says otherwise, as in Claude Code: looking around the folder.
OPEN_BY_DEFAULT = ("read", "glob", "grep", "list", "todowrite", "skill")


def _rule(rule: str) -> tuple[str, str | None]:
    m = re.fullmatch(r"([\w-]+)(?:\((.*)\))?", rule.strip(), re.S)
    return (m.group(1), m.group(2)) if m else (rule, None)


def _place(pattern: str, cwd: Path) -> tuple[str, str | None]:
    """A Claude Code path pattern as OpenCode's, and the outside folder it reaches (if any).
    Ours are "./x" (the folder) or "//abs" and "/abs" (absolute)."""
    if not pattern.startswith("/"):
        rel = pattern.removeprefix("./")
        return ("*" if rel in ("", "*", "**") else rel), None
    path = "/" + pattern.lstrip("/")
    root = str(cwd)
    if path == root or path.startswith(root + "/"):
        rel = path[len(root):].lstrip("/")
        return ("*" if rel in ("", "*", "**") else rel), None
    base = path.split("*")[0]
    folder = base.rstrip("/") if base.endswith("/") else str(Path(base).parent)
    return path, folder or "/"


def permissions(allow, deny, cwd: Path | str, add_dirs=()) -> dict:
    """Claude Code permission rules as an OpenCode `permission` block."""
    cwd = Path(cwd).resolve()
    top = next((d for d in (cwd, *cwd.parents) if (d / ".git").exists()), Path("/"))  # OpenCode's project root
    perm: dict = {"*": "deny", **{t: "allow" for t in OPEN_BY_DEFAULT}}
    outside: dict = {"*": "deny", **{f"{Path(d).resolve()}/*": "allow" for d in add_dirs}}

    def put(tool: str, pattern: str, action: str) -> None:
        current = perm.get(tool)
        if not isinstance(current, dict):
            current = perm[tool] = {"*": current} if isinstance(current, str) else {}
        current.pop(pattern, None)
        current[pattern] = action  # last match wins: re-adding moves it after the others

    for action, rules in (("allow", allow), ("deny", deny)):
        for rule in rules:
            name, arg = _rule(rule)
            if name.startswith("mcp__"):
                server, _, tool = name[5:].partition("__")
                perm[f"{server}_{tool}" if tool else f"{server}_*"] = action
                continue
            tool = TOOLS.get(name)
            if not tool:
                continue
            if arg is None or arg in ("*", "**"):
                perm[tool] = action
                continue
            if tool == "bash":
                m = re.match(r"cd (\S+) && (.*)", arg, re.S)
                if m:
                    folder, arg = m.groups()
                    if action == "allow" and not Path(folder).resolve().is_relative_to(cwd):
                        outside[f"{Path(folder).resolve()}/*"] = "allow"
                for part in re.split(r"\s*(?:&&|\|\||;)\s*", arg):
                    put("bash", part, action)
                continue
            if tool in PATH_TOOLS:
                pattern, folder = _place(arg, cwd)
                if folder and action == "allow":
                    outside[f"{folder}/*"] = "allow"
                if folder:
                    # OpenCode matches an outside path relative to the project root: written every way
                    # it can come out (absolute, from "/", from the folder).
                    for form in {pattern, pattern.lstrip("/"), os.path.relpath(pattern, cwd), os.path.relpath(pattern, top)}:
                        put(tool, form, action)
                else:
                    put(tool, pattern, action)
                continue
            put(tool, arg, action)  # webfetch: a domain rule
    perm["external_directory"] = outside
    return perm


def _tool_prefix(server: str) -> str:
    """How OpenCode starts the names of a server's tools (<prefix>_<tool>)."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", server)


def _mcp(kind: str | None) -> tuple[dict, list[str], dict]:
    """The company's MCP servers for OpenCode: (servers in OpenCode's form, Claude Code allow
    rules, servers whose calls go through approvals.py as {tool prefix: name there}).

    Steerable Cloud's servers are allowed whole: its gateway holds changes for the owner. In the
    chat ("live"), the owner's own servers go through approvals.py before each call, from the
    plugin opencode_approvals.js, as Claude Code's do through --permission-prompt-tool: reads run,
    changes wait in the owner's Decisions. In dry runs only their read tools are allowed."""
    if not kind:
        return {}, [], {}
    import integrations

    found = integrations.mcp_config(dry_run=kind == "dry", approvals=False)
    if not found:
        return {}, [], {}
    rules = integrations.claude_mcp_args(dry_run=kind == "dry")[1]
    servers, gated = {}, {}
    for name, s in json.loads(Path(found[0]).read_text()).get("mcpServers", {}).items():
        if s.get("type") in ("http", "sse") or s.get("url"):
            servers[name] = {"type": "remote", "url": s["url"], "headers": s.get("headers") or {}, "enabled": True}
        elif s.get("command"):
            servers[name] = {"type": "local", "command": [s["command"], *s.get("args", [])],
                             "environment": s.get("env") or {}, "enabled": True}
        if kind == "live" and f"mcp__{name}" not in rules:
            import tools

            gated[_tool_prefix(name)] = tools.slug(name)
    return servers, rules, gated


def _provider_model(name: str) -> tuple[str, str]:
    """OpenCode's provider and model for a tier's name. Through the gateway every name goes to it
    unchanged (it routes names, slashes and all); otherwise "provider/model" is OpenCode's own."""
    if "/" in name and not name.startswith("anthropic/") and not os.environ.get("ANTHROPIC_BASE_URL"):
        provider, _, rest = name.partition("/")
        return provider, rest
    name = name.removeprefix("anthropic/")
    return "anthropic", FULL.get(name, name)


def opencode_config(spec: dict) -> dict:
    provider, name = _provider_model(spec["model"])
    _, fast = _provider_model(model("fast"))
    providers: dict = {provider: {"models": {name: {"name": name}}}}
    if provider == "anthropic":
        providers["anthropic"]["models"][fast] = {"name": fast}
        base = os.environ.get("ANTHROPIC_BASE_URL")
        if base:  # the gateway: the company's token, the provider the gateway picks
            providers["anthropic"]["options"] = {"baseURL": base.rstrip("/") + "/v1"}
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{provider}/{name}",
        "small_model": f"anthropic/{fast}" if provider == "anthropic" else f"{provider}/{name}",
        "provider": providers,
        "autoupdate": False,
        "share": "disabled",
    }
    servers, rules, gated = _mcp(spec["mcp"])
    config["permission"] = permissions(spec["allow"] + rules, spec["deny"], spec["cwd"], spec["add_dirs"])
    config["mcp"] = servers
    if gated:  # offered, and checked before each call by the plugin
        for prefix in gated:
            config["permission"][f"{prefix}_*"] = "allow"
        config["plugin"] = [(Path(__file__).resolve().parent / "opencode_approvals.js").as_uri()]
        config["_approvals"] = gated  # taken out again by run_opencode, into the plugin's environment
    return config


def _schema_note(schema: dict) -> str:
    return ("\n\nWhen you're done, end with only a JSON object (no other text after it) that follows this "
            f"JSON schema:\n{json.dumps(schema)}")


def _claude_tool(part: dict) -> dict:
    """An OpenCode tool part as a Claude Code tool_use block (names and inputs as Claude Code's)."""
    tool = part.get("tool") or ""
    name = next((k for k, v in TOOLS.items() if v == tool and k != "MultiEdit" and k != "NotebookEdit"), tool)
    if tool == "write":
        name = "Write"
    inp = dict((part.get("state") or {}).get("input") or {})
    if "filePath" in inp:
        inp["file_path"] = inp.pop("filePath")
    return {"type": "tool_use", "id": part.get("callID") or part.get("id"), "name": name, "input": inp}


def _die_with_parent() -> None:
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    except Exception:  # noqa: BLE001
        pass


def run_opencode(spec_path: str) -> int:
    """Run OpenCode for a spec written by run(), printing Claude Code's stream-json as it goes and
    a result event at the end. Stops it once the run has cost more than its budget."""
    spec = json.loads(Path(spec_path).read_text())
    config = opencode_config(spec)
    system_file = None
    if spec["system"]:
        SPECS.mkdir(parents=True, exist_ok=True)
        system_file = SPECS / f"{Path(spec_path).stem}.system.md"
        system_file.write_text(spec["system"])
        config["instructions"] = [str(system_file)]
    prompt = spec["prompt"] + (_schema_note(spec["schema"]) if spec["schema"] else "")
    # --dir and PWD both: OpenCode takes its folder from PWD, not from where it's started.
    cmd = [env("OPENCODE_BIN") or "opencode", "run", "--format", "json", "-m", config["model"], "--dir", spec["cwd"]]
    if env("OPENCODE_PRINT_LOGS"):
        cmd.append("--print-logs")  # its own log on stderr, in the run's error output
    if spec["resume"]:
        cmd += ["--session", spec["resume"]]
    cmd += [prompt]
    budget = float(spec["budget_usd"] or 0)
    cost, session, texts, stopped, failed = 0.0, None, [], "", ""

    def emit(event: dict) -> None:
        print(json.dumps(event), flush=True)

    approvals = config.pop("_approvals", None)
    extra = {"STEERABLE_APPROVAL_SERVERS": json.dumps(approvals), "STEERABLE_PYTHON": sys.executable,
             "STEERABLE_ROOT": str(ROOT)} if approvals else {}
    proc = subprocess.Popen(cmd, cwd=spec["cwd"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True,
                            env={**os.environ, **extra, "OPENCODE_CONFIG_CONTENT": json.dumps(config), "PWD": spec["cwd"]},
                            preexec_fn=_die_with_parent)
    try:
        for line in proc.stdout:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            session = e.get("sessionID") or session
            part = e.get("part") or {}
            kind = e.get("type")
            if kind == "text" and part.get("text"):
                texts.append(part["text"])
                emit({"type": "assistant", "session_id": session,
                      "message": {"role": "assistant", "content": [{"type": "text", "text": part["text"]}]}})
            elif kind == "tool_use":
                block = _claude_tool(part)
                state = part.get("state") or {}
                emit({"type": "assistant", "session_id": session, "message": {"role": "assistant", "content": [block]}})
                emit({"type": "user", "session_id": session, "message": {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": block["id"], "is_error": state.get("status") == "error",
                    "content": str(state.get("output") or state.get("error") or "")[:2000]}]}})
            elif kind == "step_finish":
                cost += float(part.get("cost") or 0)
                if budget and cost > budget:
                    stopped = f"Stopped: this run reached its budget (${budget:.2f})."
                    proc.terminate()
                    break
            elif kind == "error":
                failed = str(((e.get("error") or {}).get("data") or {}).get("message") or e.get("error"))[:500]
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
        if system_file:
            system_file.unlink(missing_ok=True)
    final = texts[-1] if texts else ""
    is_error = bool(stopped or failed or (proc.returncode not in (0, None) and not stopped) or not (final or session))
    result = {"type": "result", "subtype": "error" if is_error else "success", "is_error": is_error,
              "result": final or stopped or failed, "session_id": session, "total_cost_usd": round(cost, 6)}
    if spec["schema"]:
        data = _json_in(final)
        if data is not None:
            result["structured_output"] = data
    emit(result)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "opencode":
        sys.exit(run_opencode(sys.argv[2]))
    print(__doc__)
