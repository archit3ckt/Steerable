"""Names the owner reads on cards: a routine's title without its goal note (even when the goal has
brackets), short routine names from propose.py, and a plan's first real sentence for its card.

    python3 -m unittest tests.test_titles -v
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
line = ("- [ ] Find Reddit leads each morning (goal: 10 conversations by 2026-11-05 (Test 1); metric: new qualified "
        "leads per week)  @workflow:reddit_lead_scan  every:daily  approved")
t = agent_api.parse_task(line)
out = {"title": t["title"], "goal": t["goal"],
       "summaries": [plans.summary("# Marketing plan\n\n_Version 3, 2026-10-15_\n\nGoal: **12 new** cafes by [December](x).\n"),
                     plans.summary("# Plan\n\n*Last updated Oct 2026*\n\n---\n\n- Win back quiet cafes\n")]}
print(json.dumps(out))
"""


class TitlesTest(unittest.TestCase):
    def test_titles(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\nCOO_NAME=Juno\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp)}
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["title"], "Find Reddit leads each morning")
            self.assertEqual(out["goal"], "10 conversations by 2026-11-05 (Test 1)")
            self.assertEqual(out["summaries"], ["Goal: 12 new cafes by December.", "Win back quiet cafes"])

            propose = lambda *a: subprocess.run([sys.executable, "scripts/propose.py", *a, "--workflow", "reddit_leads", "--saves", "1"],
                                                cwd=root, env=env, capture_output=True, text=True, timeout=60)
            long = propose("Each morning, find new Reddit posts from solo consultants and coaches struggling with follow-ups")
            self.assertEqual(long.returncode, 1)
            self.assertIn("short name, up to 80 characters", long.stderr + long.stdout)
            brackets = propose("Find Reddit leads", "--goal", "10 chats (Test 1)")
            self.assertEqual(brackets.returncode, 1)
            self.assertIn("without brackets", brackets.stderr + brackets.stdout)
            self.assertEqual(propose("Find Reddit leads each morning", "--goal", "10 chats").returncode, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
