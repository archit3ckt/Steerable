"""The engine's own jobs (learning from the day, tidying skills): a built-in schedule, not tasks;
a failure is retried, never handed to the problem-fixer; and nothing may change the engine's code.

    python3 -m unittest tests.test_system_jobs
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"
TODAY = date.today().isoformat()


class SystemJobsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "co"
        shutil.copytree(TEMPLATE, self.root)
        (self.root / ".env").write_text("COMPANY_NAME=Co\nMONTHLY_BUDGET_USD=40\n")
        (self.root / ".cache").mkdir(exist_ok=True)
        # Stand-ins for the engine's jobs: learn works, curate_skills fails its own check.
        (self.root / "scripts/learn.py").write_text("print('Learned: cafes prefer a call')\n")
        (self.root / "scripts/curate_skills.py").write_text("import sys\nprint('Quality check failed: registry unreadable')\nsys.exit(2)\n")
        (self.root / "scripts/upkeep.py").unlink()  # these tests are about the two stand-ins (a job without its script isn't due)
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"]):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def py(self, code: str) -> subprocess.CompletedProcess:
        # An API key, so the health line doesn't depend on this machine being signed in to Claude.
        return subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts')\n" + code], cwd=self.root,
                              capture_output=True, text=True, env={**os.environ, "ANTHROPIC_API_KEY": "sk-test"})

    def heartbeat(self) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "scripts/heartbeat.py"], cwd=self.root, capture_output=True, text=True)

    def state(self) -> dict:
        return json.loads((self.root / ".cache/system_jobs.json").read_text())

    def runs(self) -> list[dict]:
        return [json.loads(line) for line in (self.root / "logs/runs.jsonl").read_text().splitlines()]

    def test_a_new_company_has_no_task_lines_for_them(self):
        tasks = (TEMPLATE / "tasks.md").read_text()
        self.assertNotIn("@workflow:learn", tasks)
        self.assertNotIn("@workflow:curate_skills", tasks)

    def test_they_run_on_the_built_in_schedule_and_a_failure_is_only_retried(self):
        out = self.heartbeat()
        self.assertEqual(out.returncode, 0, out.stderr)
        state = self.state()
        self.assertEqual(state["learn"], {"last": TODAY})
        # The failed one: noted, to try again tomorrow. No incident, no pause, nothing for the owner.
        self.assertEqual((state["curate_skills"]["tried"], state["curate_skills"]["failures"]), (TODAY, 1))
        self.assertIn("registry unreadable", state["curate_skills"]["error"])
        self.assertFalse((self.root / ".cache/incidents.json").exists())
        self.assertEqual([line for line in (self.root / "tasks.md").read_text().splitlines() if line.startswith("- [")], [])
        statuses = {(r.get("system"), r["status"]) for r in self.runs() if r.get("system")}
        self.assertEqual(statuses, {("learn", "ok"), ("curate_skills", "system_error")})
        shown = self.py("import json, agent_api\nprint(json.dumps({'d': agent_api.decisions(), 'r': agent_api.routines(), 'h': agent_api.overview()['health']}))")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        seen = json.loads(shown.stdout)
        self.assertEqual((seen["d"], seen["r"], seen["h"]["state"]), ([], [], "good"))
        # Nor are they news: today's summary and the morning brief name the owner's routines only.
        said = self.py("import json, agent_api, brief\nprint(json.dumps([agent_api.overview(), brief.build()[0]]))")
        self.assertEqual(said.returncode, 0, said.stderr)
        overview, morning = json.loads(said.stdout)
        for text in (json.dumps(overview), morning):
            self.assertNotIn("Learn", text)
            self.assertNotIn("Curate", text)
            self.assertNotIn("curate_skills", text)
        self.assertEqual(overview["stats"]["doneThisWeek"], 0)  # the engine's own runs aren't work done for the owner

        # Neither runs again today; learn is due again tomorrow, and the failed one is retried then.
        before = len(self.runs())
        self.heartbeat()
        self.assertEqual([r for r in self.runs()[before:] if r.get("system")], [])
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        (self.root / ".cache/system_jobs.json").write_text(json.dumps({"learn": {"last": yesterday}, "curate_skills": {"tried": yesterday, "failures": 1}}))
        due = self.py("import heartbeat; print(sorted(heartbeat.due_system_jobs()))")
        self.assertEqual(due.stdout.strip(), "['curate_skills', 'learn']")
        # A weekly one that worked isn't due the next day.
        (self.root / ".cache/system_jobs.json").write_text(json.dumps({"learn": {"last": TODAY}, "curate_skills": {"last": yesterday}}))
        self.assertEqual(self.py("import heartbeat; print(heartbeat.due_system_jobs())").stdout.strip(), "[]")
        # Whoever runs the engine can see the failure.
        status = subprocess.run([sys.executable, "scripts/status.py"], cwd=self.root, capture_output=True, text=True)
        self.assertIn("ENGINE", status.stdout)
        self.assertIn("curate_skills", status.stdout)

    def test_an_older_company_has_its_task_lines_taken_out(self):
        week_ago = (date.today() - timedelta(days=3)).isoformat()
        tasks = self.root / "tasks.md"
        tasks.write_text(tasks.read_text() + f"- [ ] Learn from the day  @workflow:learn  every:daily  approved  last:{TODAY}\n"
                         f"- [ ] Curate skills  @workflow:curate_skills  every:weekly  needs:approval  last:{week_ago}  paused:iabc\n"
                         "- [ ] Call the supplier  @you\n")
        out = self.heartbeat()
        self.assertEqual(out.returncode, 0, out.stderr)
        text = tasks.read_text()
        self.assertNotIn("@workflow:learn", text)
        self.assertNotIn("@workflow:curate_skills", text)
        self.assertIn("Call the supplier", text)
        # They carry on from when they last ran: neither was due today.
        self.assertEqual(self.state(), {"learn": {"last": TODAY}, "curate_skills": {"last": week_ago}})
        self.assertEqual([r for r in self.runs() if r.get("system")], [])

    def test_in_steerable_cloud_a_failure_is_reported_to_the_platform(self):
        import http.server, os, threading
        got = []

        class Platform(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                got.append({"path": self.path, "auth": self.headers.get("Authorization"),
                            "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
                self.send_response(202)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Platform)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            env = {**os.environ, "STEERABLE_JOBS_URL": f"http://127.0.0.1:{server.server_address[1]}", "STEERABLE_IN_BURST": "1",
                   "ANTHROPIC_API_KEY": "sk-steerable-c1-1-sig"}
            out = subprocess.run([sys.executable, "scripts/heartbeat.py"], cwd=self.root, capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
        finally:
            server.shutdown()
        # Only the failed job, with what went wrong; the one that worked says nothing.
        self.assertEqual([(g["path"], g["auth"], g["body"]["kind"], g["body"]["name"]) for g in got],
                         [("/api/engine/problems", "Bearer sk-steerable-c1-1-sig", "system_job", "curate_skills")])
        self.assertIn("registry unreadable", got[0]["body"]["detail"])

    def test_the_problem_fixer_never_gets_them_and_engine_code_is_never_merged(self):
        out = self.py("""
import incident, subprocess
print(incident.open_incident("crash", "workflow:learn", "learn crashed", "boom", workflow="learn"))
def git(*a): subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
# A fix branch that changes a company routine, and one that changes the engine's own code.
for branch, path in (("fix/iok", "workflows/newsletter.py"), ("fix/ibad", "scripts/learn.py"), ("fix/ibad2", "workflows/_template.py")):
    git("checkout", "-q", "-b", branch); open(path, "a").write("# changed\\n"); git("add", "-A"); git("commit", "-qm", "fix"); git("checkout", "-q", "-")
print([incident.engine_code_changed(b) for b in ("fix/iok", "fix/ibad", "fix/ibad2")])
incident.save({"ibad": {"id": "ibad", "status": "investigating", "summary": "x", "verdict": {"fix_ready": True}}})
print(incident.apply_fix("ibad"))
print(open("scripts/learn.py").read().count("# changed"))
""")
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.strip().splitlines()
        self.assertEqual(lines[0], "None")  # no incident for an engine job
        self.assertEqual(lines[1], "[[], ['scripts/learn.py'], ['workflows/_template.py']]")
        self.assertIn("not applied", lines[2])
        self.assertEqual(lines[3], "0")  # the engine's file is untouched


if __name__ == "__main__":
    unittest.main()
