"""A whole library table can be archived and brought back (library.archive_table / restore_table, agent API
POST /v1/library/tables/<id>/archive|restore, GET /v1/library?archived=1). Nothing is deleted: an archived
table leaves the Library and its search, a routine that still writes to it keeps writing there (it stays
archived), and an import never lands in it by sharing its name.

    python3 -m unittest tests.test_library_archive -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402

SCRIPT = r"""
import json, re
import agent_api, library, library_io
def route(method, path, q, b):  # as the server matches them
    for verb, pattern, fn in agent_api.ROUTES:
        if verb == method and (m := re.fullmatch(pattern, path)):
            return fn(q, b, **m.groupdict())
    raise AssertionError(f"no route for {method} {path}")
leads = library.table("Leads", columns="Name:text, Stage:status(New|Won)")
leads.add({"Name": "Acme"}, key="acme")
library.table("Orders", columns="Item:text").add({"Item": "Cake"})
names = lambda tables: [t["name"] for t in tables]
out = {}
library.archive_table(leads.id)
out["active"] = names(library.tables())
out["archived"] = names(library.tables(archived=True))
out["search"] = [r["table"] for r in library.search("acme")]
out["api_archived"] = names(route("GET", "/v1/library", {"archived": ["1"]}, {}))
# a routine that still keeps its records there: no crash, no second table, still archived
again = library.table("Leads", columns="Name:text, Stage:status(New|Won), Note:text")
again.add({"Name": "Beta"}, key="beta")
out["after_routine"] = [names(library.tables()), names(library.tables(archived=True)), again.id == leads.id, again.count()]
# an import named like it gets a name of its own
got = library_io.import_sheet("Leads.csv", b"Name\nGamma\n")
out["import"] = got["table"]["name"]
try:
    route("POST", f"/v1/library/tables/{leads.id}/archive", {}, {})
    out["twice"] = "no error"
except agent_api.ApiError as e:
    out["twice"] = e.message
route("POST", f"/v1/library/tables/{leads.id}/restore", {}, {})
out["restored"] = [names(library.tables()), names(library.tables(archived=True)), library.table("Leads").count()]
out["history"] = [h["what"] for h in library.table("Leads").history(limit=20)]
try:
    library.archive_table("Nope")
except library.LibraryError as e:
    out["missing"] = str(e)
print(json.dumps(out))
"""


class LibraryArchiveTest(unittest.TestCase):
    def setUp(self):
        self.co = Company()

    def tearDown(self):
        self.co.close()

    def test_archive_and_bring_back_a_table(self):
        out = self.co.py(SCRIPT)
        self.assertEqual(out["active"], ["Orders"])
        self.assertEqual(out["archived"], ["Leads"])
        self.assertEqual(out["search"], [])  # its rows aren't found while it's archived
        self.assertEqual(out["api_archived"], ["Leads"])
        self.assertEqual(out["after_routine"], [["Orders"], ["Leads"], True, 2])
        self.assertEqual(out["import"], "Leads (2)")
        self.assertEqual(out["twice"], "That table is already archived.")
        self.assertEqual(sorted(out["restored"][0]), ["Leads", "Leads (2)", "Orders"])
        self.assertEqual(out["restored"][1:], [[], 2])
        self.assertIn("Brought the table back", out["history"])
        self.assertIn("Archived the table", out["history"])
        self.assertEqual(out["missing"], "There's no table called Nope.")


if __name__ == "__main__":
    unittest.main()
