"""The COO finding things in a big library (scripts/library.py `search` and `find`): every table at
once, word matches, filters, a date range, sorting, pages, and always the total, so a partial page
is never mistaken for everything.

    python3 -m unittest tests.test_library_search -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"

FILL = r"""
import sys
sys.path.insert(0, "scripts")
import library
leads = library.table("Leads", "Name:text, Company:text, City:text, Status:status(New|Won|Lost), Notes:longtext, Found:date, Value:number")
orders = library.table("Orders", "Customer:text, Amount:number, Date:date")
library.table("Suppliers", "Name:text, Phone:text", "Who we buy pots from")
for i in range(600):
    leads.add({"Name": f"Person {i}", "Company": "Riverside Roasters" if i % 50 == 0 else f"Cafe {i}", "City": "Delft" if i % 2 == 0 else "Gouda",
               "Status": ["New", "Won", "Lost"][i % 3], "Notes": "Late delivery, unhappy" if i % 200 == 0 else "liked the ferns",
               "Found": f"2026-{1 + i % 10:02d}-15", "Value": i}, key=f"l{i}")
for i in range(40):
    orders.add({"Customer": "Riverside Roasters" if i % 10 == 0 else f"Cafe {i}", "Amount": 10 * i, "Date": f"2026-{1 + i % 10:02d}-02"})
"""


class LibrarySearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "co"
        shutil.copytree(TEMPLATE, cls.root)
        (cls.root / ".env").write_text("COMPANY_NAME=Co\n")
        out = subprocess.run([sys.executable, "-c", FILL], cwd=cls.root, capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def lib(self, *args) -> list[str]:
        out = subprocess.run([sys.executable, "scripts/library.py", *args], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip().splitlines()

    def test_search_every_table(self):
        lines = self.lib("search", "riverside ROASTERS", "--limit", "2")
        self.assertIn("## Leads: 12 rows, showing 2", lines)  # the total, though only 2 are shown
        self.assertIn("## Orders: 4 rows, showing 2", lines)
        self.assertLess(lines.index("## Leads: 12 rows, showing 2"), lines.index("## Orders: 4 rows, showing 2"))  # most first
        rows = [json.loads(x) for x in lines if x.startswith("{")]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all("Riverside Roasters" in (r.get("Company"), r.get("Customer")) for r in rows))
        self.assertNotIn("Notes", {k for r in rows for k, v in r.items() if v in ("", None)})  # empty values left out
        # Words anywhere in a row's text, any case; a table whose description matches is named.
        self.assertIn("## Leads: 3 rows", self.lib("search", "late delivery"))
        self.assertIn("## Suppliers (its name matches; no row contains the words)", self.lib("search", "pots"))
        self.assertIn("Nothing in the library contains", self.lib("search", "unicorn")[0])
        self.assertEqual(self.lib("search", "riverside", "--table", "orders")[0], "## Orders: 4 rows")

    def test_find_filters_sort_dates_pages(self):
        lines = self.lib("find", "Leads", "--where", "Status=Won", "City=Delft", "--sort", "Value", "--desc", "--limit", "3")
        self.assertEqual(lines[0], "100 rows match; showing 1-3 (next: --offset 3).")
        self.assertTrue(lines[1].startswith("Totals: "))
        values = [json.loads(x)["Value"] for x in lines[2:]]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(values[0], 598)
        page = self.lib("find", "Leads", "--where", "Status=Won", "City=Delft", "--sort", "Value", "--desc", "--limit", "3", "--offset", "3")
        self.assertEqual(page[0], "100 rows match; showing 4-6 (next: --offset 6).")
        self.assertLess(json.loads(page[2])["Value"], values[-1])
        dated = self.lib("find", "Orders", "--between", "Date", "2026-03-01", "2026-03-31")
        self.assertEqual(dated[0], "4 rows match.")
        self.assertTrue(all(json.loads(x)["Date"].startswith("2026-03") for x in dated[2:]))
        self.assertEqual(self.lib("find", "Leads", "--search", "unhappy")[0], "3 rows match.")
        self.assertEqual(self.lib("find", "Leads", "--where", "Status=Paid"), ["No rows match."])


if __name__ == "__main__":
    unittest.main()
