"""Run now: one run of an approved routine on request (heartbeat.start_manual, run.py, the agent
API), as its schedule would run it, without moving the schedule.

    python3 -m unittest tests.test_run_now -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"


class RunNowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root)
        (self.root / ".env").write_text("COMPANY_NAME=Co\nMONTHLY_BUDGET_USD=20\n")
        subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=self.root, check=True, capture_output=True)
        (self.root / ".venv/bin").mkdir(parents=True)
        (self.root / ".venv/bin/python").symlink_to(sys.executable)
        (self.root / "tasks.md").write_text(
            "# Tasks\n\n## Open\n"
            "- [ ] Job scan  @workflow:job_scan  every:daily  at:08:00,13:00  saves:3h  last:2026-10-13T08:01\n"
            "- [ ] Weekly report  @workflow:report  every:weekly  needs:approval  saves:1h\n"
            "- [ ] Old thing  @workflow:old  every:daily  saves:1h  paused:owner\n")
        for name in ("job_scan", "report", "old"):
            (self.root / f"workflows/{name}.py").write_text(
                "import os, sys\nsys.path.insert(0, 'scripts')\nfrom common import step\nstep(1)\n"
                "print('Found 3 new jobs (' + os.environ.get('STEERABLE_CONTEXT', '') + ')')\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def runs(self):
        path = self.root / "logs/runs.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def test_run_now(self):
        out = subprocess.run([sys.executable, "scripts/run.py", "job_scan"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Started", out.stdout)
        for _ in range(100):
            done = [r for r in self.runs() if r.get("workflow") == "job_scan" and r.get("manual")]
            if done:
                break
            time.sleep(0.1)
        self.assertEqual(done[0]["status"], "ok")
        self.assertIn("Found 3 new jobs (routine)", done[0]["stdout"])  # run as a routine, like the schedule does
        self.assertIn("last:2026-10-13T08:01", (self.root / "tasks.md").read_text())  # the schedule didn't move
        for _ in range(50):
            if not (self.root / ".cache/manual-runs/job_scan.pid").exists():
                break
            time.sleep(0.1)
        self.assertFalse((self.root / ".cache/manual-runs/job_scan.pid").exists())
        # the routine's runs are only the finished ones (the start is logged on its own)
        self.assertEqual([r["status"] for r in self.runs() if r["script"] == "heartbeat"], ["ok"])
        again = subprocess.run([sys.executable, "scripts/run.py", "job_scan"], cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(again.returncode, 0)  # it just ran: asking again would only repeat it
        self.assertIn("finished a few minutes ago", again.stderr)
        self.assertIn("Found 3 new jobs", again.stderr)
        for name, expected in (("report", "switched on"), ("old", "switched on"), ("nope", "switched on")):
            refused = subprocess.run([sys.executable, "scripts/run.py", name], cwd=self.root, capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0, name)
            self.assertIn(expected, refused.stderr)


if __name__ == "__main__":
    unittest.main()
