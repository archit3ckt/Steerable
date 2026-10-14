"""The routine page while things happen: a build's steps in plain words (builder.step_words over
its stream-json log), and the step of "How it works" a running routine is on (common.step).

    python3 -m unittest tests.test_routine_progress -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"

SCRIPT = r"""
import json, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "scripts")
import agent_api, builder, heartbeat
from common import CACHE, ROOT, STEPS, now_iso
out = {}

# A build in progress: its Claude events so far.
bid = "b123"
builder.STATE.write_text(json.dumps({bid: {"id": bid, "workflow": "job_scan", "task": "x", "title": "Job scan",
                                           "status": "building", "opened": now_iso()}}))
builder.LIVE.mkdir(exist_ok=True)
wt = "/home/x/.steerable-worktrees/builds/co/b123"
def tool(name, **args):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": args}]}})
def said(text):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
builder.live_path(bid).write_text("\n".join([
    said("I'll use urllib and parse the HTML with a regex."),
    tool("Read", file_path=f"{ROOT}/memory/company.md"),
    tool("Read", file_path=f"{wt}/workflows/_template.py"),
    tool("WebFetch", url="https://jobs.example.com/"),
    tool("Write", file_path=f"{wt}/workflows/job_scan.py", content="..."),
    tool("Write", file_path=f"{wt}/workflows/job_scan.flow.json", content="..."),
    tool("Bash", command=f"cd {wt} && STEERABLE_DRY_RUN=1 .venv/bin/python workflows/job_scan.py x"),
    tool("Edit", file_path=f"{wt}/workflows/job_scan.py", old_string="a", new_string="b"),
    tool("Bash", command=f"cd {wt} && STEERABLE_DRY_RUN=1 .venv/bin/python workflows/job_scan.py x"),
    tool("Bash", command=f"git -C {wt} commit -m 'Build job_scan'"),
    '{"type": "assistant", "mess',  # the last line may be half-written
]))
out["building"] = agent_api.routine_detail("job_scan").get("building")

# The routine running: the heartbeat's note, and the step it reported.
builder.STATE.write_text("{}")
(ROOT / "workflows/job_scan.py").write_text("print('ok')\n")
heartbeat.NOW.write_text(json.dumps({"routine": "job_scan", "since": now_iso()}))
STEPS.mkdir(exist_ok=True)
(STEPS / "job_scan.json").write_text(json.dumps({"step": 2, "at": now_iso()}))
out["running"] = agent_api.routine_detail("job_scan").get("runningNow")
old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
(STEPS / "job_scan.json").write_text(json.dumps({"step": 3, "at": old}))
out["stale_step"] = agent_api.routine_detail("job_scan").get("runningNow")
heartbeat.NOW.unlink()
out["idle"] = "runningNow" in agent_api.routine_detail("job_scan")
print(json.dumps(out))
"""

WORKFLOW = r"""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from common import STEPS, step
step(1)
step(2)
Path(".cache/seen.json").write_text(f'{{"name": "{os.environ.get("STEERABLE_WORKFLOW")}", "marker": {(STEPS / "job_scan.json").exists()}}}'.replace("True", "true").replace("False", "false"))
print("Found 2 new posts")
"""


class RoutineProgressTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root)
        (self.root / ".env").write_text("COMPANY_NAME=Co\nMONTHLY_BUDGET_USD=20\n")
        subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=self.root, check=True, capture_output=True)
        (self.root / "tasks.md").write_text("# Tasks\n\n## Open\n- [ ] Job scan  @workflow:job_scan  every:3h  saves:2h\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_steps_and_running_step(self):
        proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["building"]["steps"], [
            "Reading your notes", "Starting from the routine template", "Reading jobs.example.com", "Writing the routine",
            "Drawing how it works", "Testing it in a practice run (nothing is sent)", "Improving the routine",
            "Testing it in a practice run (nothing is sent)", "Saving the finished routine"])  # no engineer's remarks
        self.assertEqual(out["running"]["step"], 2)
        self.assertIsNone(out["stale_step"]["step"])  # from before this run started
        self.assertFalse(out["idle"])

    def test_heartbeat_names_the_routine_and_clears_its_step(self):
        (self.root / "workflows/job_scan.py").write_text(WORKFLOW)
        run = subprocess.run([sys.executable, "scripts/heartbeat.py"], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        seen = json.loads((self.root / ".cache/seen.json").read_text())
        self.assertEqual(seen, {"name": "job_scan", "marker": True})  # it reported a step while running
        self.assertFalse((self.root / ".cache/running/job_scan.json").exists())  # and it's gone after


if __name__ == "__main__":
    unittest.main()
