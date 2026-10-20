"""A failed build is the system's, never the owner's (builder._triage, Jev first through decide): it's
tried again with what went wrong, or, when it can't be built this way, stopped and reported once until
a new engine; a used-up budget waits for next month. Nothing of it reaches the owner's Decisions. Here
decide runs on keyword rules, and a fake `claude` fails the build as told.

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
import agent_api
asks = [d["id"] for d in agent_api.decisions() if d["id"].startswith("build:")]
print(json.dumps({"first": b, "retried": retried, "prompt": prompt, "reported": len(reported), "asks": asks}))
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

    def test_failures_never_reach_the_owner(self):
        # Even when its words sound like the owner's business: what only they can give, a build asks
        # for itself (status needs_owner); a failure is the system's to sort out.
        for summary in ("It has to log in to the supplier portal to see the orders.",
                        "Couldn't connect to the shop's server."):
            with self.subTest(summary=summary):
                out = self.fail(summary)
                self.assertEqual(out["first"]["status"], "failed")
                self.assertEqual(out["first"]["triage"], "retry")
                self.assertEqual(out["asks"], [])
                self.assertEqual(len(out["retried"]), 1)
                self.co.builds({})

    def test_impossible_is_reported_once(self):
        out = self.fail("The shop's terms say automated orders are not allowed.")
        self.assertEqual(out["first"]["status"], "failed")
        self.assertEqual(out["first"]["triage"], "stop")
        self.assertEqual(out["retried"], [])
        self.assertEqual(out["reported"], 1)
        self.assertEqual(out["asks"], [])
        # A new engine may well fix it: then it gets a fresh round.
        (self.co.tmp / "VERSION").write_text("newer")
        code = r"""
import json, subprocess
from datetime import datetime, timedelta, timezone
import builder
real_popen = subprocess.Popen
builder.subprocess.Popen = lambda cmd, *a, **k: None if str(cmd[1]).endswith("builder.py") else real_popen(cmd, *a, **k)
print(json.dumps(builder.retry_failed(now=datetime.now(timezone.utc) + timedelta(hours=2))))
"""
        self.assertEqual(len(self.co.py(code, STEERABLE_VERSION_FILE=str(self.co.tmp / "VERSION"))), 1)

    def test_budget_waits_for_next_month(self):
        self.co.builds({"bx": {"id": "bx", "workflow": "count_new", "task": "Count new things  @workflow:count_new  every:daily",
                               "title": "Count new things", "status": "failed", "wait_month": True, "triage": "retry",
                               "opened": "2026-10-05T08:00:00+00:00", "finished": "2026-10-05T08:00:00+00:00"}})
        code = r"""
import json, subprocess
from datetime import datetime, timezone
import builder
real_popen = subprocess.Popen
builder.subprocess.Popen = lambda cmd, *a, **k: None if str(cmd[1]).endswith("builder.py") else real_popen(cmd, *a, **k)
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
real_popen = subprocess.Popen
builder.subprocess.Popen = lambda cmd, *a, **k: None if str(cmd[1]).endswith("builder.py") else real_popen(cmd, *a, **k)
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
