"""A failed build is retried only when a retry can help (builder._triage, Jev first through decide):
a passing problem is tried again with what went wrong, something only the owner can give becomes
their decision, something impossible stops and is reported once, a used-up budget waits for next
month. Here decide runs on keyword rules, and a fake `claude` fails the build as told.

    python3 -m unittest tests.test_build_triage -v
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"prompt": args[args.index("-p") + 1]}) + "\n")
out = {"status": "failed", "summary": os.environ["FAKE_SUMMARY"], "needs": "", "needs_connection": "",
       "test_output": os.environ.get("FAKE_OUTPUT", "")}
print(json.dumps({"type": "result", "structured_output": out, "total_cost_usd": 0.1, "num_turns": 3, "session_id": "s1"}))
"""

# Start a build and run it here; then retry_failed at `now`, catching what it would start in the background.
FAIL_THEN_RETRY = r"""
import json, subprocess, sys
from datetime import datetime, timedelta, timezone
import builder, burst
reported = []
burst.report_problem = lambda *a, **k: reported.append(a)
started = []
real_popen = subprocess.Popen
def popen(cmd, *a, **k):
    if str(cmd[1]).endswith("builder.py") and cmd[2] == "build":
        return started.append(cmd[3])
    return real_popen(cmd, *a, **k)
builder.subprocess.Popen = popen
first = builder.start_build("count_new", "Count new things  @workflow:count_new  every:daily")
builder.build(started.pop(0))
b = builder.load()[first]
retried = builder.retry_failed(now=datetime.now(timezone.utc) + timedelta(hours=2))
prompt = builder._prompt(builder.load()[retried[0]], "/wt") if retried else ""
print(json.dumps({"first": b, "retried": retried, "prompt": prompt, "reported": len(reported)}))
"""


class BuildTriageTest(unittest.TestCase):
    def setUp(self):
        self.co = Company(fake_claude=FAKE_CLAUDE)
        (self.co.root / "tasks.md").write_text(
            "# Tasks\n\n## Open\n- [ ] Count new things  @workflow:count_new  every:daily  approved\n")

    def tearDown(self):
        self.co.close()

    def fail(self, summary: str, output: str = "") -> dict:
        return self.co.py(FAIL_THEN_RETRY, timeout=300, FAKE_SUMMARY=summary, FAKE_OUTPUT=output)

    def test_passing_problem_is_retried_with_its_failure(self):
        out = self.fail("The test didn't finish.", "requests.exceptions.ReadTimeout: timeout after 30s")
        self.assertEqual(out["first"]["status"], "failed")
        self.assertEqual(out["first"]["triage"], "retry")
        self.assertEqual(len(out["retried"]), 1)
        self.assertIn("ReadTimeout", out["prompt"])  # the next attempt knows what went wrong

    def test_needs_owner_is_not_retried(self):
        out = self.fail("It has to log in to the supplier portal to see the orders.")
        self.assertEqual(out["first"]["status"], "needs_owner")
        self.assertEqual(out["first"]["triage"], "owner")
        self.assertIn("supplier portal", out["first"]["needs"])
        self.assertEqual(out["retried"], [])

    def test_impossible_is_reported_once(self):
        out = self.fail("The shop's terms say automated orders are not allowed.")
        self.assertEqual(out["first"]["status"], "failed")
        self.assertEqual(out["first"]["triage"], "stop")
        self.assertEqual(out["retried"], [])
        self.assertEqual(out["reported"], 1)

    def test_budget_waits_for_next_month(self):
        self.co.builds({"bx": {"id": "bx", "workflow": "count_new", "task": "Count new things  @workflow:count_new  every:daily",
                               "title": "Count new things", "status": "failed", "wait_month": True, "triage": "retry",
                               "opened": "2026-10-05T08:00:00+00:00", "finished": "2026-10-05T08:00:00+00:00"}})
        code = r"""
import json, subprocess
from datetime import datetime, timezone
import builder
builder.subprocess.Popen = lambda *a, **k: None
same = builder.retry_failed(now=datetime(2026, 10, 30, tzinfo=timezone.utc))
later = builder.retry_failed(now=datetime(2026, 11, 1, 0, 30, tzinfo=timezone.utc))
print(json.dumps({"same": same, "later": later}))
"""
        out = self.co.py(code)
        self.assertEqual(out["same"], [])
        self.assertEqual(len(out["later"]), 1)

    def test_used_up_budget_marks_the_build(self):
        code = r"""
import json, subprocess
import builder
from budget import BudgetExceeded
def over():
    raise BudgetExceeded("over")
builder.check = over
builder.subprocess.Popen = lambda *a, **k: None
bid = builder.start_build("count_new", "Count new things  @workflow:count_new  every:daily")
builder.build(bid)
print(json.dumps(builder.load()[bid]))
"""
        b = self.co.py(code)
        self.assertEqual(b["status"], "failed")
        self.assertTrue(b["wait_month"])

    def test_triage_falls_back_to_retry_when_deciding_fails(self):
        code = r"""
import json
import builder, decide
def broken(*a, **k):
    raise RuntimeError("no backend")
decide.decide = broken
print(json.dumps(builder._triage({"workflow": "x"}, {"summary": "It has to log in."}, "")))
"""
        self.assertEqual(self.co.py(code), "retry")

    def test_unclear_failure_defaults_to_retry(self):
        out = self.fail("Something odd happened.")
        self.assertEqual(out["first"]["triage"], "retry")
        self.assertEqual(len(out["retried"]), 1)


if __name__ == "__main__":
    unittest.main()
