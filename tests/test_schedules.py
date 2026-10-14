"""How often routines run: daily, weekly, every N hours, or at set times each day
(common.due_again), proposed with propose.py (--every, --at, --replace) and run by the heartbeat.

    python3 -m unittest tests.test_schedules -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"
sys.path.insert(0, str(TEMPLATE / "scripts"))
from common import check_schedule, due_again, next_run, stamp  # noqa: E402
from agent_api import when  # noqa: E402

AT = datetime(2026, 10, 13, 12, 0)  # a Tuesday, noon


def line(**tags) -> str:
    return "- [ ] Check new job posts  @workflow:job_scan  " + "  ".join(f"{k}:{v}" for k, v in tags.items())


class DueTest(unittest.TestCase):
    def test_daily_and_weekly_as_before(self):
        self.assertTrue(due_again(line(every="daily"), AT))  # never ran
        self.assertFalse(due_again(line(every="daily", last="2026-10-13"), AT))
        self.assertTrue(due_again(line(every="daily", last="2026-10-12"), AT))
        self.assertFalse(due_again(line(every="weekly", last="2026-10-08"), AT))
        self.assertTrue(due_again(line(every="weekly", last="2026-10-06"), AT))
        self.assertEqual(stamp(line(every="daily"), AT), "2026-10-13")

    def test_every_few_hours(self):
        self.assertFalse(due_again(line(every="3h", last="2026-10-13T09:30"), AT))
        self.assertTrue(due_again(line(every="3h", last="2026-10-13T09:00"), AT))
        self.assertTrue(due_again(line(every="3h", last="2026-10-13T09:05"), AT))  # the heartbeat isn't on the dot
        self.assertTrue(due_again(line(every="3h", last="2026-10-12"), AT))  # was daily until now
        self.assertEqual(stamp(line(every="3h"), AT), "2026-10-13T12:00")

    def test_set_times(self):
        times = "08:00,13:00,18:00"
        self.assertTrue(due_again(line(every="daily", at=times, last="2026-10-12T18:01"), AT))  # 08:00 is due
        self.assertFalse(due_again(line(every="daily", at=times, last="2026-10-13T08:02"), AT))  # next is 13:00
        self.assertTrue(due_again(line(every="daily", at=times, last="2026-10-13T08:02"), datetime(2026, 10, 13, 12, 55)))
        self.assertFalse(due_again(line(every="daily", at=times, last="2026-10-13T13:00"), datetime(2026, 10, 13, 17, 0)))
        # Down over a slot: one catch-up run, not one per missed slot.
        self.assertTrue(due_again(line(every="daily", at=times, last="2026-10-12T08:00"), AT))
        self.assertFalse(due_again(line(every="daily", at=times, last="2026-10-13T12:00"), AT))
        # Before the day's first slot, yesterday's last one counts.
        early = datetime(2026, 10, 13, 6, 0)
        self.assertFalse(due_again(line(every="daily", at=times, last="2026-10-12T18:00"), early))
        self.assertTrue(due_again(line(every="daily", at=times, last="2026-10-12T13:00"), early))
        self.assertEqual(stamp(line(every="daily", at=times), AT), "2026-10-13T12:00")

    def test_next_run(self):
        at = lambda h, m=0, d=13: datetime(2026, 10, d, h, m)
        times = "08:00,13:00,18:00"
        self.assertEqual(next_run(line(every="daily", at=times, last="2026-10-13T08:02"), AT), at(13))
        self.assertEqual(next_run(line(every="daily", at=times, last="2026-10-13T18:00"), at(19)), at(8, d=14))
        self.assertEqual(next_run(line(every="daily", at=times, last="2026-10-12T18:00"), AT), AT)  # due now (08:00 missed)
        self.assertEqual(next_run(line(every="3h", last="2026-10-13T11:00"), AT), at(14))
        self.assertEqual(next_run(line(every="daily", last="2026-10-13"), AT), at(0, d=14))
        self.assertEqual(next_run(line(every="weekly", last="2026-10-12"), AT), at(0, d=19))
        self.assertEqual(next_run(line(every="daily"), AT), AT)  # never ran
        self.assertEqual(next_run(line(due="2026-10-20"), AT), at(0, d=20))  # a one-off on a date
        # As the owner reads it.
        self.assertEqual(when(at(13), AT), "Today at 13:00")
        self.assertEqual(when(at(8, d=14), AT), "Tomorrow at 08:00")
        self.assertEqual(when(at(0, d=14), AT), "Tomorrow, early morning")
        self.assertEqual(when(at(14), AT, about=True), "Today around 14:00")
        self.assertEqual(when(at(8, d=16), AT), "Friday at 08:00")
        self.assertEqual(when(at(8, d=24), AT), "Oct 24 at 08:00")
        self.assertEqual(when(AT, AT), "In the next few minutes")

    def test_checks(self):
        for every, at in [("daily", None), ("weekly", None), ("1h", None), ("12h", None), ("daily", "08:00,18:30"), (None, "09:00")]:
            self.assertIsNone(check_schedule(every, at), (every, at))
        for every, at in [("13h", None), ("0h", None), ("hourly", None), ("daily", "8am"), ("daily", "25:00"), ("weekly", "08:00")]:
            self.assertIsNotNone(check_schedule(every, at), (every, at))


class ProposeAndRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root)
        (self.root / ".env").write_text("COMPANY_NAME=Co\nMONTHLY_BUDGET_USD=20\n")
        subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=self.root, check=True, capture_output=True)
        (self.root / "tasks.md").write_text("# Tasks\n\n## Open\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def propose(self, *args):
        return subprocess.run([sys.executable, "scripts/propose.py", "Check new job posts", "--workflow", "job_scan",
                               "--saves", "3", *args], cwd=self.root, capture_output=True, text=True)

    def task(self) -> str:
        return next(l for l in (self.root / "tasks.md").read_text().splitlines() if "job_scan" in l)

    def test_propose_replace_and_run(self):
        self.assertEqual(self.propose("--every", "daily").returncode, 0)
        self.assertIn("every:daily", self.task())
        # A second proposal is refused unless it replaces the one still waiting.
        self.assertIn("--replace", self.propose("--at", "13:00,08:00,18:00").stdout)
        self.assertEqual(self.propose("--at", "13:00,08:00,18:00", "--replace").returncode, 0)
        task = self.task()
        self.assertIn("every:daily  at:08:00,13:00,18:00", task)
        self.assertIn("needs:approval", task)
        self.assertEqual((self.root / "tasks.md").read_text().count("job_scan"), 1)
        bad = self.propose("--every", "30m", "--replace")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("every 1 to 12 hours", bad.stderr)

        # The owner approves; the heartbeat runs it and keeps the time, so it runs again at the next slot.
        tasks = (self.root / "tasks.md").read_text().replace("  needs:approval", "")
        (self.root / "tasks.md").write_text(tasks)
        (self.root / "workflows/job_scan.py").write_text("print('Found 4 new job posts')\n")
        code = ("import json, sys\nsys.path.insert(0, 'scripts')\nimport agent_api\n"
                "print(json.dumps([[r['schedule'], r.get('nextRun')] for r in agent_api.routines()]))")
        out = subprocess.run([sys.executable, "-c", code], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout), [["Every day at 08:00, 13:00 and 18:00", "In the next few minutes"]], out.stderr)
        run = subprocess.run([sys.executable, "scripts/heartbeat.py"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertRegex(self.task(), r"last:\d{4}-\d\d-\d\dT\d\d:\d\d$")
        out = subprocess.run([sys.executable, "-c", code], cwd=self.root, capture_output=True, text=True)
        self.assertRegex(json.loads(out.stdout)[0][1], r"^(Today|Tomorrow) at (08|13|18):00$")
        # Right after, it's not due again.
        dry = subprocess.run([sys.executable, "scripts/heartbeat.py", "--dry-run"], cwd=self.root, capture_output=True, text=True)
        self.assertNotIn("job_scan", dry.stdout)


if __name__ == "__main__":
    unittest.main()
