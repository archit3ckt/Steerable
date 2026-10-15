"""Keeping the Goals page current (scripts/ops_db.py): the COO moves missions and goals from the
chat, and a cheap check after each chat turn (decide(): Jev, then Haiku) marks a project done when
the conversation clearly says it is. decide() is stubbed here.

    python3 -m unittest tests.test_board -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"

SEED = {"goals": [{"Goal": "Launch Steerable", "Priority": "P0", "Status": "Active", "Metric": "steps done", "Target": "5", "Current": "1"}],
        "missions": [{"Mission": "Make the code public on GitHub with a clear README", "Goal": "Launch Steerable", "Owner": "CEO", "Status": "Todo",
                      "Definition of done": "Public repo with README explaining what Steerable does in plain words"},
                     {"Mission": "Post on Show HN", "Goal": "Launch Steerable", "Owner": "CEO", "Status": "Todo"},
                     {"Mission": "Post on X", "Goal": "Launch Steerable", "Owner": "COO", "Status": "Todo"}]}

SCRIPT = r"""
import json, sys
sys.path.insert(0, "scripts")
import decide, ops_db, agent_api
out = {}
answers = iter(json.loads(sys.argv[1]))
seen = []
def fake(question, options, context="", rules=None, use_cache=True):
    seen.append(sorted(options))
    choice, confidence, backend = next(answers)
    if choice.startswith("@"):  # the mission with this title
        choice = next(k for k, v in options.items() if v.startswith(choice[1:]))
    return decide.Decision(choice, confidence, backend)
decide.decide = fake

def status(title):
    return next(p["status"] for g in agent_api.goals() for p in g["projects"] if p["title"] == title)

# The Jev check: unsure, then "none", then the keyword fallback: nothing changes.
out["unsure"] = ops_db.notice_done("I think I'll publish the repo soon", "Great")
out["none"] = ops_db.notice_done("How's the weather", "Sunny")
out["rules"] = ops_db.notice_done("published it", "ok")
out["options"] = seen[0]
# Confident: done, with the owner's words.
out["marked"] = ops_db.notice_done("I made the repo public and the README is up", "Nice, that's the launch step done.")
out["status"] = status("Make the code public on GitHub with a clear README")
out["timeline"] = [e["title"] for e in agent_api.timeline()][:2]
# A done mission isn't offered again.
ops_db.notice_done("anything", "x")
out["options_after"] = seen[-1]
print(json.dumps(out))
"""


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root)
        (self.root / ".env").write_text("COMPANY_NAME=Co\n")
        (self.root / "memory/ops_seed.json").write_text(json.dumps(SEED))
        subprocess.run([sys.executable, "scripts/ops_db.py", "--seed"], cwd=self.root, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def board(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "scripts/ops_db.py", *args], cwd=self.root, capture_output=True, text=True, timeout=60)

    def test_commands(self):
        out = self.board("mission", "code public", "--status", "Done", "--outcome", "github.com/archit3ckt/steerable")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("is now Done", out.stdout)
        self.assertIn("Which mission?", self.board("mission", "post", "--status", "Done").stderr)  # two match: it asks
        self.assertIn("no mission like", self.board("mission", "unicorn", "--status", "Done").stderr)
        self.assertEqual(self.board("goal", "launch", "--current", "2").returncode, 0)
        self.assertIn("already a mission", self.board("add-mission", "Post on X", "--goal", "launch").stderr)
        self.assertEqual(self.board("add-mission", "Write the launch post", "--goal", "g1", "--done-when", "Posted").returncode, 0)
        shown = self.board("--show").stdout
        self.assertIn("Done           Make the code public", shown)
        self.assertIn("2 -> 5", shown)
        self.assertIn("Write the launch post", shown)

    def test_jev_notices_a_finished_project(self):
        answers = [["@Make the code public", 0.6, "jev"], ["none", 0.97, "jev"], ["@Make the code public", 0.99, "rules"],
                   ["@Make the code public", 0.93, "jev"], ["none", 0.9, "jev"]]
        out = subprocess.run([sys.executable, "-c", SCRIPT, json.dumps(answers)], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        self.assertEqual([got["unsure"], got["none"], got["rules"]], [None, None, None])
        self.assertEqual(got["options"], ["m1", "m2", "m3", "none"])
        self.assertEqual(got["marked"], "Make the code public on GitHub with a clear README")
        self.assertEqual(got["status"], "done")
        self.assertTrue(got["timeline"][0].startswith("Done: Make the code public"), got["timeline"])
        self.assertEqual(got["options_after"], ["m2", "m3", "none"])


if __name__ == "__main__":
    unittest.main()
