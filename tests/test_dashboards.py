"""Dashboards over the library (scripts/dashboards.py): widgets checked against their tables, counted
in SQL (numbers with this period vs the last, bars by a column, trends, top rows, progress), one
dashboard per name, the owner's edits, requests to the COO, and the COO's command line.

    python3 -m unittest tests.test_dashboards -v
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
from datetime import date
sys.path.insert(0, "scripts")
import agent_api, dashboards, library
out = {}
TODAY = date(2026, 10, 15)  # a Thursday
leads = library.table("Leads", columns="Name:text, Status:status(New|Contacted|Won|Lost), Value:number($), "
                      "Next step:date, Sample:checkbox, Tags:tags")
for name, status, value, day, sample, tags in [
        ("Northside Bakery", "New", 800, "2026-10-14", False, ["Cafe"]),
        ("Harbor Dental", "Contacted", 1200, "2026-10-02", True, ["Office"]),
        ("Luna 2", "Won", 950, "2026-10-12", True, ["Cafe", "Repeat"]),
        ("Riverside Gym", "Lost", 400, "2026-09-20", False, []),
        ("Corner Shop", "New", None, "2026-09-03", False, ["Cafe"])]:
    leads.add({"Name": name, "Status": status, "Value": value, "Next step": day, "Sample": sample, "Tags": tags})

W = [
    {"type": "number", "title": "Leads", "table": "Leads"},
    {"type": "number", "table": "Leads", "date": "Next step", "period": "month"},
    {"type": "number", "table": "leads", "measure": "sum", "column": "Value", "where": {"Status": "Won"}},
    {"type": "bars", "table": "Leads", "by": "Status"},
    {"type": "bars", "table": "Leads", "by": "Tags", "measure": "sum", "column": "Value"},
    {"type": "bars", "table": "Leads", "by": "Sample"},
    {"type": "trend", "table": "Leads", "date": "Next step", "every": "week", "last": 4},
    {"type": "list", "table": "Leads", "sort": "Value", "dir": "desc", "limit": 2, "show": ["Name", "Value"]},
    {"type": "progress", "table": "Leads", "where": {"Status": "Won"}, "goal": 4},
    {"type": "number", "table": "Leads", "where": {"Value": ""}},
]
a = dashboards.save("Sales", W, "How sales are going")
b = dashboards.save("sales", W[:3], "Fewer")                 # the same name: updated, not a second one
out["created"] = [a["created"], b["created"], a["dashboard"]["id"] == b["dashboard"]["id"]]
did = a["dashboard"]["id"]
dashboards.save("Sales", W)
d = dashboards.detail(did, TODAY)
out["titles"] = [w["title"] for w in d["widgets"]]
out["data"] = [w.get("data") or w.get("error") for w in d["widgets"]]
out["wide"] = [bool(w.get("wide")) for w in d["widgets"]]
out["tableName"] = d["widgets"][0]["tableName"]

def refused(*args, **kw):
    try:
        dashboards.save(*args, **kw)
        return "saved"
    except dashboards.DashboardError as e:
        return str(e)
out["errors"] = [
    refused("X", [{"type": "pie", "table": "Leads"}]),
    refused("X", [{"type": "number", "table": "Nope"}]),
    refused("X", [{"type": "bars", "table": "Leads", "by": "Value"}]),
    refused("X", [{"type": "number", "table": "Leads", "measure": "sum", "column": "Name"}]),
    refused("X", [{"type": "progress", "table": "Leads"}]),
    refused("X", [{"type": "number", "table": "Leads", "where": {"Colour": "red"}}]),
]
out["no_x"] = dashboards.find("X") is None

# The owner, through the API: an empty one, a chart added, changed, moved and removed, renamed.
api = agent_api._dash(dashboards.create, "Jobs", "", "you")
try:
    agent_api._dash(dashboards.create, "jobs", "", "you")
except agent_api.ApiError as e:
    out["taken"] = (e.status, str(e))
w1 = agent_api.dashboard_widget(api["id"], {"widget": {"type": "number", "table": "Leads"}})
w2 = agent_api.dashboard_widget(api["id"], {"widget": {"type": "bars", "table": "Leads", "by": "Status"}})
agent_api.dashboard_widget(api["id"], {"widget": {"type": "number", "table": "Leads", "title": "All leads"}}, w1["id"])
agent_api._dash(dashboards.change_widget, api["id"], w2["id"], "up", "you")
detail = agent_api.dashboard_detail(api["id"])
out["edited"] = [(w["id"] == w2["id"], w["title"]) for w in detail["widgets"]]
out["sources"] = [(s["name"], [c["name"] for c in s["columns"]][:3]) for s in detail["sources"]]
agent_api._dash(dashboards.change_widget, api["id"], w1["id"], "remove", "you")
renamed = agent_api.dashboard_edit(api["id"], {"name": "Job search"})
out["after"] = (renamed["name"], renamed["widgets"], renamed["updatedBy"])
try:
    agent_api.dashboard_detail("db00000000")
except agent_api.ApiError as e:
    out["missing"] = e.status

# A column that goes away breaks only its own chart.
with library.connect() as con:
    con.execute("DELETE FROM columns WHERE name = 'Tags'")
out["broken"] = [w.get("error", "") for w in dashboards.detail(did, TODAY)["widgets"]][4]
out["others_fine"] = "data" in dashboards.detail(did, TODAY)["widgets"][3]

# Requests to the COO: recorded, answered with the dashboard it saved, listed for the page.
ask = dashboards.ask("Leads per week", None)
out["asked"] = [x["status"] for x in dashboards.asks()]
dashboards.save("Leads per week", [{"type": "trend", "table": "Leads"}])
dashboards.answered(ask["id"], "It shows leads added each week.")
got = dashboards.asks()[0]
out["answered"] = (got["status"], got["reply"], got["made"] == dashboards.find("Leads per week")["id"])
out["prompt"] = "dashboards.py sources" in dashboards.ask_prompt(ask)
try:
    dashboards.ask("", None)
except dashboards.DashboardError as e:
    out["empty_ask"] = str(e)
agent_api._dash(dashboards.remove, api["id"])
out["listed"] = sorted(x["name"] for x in dashboards.dashboards())
print(json.dumps(out))
"""


class DashboardsTest(unittest.TestCase):
    def test_dashboards(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\nCOO_NAME=Juno\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp)}
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)

            self.assertEqual(out["created"], [True, False, True])
            self.assertEqual(out["tableName"], "Leads")
            self.assertEqual(out["titles"][:4], ["Leads", "Leads this month", "Sum of Value", "Leads by Status"])
            data = out["data"]
            self.assertEqual(data[0], {"value": 5})
            # This month (October) vs September, by the Next step date.
            self.assertEqual(data[1], {"value": 3, "previous": 2})
            self.assertEqual(data[2], {"unit": "$", "value": 950.0})
            # Bars: a status in its labels' order; tags counted per tag; a checkbox as Yes/No, with filters for the grid.
            self.assertEqual([[i["label"], i["value"], i["filter"]] for i in data[3]["items"]],
                             [["New", 2, "New"], ["Contacted", 1, "Contacted"], ["Won", 1, "Won"], ["Lost", 1, "Lost"]])
            self.assertEqual([[i["label"], i["value"]] for i in data[4]["items"]], [["Cafe", 1750.0], ["Office", 1200.0], ["Repeat", 950.0]])
            self.assertEqual([[i["label"], i["value"], i["filter"]] for i in data[5]["items"]], [["Yes", 2, "true"], ["No", 3, "false"]])
            # Four weeks ending this one (Monday starts), empty weeks as 0.
            self.assertEqual([[p["start"], p["value"]] for p in data[6]["points"]],
                             [["2026-09-21", 0], ["2026-09-28", 1], ["2026-10-05", 0], ["2026-10-12", 2]])
            self.assertEqual([r["cells"]["Name"] for r in data[7]["rows"]], ["Harbor Dental", "Luna 2"])
            self.assertEqual(data[7]["total"], 5)
            self.assertEqual(data[7]["columns"], [{"name": "Name", "type": "text"}, {"name": "Value", "type": "number", "unit": "$"}])
            self.assertEqual(data[8], {"value": 1, "goal": 4})
            self.assertEqual(data[9], {"value": 1})  # "" = an empty cell, like a view's filter
            self.assertEqual(out["wide"], [False, False, False, False, False, False, True, True, False, False])

            errors = out["errors"]
            self.assertIn("type is one of", errors[0])
            self.assertIn("no table called Nope", errors[1])
            self.assertIn("Value can't be the one the bars are by", errors[2])
            self.assertIn("Name can't be", errors[3])
            self.assertIn("goal above zero", errors[4])
            self.assertIn("no column Colour", errors[5])
            self.assertTrue(errors[0].startswith("Widget 1: "))
            self.assertTrue(out["no_x"])

            self.assertEqual(out["taken"][0], 400)
            self.assertIn("already a dashboard called jobs", out["taken"][1])
            self.assertEqual(out["edited"], [[True, "Leads by Status"], [False, "All leads"]])
            self.assertEqual(out["sources"], [["Leads", ["Name", "Status", "Value"]]])
            self.assertEqual(out["after"], ["Job search", 1, "you"])
            self.assertEqual(out["missing"], 404)

            self.assertIn("no column Tags", out["broken"])
            self.assertTrue(out["others_fine"])

            self.assertEqual(out["asked"], ["asked"])
            self.assertEqual(out["answered"], ["answered", "It shows leads added each week.", True])
            self.assertTrue(out["prompt"])
            self.assertIn("Say what you'd like to see", out["empty_ask"])
            self.assertEqual(out["listed"], ["Leads per week", "Sales"])

            # The COO's command line: tables and columns, save from a file, show what it shows.
            (root / "drafts").mkdir(exist_ok=True)
            (root / "drafts" / "d.json").write_text(json.dumps({"description": "Weekly", "widgets": [
                {"type": "number", "table": "Leads", "title": "Leads"}, {"type": "bars", "table": "Leads", "by": "Status"}]}))
            run = lambda *a: subprocess.run([sys.executable, "scripts/dashboards.py", *a], cwd=root, env=env,
                                            capture_output=True, text=True, timeout=60)
            src = run("sources")
            self.assertIn("Status (status: New|Contacted|Won|Lost)", src.stdout)
            saved = run("save", "Weekly", "--from", "drafts/d.json")
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertIn("Made the dashboard “Weekly”", saved.stdout)
            self.assertIn("- Leads: 5", saved.stdout)
            self.assertIn("New: 2, Contacted: 1", saved.stdout)
            shown = run("show", "weekly")
            self.assertIn('"table": "Leads"', shown.stdout)
            bad = run("save", "Weekly", "--from", "../outside.json")
            self.assertEqual(bad.returncode, 1)
            self.assertIn("in the company folder", bad.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
