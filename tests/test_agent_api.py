"""End-to-end tests for template/scripts/agent_api.py.

Each run builds a throwaway company from the template with realistic state (tasks, a mission
board, run and spend logs, an incident with a prepared fix on a git branch), starts the API as
a real server, and talks to it over HTTP. A fake `claude` on PATH answers chat messages.

    python3 -m unittest discover -s tests -v
"""
import http.server
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"
TOKEN = "t" * 40
TODAY = date.today().isoformat()
ENGINE_WORDS = ("workflow", "incident", "heartbeat", "exit code")
SHOWN_FIELDS = {"title", "context", "detail", "summary", "label", "outcome", "why", "headline",
                "points", "name", "description", "value", "doneWhen", "error"}

TASKS = f"""# Tasks

## Goals
- 40 cafe accounts

## Open
- [ ] Remind cafes to reorder (goal: 40 cafe accounts; metric: reorders)  @workflow:reorder_reminders  every:weekly  saves:2h
- [ ] Send a weekly Plant of the Week email (goal: $8k monthly revenue)  @workflow:newsletter  every:weekly  needs:approval  saves:1.5h
- [ ] Answer common customer questions  @workflow:answer_questions  every:daily  saves:4h  paused:iabc12345
- [ ] Update stock counts from the shop  @workflow:stock_counts  every:daily  paused:owner
- [ ] Reply to Juniper & Co about Friday  @you  due:2026-10-09
- [ ] Draft the spring price sheet  due:2026-10-12

## Done
- [x] Set up the Telegram app  @you  done:{TODAY}
- [x] Old thing from long ago  done:2020-01-01
"""

FAKE_CLAUDE = """#!/usr/bin/env python3
import json, re, subprocess, sys
from pathlib import Path
prompt = sys.argv[sys.argv.index("-p") + 1]
Path(".cache").mkdir(exist_ok=True)
Path(".cache/last_claude_argv.json").write_text(json.dumps(sys.argv))
if "flow chart" in prompt and "Describe this routine" in prompt:
    steps = [{"kind": "trigger", "label": "Every week"}, {"kind": "read", "label": "Check which cafes reordered"},
             {"kind": "send", "label": "Remind the quiet ones", "service": "Gmail"}]
    print(json.dumps({"result": "", "structured_output": {"steps": steps}, "session_id": "f1", "total_cost_usd": 0.002}))
elif "approved a change to a routine" in prompt:
    # Play the builder changing a running routine: edit it in the worktree and commit.
    wt, name = re.search(r"worktree for the change is at: (\\S+) \\(branch build/(\\w+)\\)", prompt).groups()
    path = Path(wt, "workflows", name + ".py")
    path.write_text(path.read_text() + "# updated: tells the owner about new reorders\\n")
    subprocess.run(["git", "-C", wt, "commit", "-qam", "Update " + name], check=True)
    result = {"status": "built", "summary": "It now tells you about new reorders in the chat.",
              "needs": "", "needs_connection": "", "test_output": "ok"}
    print(json.dumps({"result": json.dumps(result), "session_id": "c1", "total_cost_usd": 0.2}))
elif "just approved a new routine" in prompt:
    # Play the routine builder: write the workflow in the worktree and commit it,
    # or report that it needs the owner (for routines named *_needs_login).
    wt, name = re.search(r"worktree for the build is at: (\\S+) \\(branch build/(\\w+)\\)", prompt).groups()
    if name.endswith("_needs_google"):
        result = {"status": "needs_owner", "summary": "It reads your inbox, so it needs Google.",
                  "needs": "", "needs_connection": "google", "test_output": ""}
    elif name.endswith("_needs_login"):
        result = {"status": "needs_owner", "summary": "I can't reach your invoicing tool yet.",
                  "needs": "a login for your invoicing tool", "needs_connection": "", "test_output": ""}
    else:
        body = "print('Sent the weekly email to 120 customers')\\n"
        if name.endswith("_messy"):  # keeps its own file, as the engine doesn't allow
            body = "from pathlib import Path\\nPath('seen.json').write_text('{}')\\n" + body
        Path(wt, "workflows", name + ".py").write_text(body)
        subprocess.run(["git", "-C", wt, "add", "workflows/"], check=True)
        subprocess.run(["git", "-C", wt, "commit", "-qm", "Build " + name], check=True)
        result = {"status": "built", "summary": "It emails your customers every Monday morning.",
                  "needs": "", "needs_connection": "", "test_output": "Sent the weekly email to 120 customers"}
    print(json.dumps({"result": json.dumps(result), "session_id": "b1", "total_cost_usd": 0.3}))
elif "stream-json" in sys.argv:
    # Like Claude Code: one event per line as it works, then the result.
    def event(e):
        print(json.dumps(e), flush=True)
    event({"type": "system", "subtype": "init", "session_id": "s1"})
    # It says what it's about to do, does it, and its last words are the reply.
    for say, name, args in [("Let me check **your notes** first.", "Read", {"file_path": str(Path("memory/company.md").resolve())}),
                            ("Now the going rates.", "WebSearch", {"query": "cafe wholesale prices"})]:
        event({"type": "assistant", "message": {"content": [{"type": "text", "text": say}]}})
        event({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": args}]}})
        if "slowly" in prompt:
            import time; time.sleep(1.5)
    event({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Got it: {prompt}"}]}})
    event({"type": "result", "result": f"Got it: {prompt}", "session_id": "s1", "total_cost_usd": 0.01})
else:
    print(json.dumps({"result": f"Got it: {prompt}", "session_id": "s1", "total_cost_usd": 0.01}))
"""


def ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def build_company(root: Path) -> None:
    shutil.copytree(TEMPLATE, root)
    (root / ".env").write_text(f"COMPANY_NAME=Bloom & Root\nAGENT_API_TOKEN={TOKEN}\nMONTHLY_BUDGET_USD=40\n")
    (root / "tasks.md").write_text(TASKS)
    (root / "logs").mkdir(exist_ok=True)
    (root / ".cache").mkdir(exist_ok=True)

    runs = [
        {"ts": ago(hours=3), "script": "heartbeat", "status": "ok", "workflow": "reorder_reminders",
         "stdout": "checked 40 cafes\nReminded 6 cafes that haven't reordered", "cost_usd": 0},
        {"ts": ago(hours=2), "script": "heartbeat", "status": "error", "workflow": "answer_questions",
         "stdout": "", "stderr": "Traceback...", "cost_usd": 0},
        {"ts": ago(minutes=5), "script": "heartbeat", "status": "idle", "cost_usd": 0},
    ]
    (root / "logs/runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    spend = [{"ts": ago(days=2), "source": "reorder_reminders", "cost_usd": 0.4},
             {"ts": ago(days=1), "source": "incident", "cost_usd": 0.6}]
    (root / "logs/spend.jsonl").write_text("".join(json.dumps(s) + "\n" for s in spend))

    con = sqlite3.connect(root / "ops.db")
    sys.path.insert(0, str(root / "scripts"))
    from ops_db import SCHEMA  # noqa: E402
    sys.path.pop(0)
    con.executescript(SCHEMA)
    con.execute("""INSERT INTO goals (id, goal, why, metric, target, current, due, created) VALUES
        (1, '40 cafe accounts', 'Wholesale is steady money', 'cafe accounts', '40', '31', ?, ?),
        (2, '$8k monthly revenue', 'Pays for a part-time hire', 'monthly revenue', '$8k', '$6,120', NULL, ?)""",
                (str(date.today() + timedelta(days=30)), (date.today() - timedelta(days=60)).isoformat(),
                 date.today().isoformat()))
    con.execute("""INSERT INTO missions (id, mission, goal_id, status, owner, workflow, needs_ceo_approval,
                   definition_of_done) VALUES
        (1, 'Remind cafes to reorder', 1, 'Recurring', 'Workflow', 'reorder_reminders', 0, 'Every quiet cafe hears from us within 3 weeks'),
        (2, 'Weekly newsletter', 2, 'Todo', 'COO', 'newsletter', 1, 'A weekly email brings repeat orders'),
        (3, 'Answer questions', 2, 'Blocked', 'Workflow', 'answer_questions', 0, NULL),
        (4, 'Handle the supplier price rise', 2, 'Waiting on CEO', 'COO', NULL, 0, NULL),
        (5, 'Old idea', 1, 'Cancelled', 'COO', NULL, 0, NULL)""")
    con.execute("UPDATE missions SET outcome = 'The supplier raised prices 8%. Raise ours 5% or switch suppliers?' WHERE id = 4")
    activity = [
        (1, "Ran OK: checked 40 cafes\nReminded 6 cafes that haven't reordered", "Workflow", 0.0),
        (3, "Incident opened: Workflow 'answer_questions' crashed", "Workflow", 0.0),
        (3, "Diagnosed (ceo): The inbox password changed, so the workflow can't log in.", "COO", 0.6),
        (3, "Needs CEO: The inbox password changed, so the workflow can't log in.", "COO", 0.0),
        (None, "Wrote the spring price sheet draft", "COO", 0.05),
    ]
    con.executemany("INSERT INTO activity (mission_id, what, who, cost, ts) VALUES (?, ?, ?, ?, datetime('now', '-1 hour'))",
                    activity)
    con.commit()
    con.close()

    incidents = {"iabc12345": {
        "id": "iabc12345", "kind": "crash", "key": "workflow:answer_questions",
        "summary": "Workflow 'answer_questions' crashed", "details": "...", "workflow": "answer_questions",
        "task": "Answer common customer questions", "repeats": 2, "status": "awaiting_ceo", "opened": ago(hours=2),
        "cost_usd": 0.6, "board_prev_status": "Recurring",
        "verdict": {"severity": "ceo", "summary": "The inbox password changed, so the workflow can't log in. Two customers are waiting.",
                    "root_cause": "auth", "fix_ready": True, "fix_summary": "Reads the new password from .env",
                    "recommendation": "Apply it, then send the two replies.",
                    "actions": [{"label": "Send the two replies", "command": [".venv/bin/python", "workflows/x.py"]}]},
    }}
    (root / ".cache/incidents.json").write_text(json.dumps(incidents))
    (root / "drafts").mkdir()
    (root / "drafts/iabc12345-reply.txt").write_text("Hi Dana, sorry for the wait...")
    # Routines that exist already (answer_questions has the bug the incident fixes).
    for name in ("reorder_reminders", "stock_counts", "answer_questions"):
        (root / f"workflows/{name}.py").write_text("print('ok')\n" if name != "answer_questions" else "raise SystemExit(1)\n")
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python").symlink_to(sys.executable)

    # A git repo with the incident's fix on its own branch, as incident.py leaves it.
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "start")
    git(root, "switch", "-qc", "fix/iabc12345")
    (root / "workflows/answer_questions.py").write_text("print('Answered 4 questions')\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "fix")
    git(root, "switch", "-q", "main")

    bin_dir = root / "fakebin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(FAKE_CLAUDE)
    (bin_dir / "claude").chmod(stat.S_IRWXU)


def shown_strings(value, key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from shown_strings(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from shown_strings(v, key)
    elif isinstance(value, str) and key in SHOWN_FIELDS:
        yield value


class FakeGateway(http.server.BaseHTTPRequestHandler):
    """Stands in for Steerable Cloud's gateway: lists services and records calls."""
    calls: list = []

    def _reply(self):
        length = int(self.headers.get("Content-Length") or 0)
        FakeGateway.calls.append({"method": self.command, "path": self.path, "headers": dict(self.headers),
                                  "body": self.rfile.read(length).decode() if length else ""})
        if self.path == "/x":
            body, status = {"available": [{"id": "google", "name": "Google", "mcp": False}, {"id": "stripe", "name": "Stripe", "mcp": True},
                                          {"id": "notion", "name": "Notion", "mcp": True}],
                            "connected": [{"provider": "stripe", "name": "Stripe", "account": "rk_live_…4kx2", "status": "ACTIVE", "mcp": True},
                                          {"provider": "notion", "name": "Notion", "account": None, "status": "ACTIVE", "mcp": True}]}, 200
        elif self.path == "/mcp/notion":
            message = json.loads(FakeGateway.calls[-1]["body"])
            if "id" not in message:  # a notification
                self.send_response(202)
                self.end_headers()
                return
            result = ({"protocolVersion": "2025-06-18", "capabilities": {}} if message["method"] == "initialize" else
                      {"content": [{"type": "text", "text": "3 pages"}], "structuredContent": {"pages": 3},
                       "isError": message["params"]["name"] == "broken_tool"})
            data = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "s-1")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        elif self.path.startswith("/x/google/"):
            body, status = {"error": "Google isn't connected. The owner can connect it in Connections.", "connect": "google"}, 409
        else:
            body, status = {"ok": True}, 200
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _reply

    def log_message(self, *args):
        pass


class AgentApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGateway)
        threading.Thread(target=cls.gateway.serve_forever, daemon=True).start()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "bloom"
        build_company(cls.root)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        (cls.tmp / "home").mkdir()
        cls.gateway_env = {"STEERABLE_GATEWAY_URL": f"http://127.0.0.1:{cls.gateway.server_address[1]}",
                           "ANTHROPIC_API_KEY": "sk-steerable-test-token"}
        env = {**os.environ, **cls.gateway_env, "AGENT_API_PORT": str(cls.port), "HOME": str(cls.tmp / "home"),
               "GIT_AUTHOR_NAME": "COO", "GIT_AUTHOR_EMAIL": "coo@test", "GIT_COMMITTER_NAME": "COO",
               "GIT_COMMITTER_EMAIL": "coo@test",
               "PATH": f"{cls.root / 'fakebin'}{os.pathsep}{os.environ['PATH']}"}
        cls.proc = subprocess.Popen([sys.executable, "scripts/agent_api.py"], cwd=cls.root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError(cls.proc.stdout.read().decode())

    @classmethod
    def tearDownClass(cls):
        cls.gateway.shutdown()
        cls.proc.terminate()
        cls.proc.wait(5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, token=TOKEN):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait_for(self, check, timeout=15):
        """Poll until check() returns something truthy (background builds take a moment)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if value := check():
                return value
            time.sleep(0.2)
        self.fail("timed out waiting")

    def assertPlain(self, payload):
        for text in shown_strings(payload):
            for word in ENGINE_WORDS:
                self.assertNotIn(word, text.lower(), f"engine word in: {text!r}")

    # Tests run in name order. Reads come before the writes that change state.

    def test_00_onboarding_kickoff(self):
        self.assertEqual(self.call("GET", "/v1/onboarding")[1], {"done": False, "started": False})
        status, body = self.call("POST", "/v1/onboarding/start")
        self.assertEqual(status, 200)
        self.assertTrue(body["started"])
        self.assertTrue(body["reply"]["text"].startswith("Got it: start onboarding."))
        # The kickoff prompt is hidden: the conversation opens with the COO.
        _, messages = self.call("GET", "/v1/chat")
        self.assertEqual([m["from"] for m in messages], ["coo"])
        self.assertEqual(self.call("GET", "/v1/onboarding")[1], {"done": False, "started": True})
        self.assertEqual(self.call("POST", "/v1/onboarding/start")[1], {"reply": None, "started": False})

    def test_01_auth(self):
        self.assertEqual(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health").status, 200)
        self.assertEqual(self.call("GET", "/v1/overview", token="wrong")[0], 401)
        self.assertEqual(self.call("GET", "/v1/overview", token="")[0], 401)
        self.assertEqual(self.call("GET", "/v1/nope")[0], 404)

    def test_02_decisions(self):
        status, ds = self.call("GET", "/v1/decisions")
        self.assertEqual(status, 200)
        self.assertEqual([d["id"].split(":")[0] for d in ds], ["incident", "task", "mission"])
        problem, approval, choice = ds
        self.assertEqual(problem["title"], "The inbox password changed, so the routine can't log in")
        self.assertIn("Two customers are waiting.", problem["context"])
        self.assertIn("I've paused Answer common customer questions", problem["context"])
        self.assertIn("I've prepared a fix: Reads the new password from .env. I've paused", problem["context"])
        self.assertEqual([o["id"] for o in problem["options"]], ["apply", "action-0", "discard"])
        self.assertEqual(problem["recommendation"]["optionId"], "apply")
        self.assertEqual(problem["draft"]["body"], "Hi Dana, sorry for the wait...")
        self.assertIn({"label": "This week", "value": "Happened 2 times"}, problem["facts"])
        self.assertEqual(approval["title"], "Send a weekly Plant of the Week email")
        self.assertEqual(approval["goal"], "$8k monthly revenue")
        self.assertIn("A weekly email brings repeat orders", approval["context"])
        self.assertEqual(choice["title"], "Handle the supplier price rise")
        self.assertIn("8%", choice["context"])
        self.assertPlain(ds)

    def test_03_overview(self):
        _, o = self.call("GET", "/v1/overview")
        self.assertEqual(o["company"]["name"], "Bloom & Root")
        self.assertEqual(o["health"], {"state": "attention", "summary": "1 routine paused while I fix it"})
        self.assertEqual(o["brief"]["headline"], "3 things need your call today.")
        self.assertIn("Ran on schedule: Remind cafes to reorder.", o["brief"]["points"])
        self.assertIn("Answer common customer questions hit a problem, so I paused it.", o["brief"]["points"])
        self.assertEqual(o["spend"], {"monthToDateUsd": 1.01, "monthlyCapUsd": 40.0})  # + the kickoff turn
        self.assertEqual(o["stats"]["hoursSavedThisWeek"], 2.0)  # only running routines count
        self.assertPlain(o)

    def test_04_routines(self):
        _, rs = self.call("GET", "/v1/routines")
        by_id = {r["id"]: r for r in rs}
        self.assertEqual(by_id["reorder_reminders"]["status"], "running")
        self.assertEqual(by_id["reorder_reminders"]["lastRun"]["summary"], "Reminded 6 cafes that haven't reordered")
        self.assertEqual(by_id["reorder_reminders"]["monthlyCostUsd"], 0.4)
        self.assertEqual(by_id["reorder_reminders"]["schedule"], "Every week")
        self.assertEqual(by_id["reorder_reminders"]["description"], "Every quiet cafe hears from us within 3 weeks")
        self.assertEqual(by_id["newsletter"]["status"], "needs-approval")
        self.assertEqual((by_id["answer_questions"]["status"], by_id["answer_questions"]["pausedBy"]), ("paused", "coo"))
        self.assertEqual(by_id["answer_questions"]["lastRun"]["ok"], False)
        self.assertEqual((by_id["stock_counts"]["status"], by_id["stock_counts"]["pausedBy"]), ("paused", "you"))
        self.assertPlain(rs)

    def test_04b_routine_page(self):
        self.assertEqual(self.call("GET", "/v1/routines/nope")[0], 404)
        status, r = self.call("GET", "/v1/routines/reorder_reminders")
        self.assertEqual(status, 200, r)
        self.assertEqual(r["name"], "Remind cafes to reorder")
        self.assertEqual(r["runs"][0]["summary"], "Reminded 6 cafes that haven't reordered")
        self.assertTrue(r["runs"][0]["ok"])
        # No steps written yet: described once, in the background, then shown.
        self.assertIsNone(r["flow"])
        self.assertTrue(r["flowPending"])
        r = self.wait_for(lambda: (d := self.call("GET", "/v1/routines/reorder_reminders")[1])["flow"] and d)
        self.assertEqual([s["kind"] for s in r["flow"]], ["trigger", "read", "send"])
        self.assertEqual(r["flow"][2]["service"], "Gmail")
        self.assertFalse(r["flowPending"])
        self.assertTrue((self.root / "workflows/reorder_reminders.flow.json").exists())
        self.assertPlain(r)

    def test_05_todos_and_goals(self):
        _, todos = self.call("GET", "/v1/todos")
        self.assertEqual([(t["title"], t["owner"], t["done"]) for t in todos], [
            ("Reply to Juniper & Co about Friday", "you", False),
            ("Draft the spring price sheet", "coo", False),
            ("Set up the Telegram app", "you", True),
        ])
        _, goals = self.call("GET", "/v1/goals")
        cafes, revenue = goals
        self.assertEqual(cafes["metric"], {"label": "cafe accounts", "current": 31.0, "target": 40.0, "unit": ""})
        self.assertEqual(cafes["pace"], "ahead")  # 78% done, 67% of the time gone
        self.assertEqual([p["status"] for p in cafes["projects"]], ["in-progress"])  # the cancelled one is hidden
        self.assertEqual(revenue["metric"], {"label": "monthly revenue", "current": 6120.0, "target": 8000.0, "unit": "$"})
        self.assertEqual({p["title"]: p["status"] for p in revenue["projects"]}["Handle the supplier price rise"],
                         "waiting-on-you")

    def test_06_timeline_reads_plainly(self):
        _, events = self.call("GET", "/v1/timeline?limit=10")
        titles = [e["title"] for e in events]
        self.assertEqual(titles, [
            "Wrote the spring price sheet draft",
            "Asked for your call on a problem",
            "Paused Answer common customer questions after a problem",
            "Reminded 6 cafes that haven't reordered",
        ])  # "Diagnosed" is internal and left out
        self.assertEqual(events[-1]["actor"], "autopilot")
        self.assertEqual(events[-1]["goal"], "40 cafe accounts")
        self.assertPlain(events)

    def test_07_pause_and_resume(self):
        self.assertEqual(self.call("POST", "/v1/routines/stock_counts/paused", {"paused": False})[0], 200)
        self.assertIn("Update stock counts from the shop  @workflow:stock_counts  every:daily\n",
                      (self.root / "tasks.md").read_text())
        self.assertEqual(self.call("POST", "/v1/routines/stock_counts/paused", {"paused": True})[0], 200)
        self.assertIn("every:daily  paused:owner", (self.root / "tasks.md").read_text())
        status, err = self.call("POST", "/v1/routines/answer_questions/paused", {"paused": False})
        self.assertEqual((status, err["error"]), (409, "It's paused while I fix a problem. You'll find it in Decisions."))
        self.assertEqual(self.call("POST", "/v1/routines/newsletter/paused", {"paused": True})[0], 409)
        self.assertEqual(self.call("POST", "/v1/routines/nope/paused", {"paused": True})[0], 404)
        self.assertEqual(self.call("POST", "/v1/routines/stock_counts/paused", {"paused": "yes"})[0], 400)

    def test_08_toggle_todo(self):
        _, todos = self.call("GET", "/v1/todos")
        tid = todos[0]["id"]
        self.assertEqual(self.call("POST", f"/v1/todos/{tid}/toggle")[0], 200)
        self.assertIn(f"- [x] Reply to Juniper & Co about Friday  @you  due:2026-10-09  done:{TODAY}",
                      (self.root / "tasks.md").read_text())
        self.assertEqual(self.call("POST", f"/v1/todos/{tid}/toggle")[0], 200)
        self.assertIn("- [ ] Reply to Juniper & Co about Friday  @you  due:2026-10-09\n", (self.root / "tasks.md").read_text())

    def test_09_approve_task(self):
        _, ds = self.call("GET", "/v1/decisions")
        task = next(d for d in ds if d["id"].startswith("task:"))
        status, event = self.call("POST", f"/v1/decisions/{task['id']}", {"optionId": "approve"})
        self.assertEqual(status, 200)
        self.assertEqual(event["title"], "You decided: Start it")
        self.assertIn("every:weekly  approved  saves:1.5h", (self.root / "tasks.md").read_text())
        # Deciding twice: the decision is gone.
        self.assertEqual(self.call("POST", f"/v1/decisions/{task['id']}", {"optionId": "approve"})[0], 410)
        # Approving a routine that doesn't exist yet starts the builder; a tested build is tried once more in a
        # practice run, which the owner looks at before it's switched on.
        ready = self.wait_for(lambda: next((d for d in self.call("GET", "/v1/decisions")[1] if d["id"].startswith("build:")), None))
        self.assertEqual(ready["title"], "See what \u201cSend a weekly Plant of the Week email\u201d will do, then switch it on")
        self.assertEqual([o["id"] for o in ready["options"]], ["switch_on", "change", "drop"])
        self.assertFalse((self.root / "workflows/newsletter.py").exists())  # not before the owner says so
        status, trace = self.call("GET", f"/v1/traces/{ready['trace']}")
        self.assertEqual((status, trace["kind"], trace["ok"]), (200, "practice", True))
        self.assertEqual(self.call("GET", "/v1/traces/nope")[0], 404)
        _, routine = self.call("GET", "/v1/routines/newsletter")
        self.assertEqual(routine["ready"], {"trace": ready["trace"], "decision": ready["id"]})
        self.assertEqual(self.call("POST", f"/v1/decisions/{ready['id']}", {"optionId": "switch_on"})[0], 200)
        self.assertEqual({r["id"]: r["status"] for r in self.call("GET", "/v1/routines")[1]}["newsletter"], "running")
        self.assertIn("Sent the weekly email", (self.root / "workflows/newsletter.py").read_text())
        _, routine = self.call("GET", "/v1/routines/newsletter")
        self.assertTrue(routine["watching"])  # its first runs are watched
        self.assertEqual(routine["watch"]["runs"], 0)
        self.assertEqual(self.call("POST", "/v1/routines/newsletter/watch", {"watch": False})[0], 200)
        self.assertNotIn("watching", self.call("GET", "/v1/routines/newsletter")[1])
        events = self.call("GET", "/v1/timeline?limit=6")[1]
        titles = [e["title"] for e in events]
        self.assertIn("Built Send a weekly Plant of the Week email and tried it in a practice run", titles)
        self.assertTrue(any(t.startswith("You switched on Send a weekly Plant of the Week email.") for t in titles))
        self.assertIn("Started building Send a weekly Plant of the Week email", titles)
        self.assertIn("You decided: Start it", titles)
        built = next(e for e in events if e["title"].startswith("Built"))
        self.assertEqual(built["detail"], "It emails your customers every Monday morning.")
        switched = next(e for e in events if e["title"].startswith("You switched on"))
        self.assertEqual(switched["kind"], "decided")
        self.assertNotIn("build/newsletter", subprocess.run(["git", "branch"], cwd=self.root, capture_output=True, text=True).stdout)

    def test_10_apply_fix(self):
        status, _ = self.call("POST", "/v1/decisions/incident:iabc12345", {"optionId": "apply"})
        self.assertEqual(status, 200)
        tasks = (self.root / "tasks.md").read_text()
        self.assertNotIn("paused:iabc12345", tasks)
        self.assertIn("Answered 4 questions", (self.root / "workflows/answer_questions.py").read_text())  # fix merged
        _, rs = self.call("GET", "/v1/routines")
        self.assertEqual({r["id"]: r["status"] for r in rs}["answer_questions"], "running")
        _, events = self.call("GET", "/v1/timeline?limit=1")
        self.assertEqual(events[0]["kind"], "fixed")
        self.assertEqual(events[0]["title"], "Fixed Answer common customer questions and restarted it")
        # Its other step (sending the two replies) is still on offer after the fix goes in.
        d = next(d for d in self.call("GET", "/v1/decisions")[1] if d["id"] == "incident:iabc12345")
        self.assertEqual([o["id"] for o in d["options"]], ["action-0", "keep-paused"])
        self.assertEqual(d["options"][1]["label"], "That's all")
        self.assertTrue(d["context"].startswith("The fix is in."))
        self.assertEqual(self.call("POST", "/v1/decisions/incident:iabc12345", {"optionId": "keep-paused"})[0], 200)
        self.assertNotIn("incident:iabc12345", [d["id"] for d in self.call("GET", "/v1/decisions")[1]])

    def test_11_mission_choice(self):
        status, _ = self.call("POST", "/v1/decisions/mission:4", {"optionId": "hold"})
        self.assertEqual(status, 200)
        _, ds = self.call("GET", "/v1/decisions")
        self.assertEqual(ds, [])
        _, o = self.call("GET", "/v1/overview")
        self.assertEqual(o["health"]["summary"], "Everything's running smoothly")
        self.assertEqual(self.call("POST", "/v1/decisions/mission:4", {"optionId": "go"})[0], 410)

    def test_12_chat(self):
        status, body = self.call("POST", "/v1/chat", {"text": "How are we doing?"})
        self.assertEqual(status, 200)
        self.assertEqual(body["reply"]["text"], "Got it: How are we doing?")
        _, messages = self.call("GET", "/v1/chat")
        self.assertEqual([(m["from"], m["text"]) for m in messages[-2:]],
                         [("you", "How are we doing?"), ("coo", "Got it: How are we doing?")])
        # What it did, with what it said on the way (plain, and never the reply itself).
        self.assertEqual(messages[-1]["steps"], [{"say": "Let me check your notes first."}, "Reading your notes",
                                                 {"say": "Now the going rates."}, "Searching the web for \u201ccafe wholesale prices\u201d"])
        self.assertEqual(self.call("POST", "/v1/chat", {"text": "   "})[0], 400)
        self.assertEqual(self.call("GET", "/v1/chat/activity")[1], {"working": False, "steps": []})

    def test_12a_new_conversation(self):
        """A fresh start: the COO forgets the thread, and the history stays, with a divider."""
        argv = lambda: json.loads((self.root / ".cache/last_claude_argv.json").read_text())
        self.call("POST", "/v1/chat", {"text": "First topic"})
        self.call("POST", "/v1/chat", {"text": "More on that"})
        self.assertIn("--resume", argv())  # the same conversation carries on
        self.assertEqual(self.call("POST", "/v1/chat/new"), (200, {"started": True}))
        self.assertEqual(self.call("POST", "/v1/chat/new"), (200, {"started": False}))  # already fresh: no second divider
        _, messages = self.call("GET", "/v1/chat")
        self.assertEqual([m["from"] for m in messages[-3:]], ["you", "coo", "divider"])
        self.call("POST", "/v1/chat", {"text": "Something else"})
        self.assertNotIn("--resume", argv())  # a new conversation for the COO
        _, messages = self.call("GET", "/v1/chat")
        self.assertEqual([m["from"] for m in messages[-4:]], ["coo", "divider", "you", "coo"])
        self.assertEqual(len([m for m in messages if m["from"] == "divider"]), 1)
        # Not while it's answering.
        threading.Thread(target=self.call, args=("POST", "/v1/chat", {"text": "Look into prices slowly"}), daemon=True).start()
        self.wait_for(lambda: self.call("GET", "/v1/chat/activity")[1]["working"])
        status, body = self.call("POST", "/v1/chat/new")
        self.assertEqual(status, 409)
        self.assertIn("still answering", body["error"])
        self.wait_for(lambda: not self.call("GET", "/v1/chat/activity")[1]["working"])

    def test_12b_chat_activity(self):
        """While the COO works on a reply, the app can see what it's doing, step by step."""
        threading.Thread(target=self.call, args=("POST", "/v1/chat", {"text": "Look into prices slowly"}), daemon=True).start()
        activity = self.wait_for(lambda: (a := self.call("GET", "/v1/chat/activity")[1])["steps"] and a)
        self.assertTrue(activity["working"])
        self.assertEqual(activity["steps"][:2], [{"say": "Let me check your notes first."}, "Reading your notes"])
        self.assertPlain(activity)
        self.wait_for(lambda: not self.call("GET", "/v1/chat/activity")[1]["working"])

    def test_12c_status(self):
        """Behind the health line: each background helper, what it's doing, in plain words."""
        def helpers():
            body = self.call("GET", "/v1/status")[1]
            self.assertPlain(body)
            return {h["id"]: h for h in body["helpers"]}

        hs = helpers()
        self.assertEqual(list(hs), ["routines", "chat", "builder", "fixer", "learn", "curate_skills", "upkeep"])
        self.assertEqual(hs["routines"]["state"], "idle")
        self.assertIn("on schedule", hs["routines"]["summary"])
        self.assertEqual(hs["chat"]["summary"], "Ready when you are")
        self.assertEqual(hs["fixer"]["state"], "idle")  # test_10 applied the fix
        self.assertEqual(hs["learn"]["summary"], "Once a day")
        # The heartbeat notes what it's running; a note from a run long gone doesn't count.
        note = self.root / ".cache/heartbeat_now.json"
        note.write_text(json.dumps({"routine": "reorder_reminders", "since": ago(minutes=1)}))
        self.assertEqual(helpers()["routines"]["state"], "working")
        self.assertIn("Remind", helpers()["routines"]["summary"])
        note.write_text(json.dumps({"system": "learn", "since": ago(minutes=1)}))
        self.assertEqual(helpers()["learn"]["state"], "working")
        note.write_text(json.dumps({"routine": "reorder_reminders", "since": ago(hours=2)}))
        self.assertEqual(helpers()["routines"]["state"], "idle")
        note.unlink()

    def raw(self, method, path, data=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=data,
                                     headers={"Authorization": f"Bearer {TOKEN}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_12d_files_in_chat(self):
        """Pictures and files attached in the chat: kept in the company folder, named to the COO,
        shown in the conversation, and downloadable (pictures inline, the rest as files)."""
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
        status, _, body = self.raw("POST", "/v1/files?name=" + urllib.parse.quote("../My CV<1>.png"), png)
        self.assertEqual(status, 200, body)
        pic = json.loads(body)
        self.assertEqual((pic["name"], pic["kind"], pic["size"]), ("My CV1.png", "image", len(png)))
        self.assertTrue((self.root / pic["path"]).is_file())  # in files/<year-month>/, never outside
        self.assertTrue(pic["path"].startswith("files/"))
        status, _, body = self.raw("POST", "/v1/files?name=notes.pdf", b"%PDF-1.4 hello")
        pdf = json.loads(body)
        self.assertEqual(self.raw("POST", "/v1/files?name=run.exe", b"MZ")[0], 400)
        self.assertEqual(self.raw("POST", "/v1/files?name=empty.txt", b"")[0], 400)

        status, body = self.call("POST", "/v1/chat", {"text": "", "files": [pic["id"], pdf["id"]]})
        self.assertEqual(status, 200)
        # The COO is told where they are, so it opens them.
        self.assertIn(pic["path"], body["reply"]["text"])
        self.assertIn(pdf["path"], body["reply"]["text"])
        mine = [m for m in self.call("GET", "/v1/chat")[1] if m["from"] == "you"][-1]
        self.assertEqual([f["name"] for f in mine["files"]], ["My CV1.png", "notes.pdf"])
        self.assertNotIn("path", mine["files"][0])
        self.assertEqual(self.call("POST", "/v1/chat", {"text": "hi", "files": ["0123456789"]})[0], 400)

        status, headers, data = self.raw("GET", f"/v1/files/{pic['id']}")
        self.assertEqual((status, data, headers["Content-Type"]), (200, png, "image/png"))
        self.assertTrue(headers["Content-Disposition"].startswith("inline"))
        status, headers, _ = self.raw("GET", f"/v1/files/{pdf['id']}")
        self.assertTrue(headers["Content-Disposition"].startswith("attachment"))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.raw("GET", "/v1/files/0123456789")[0], 404)

    def test_12e_search_and_long_messages(self):
        """Search covers the whole history (every word, any case, file names too), newest first."""
        status, found = self.call("GET", "/v1/chat/search?q=" + urllib.parse.quote("HOW are"))
        self.assertEqual(status, 200)
        self.assertTrue(found)
        self.assertTrue(all("how are" in m["text"].lower() for m in found))
        self.assertEqual(found, sorted(found, key=lambda m: m["at"], reverse=True))
        self.assertIn("you", {m["from"] for m in found})
        self.assertIn("coo", {m["from"] for m in found})  # the fake COO echoes the question
        by_file = self.call("GET", "/v1/chat/search?q=cv1.png")[1]  # test_12d attached it
        self.assertEqual(next(m for m in by_file if m["from"] == "you")["files"][0]["name"], "My CV1.png")
        self.assertEqual(self.call("GET", "/v1/chat/search?q=zebra%20unicorn")[1], [])
        self.assertEqual(self.call("GET", "/v1/chat/search?q=")[1], [])
        self.assertPlain(found)
        # Long messages are fine; past the limit, a plain reason instead of a cut-off message.
        long_text = "Here are my notes. " + "word " * 3000
        status, body = self.call("POST", "/v1/chat", {"text": long_text})
        self.assertEqual(status, 200)
        mine = [m for m in self.call("GET", "/v1/chat")[1] if m["from"] == "you"][-1]
        self.assertEqual(mine["text"], long_text.strip())
        status, body = self.call("POST", "/v1/chat", {"text": "x" * 20_001})
        self.assertEqual(status, 400)
        self.assertIn("attach it as a file", body["error"])

    def test_14_propose_routine(self):
        def propose(*args):
            return subprocess.run([sys.executable, "scripts/propose.py", *args], cwd=self.root,
                                  capture_output=True, text=True)
        out = propose("Follow up on new wholesale leads", "--workflow", "lead_followup", "--every", "daily",
                      "--goal", "40 cafe accounts", "--metric", "replies", "--saves", "1.5")
        self.assertEqual(out.returncode, 0, out.stderr)
        line = ("- [ ] Follow up on new wholesale leads (goal: 40 cafe accounts; metric: replies)  "
                "@workflow:lead_followup  every:daily  saves:1.5h  needs:approval")
        tasks = (self.root / "tasks.md").read_text().splitlines()
        self.assertIn(line, tasks)
        self.assertLess(tasks.index(line), tasks.index("## Done"))  # under Open
        _, ds = self.call("GET", "/v1/decisions")
        self.assertIn("Follow up on new wholesale leads", [d["title"] for d in ds])
        # It can't approve itself, and can't be proposed twice.
        self.assertIn("already proposed", propose("Again", "--workflow", "lead_followup", "--saves", "1").stdout)
        self.assertEqual(propose("Bad name", "--workflow", "Lead-Followup", "--saves", "1").returncode, 1)
        self.assertEqual(propose("No estimate", "--workflow", "no_estimate").returncode, 2)  # --saves is required
        out = propose("Sneaky  approved  @workflow:x", "--workflow", "sneaky_one", "--saves", "0")
        self.assertIn("- [ ] Sneaky  @workflow:sneaky_one  saves:0h  needs:approval",
                      (self.root / "tasks.md").read_text())
        _, events = self.call("GET", "/v1/timeline?limit=1")
        self.assertEqual(events[0]["title"], "Suggested a new routine: Sneaky")

    def test_16_build_needs_the_owner(self):
        subprocess.run([sys.executable, "scripts/propose.py", "Chase unpaid invoices", "--workflow",
                        "invoices_needs_login", "--every", "weekly", "--saves", "2"], cwd=self.root, check=True, capture_output=True)
        task = next(d for d in self.call("GET", "/v1/decisions")[1] if d["title"] == "Chase unpaid invoices")
        self.assertEqual(task["options"][0]["outcome"], "I'll build it, test it safely, then run it every week")
        self.call("POST", f"/v1/decisions/{task['id']}", {"optionId": "approve"})
        routine = next(r for r in self.call("GET", "/v1/routines")[1] if r["id"] == "invoices_needs_login")
        self.assertEqual(routine["status"], "setting-up")

        def build_decision():
            return next((d for d in self.call("GET", "/v1/decisions")[1] if d["id"].startswith("build:")), None)
        d = self.wait_for(build_decision)
        self.assertEqual(d["title"], "Chase unpaid invoices needs something from you")
        self.assertIn("What I need from you: a login for your invoicing tool.", d["context"])
        self.assertFalse((self.root / "workflows/invoices_needs_login.py").exists())  # nothing half-built
        self.assertPlain(d)
        # Try again: a fresh attempt, which needs the owner again.
        self.assertEqual(self.call("POST", f"/v1/decisions/{d['id']}", {"optionId": "retry"})[0], 200)
        d2 = self.wait_for(lambda: (x := build_decision()) and x["id"] != d["id"] and x)
        # Don't build it: gone from decisions, task rejected.
        self.assertEqual(self.call("POST", f"/v1/decisions/{d2['id']}", {"optionId": "drop"})[0], 200)
        self.assertIsNone(build_decision())
        self.assertRegex((self.root / "tasks.md").read_text(), r"- \[x\] Chase unpaid invoices  @workflow:invoices_needs_login.*rejected:")

    def test_16b_build_below_standard_isnt_switched_on(self):
        subprocess.run([sys.executable, "scripts/propose.py", "Weekly email", "--workflow", "weekly_messy",
                        "--every", "weekly", "--saves", "1"], cwd=self.root, check=True, capture_output=True)
        task = next(d for d in self.call("GET", "/v1/decisions")[1] if d["title"] == "Weekly email")
        self.call("POST", f"/v1/decisions/{task['id']}", {"optionId": "approve"})
        d = self.wait_for(lambda: next((x for x in self.call("GET", "/v1/decisions")[1]
                                        if x["id"].startswith("build:") and "Weekly email" in x["title"]), None))
        self.assertIn("keeps its data in ways the engine doesn't allow", d["context"])
        self.assertFalse((self.root / "workflows/weekly_messy.py").exists())  # never merged
        runs = (self.root / "logs/runs.jsonl").read_text()
        self.assertIn('"status": "standards"', runs)
        self.assertIn("write_text", runs)
        self.call("POST", f"/v1/decisions/{d['id']}", {"optionId": "drop"})

    def test_16c_change_a_running_routine(self):
        out = subprocess.run([sys.executable, "scripts/change.py", "reorder_reminders", "Tell me about new reorders in the chat",
                              "--why", "I miss them in the timeline"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        d = next(x for x in self.call("GET", "/v1/decisions")[1] if x["id"].startswith("change:"))
        self.assertEqual(d["title"], "Update \u201cRemind cafes to reorder\u201d?")
        self.assertEqual(d["draft"]["body"], "Tell me about new reorders in the chat")
        self.assertIn("keeps running as it is", d["context"])
        self.assertPlain(d)
        before = (self.root / "workflows/reorder_reminders.py").read_text()
        self.assertEqual(self.call("POST", f"/v1/decisions/{d['id']}", {"optionId": "approve"})[0], 200)
        ready = self.wait_for(lambda: next((x for x in self.call("GET", "/v1/decisions")[1] if x["id"].startswith("build:")), None), timeout=30)
        self.assertEqual(ready["title"], "The update to \u201cRemind cafes to reorder\u201d is ready: see what changes")
        self.assertEqual(ready["options"][0]["label"], "Use the new version")
        self.assertEqual((self.root / "workflows/reorder_reminders.py").read_text(), before)  # the old one runs meanwhile
        routine = next(r for r in self.call("GET", "/v1/routines")[1] if r["id"] == "reorder_reminders")
        self.assertNotEqual(routine["status"], "setting-up")  # it was never off
        # Change something: a new attempt from this one, with the owner's words; then use it.
        self.assertEqual(self.call("POST", f"/v1/decisions/{ready['id']}", {"optionId": "change"})[0], 400)
        self.assertEqual(self.call("POST", f"/v1/decisions/{ready['id']}", {"optionId": "change", "note": "Name the cafe"})[0], 200)
        again = self.wait_for(lambda: next((x for x in self.call("GET", "/v1/decisions")[1]
                                            if x["id"].startswith("build:") and x["id"] != ready["id"]), None), timeout=30)
        builds = json.loads((self.root / ".cache/builds.json").read_text())
        self.assertEqual(builds[again["id"][6:]]["feedback"], "Name the cafe")
        self.assertEqual(self.call("POST", f"/v1/decisions/{again['id']}", {"optionId": "switch_on"})[0], 200)
        self.assertIn("# updated", (self.root / "workflows/reorder_reminders.py").read_text())
        self.assertTrue((self.root / "workflows/reorder_reminders.py").read_text().startswith(before))
        self.assertTrue(any("You switched on the update to Remind cafes to reorder" in e["title"]
                            for e in self.call("GET", "/v1/timeline?limit=10")[1]))
        # Declining keeps it as it is; a routine that doesn't exist can't be changed.
        subprocess.run([sys.executable, "scripts/change.py", "reorder_reminders", "Run it hourly"], cwd=self.root, check=True,
                       capture_output=True)
        d2 = next(x for x in self.call("GET", "/v1/decisions")[1] if x["id"].startswith("change:"))
        self.call("POST", f"/v1/decisions/{d2['id']}", {"optionId": "decline"})
        self.assertFalse(any(x["id"].startswith("change:") for x in self.call("GET", "/v1/decisions")[1]))
        missing = subprocess.run([sys.executable, "scripts/change.py", "nope", "x"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no routine nope", missing.stderr)

    def test_16d_a_killed_attempt_doesnt_block_the_next(self):
        """A build killed by a restart leaves its worktree holding the branch; the next attempt clears it."""
        leftover = self.tmp / "leftover-worktree"
        git(self.root, "worktree", "add", "-q", str(leftover), "-b", "build/reorder_reminders", "HEAD")
        subprocess.run([sys.executable, "scripts/change.py", "reorder_reminders", "Mention the cafe's name"], cwd=self.root,
                       check=True, capture_output=True)
        d = next(x for x in self.call("GET", "/v1/decisions")[1] if x["id"].startswith("change:"))
        before = (self.root / "workflows/reorder_reminders.py").read_text()
        self.call("POST", f"/v1/decisions/{d['id']}", {"optionId": "approve"})
        ready = self.wait_for(lambda: next((x for x in self.call("GET", "/v1/decisions")[1] if x["id"].startswith("build:")), None), timeout=30)
        self.call("POST", f"/v1/decisions/{ready['id']}", {"optionId": "switch_on"})
        self.assertNotEqual((self.root / "workflows/reorder_reminders.py").read_text(), before)
        self.assertFalse(leftover.exists())

    def test_18_integrations_helper(self):
        script = """
import json, sys
sys.path.insert(0, "scripts")
from integrations import IntegrationError, call, connected
print(json.dumps(connected()))
print(json.dumps(call("stripe", "GET", "https://api.stripe.com/v1/invoices", params={"status": "open"})))
print(json.dumps(call("stripe", "POST", "https://api.stripe.com/v1/invoices/in_1/send", json={"a": 1})))
try:
    call("google", "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages")
except IntegrationError as e:
    print(json.dumps({"error": str(e), "connect": e.connect, "status": e.status}))
"""
        FakeGateway.calls.clear()
        out = subprocess.run([sys.executable, "-c", script], cwd=self.root, capture_output=True, text=True,
                             env={**os.environ, **self.gateway_env, "STEERABLE_DRY_RUN": "1"})
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = [json.loads(line) for line in out.stdout.splitlines()]
        self.assertEqual(lines[0][0]["provider"], "stripe")
        self.assertEqual(lines[3], {"error": "Google isn't connected. The owner can connect it in Connections.",
                                    "connect": "google", "status": 409})
        get, post = FakeGateway.calls[1], FakeGateway.calls[2]
        self.assertEqual(get["path"], "/x/stripe/api.stripe.com/v1/invoices?status=open")
        self.assertEqual(get["headers"]["Authorization"], "Bearer sk-steerable-test-token")
        self.assertEqual(get["headers"]["X-Steerable-Dry-Run"], "1")
        self.assertEqual((post["method"], post["body"]), ("POST", '{"a": 1}'))

    def test_20_mcp(self):
        script = """
import json, sys
sys.path.insert(0, "scripts")
from integrations import IntegrationError, claude_mcp_args, mcp_call, mcp_config
path, servers = mcp_config()
live = json.load(open(path))
dry = json.load(open(mcp_config(dry_run=True)[0]))
print(json.dumps({"servers": servers, "live": live, "dry": dry, "args": claude_mcp_args()}))
print(json.dumps(mcp_call("notion", "search", {"query": "pricing"})))
try:
    mcp_call("notion", "broken_tool")
except IntegrationError as e:
    print(json.dumps({"error": str(e)}))
"""
        FakeGateway.calls.clear()
        out = subprocess.run([sys.executable, "-c", script], cwd=self.root, capture_output=True, text=True,
                             env={**os.environ, **self.gateway_env})
        self.assertEqual(out.returncode, 0, out.stderr)
        first, called, failed = [json.loads(line) for line in out.stdout.splitlines()]
        gateway = self.gateway_env["STEERABLE_GATEWAY_URL"]
        # Steerable playbooks come first, from the same gateway, whatever is connected.
        self.assertEqual(first["servers"], ["steerable", "stripe", "notion"])
        self.assertEqual(first["live"]["mcpServers"]["steerable"]["url"], f"{gateway}/mcp/steerable")
        self.assertEqual(first["live"]["mcpServers"]["notion"],
                         {"type": "http", "url": f"{gateway}/mcp/notion", "headers": {"Authorization": "Bearer sk-steerable-test-token"}})
        self.assertEqual(first["dry"]["mcpServers"]["notion"]["headers"]["X-Steerable-Dry-Run"], "1")
        self.assertEqual(first["args"][1], ["mcp__steerable", "mcp__stripe", "mcp__notion"])
        self.assertEqual(called, {"pages": 3})
        self.assertEqual(failed, {"error": "3 pages"})
        tool_call = next(c for c in FakeGateway.calls if '"tools/call"' in c["body"])
        self.assertEqual(tool_call["headers"]["Mcp-Session-Id"], "s-1")  # the session from initialize

        # The chat gives Claude Code the live servers; the builder the dry-run ones.
        self.call("POST", "/v1/chat", {"text": "What's in Notion?"})
        argv = json.loads((self.root / ".cache/last_claude_argv.json").read_text())
        self.assertIn(str(self.root / ".cache/mcp-live.json"), argv)
        self.assertIn("mcp__notion", argv[argv.index("--allowedTools"):argv.index("--disallowedTools")])

    def test_21_routine_context(self):
        script = """
import sys
sys.path.insert(0, "scripts")
from integrations import call, mcp_call
call("stripe", "GET", "https://api.stripe.com/v1/balance")
mcp_call("notion", "search", {})
"""
        for context in ("routine", None):
            FakeGateway.calls.clear()
            extra = {"STEERABLE_CONTEXT": context} if context else {}
            env = {k: v for k, v in os.environ.items() if k != "STEERABLE_CONTEXT"}
            subprocess.run([sys.executable, "-c", script], cwd=self.root, check=True, capture_output=True,
                           env={**env, **self.gateway_env, **extra})
            marks = {c["headers"].get("X-Steerable-Context") for c in FakeGateway.calls}
            self.assertEqual(marks, {"routine"} if context else {None})

    def test_22_questions_with_a_pick(self):
        out = subprocess.run([sys.executable, "scripts/ask.py", "Handle the courier price rise",
                              "--context", "The courier raised prices 10% from June.",
                              "--option", "raise=Raise delivery to $6|Covers the rise",
                              "--option", "switch=Switch to Swift Couriers", "--recommend", "raise",
                              "--why", "Customers barely noticed the last change."],
                             cwd=self.root, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        d = next(d for d in self.call("GET", "/v1/decisions")[1] if d["title"] == "Handle the courier price rise")
        self.assertEqual(d["recommendation"], {"optionId": "raise", "why": "Customers barely noticed the last change."})
        self.assertEqual([(o["id"], o["label"], o.get("outcome"), o["tone"]) for o in d["options"]],
                         [("raise", "Raise delivery to $6", "Covers the rise", "primary"), ("switch", "Switch to Swift Couriers", None, "neutral")])
        self.assertEqual(self.call("POST", f"/v1/decisions/{d['id']}", {"optionId": "switch"})[0], 200)
        import sqlite3
        con = sqlite3.connect(self.root / "ops.db")
        status, outcome = con.execute("SELECT status, outcome FROM missions WHERE mission = 'Handle the courier price rise'").fetchone()
        self.assertEqual(status, "In progress")
        self.assertTrue(outcome.endswith("Owner chose: Switch to Swift Couriers."))
        # A plain "waiting on you" claims no pick.
        con.execute("INSERT INTO missions (mission, status, owner) VALUES ('Pick a logo', 'Waiting on CEO', 'COO')")
        con.commit()
        d = next(d for d in self.call("GET", "/v1/decisions")[1] if d["title"] == "Pick a logo")
        self.assertEqual(d["recommendation"]["optionId"], "")

    def test_19_build_needs_a_connection(self):
        subprocess.run([sys.executable, "scripts/propose.py", "Answer customer email", "--workflow",
                        "inbox_needs_google", "--every", "daily", "--saves", "3"], cwd=self.root, check=True, capture_output=True)
        task = next(d for d in self.call("GET", "/v1/decisions")[1] if d["title"] == "Answer customer email")
        self.call("POST", f"/v1/decisions/{task['id']}", {"optionId": "approve"})
        d = self.wait_for(lambda: next((d for d in self.call("GET", "/v1/decisions")[1]
                                        if d["title"] == "Answer customer email needs Google"), None))
        self.assertEqual(d["connect"], {"provider": "google", "label": "Connect Google"})
        # The builder ran Claude Code with the connected MCP servers in dry-run mode.
        argv = json.loads((self.root / ".cache/last_claude_argv.json").read_text())
        self.assertEqual(argv[argv.index("--mcp-config") + 1], str(self.root / ".cache/mcp-dry.json"))
        self.assertIn(".steerable-worktrees/builds", argv[argv.index("--add-dir") + 1])
        self.assertNotIn(".cache", argv[argv.index("--add-dir") + 1])  # agents are denied .cache folders
        self.assertIn("mcp__stripe", argv[argv.index("--allowedTools"):argv.index("--disallowedTools")])
        self.assertEqual(d["recommendation"]["why"], "Connect Google, then try again and I'll pick it up from there.")
        self.assertPlain(d)

    def test_09b_approving_a_routine_finishes_onboarding(self):
        """test_09 approved a routine: the engine took the onboarding section out itself."""
        self.assertNotIn("## First session: onboarding", (self.root / "CLAUDE.md").read_text())
        self.assertTrue(self.call("GET", "/v1/onboarding")[1]["done"])

    def test_15_onboarding_done(self):
        self.assertEqual(self.call("GET", "/v1/onboarding")[1], {"done": True, "started": True})

    def test_17_export(self):
        import io, tarfile
        (self.root / ".env").write_text((self.root / ".env").read_text() + "SECRET_THING=do-not-export\n")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/export", headers={"Authorization": f"Bearer {TOKEN}"})
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.headers["Content-Type"], "application/gzip")
            data = r.read()
        names = tarfile.open(fileobj=io.BytesIO(data)).getnames()
        for expected in ("company/tasks.md", "company/CLAUDE.md", "company/ops.db", "company/memory/company.md",
                         "company/workflows/newsletter.py", "company/logs/chat.jsonl"):
            self.assertIn(expected, names)
        self.assertTrue([n for n in names if n.startswith("company/files/") and n.endswith("My CV1.png")])  # test_12d
        self.assertFalse([n for n in names if n.startswith(("company/.env", "company/.cache", "company/.home", "company/.venv"))])
        self.assertNotIn(b"do-not-export", data)
        self.assertEqual(self.call("GET", "/v1/export", token="wrong")[0], 401)

    def test_13_bad_requests(self):
        self.assertEqual(self.call("POST", "/v1/decisions/task:nope", {"optionId": "approve"})[0], 410)
        self.assertEqual(self.call("POST", "/v1/decisions/task:nope", {})[0], 400)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat", method="POST", data=b"not json",
                                     headers={"Authorization": f"Bearer {TOKEN}"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 400)


class TaskEditTest(unittest.TestCase):
    """The heartbeat must not overwrite edits made while a workflow runs."""

    def test_heartbeat_keeps_edits_made_during_a_run(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\n")
            (root / "tasks.md").write_text(
                "- [ ] Slow one  @workflow:slow\n- [ ] Approve me  @workflow:other  needs:approval\n")
            (root / "workflows/other.py").write_text("print('ok')\n")  # exists, so approving it builds nothing
            # The workflow approves the other task halfway through, like an owner tapping a button.
            (root / "workflows/slow.py").write_text(
                "import sys\nsys.path.insert(0, 'scripts')\nfrom brief import task_id\nfrom bridge import set_approval\n"
                "set_approval(task_id('- [ ] Approve me  @workflow:other  needs:approval'), True)\n"
                "import os\nopen('context.txt', 'w').write(os.environ.get('STEERABLE_CONTEXT', ''))\nprint('done')\n")
            subprocess.run([sys.executable, "scripts/heartbeat.py"], cwd=root, check=True, capture_output=True)
            tasks = (root / "tasks.md").read_text()
            self.assertIn("- [x] Slow one  @workflow:slow  done:", tasks)
            # Routines run as approved work.
            self.assertEqual((root / "context.txt").read_text(), "routine")
            self.assertIn("- [ ] Approve me  @workflow:other  approved", tasks)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CoreWorkflowsTest(unittest.TestCase):
    """Learning and skill curation are the COO's own upkeep: they run without the owner's OK and
    stay out of their view, except what it learned."""

    def test_upkeep_runs_unseen(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\n")
            # An older company: the engine's own jobs are still lines in its tasks.md (even waiting
            # for approval), next to a real routine.
            (root / "tasks.md").write_text(
                "- [ ] Learn from the day  @workflow:learn  every:daily  needs:approval\n"
                "- [ ] Curate skills  @workflow:curate_skills  every:weekly  needs:approval\n"
                "- [ ] Weekly newsletter  @workflow:newsletter  every:weekly  needs:approval\n")
            script = """
import json, sys
sys.path.insert(0, "scripts")
import agent_api, heartbeat
from brief import pending_approvals
from ops_db import record_event
ready, waiting, _ = heartbeat.runnable_tasks(open("tasks.md").read().splitlines())
for what in ["Ran OK: Learned: cafes prefer a call to an email", "Ran OK: Nothing new to learn",
             "Ran OK: 12 active, 0 stale, 0 archived", "Ran OK: learn", "Ran OK: Sent the newsletter to 120 people"]:
    record_event(what)
print(json.dumps({"ready": [r[2] for r in ready], "waiting": waiting, "system": heartbeat.due_system_jobs(),
                  "approvals": [text for _, text in pending_approvals()],
                  "routines": [r["id"] for r in agent_api.routines()],
                  "decisions": [d["title"] for d in agent_api.decisions()],
                  "timeline": [(e["kind"], e["title"]) for e in agent_api.timeline()]}))
"""
            out = subprocess.run([sys.executable, "-c", script], cwd=root, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            seen = json.loads(out.stdout)
            # They aren't tasks any more: the heartbeat runs them on its built-in schedule.
            self.assertEqual(seen["ready"], [])
            self.assertEqual(sorted(seen["system"]), ["curate_skills", "learn", "upkeep"])
            self.assertEqual(len(seen["waiting"]), 1)  # only the newsletter waits for the owner
            self.assertEqual(len(seen["approvals"]), 1)
            self.assertIn("newsletter", seen["approvals"][0])
            self.assertEqual(seen["routines"], ["newsletter"])
            self.assertEqual(seen["decisions"], ["Weekly newsletter"])
            self.assertEqual(seen["timeline"], [["done", "Sent the newsletter to 120 people"],
                                                ["learned", "Got better at: cafes prefer a call to an email"]])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
