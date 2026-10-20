"""Common routines start from code we wrote and tested (scripts/catalog/, catalog.py): an approved
task that matches one, confidently, is adapted from it at a lower cap; anything else gets a full
build. And every routine in the catalog meets the engine's standards.

    python3 -m unittest tests.test_catalog -v
"""
import ast
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import TEMPLATE, Company  # noqa: E402

sys.path.insert(0, str(TEMPLATE / "scripts"))

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"prompt": args[args.index("-p") + 1], "budget": args[args.index("--max-budget-usd") + 1],
                        "add_dirs": [args[i + 1] for i, a in enumerate(args) if a == "--add-dir"]}) + "\n")
out = {"status": "needs_owner", "summary": "Waiting for you.", "needs": "Which day?", "needs_connection": "", "test_output": ""}
print(json.dumps({"type": "result", "structured_output": out, "total_cost_usd": 0.1, "num_turns": 3, "session_id": "s1"}))
"""

DEMO_ROUTINE = '''"""Remind clients about overdue invoices."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from common import step

SETTINGS = {"DAYS_OVERDUE": 7}

step(1)
print("Would remind 0 clients")
'''

# Build with decide answering as told (choice, confidence), keeping the worktree to look at.
BUILD = r"""
import json, os, subprocess
import builder, decide
choice, confidence = os.environ["PICK"].split(":")
decide.decide = lambda q, o, context="", **k: decide.Decision(choice, float(confidence), "jev")
real_popen = subprocess.Popen
builder.subprocess.Popen = lambda cmd, *a, **k: None if str(cmd[1]).endswith("builder.py") else real_popen(cmd, *a, **k)
builder._cleanup = lambda *a, **k: None
task = "Remind clients about overdue invoices  @workflow:remind  every:weekly"
if os.environ.get("RETRY"):  # a later attempt of a build that started from the catalog
    bid = builder._open("remind", task, exists=False, catalog="demo", failure="It timed out.")
else:
    bid = builder.start_build("remind", task)
builder.build(bid)
wt = builder.WORKTREES / bid
log = builder.git("-C", str(wt), "log", "--format=%s") if wt.exists() else ""
print(json.dumps({"build": builder.load()[bid], "log": log,
                  "installed": (wt / "workflows/remind.py").read_text() if (wt / "workflows/remind.py").exists() else ""}))
"""


class CatalogRoutingTest(unittest.TestCase):
    def setUp(self):
        self.co = Company(fake_claude=FAKE_CLAUDE)
        demo = self.co.root / "scripts/catalog/demo"
        demo.mkdir(parents=True)
        (demo / "routine.py").write_text(DEMO_ROUTINE)
        (demo / "routine.flow.json").write_text(json.dumps({"steps": [
            {"kind": "trigger", "label": "Every Monday"}, {"kind": "check", "label": "Find overdue invoices"}]}))
        (demo / "about.json").write_text(json.dumps({
            "title": "Overdue invoice reminders", "description": "Remind clients about invoices past their due date",
            "services": ["stripe"], "settings": {"DAYS_OVERDUE": "how many days past due before a reminder"}}))
        (self.co.root / "tasks.md").write_text(
            "# Tasks\n\n## Open\n- [ ] Remind clients about overdue invoices  @workflow:remind  every:weekly  approved\n")
        self.co.home.joinpath(".steerable-worktrees").mkdir()

    def tearDown(self):
        self.co.close()

    def test_matching_task_starts_from_the_catalog(self):
        out = self.co.py(BUILD, timeout=300, PICK="demo:0.9")
        self.assertEqual(out["build"]["catalog"], "demo")
        self.assertIn("Start remind from demo", out["log"])
        self.assertIn('SETTINGS = {"DAYS_OVERDUE": 7}', out["installed"])
        call = self.co.calls()[0]
        self.assertEqual(call["budget"], "0.75")
        self.assertIn("Overdue invoice reminders", call["prompt"])
        self.assertIn("DAYS_OVERDUE: how many days past due", call["prompt"])
        self.assertNotIn("Build it as workflows/", call["prompt"])

    def full_build(self, pick: str) -> None:
        out = self.co.py(BUILD, timeout=300, PICK=pick)
        self.assertNotIn("catalog", out["build"])
        call = self.co.calls()[0]
        self.assertEqual(call["budget"], "2.00")
        self.assertIn("Build it as workflows/", call["prompt"])

    def test_low_confidence_or_none_goes_to_a_full_build(self):
        self.full_build("demo:0.6")

    def test_none_goes_to_a_full_build(self):
        self.full_build("none:0.95")

    def test_a_retry_starts_from_the_same_routine(self):
        out = self.co.py(BUILD, timeout=300, PICK="none:0.99", RETRY="1")  # not asked again: it has its routine
        self.assertEqual(out["build"]["catalog"], "demo")
        self.assertIn("Start remind from demo", out["log"])
        call = self.co.calls()[0]
        self.assertEqual(call["budget"], "0.75")
        self.assertIn("It timed out.", call["prompt"])


class CatalogStandardTest(unittest.TestCase):
    def test_every_catalog_routine_meets_the_standard(self):
        import flow
        import routine_check

        entries = [d for d in sorted((TEMPLATE / "scripts/catalog").iterdir()) if d.is_dir() and not d.name.startswith("_")]
        for d in entries:
            with self.subTest(entry=d.name):
                about = json.loads((d / "about.json").read_text())
                self.assertEqual(set(about), {"title", "description", "services", "settings"})
                steps = flow.valid(json.loads((d / "routine.flow.json").read_text()))
                self.assertTrue(steps)
                self.assertEqual(routine_check.check_source((d / "routine.py").read_text(), len(steps) - 1), [])
                tree = ast.parse((d / "routine.py").read_text())
                settings = next(ast.literal_eval(n.value) for n in tree.body
                                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SETTINGS")
                self.assertEqual(set(settings), set(about["settings"]))


if __name__ == "__main__":
    unittest.main()
