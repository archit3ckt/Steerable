"""The business's plans (scripts/plans.py): one per subject, updated instead of duplicated, every
version kept with who and why, what each version changed, and restoring an earlier one.

    python3 -m unittest tests.test_plans -v
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
sys.path.insert(0, "scripts")
import agent_api, plans
out = {}
V1 = "# Marketing plan\n\nGoal: 10 new cafes.\n\n## Channels\n- Instagram\n- Visits\n\n## Budget\n$300\n"
V2 = V1.replace("10 new cafes", "12 new cafes").replace("- Visits\n", "- Visits\n- Tasting mornings\n")
a = plans.save("Marketing plan", V1, "First draft")
b = plans.save("Q4 Marketing Plan 2026", V2, "Raised the goal")          # the same subject: a new version
c = plans.save("Marketing plan", V2, "same again")                       # nothing changed
out["ids"] = [a["plan"]["id"], b["plan"]["id"], c["plan"]["id"]]
out["created"] = [a["created"], b["created"], c["created"], c["changed"]]
try:
    plans.save("Marketing plan", "# Marketing plan\n\nShort.\n", "oops")
    out["short"] = "saved"
except plans.PlanError as e:
    out["short"] = str(e)
other = plans.save("Business plan", "# Business plan\n\nPlants for cafes.\n", "First draft")
separate = plans.save("Marketing plan for the online shop", V1, "Its own plan", different=True)
out["list"] = [(p["title"], p["kind"], p["version"]) for p in plans.plans()]
pid = a["plan"]["id"]
v2 = plans.version(pid, 2)
out["v2"] = {"note": v2["note"], "who": v2["who"], "changes": [(x["op"], x.get("text", x.get("count"))) for x in v2["changes"]]}
out["v1_first"] = sorted({x["op"] for x in plans.version(pid, 1)["changes"]})

# The owner, through the dashboard's API: edits (shorter is fine when they write it), restores.
api = agent_api.edit_plan(pid, {"body": "# Marketing plan\n\nJust Instagram.\n", "note": "Simpler"})
out["edited"] = (api["version"], api["updatedBy"], plans.body(pid))
restored = agent_api.restore_plan(pid, {"version": 2})
out["restored"] = (restored["version"], plans.body(pid) == V2, plans.versions(pid)[0]["restoredFrom"])
detail = agent_api.plan_detail(pid)
out["detail"] = (detail["version"], len(detail["versions"]), detail["versions"][0]["who"])
try:
    agent_api.restore_plan(pid, {"version": detail["version"]})
except agent_api.ApiError as e:
    out["restore_current"] = str(e)
agent_api._plans(plans.remove, other["plan"]["id"])
out["after_remove"] = [p["title"] for p in plans.plans()]
try:
    agent_api.plan_detail(other["plan"]["id"])
except agent_api.ApiError as e:
    out["removed_detail"] = e.status
out["timeline"] = [e["title"] for e in agent_api.timeline()][:3]
print(json.dumps(out))
"""


class PlansTest(unittest.TestCase):
    def test_plans(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\nCOO_NAME=Juno\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp)},
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)

            # One plan per subject: "Q4 Marketing Plan 2026" updated "Marketing plan"; an identical save did nothing.
            self.assertEqual(len(set(out["ids"])), 1)
            self.assertEqual(out["created"], [True, False, False, False])
            self.assertIn("less than half", out["short"])
            self.assertEqual(sorted(out["list"]), sorted([["Marketing plan", "marketing", 2], ["Business plan", "business", 1],
                                                          ["Marketing plan for the online shop", "marketing", 1]]))
            # What version 2 changed, with the untouched part folded.
            self.assertEqual(out["v2"]["note"], "Raised the goal")
            self.assertEqual(out["v2"]["who"], "coo")
            changes = out["v2"]["changes"]
            self.assertIn(["del", "Goal: 10 new cafes."], changes)
            self.assertIn(["add", "Goal: 12 new cafes."], changes)
            self.assertIn(["add", "- Tasting mornings"], changes)
            self.assertIn("skip", [op for op, _ in changes])
            self.assertEqual(out["v1_first"], ["add"])
            # The owner's edit, then back to version 2 as a new version; nothing lost.
            self.assertEqual(out["edited"], [3, "you", "# Marketing plan\n\nJust Instagram.\n"])
            self.assertEqual(out["restored"], [4, True, 2])
            self.assertEqual(out["detail"], [4, 4, "you"])
            self.assertIn("already the current version", out["restore_current"])
            self.assertNotIn("Business plan", out["after_remove"])
            self.assertEqual(out["removed_detail"], 404)
            self.assertTrue(any("back to version 2" in t for t in out["timeline"]), out["timeline"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
