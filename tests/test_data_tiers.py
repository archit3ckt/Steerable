"""Data in its place: working state that expires (state.py), records in the library (library.py),
lessons for the learning review (common.lesson), and upkeep that keeps logs from growing forever.

    python3 -m unittest tests.test_data_tiers -v
"""
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"

SCRIPT = r"""
import io, json, os, sqlite3, sys, tarfile, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "scripts")
import agent_api, learn, library, state
from common import LESSONS, lesson
out = {}

# ---- working state ----
s = state.State("job_scan")
out["first"] = s.seen("board:1", keep_days=60)
out["again"] = s.seen("board:1", keep_days=60)
s.set("last", "2026-10-13", keep_days=1)
with sqlite3.connect(state.DB) as con:  # pretend a day went by for "last"
    con.execute("UPDATE state SET expires = ? WHERE key = 'last'", (time.time() - 1,))
out["expired_get"] = s.get("last")
state.State("old_routine").set("x", 1)
out["pruned"] = state.prune(keep_routines={"job_scan"})
with sqlite3.connect(state.DB) as con:
    out["left"] = [r[0] for r in con.execute("SELECT routine || ':' || key FROM state ORDER BY 1")]
os.environ["STEERABLE_DRY_RUN"] = "1"
out["dry_seen"] = state.State("job_scan").seen("board:2")
lesson("not in a dry run")
del os.environ["STEERABLE_DRY_RUN"]
out["dry_kept"] = state.State("job_scan").get("board:2")

# ---- the library ----
def err(fn):
    try:
        fn(); return None
    except library.LibraryError as e:
        return str(e)
cos = library.table("Companies", columns="Name:text")
acme = cos.add({"Name": "Acme"}, key="acme")
os.environ["STEERABLE_CONTEXT"] = "routine"
jobs = library.table("Job openings", columns="Title:text, Link:link, Status:status(New|Interesting|Applied|Rejected), "
                     "Salary:number($), Found:date, Remote:checkbox, Company:relation(Companies)")
j1 = jobs.add({"Title": "DevOps Engineer", "Link": "https://example.com/1", "Found": "2026-10-13T08:00:00", "Company": "acme"}, key="d:1")
out["status_default"] = jobs.get("d:1")["cells"]["Status"]
out["company_link"] = jobs.get("d:1")["cells"]["Company"] == acme
out["errors"] = [err(lambda: jobs.add({"Status": "Maybe"})), err(lambda: jobs.add({"Found": "13/10/2026"})),
                 err(lambda: jobs.add({"Salary": "lots"})), err(lambda: jobs.add({"Link": "example.com"})),
                 err(lambda: jobs.add({"Nope": 1})), err(lambda: jobs.add({"Company": "nobody"})),
                 err(lambda: library.parse_columns("Status:status")), err(lambda: library.table("Missing"))]
with library.acting("you"):  # the owner, in the app
    jobs.update("d:1", {"Status": "Applied", "Remote": "yes"})
del os.environ["STEERABLE_CONTEXT"]
os.environ["STEERABLE_CONTEXT"] = "routine"
jobs.add({"Title": "DevOps Engineer (updated)", "Status": "New"}, key="d:1")  # the next scan finds it again
out["kept_owner_edit"] = jobs.get("d:1")["cells"]
jobs.add({"Salary": 18000}, key="d:1", overwrite=True)
out["overwritten"] = jobs.get("d:1")["cells"]["Salary"]
jobs.add({"Title": "Java dev"}, key="d:2")
jobs.archive("d:2")
jobs.add({"Title": "Java dev again"}, key="d:2")
out["archived_stays"] = [r["key"] for r in jobs.rows()]
out["where"] = [r["key"] for r in jobs.rows(where={"status": "applied"})]
out["history"] = [(h["who"], h["what"]) for h in jobs.history("d:1")][::-1]
del os.environ["STEERABLE_CONTEXT"]
out["owner_changes"] = library.owner_changes("2000-01-01")
out["tables"] = [(t["name"], t["rows"]) for t in library.tables()]

# the app's endpoints: the owner's changes
row = agent_api.library_write(jobs.id, {"cells": {"Title": "Platform engineer", "Status": "Interesting"}, "key": "d:3"})
agent_api.library_write(jobs.id, {"cells": {"Status": "Rejected"}}, row["id"])
out["api_row"] = agent_api.library_row(jobs.id, row["id"])
out["api_table"] = {k: agent_api.library_table("Job openings", {})[k] for k in ("total",)}
try:
    agent_api.library_table("Nope", {})
except agent_api.ApiError as e:
    out["api_404"] = e.status

# ---- a practice run: new tables and columns are checked but nothing is kept ----
os.environ["STEERABLE_DRY_RUN"] = "1"
fresh = library.table("Suppliers", columns="Name:text, Rating:number")
out["dry_add"] = fresh.add({"Name": "Acme", "Rating": 5})
out["dry_bad"] = err(lambda: fresh.add({"Rating": "great"}))
more = library.table("Job openings", columns="Title:text, Priority:status(Low|High)")
out["dry_newcol"] = more.add({"Title": "x", "Priority": "High"})
del os.environ["STEERABLE_DRY_RUN"]
out["dry_tables"] = [t["name"] for t in library.tables()]

# ---- lessons and the learning review ----
os.environ["STEERABLE_WORKFLOW"] = "job_scan"
lesson("Maya marks jobs that need a driving licence as not interesting.")
since = datetime.now(timezone.utc) - timedelta(hours=1)
out["lessons"] = learn.lessons(since)
out["library_changes"] = learn.library_changes(since)

# ---- export ----
names = tarfile.open(fileobj=io.BytesIO(agent_api.export_archive())).getnames()
out["exported"] = "company/library.db" in names
print(json.dumps(out, default=str))
"""


class DataTiersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root)
        (self.root / ".env").write_text("COMPANY_NAME=Co\n")
        subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=self.root, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_state_library_lessons(self):
        proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=self.root, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        # Working state: remembered, expiring, cleaned up, untouched by dry runs.
        self.assertEqual((out["first"], out["again"]), (False, True))
        self.assertIsNone(out["expired_get"])
        self.assertEqual(out["left"], ["job_scan:board:1"])  # the expired one and the gone routine's are deleted
        self.assertFalse(out["dry_seen"])
        self.assertIsNone(out["dry_kept"])

        # The library: checked values, keys, the owner's edits kept, archived rows stay archived.
        self.assertEqual(out["status_default"], "New")
        self.assertTrue(out["company_link"])
        e = out["errors"]
        self.assertIn("is one of New, Interesting, Applied, Rejected", e[0])
        self.assertIn("YYYY-MM-DD", e[1])
        self.assertIn("takes a number", e[2])
        self.assertIn("https://", e[3])
        self.assertIn("has no column Nope", e[4])
        self.assertIn("isn't one", e[5])
        self.assertIn("needs its labels", e[6])
        self.assertIn("no table called Missing", e[7])
        kept = out["kept_owner_edit"]
        self.assertEqual((kept["Status"], kept["Remote"], kept["Title"], kept["Found"]), ("Applied", True, "DevOps Engineer", "2026-10-13"))
        self.assertEqual(out["overwritten"], 18000.0)
        self.assertEqual(out["archived_stays"], ["d:1"])
        self.assertEqual(out["where"], ["d:1"])
        self.assertEqual(out["history"][0], ["autopilot", "Added it"])
        self.assertIn(["you", "Set Status to Applied; Set Remote to yes"], out["history"])  # one line per row change
        self.assertIn(["autopilot", "Set Salary to 18000"], out["history"])
        self.assertTrue(any(c["what"].startswith("Set Status to Applied") and c["row"] == "“DevOps Engineer”" for c in out["owner_changes"]))
        self.assertIn(["Job openings", 1], out["tables"])
        self.assertEqual(out["api_row"]["cells"]["Status"], "Rejected")
        self.assertEqual(out["api_row"]["history"][0]["who"], "you")
        self.assertEqual(out["api_table"]["total"], 2)
        self.assertEqual(out["api_404"], 404)

        self.assertEqual((out["dry_add"], out["dry_newcol"]), ("dry", "dry"))
        self.assertIn("takes a number", out["dry_bad"])
        self.assertNotIn("Suppliers", out["dry_tables"])

        # Learning: what routines noticed, and what the owner changed.
        self.assertEqual(len(out["lessons"]), 1)  # the dry run's lesson wasn't kept
        self.assertIn("driving licence", out["lessons"][0])
        self.assertIn("noticed by the routine job_scan", out["lessons"][0])
        self.assertIn("Job openings “Platform engineer”: Set Status to Rejected", out["library_changes"][0])
        self.assertTrue(out["exported"])

    def test_upkeep(self):
        now = datetime.now(timezone.utc)
        ago = lambda days: (now - timedelta(days=days)).isoformat(timespec="seconds")
        logs = self.root / "logs"
        (logs / "runs.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
            {"ts": ago(400), "script": "heartbeat", "status": "ok", "stdout": "old"},
            {"ts": ago(60), "script": "heartbeat", "status": "ok", "stdout": "two months ago", "workflow": "x"},
            {"ts": ago(1), "script": "heartbeat", "status": "ok", "stdout": "yesterday"}]))
        (logs / "spend.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
            {"ts": ago(500), "source": "x", "cost_usd": 1}, {"ts": ago(10), "source": "x", "cost_usd": 2}]))
        (self.root / ".cache").mkdir(exist_ok=True)
        (self.root / ".cache/lessons.jsonl").write_text(json.dumps({"ts": ago(40), "text": "old"}) + "\n")
        proc = subprocess.run([sys.executable, "scripts/upkeep.py"], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        runs = [json.loads(l) for l in (logs / "runs.jsonl").read_text().splitlines()]
        self.assertEqual([r.get("stdout") for r in runs if r["script"] == "heartbeat"], [None, "yesterday"])  # year kept, output 30 days
        self.assertEqual(runs[0]["workflow"], "x")
        self.assertEqual([json.loads(l)["cost_usd"] for l in (logs / "spend.jsonl").read_text().splitlines()], [2])
        self.assertEqual((self.root / ".cache/lessons.jsonl").read_text(), "")
        self.assertTrue(proc.stdout.strip().startswith("Cleared"))
        self.assertIn('"script": "upkeep"', (logs / "runs.jsonl").read_text())  # its own run, appended after


if __name__ == "__main__":
    unittest.main()
