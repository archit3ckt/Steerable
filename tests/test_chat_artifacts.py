"""A chat reply carries what the turn made or changed in the library ("artifacts"): the plans it
saved, at the version it saved, and its row changes per table. They point at the Library's own
plans and tables. Claude is stubbed: the turn saves a plan and adds a row, as the chat would through
plans.py and library.py.

    python3 -m unittest tests.test_chat_artifacts -v
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
import json, os, sys
sys.path.insert(0, "scripts")
import agent_api, bridge, library, plans
out = {}

def turn(saves):
    def fake(text, channel, live=None, run=None):
        os.environ["STEERABLE_RUN"] = run  # what Claude Code passes on to the scripts it runs
        try:
            saves()
        finally:
            os.environ.pop("STEERABLE_RUN", None)
        return "Done."
    return fake

plans.save("Marketing plan", "# Marketing plan\n\nGoal: 10 cafes.\n", "First draft")  # before the chat: not this turn's
def both():
    plans.save("Business plan", "# Business plan\n\nPlants for cafes.\n", "First draft")
    plans.save("Marketing plan", "# Marketing plan\n\nGoal: 12 cafes.\n", "Raised the goal")
    plans.save("Marketing plan", "# Marketing plan\n\nGoal: 12 cafes by December.\n", "Added a date")
    library.table("Leads", "Name:text").add({"Name": "Riverside Roasters"}, key="riverside")
bridge.ask_claude = turn(both)
bridge.converse("Write the business plan and update the marketing one", channel="Dashboard")
out["first"] = agent_api.chat()[-1].get("artifacts")
bridge.ask_claude = turn(lambda: None)
bridge.converse("Thanks", channel="Dashboard")
out["second"] = agent_api.chat()[-1].get("artifacts")
print(json.dumps(out))
"""


class ChatArtifactsTest(unittest.TestCase):
    def test_a_reply_carries_what_it_saved(self):
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
            first = out["first"]
            self.assertTrue(first["run"])
            self.assertEqual([(p["title"], p["version"], p["note"], p["created"]) for p in first["plans"]],
                             [("Business plan", 1, "First draft", True), ("Marketing plan", 3, "Added a date", False)])
            self.assertEqual([(c["table"], c.get("added")) for c in first["changes"]], [("Leads", 1)])
            self.assertIsNone(out["second"])  # a reply that changed nothing has none
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
