"""Background work a restart killed doesn't stay "working on it" forever (incident.recover_stale,
builder.recover_stale, run by the heartbeat).

    python3 -m unittest tests.test_recovery -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"

SCRIPT = r"""
import json, sys
sys.path.insert(0, "scripts")
import builder, change, incident
out = {"builds": builder.recover_stale(), "incidents": incident.recover_stale()}
out["incident_states"] = {k: v["status"] for k, v in incident.load().items()}
out["build_states"] = {k: (v["status"], v.get("summary", "")) for k, v in builder.load().items()}
out["changes"] = [(c["workflow"], c["change"]) for c in change.pending()]
print(json.dumps(out))
"""


class RecoveryTest(unittest.TestCase):
    def test_dead_background_work_is_recovered(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            (root / "tasks.md").write_text("# Tasks\n\n## Open\n- [ ] Job scan  @workflow:job_scan  every:daily  saves:3h\n")
            (root / "workflows/job_scan.py").write_text("print('ok')\n")
            (root / ".cache").mkdir(exist_ok=True)
            (root / ".venv/bin").mkdir(parents=True)
            (root / ".venv/bin/python").symlink_to(sys.executable)  # what a resumed build is launched with
            old = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat(timespec="seconds")
            new = datetime.now(timezone.utc).isoformat(timespec="seconds")
            recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
            request = "Add a second job board as a source and show matches in two groups: full-time and part-time."
            (root / ".cache/incidents.json").write_text(json.dumps({
                "ireq": {"id": "ireq", "kind": "request", "workflow": "job_scan", "status": "investigating", "opened": old,
                         "summary": "Fix requested for job_scan: Add a second job board",
                         "details": f"Requested from the chat (not a crash; the routine is still running):\n{request}\n\nRecent runs:\nx"},
                "icrash": {"id": "icrash", "kind": "crash", "workflow": "job_scan", "status": "investigating", "opened": old,
                           "restarts": 1, "restarted": old, "summary": "Workflow 'job_scan' crashed", "details": "..."},
                "ifresh": {"id": "ifresh", "kind": "crash", "workflow": "job_scan", "status": "investigating", "opened": new,
                           "summary": "x", "details": "..."}}))
            (root / ".cache/builds.json").write_text(json.dumps({
                "bdead": {"id": "bdead", "workflow": "older", "task": "Older", "title": "Older", "change": "x",
                          "status": "building", "opened": old},
                "blive": {"id": "blive", "workflow": "other", "task": "Other", "title": "Other", "status": "building", "opened": new},
                # killed by a restart a few minutes ago: its process is gone, so it's picked up again at once
                "bkilled": {"id": "bkilled", "workflow": "job_scan", "task": "Job scan", "title": "Job scan", "change": "y",
                            "status": "building", "opened": recent, "pid": 999999}}))
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["incident_states"], {"ireq": "resolved", "icrash": "awaiting_ceo", "ifresh": "investigating"})
            self.assertEqual(out["changes"], [["job_scan", request]])  # the request, in its proper place now
            self.assertEqual(out["build_states"]["bdead"][0], "failed")
            self.assertIn("interrupted", out["build_states"]["bdead"][1])
            self.assertIn("keeps running as it was", out["build_states"]["bdead"][1])
            self.assertEqual(out["build_states"]["blive"][0], "building")  # recent: still working
            self.assertEqual(out["build_states"]["bkilled"][0], "retried")
            resumed = [k for k, v in out["build_states"].items() if k not in ("bdead", "blive", "bkilled")]
            self.assertEqual(len(resumed), 1)  # a fresh attempt of the same change, started by the engine itself
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
