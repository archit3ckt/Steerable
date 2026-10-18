"""agent.py: the one place the engine runs the AI, so the coding agent (Claude Code or OpenCode) and
the model behind each tier can change by setting.

A fake `claude` and a fake `opencode` stand in for the agents, and a fake Messages API for the model.
With a real OpenCode (OPENCODE_BIN, or `opencode` on PATH) the last test runs it against that fake
Messages API: permissions, a write outside the folder, instructions, a JSON answer, a resumed session.

    python3 -m unittest tests.test_agent -v
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"
sys.path.insert(0, str(TEMPLATE / "scripts"))

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ["SEEN"]).write_text(json.dumps({"args": sys.argv[1:], "stdin": "" if sys.stdin.isatty() else sys.stdin.read()}))
print(json.dumps({"type": "result", "result": '{"status": "built"}', "session_id": "6f1c-uuid", "total_cost_usd": 0.12}))
"""

# Prints what OpenCode 1.19 prints with --format json (seen against a real one).
FAKE_OPENCODE = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ["SEEN"]).write_text(json.dumps({"args": sys.argv[1:], "config": json.loads(os.environ["OPENCODE_CONFIG_CONTENT"]), "cwd": os.getcwd()}))
s = "ses_abc"
def out(kind, part): print(json.dumps({"type": kind, "sessionID": s, "part": part}), flush=True)
out("step_start", {"type": "step-start"})
out("tool_use", {"type": "tool", "tool": "write", "callID": "toolu_1", "state": {"status": "completed", "input": {"filePath": "/w/a.py", "content": "x"}, "output": ""}})
out("tool_use", {"type": "tool", "tool": "bash", "callID": "toolu_2", "state": {"status": "error", "input": {"command": "rm -rf x"}, "error": "The user rejected permission"}})
out("step_finish", {"type": "step-finish", "cost": float(os.environ.get("STEP_COST", "0.01")), "tokens": {}})
out("text", {"type": "text", "text": 'Done.\n```json\n{"status": "built"}\n```'})
out("step_finish", {"type": "step-finish", "cost": float(os.environ.get("STEP_COST", "0.01")), "tokens": {}})
"""


class FakeMessages(http.server.BaseHTTPRequestHandler):
    """A Messages API: answers with tool calls when the prompt names one (TOOL:<name>:<json>), else
    text, JSON when the conversation asks for it (JSONPLEASE)."""
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeMessages.seen.append({"path": self.path, "body": body, "key": self.headers.get("x-api-key")})
        raw = json.dumps(body["messages"])
        for _ in range(3):
            raw = raw.replace("\\\\", "\\").replace('\\"', '"')
        last = body["messages"][-1]["content"]
        answered = isinstance(last, list) and any(b.get("type") == "tool_result" for b in last)
        answered = answered or "title generator" in json.dumps(body.get("system", ""))  # OpenCode names the session
        import re
        tool = None if answered else re.search(r"TOOL:(\w+):(\{[^{}]*\})", raw)
        text = '{"steps": 3}' if "output_config" in body else ('Built it.\n```json\n{"status": "built"}\n```' if "JSONPLEASE" in raw else "All done.")
        if not body.get("stream"):
            data = json.dumps({"id": "m", "type": "message", "role": "assistant", "model": body["model"],
                               "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                               "usage": {"input_tokens": 1000, "output_tokens": 100}}).encode()
            self.send_response(200); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
            return
        self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()

        def sse(kind, d):
            self.wfile.write(f"event: {kind}\ndata: {json.dumps({'type': kind, **d})}\n\n".encode())
        sse("message_start", {"message": {"id": "m", "type": "message", "role": "assistant", "model": body["model"], "content": [],
                                          "stop_reason": None, "usage": {"input_tokens": 100, "output_tokens": 1}}})
        if tool:
            sse("content_block_start", {"index": 0, "content_block": {"type": "tool_use", "id": f"toolu_{len(FakeMessages.seen)}", "name": tool.group(1), "input": {}}})
            sse("content_block_delta", {"index": 0, "delta": {"type": "input_json_delta", "partial_json": tool.group(2)}})
        else:
            sse("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}})
            sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": text}})
        sse("content_block_stop", {"index": 0})
        sse("message_delta", {"delta": {"stop_reason": "tool_use" if tool else "end_turn"}, "usage": {"output_tokens": 20}})
        sse("message_stop", {})

    def log_message(self, *a):
        pass


class AgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeMessages)
        threading.Thread(target=cls.api.serve_forever, daemon=True).start()
        cls.api_url = f"http://127.0.0.1:{cls.api.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.api.shutdown()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root, ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / ".env").write_text("COMPANY_NAME=Co\n")
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        for name, text in (("claude", FAKE_CLAUDE), ("opencode", FAKE_OPENCODE)):
            (bin_ / name).write_text(text)
            (bin_ / name).chmod(0o755)
        self.seen = self.tmp / "seen.json"
        drop = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "STEERABLE_GATEWAY_URL", "STEERABLE_JOBS_URL", "STEERABLE_AGENT",
                "STEERABLE_MODEL_SMART", "STEERABLE_MODEL_FAST", "OPENCODE_BIN")
        self.env = {k: v for k, v in os.environ.items() if k not in drop}
        self.env.update(PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}", HOME=str(self.tmp), SEEN=str(self.seen))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def py(self, code: str, **env) -> dict:
        proc = subprocess.run([sys.executable, "-c", "import json, sys\nsys.path.insert(0, 'scripts')\nimport agent\n" + code],
                              cwd=self.root, env={**self.env, **env}, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    RUN = ("r = agent.run('Build it', budget_usd='2.00', schema={'type': 'object'}, system='Be brief', add_dirs=['/w'],\n"
           "              allow=['Read(./**)', 'Edit(//w/**)', 'Bash(git -C /w *)'], deny=['Read(./.env)'], resume=RESUME, burst=False)\n"
           "print(json.dumps({'ok': r.ok, 'structured': r.structured, 'cost': r.cost, 'session': r.session_id, 'model': r.model,\n"
           "                  'error': r.is_error}))")

    def test_claude_code_by_default_with_the_tier_model(self):
        out = self.py("RESUME = 'ses_from_opencode'\n" + self.RUN)
        self.assertEqual(out, {"ok": True, "structured": {"status": "built"}, "cost": 0.12, "session": "6f1c-uuid",
                               "model": "sonnet", "error": False})
        args = json.loads(self.seen.read_text())["args"]
        self.assertEqual(args[:2], ["-p", "Build it"])
        self.assertEqual(args[args.index("--model") + 1], "sonnet")
        self.assertEqual(args[args.index("--max-budget-usd") + 1], "2.00")
        self.assertEqual(args[args.index("--append-system-prompt") + 1], "Be brief")
        self.assertEqual(args[args.index("--allowedTools") + 1:args.index("--disallowedTools")], ["Read(./**)", "Edit(//w/**)", "Bash(git -C /w *)"])
        self.assertNotIn("--resume", args)  # an OpenCode session can't be continued by Claude Code
        # Any model, by setting: an id, or a name the gateway routes to another provider.
        self.py("RESUME = 'c0ffee'\n" + self.RUN, STEERABLE_MODEL_SMART="glm-4.6")
        args = json.loads(self.seen.read_text())["args"]
        self.assertEqual((args[args.index("--model") + 1], args[-1]), ("glm-4.6", "c0ffee"))

    def test_a_prompt_on_stdin(self):
        self.py("agent.run('A long digest', budget_usd='1', burst=False, prompt_on_stdin=True)\nprint('{}')")
        seen = json.loads(self.seen.read_text())
        self.assertEqual((seen["args"][0], seen["args"][1], seen["stdin"]), ("-p", "--output-format", "A long digest"))

    def test_opencode_prints_what_claude_code_would(self):
        live = self.root / ".cache/live.jsonl"
        out = self.py(f"RESUME = 'ses_prev'\n" + self.RUN.replace("burst=False", f"burst=True, live={str(live)!r}"),
                      STEERABLE_AGENT="opencode", ANTHROPIC_API_KEY="tok", ANTHROPIC_BASE_URL="http://gw.test",
                      STEERABLE_MODEL_FAST="z-ai/glm-4.6-air")
        self.assertEqual(out, {"ok": True, "structured": {"status": "built"}, "cost": 0.02, "session": "ses_abc",
                               "model": "sonnet", "error": False})
        seen = json.loads(self.seen.read_text())
        args, config = seen["args"], seen["config"]
        self.assertEqual(args[:7], ["run", "--format", "json", "-m", "anthropic/claude-sonnet-5-5", "--dir", str(self.root)])
        self.assertEqual(Path(seen["cwd"]).resolve(), self.root.resolve())
        self.assertEqual(args[args.index("--session") + 1], "ses_prev")
        self.assertIn("follows this JSON schema", args[-1])  # OpenCode has no --json-schema: asked in words, read back
        self.assertEqual(config["provider"]["anthropic"]["options"]["baseURL"], "http://gw.test/v1")  # through the gateway
        self.assertEqual(config["small_model"], "anthropic/z-ai/glm-4.6-air")  # the gateway routes it by name
        perm = config["permission"]
        self.assertEqual(perm["*"], "deny")
        self.assertEqual(perm["read"][".env"], "deny")
        self.assertEqual(perm["edit"]["/w/**"], "allow")
        self.assertEqual(perm["bash"]["git -C /w *"], "allow")
        self.assertEqual(perm["external_directory"]["/w/*"], "allow")
        self.assertTrue(Path(config["instructions"][0]).name.endswith(".system.md"))
        self.assertFalse(list((self.root / ".cache/agent").glob("*")))  # the spec and instructions are cleaned up
        # The live file reads like Claude Code's: tool calls under Claude Code's names, then the result.
        events = [json.loads(line) for line in live.read_text().splitlines()]
        tools = [b for e in events if e["type"] == "assistant" for b in e["message"]["content"] if b["type"] == "tool_use"]
        self.assertEqual([(t["name"], t["input"].get("file_path") or t["input"].get("command")) for t in tools],
                         [("Write", "/w/a.py"), ("Bash", "rm -rf x")])
        refused = [b for e in events if e["type"] == "user" for b in e["message"]["content"]]
        self.assertEqual([r["is_error"] for r in refused], [False, True])
        self.assertEqual(events[-1]["type"], "result")

    def test_opencode_is_stopped_at_its_budget(self):
        out = self.py("r = agent.run('Go', budget_usd='0.50', burst=False)\nprint(json.dumps({'error': r.is_error, 'text': r.text, 'cost': r.cost}))",
                      STEERABLE_AGENT="opencode", ANTHROPIC_API_KEY="tok", STEP_COST="0.80")
        self.assertEqual(out, {"error": True, "text": "Stopped: this run reached its budget ($0.50).", "cost": 0.8})

    def test_permissions_in_opencode_terms(self):
        import agent

        wt = "/home/x/.steerable-worktrees/builds/co/b1"
        perm = agent.permissions(
            ["Read(./**)", f"Read(/{wt}/**)", "Glob", f"Edit(/{wt}/**)", f"Write(/{wt}/**)", "Edit(./drafts/**)",
             f"Bash(cd {wt} && STEERABLE_DRY_RUN=1 .venv/bin/python *)", "Bash(.venv/bin/python scripts/ops_db.py*)",
             "mcp__steerable", "mcp__notion__search", "WebFetch"],
            ["Read(./.env)", "Read(./.cache/**)"], cwd=str(self.root))
        self.assertEqual(perm["*"], "deny")  # anything not allowed isn't even offered
        self.assertEqual(perm["read"], {"*": "allow", wt + "/**": "allow", wt.lstrip("/") + "/**": "allow",
                                        os.path.relpath(wt, self.root) + "/**": "allow", ".env": "deny", ".cache/**": "deny"})
        self.assertEqual(perm["edit"]["drafts/**"], "allow")
        self.assertEqual(perm["edit"][wt + "/**"], "allow")
        # A leading `cd dir &&` isn't checked as a command: the folder is allowed instead.
        self.assertEqual(perm["bash"], {"STEERABLE_DRY_RUN=1 .venv/bin/python *": "allow", ".venv/bin/python scripts/ops_db.py*": "allow"})
        self.assertEqual(perm["external_directory"], {"*": "deny", wt + "/*": "allow"})
        self.assertEqual((perm["steerable_*"], perm["notion_search"], perm["webfetch"]), ("allow", "allow", "allow"))
        # Denied outright wins over allowed patterns, as in Claude Code.
        self.assertEqual(agent.permissions(["Bash(git *)"], ["Bash"], cwd=str(self.root))["bash"], "deny")

    def test_one_question_through_the_messages_api_with_any_model(self):
        FakeMessages.seen.clear()
        out = self.py("print(json.dumps(agent.complete('How many steps?', source='flow', schema={'type': 'object'})))",
                      ANTHROPIC_API_KEY="sk-steerable-co", ANTHROPIC_BASE_URL=self.api_url, STEERABLE_MODEL_FAST="kimi-k2")
        self.assertEqual(out, {"steps": 3})
        sent = FakeMessages.seen[-1]
        self.assertEqual((sent["path"], sent["key"], sent["body"]["model"]), ("/v1/messages", "sk-steerable-co", "kimi-k2"))
        spend = json.loads((self.root / "logs/spend.jsonl").read_text().splitlines()[-1])
        self.assertEqual((spend["source"], spend["model"], spend["input_tokens"]), ("flow", "kimi-k2", 1000))
        # Without a key (a Claude account): through the coding agent, from a neutral folder.
        out = self.py("print(json.dumps(agent.complete('Pick one', source='decide', schema={'type': 'object'})))")
        self.assertEqual(out, {"status": "built"})
        args = json.loads(self.seen.read_text())["args"]
        self.assertEqual(args[args.index("--model") + 1], "haiku")

    @unittest.skipUnless(os.environ.get("OPENCODE_BIN") or shutil.which("opencode"), "OpenCode isn't installed")
    def test_real_opencode(self):
        """The same run through a real OpenCode against a fake Messages API."""
        wt = self.tmp / "wt"
        wt.mkdir()
        for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(["git", *args], cwd=self.root, check=True)
        env = dict(STEERABLE_AGENT="opencode", ANTHROPIC_API_KEY="tok", ANTHROPIC_BASE_URL=self.api_url,
                   OPENCODE_BIN=os.environ.get("OPENCODE_BIN") or shutil.which("opencode"))
        env["PATH"] = os.environ["PATH"]  # not the fake opencode
        FakeMessages.seen.clear()
        out = self.py(
            f"r = agent.run('JSONPLEASE TOOL:write:{{\"filePath\":\"{wt}/flow.py\",\"content\":\"print(1)\"}}', budget_usd='1',\n"
            f"    schema={{'type': 'object'}}, system='SYSTEM-MARK', allow=['Edit(/{wt}/**)'], deny=['Read(./.env)'], burst=False, timeout=120)\n"
            "r2 = agent.run('TOOL:write:{\"filePath\":\"notes.md\",\"content\":\"x\"}', budget_usd='1', resume=r.session_id, burst=False, timeout=120)\n"
            "print(json.dumps({'s': r.structured, 'session': r.session_id, 'same': r2.session_id == r.session_id, }))", **env)
        self.assertEqual(out["s"], {"status": "built"})
        self.assertTrue(out["session"].startswith("ses_") and out["same"])
        self.assertEqual((wt / "flow.py").read_text(), "print(1)")  # allowed: written outside the folder
        self.assertFalse((self.root / "notes.md").exists())  # not allowed: refused
        self.assertIn("SYSTEM-MARK", json.dumps([s["body"].get("system") for s in FakeMessages.seen]))


if __name__ == "__main__":
    unittest.main()
