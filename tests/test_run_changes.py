"""What one run changed in the library, as a table (library.run_counts / run_changes, the heartbeat's
run ids, the agent API's /v1/runs/<run>/changes and the timeline), and that it stays quick for a
run that touches thousands of rows.

    python3 -m unittest tests.test_run_changes -v
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
import json, os, sys, time
sys.path.insert(0, "scripts")
import library
out = {}
cos = library.table("Companies", columns="Name:text")
cos.add({"Name": "Acme"}, key="acme")
jobs = library.table("Job openings", columns="Title:text, Status:status(New|Applied|Rejected), Salary:number, "
                     "Company:relation(Companies), Notes:longtext")
jobs.add({"Title": "Old one", "Salary": 100, "Notes": "keep"}, key="old")
jobs.add({"Title": "Gone", "Status": "New"}, key="gone")

os.environ.update(STEERABLE_CONTEXT="routine", STEERABLE_RUN="r1")
jobs.add({"Title": "DevOps", "Company": "acme"}, key="new")
jobs.update("new", {"Status": "Applied"})               # added then changed in the same run: still "added"
jobs.add({"Salary": 120, "Notes": None}, key="old", overwrite=True)  # a cell changed, one cleared
jobs.archive("gone")
with library.acting("you"):
    pass
del os.environ["STEERABLE_RUN"]
with library.acting("you"):
    jobs.update("old", {"Status": "Rejected"})          # the owner's edit: no run, not in r1

out["counts"] = library.run_counts("r1")
page = library.run_changes("r1")
out["page"] = page["table"]
out["other_table"] = library.run_changes("r1", table_id="nope")["table"]["name"]
out["none"] = library.run_changes("nothing")

# A big run: thousands of rows, then paging through them.
os.environ["STEERABLE_RUN"] = "rbig"
t0 = time.time()
for i in range(3000):
    jobs.add({"Title": f"Job {i}", "Salary": i}, key=f"k{i}")
out["add_seconds"] = time.time() - t0
t0 = time.time()
first = library.run_changes("rbig", limit=50)
seen, cursor, pages = len(first["table"]["rows"]), first["table"]["next"], 1
while cursor:
    nxt = library.run_changes("rbig", after=cursor, limit=200)
    seen += len(nxt["table"]["rows"]); cursor = nxt["table"]["next"]; pages += 1
out["page_seconds"] = time.time() - t0
out["big"] = {"counts": library.run_counts("rbig"), "seen": seen, "pages": pages,
              "first": first["table"]["rows"][0]["cells"]["Title"]["value"]}
del os.environ["STEERABLE_RUN"]
out["forgot"] = library.forget_details(days=-1)
out["after_forget"] = library.run_changes("r1")["table"]["details"]
print(json.dumps(out))
"""


class RunChangesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root)
        (self.root / ".env").write_text("COMPANY_NAME=Co\nMONTHLY_BUDGET_USD=20\n")
        subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=self.root, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_runs_changes(self):
        proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=self.root, capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual([{k: v for k, v in c.items() if k != "tableId"} for c in out["counts"]],
                         [{"table": "Job openings", "added": 1, "changed": 1, "archived": 1}])
        page = out["page"]
        self.assertEqual(page["name"], "Job openings")
        self.assertTrue(page["details"])
        self.assertIsNone(page["next"])
        self.assertEqual([c["name"] for c in page["columns"]], ["Title", "Status", "Salary", "Company", "Notes"])
        rows = {r["cells"]["Title"]["value"]: r for r in page["rows"]}
        added, changed, archived = rows["DevOps"], rows["Old one"], rows["Gone"]
        self.assertEqual(added["change"], "added")
        self.assertEqual(added["cells"]["Status"], {"value": "Applied"})  # no "before": it's new
        self.assertEqual(added["cells"]["Company"], {"value": "Acme"})    # a related row, in words
        self.assertEqual(changed["change"], "changed")
        self.assertEqual(changed["cells"]["Salary"], {"value": 120.0, "before": 100.0})
        self.assertEqual(changed["cells"]["Notes"], {"value": None, "before": "keep"})
        self.assertEqual(changed["cells"]["Status"], {"value": "Rejected"})  # the owner's later edit: not this run's
        self.assertEqual(archived["change"], "archived")
        self.assertEqual(out["other_table"], "Job openings")
        self.assertEqual(out["none"], {"tables": [], "table": None})

        big = out["big"]
        self.assertEqual(big["counts"][0]["added"], 3000)
        self.assertEqual(big["seen"], 3000)
        self.assertEqual(big["first"], "Job 0")
        self.assertLess(out["add_seconds"], 30)
        self.assertLess(out["page_seconds"], 10)
        self.assertGreater(out["forgot"], 3000)
        self.assertFalse(out["after_forget"])

    def test_heartbeat_and_api(self):
        (self.root / ".venv/bin").mkdir(parents=True)
        (self.root / ".venv/bin/python").symlink_to(sys.executable)
        (self.root / "tasks.md").write_text("# Tasks\n\n## Open\n- [ ] Job scan  @workflow:job_scan  every:daily  saves:3h\n")
        (self.root / "workflows/job_scan.py").write_text(
            "import sys\nsys.path.insert(0, 'scripts')\nimport library\nfrom common import step\nstep(1)\n"
            "t = library.table('Job openings', columns='Title:text')\n"
            "for i in range(3):\n    t.add({'Title': f'Job {i}'}, key=str(i))\nprint('Found 3 new jobs')\n")
        code = ("import json, sys\nsys.path.insert(0, 'scripts')\nimport heartbeat, agent_api\n"
                "from datetime import date\n"
                "line = open('tasks.md').read().splitlines()[-1]\n"
                "heartbeat.run_routine(line, line[6:], 'job_scan', date.today().isoformat())\n"
                "d = agent_api.routine_detail('job_scan')\n"
                "run = d['runs'][0]\n"
                "page = agent_api.run_changes(run['id'], {'limit': ['2']})\n"
                "more = agent_api.run_changes(run['id'], {'after': [str(page['table']['next'])]})\n"
                "ev = [e for e in agent_api.timeline() if e.get('run')]\n"
                "try:\n    agent_api.run_changes(run['id'], {'after': ['x']})\nexcept agent_api.ApiError as e:\n    bad = e.status\n"
                "print(json.dumps({'run': run, 'page': len(page['table']['rows']), 'more': len(more['table']['rows']),"
                " 'event': ev[0] if ev else None, 'bad': bad}))\n")
        proc = subprocess.run([sys.executable, "-c", code], cwd=self.root, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertTrue(out["run"]["id"].startswith("r"))
        self.assertEqual(out["run"]["changes"][0]["added"], 3)
        self.assertEqual((out["page"], out["more"]), (2, 1))
        self.assertEqual(out["event"]["run"], out["run"]["id"])
        self.assertEqual(out["event"]["changes"][0]["added"], 3)
        self.assertEqual(out["bad"], 400)


if __name__ == "__main__":
    unittest.main()
