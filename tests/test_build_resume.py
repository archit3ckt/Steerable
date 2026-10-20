"""Later attempts of a build go on in the build's own conversation (agent.run resume=), in their new
worktree, and start afresh when that conversation is gone. A fake `claude` stands in for the AI.

    python3 -m unittest tests.test_build_resume -v
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
schema = json.loads(args[args.index("--json-schema") + 1]) if "--json-schema" in args else {}
resume = args[args.index("--resume") + 1] if "--resume" in args else None
add_dirs = [args[i + 1] for i, a in enumerate(args) if a == "--add-dir"]
allowed = args[args.index("--allowedTools") + 1:] if "--allowedTools" in args else []
props = schema.get("properties", {})
kind = "build" if "needs_connection" in props else "review" if "fixes" in props else "other"
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"kind": kind, "prompt": prompt, "resume": resume, "add_dirs": add_dirs,
                        "allowed": " ".join(allowed), "budget": args[args.index("--max-budget-usd") + 1]}) + "\n")
if resume and resume != "s-ok":
    print(json.dumps({"type": "result", "is_error": True, "result": "No conversation found with session ID"}))
    sys.exit(1)
if kind == "build":
    wt = add_dirs[0]
    open(os.path.join(wt, "workflows/count_new.py"), "w").write(os.environ["FAKE_ROUTINE"])
    open(os.path.join(wt, "workflows/count_new.flow.json"), "w").write(json.dumps({"steps": [
        {"kind": "trigger", "label": "Every day"}, {"kind": "check", "label": "Count new things"}]}))
    subprocess.run(["git", "-C", wt, "add", "workflows/"], check=True)
    subprocess.run(["git", "-C", wt, "commit", "-qm", "Build count_new", "--allow-empty"], check=True)
    out = {"status": "built", "summary": "Counts new things every day.", "needs": "", "needs_connection": "",
           "test_output": "Checked 0 new things"}
elif kind == "review":
    count = os.environ["FAKE_LOG"] + ".reviews"
    n = int(open(count).read()) if os.path.exists(count) else 0
    open(count, "w").write(str(n + 1))
    out = {"summary": "Counts new things.", "fixes": ["Say so when there's nothing new."] if n == 0 else [], "concerns": []}
else:
    out = {}
print(json.dumps({"type": "result", "structured_output": out, "total_cost_usd": 0.1, "num_turns": 5,
                  "session_id": os.environ.get("FAKE_SESSION", "s-ok")}))
"""

ROUTINE = '''"""Count new things."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from common import step

step(1)
print("Checked 0 new things")
'''

# Builds one attempt after another in this process (the background Popen of each next attempt is
# caught and run here instead), until nothing new starts.
BUILD = r"""
import json, subprocess, sys
import builder
started = []
real_popen = subprocess.Popen
def popen(cmd, *a, **k):
    if str(cmd[1]).endswith("builder.py") and cmd[2] == "build":
        return started.append(cmd[3])
    return real_popen(cmd, *a, **k)
builder.subprocess.Popen = popen
first = builder.start_build("count_new", "Count new things  @workflow:count_new  every:daily")
while started:
    builder.build(started.pop(0))
print(json.dumps({"first": first, "builds": builder.load()}))
"""


class BuildResumeTest(unittest.TestCase):
    def setUp(self):
        self.co = Company(fake_claude=FAKE_CLAUDE)
        (self.co.root / "tasks.md").write_text(
            "# Tasks\n\n## Open\n- [ ] Count new things  @workflow:count_new  every:daily  approved\n")

    def tearDown(self):
        self.co.close()

    def build(self, session: str) -> dict:
        return self.co.py(BUILD, timeout=300, FAKE_ROUTINE=ROUTINE, FAKE_SESSION=session)

    def test_review_fixes_continue_the_same_session(self):
        out = self.build("s-ok")
        builds = sorted(out["builds"].values(), key=lambda b: b["opened"] + b["id"])
        self.assertEqual(len(builds), 2)
        fix = next(b for b in builds if b["id"] != out["first"])
        self.assertEqual(fix["prev"], out["first"])
        self.assertEqual(fix["resume"], "s-ok")
        self.assertEqual(fix["status"], "ready")
        calls = [c for c in self.co.calls() if c["kind"] == "build"]
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[0]["resume"])
        self.assertIn("Build it as workflows/", calls[0]["prompt"])
        self.assertEqual(calls[1]["resume"], "s-ok")
        self.assertIn("now in a\nnew worktree", calls[1]["prompt"])
        self.assertIn("Say so when there's nothing new.", calls[1]["prompt"])
        self.assertNotIn("Build it as workflows/", calls[1]["prompt"])

    def test_resumed_attempt_gets_the_new_worktree(self):
        out = self.build("s-ok")
        fix = next(b for b in out["builds"].values() if b["id"] != out["first"])
        call = [c for c in self.co.calls() if c["kind"] == "build"][1]
        self.assertTrue(call["add_dirs"][0].endswith("/" + fix["id"]), call["add_dirs"])
        self.assertIn(call["add_dirs"][0], call["prompt"])
        self.assertIn(f"Edit(/{call['add_dirs'][0]}/**)", call["allowed"])

    def test_resume_falls_back_when_session_is_gone(self):
        out = self.build("s-gone")
        fix = next(b for b in out["builds"].values() if b["id"] != out["first"])
        self.assertEqual(fix["status"], "ready")
        calls = [c for c in self.co.calls() if c["kind"] == "build"]
        self.assertEqual([c["resume"] for c in calls], [None, "s-gone", None])
        self.assertIn("Build it as workflows/", calls[2]["prompt"])
        self.assertIn("Say so when there's nothing new.", calls[2]["prompt"])  # the fixes still come along
        self.assertAlmostEqual(fix["cost_usd"], 0.1)  # the failed resume cost nothing here; the fresh start is counted
        self.assertEqual(fix["turns"], 5)


if __name__ == "__main__":
    unittest.main()
