"""The library's table view (Table.query and GET /v1/library/tables/<id>): search, filters, sorting,
paging, sums and related rows' labels, done in SQL so a big table stays quick.

    python3 -m unittest tests.test_library_view -v
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
import json, sys, time
sys.path.insert(0, "scripts")
import agent_api, library
out = {}
cos = library.table("Companies", columns="Name:text")
cos.add({"Name": "Northwind"}, key="northwind")
jobs = library.table("Job openings", columns="Title:text, Status:status(New|Interesting|Applied|Rejected), "
                     "Salary:number, Remote:checkbox, Company:relation(Companies)")
jobs.add({"Title": "Μηχανικός DevOps στην Αθήνα", "Status": "Applied", "Salary": 20000, "Company": "northwind"}, key="1")
jobs.add({"Title": "Junior DevOps", "Status": "New", "Salary": 15000, "Remote": True}, key="2")
jobs.add({"Title": "Barista", "Status": "Rejected"}, key="3")
jobs.add({"Title": "Old one"}, key="4")
jobs.archive("4")

titles = lambda page: [r["cells"]["Title"] for r in page["rows"]]
out["newest"] = titles(jobs.query())
out["unicode"] = titles(jobs.query(search="Αθήνα"))
out["words"] = titles(jobs.query(search="junior devops"))
out["status_sort"] = titles(jobs.query(sort="Status"))
out["status_desc"] = titles(jobs.query(sort="status", desc=True))
out["salary_sort"] = titles(jobs.query(sort="Salary"))  # empty last
out["where"] = titles(jobs.query(where={"status": "applied"}))
out["remote"] = titles(jobs.query(where={"Remote": "yes"}))
out["empty"] = titles(jobs.query(where={"Salary": ""}))
out["archived"] = titles(jobs.query(archived=True))
full = jobs.query()
out["sums"] = full["sums"]
out["related"] = list(full["related"].values())
out["page"] = [titles(jobs.query(limit=2)), titles(jobs.query(limit=2, offset=2)), jobs.query(limit=2)["total"]]
try:
    jobs.query(sort="Nope")
except library.LibraryError as e:
    out["bad_sort"] = str(e)

api = agent_api.library_table("Job openings", {"q": ["devops"], "sort": ["Salary"], "dir": ["desc"], "where.Status": ["New"]})
out["api"] = [api["total"], titles(api), api["table"]["name"], [c["name"] for c in api["columns"]]]
try:
    agent_api.library_table("Job openings", {"limit": ["many"]})
except agent_api.ApiError as e:
    out["api_bad"] = e.status

big = library.table("Big", columns="Title:text, Status:status(A|B|C), N:number")
with library.connect():
    pass
t0 = time.time()
for i in range(20000):
    big.add({"Title": f"Row {i}", "Status": "ABC"[i % 3], "N": i})
out["write"] = time.time() - t0
t0 = time.time()
page = big.query(search="row 1999", sort="N", desc=True, limit=100)
deep = big.query(where={"Status": "B"}, sort="Status", offset=6000, limit=100)
out["read"] = time.time() - t0
out["big"] = [page["total"], page["rows"][0]["cells"]["Title"], deep["total"], len(deep["rows"]), big.query()["sums"]["N"]]
print(json.dumps(out, ensure_ascii=False))
"""


class LibraryViewTest(unittest.TestCase):
    def test_query(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(out["newest"], ["Barista", "Junior DevOps", "Μηχανικός DevOps στην Αθήνα"])
        self.assertEqual(out["unicode"], ["Μηχανικός DevOps στην Αθήνα"])
        self.assertEqual(out["words"], ["Junior DevOps"])
        self.assertEqual(out["status_sort"], ["Junior DevOps", "Μηχανικός DevOps στην Αθήνα", "Barista"])  # the labels' order
        self.assertEqual(out["status_desc"], ["Barista", "Μηχανικός DevOps στην Αθήνα", "Junior DevOps"])
        self.assertEqual(out["salary_sort"], ["Junior DevOps", "Μηχανικός DevOps στην Αθήνα", "Barista"])
        self.assertEqual(out["where"], ["Μηχανικός DevOps στην Αθήνα"])
        self.assertEqual(out["remote"], ["Junior DevOps"])
        self.assertEqual(out["empty"], ["Barista"])
        self.assertEqual(out["archived"], ["Old one"])
        self.assertEqual(out["sums"], {"Salary": 35000.0})
        self.assertEqual(out["related"], ["Northwind"])
        self.assertEqual(out["page"], [["Barista", "Junior DevOps"], ["Μηχανικός DevOps στην Αθήνα"], 3])
        self.assertIn("no column Nope", out["bad_sort"])
        self.assertEqual(out["api"], [1, ["Junior DevOps"], "Job openings", ["Title", "Status", "Salary", "Remote", "Company"]])
        self.assertEqual(out["api_bad"], 400)
        total, first, deep_total, deep_rows, n_sum = out["big"]
        self.assertEqual((total, first, deep_total, deep_rows), (12, "Row 19999", 6667, 100))  # 1999, 1999x and 11999
        self.assertEqual(n_sum, sum(range(20000)))
        self.assertLess(out["read"], 3)


if __name__ == "__main__":
    unittest.main()
