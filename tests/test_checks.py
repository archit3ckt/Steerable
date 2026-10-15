"""Testing a proposal before the owner acts on it (scripts/checks.py): Jev offers a test under replies
that propose something (always under a saved plan, never under short answers), the test is one AI call
held to its rules (concrete moments, two voices where it takes two, edits only for findings that stand),
a finished test isn't run twice, and the owner's picks become a new version of the plan. Jev and the AI
are stubbed.

    python3 -m unittest tests.test_checks -v
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
import json, os, sys, time
sys.path.insert(0, "scripts")
import agent_api, bridge, checks, decide, plans, supervise
out = {}
LONG = "Here's how I'd lay out your landing page. " + "Lead with the result, then proof, then the price. " * 10

# Jev picks the test; "none" for a reply that doesn't propose anything.
jev_said = {"choice": "customers", "confidence": 0.9}
decide._jev_target = lambda: ("http://jev", "key")
def fake_jev(question, options, context, target=None):
    out.setdefault("jev_calls", 0)
    out["jev_calls"] += 1
    return decide.Decision(jev_said["choice"], jev_said["confidence"], "jev")
decide._jev = fake_jev

def turn(reply, saves=lambda: None):
    def fake(text, channel, live=None, run=None):
        os.environ["STEERABLE_RUN"] = run
        try:
            saves()
        finally:
            os.environ.pop("STEERABLE_RUN", None)
        return reply
    return fake

bridge.ask_claude = turn("Sure, done.")
bridge.converse("Thanks", channel=bridge.APP)
out["short"] = (agent_api.chat()[-1].get("artifacts"), out.get("jev_calls", 0))   # short answer: Jev not even asked

bridge.ask_claude = turn(LONG)
bridge.converse("How should I lay out my landing page?", channel=bridge.APP)
out["long"] = agent_api.chat()[-1]["artifacts"]["check"]

jev_said["choice"] = "none"
bridge.converse("And what about the status?", channel=bridge.APP)
out["none"] = agent_api.chat()[-1].get("artifacts")

bridge.converse("Again, from Telegram", channel="Telegram")
out["telegram"] = agent_api.chat()[-1].get("artifacts")

# A saved plan is always offered one: Jev unsure, so by the plan's kind.
jev_said.update(choice="customers", confidence=0.2)
PLAN = "# Marketing plan\n\nHeadline: Fresh plants for busy cafes.\n\nPrice: $49 a month.\n\nChannels: Instagram.\n"
def fake_jev_unsure(question, options, context, target=None):
    raise decide.Uncertain(decide.Decision("customers", 0.2, "jev"))
decide._jev = fake_jev_unsure
bridge.ask_claude = turn("Saved your marketing plan.", lambda: plans.save("Marketing plan", PLAN, "First draft"))
bridge.converse("Write my marketing plan", channel=bridge.APP)
msg = agent_api.chat()[-1]
out["plan_offer"] = msg["artifacts"]["check"]

# The test: one call, held to its rules.
asked = []
def fake_ask(prompt, images, schema, source, cap_usd="0.30", max_tokens=1500):
    asked.append(prompt)
    return {"summary": "Mostly holds; say what's included in the price.",
            "voices": [{"who": "Dana", "went": "Read the headline.", "stuck": "Price"},
                       {"who": "Sam", "went": "Skimmed.", "stuck": "Price"},
                       {"who": "Lee", "went": "Liked it.", "stuck": ""}],
            "findings": [{"id": "f1", "moment": "At the price", "problem": "Not clear what $49 covers",
                          "voices": ["Dana", "Sam"], "fix": "Say what's included"},
                         {"id": "f2", "moment": "The headline", "problem": "Only Lee minded", "voices": ["Lee"], "fix": "x"},
                         {"id": "f3", "moment": "", "problem": "Vague doubt", "voices": ["Dana", "Sam"], "fix": "y"}],
            "held": ["The headline"],
            "edits": [{"finding": "f1", "find": "Price: $49 a month.", "replace": "Price: $49 a month, plants and care included.", "why": "Say what's included"},
                      {"finding": "f2", "find": "Headline: Fresh plants for busy cafes.", "replace": "Headline: other", "why": "one voice"},
                      {"finding": "f1", "find": "Not in the plan", "replace": "z", "why": "doesn't fit"}]}
supervise._ask = fake_ask
started = agent_api.start_check(msg["id"], {})
out["started"] = started["status"]
for _ in range(100):
    if checks.view(msg["id"])["status"] != "running":
        break
    time.sleep(0.05)
done = checks.view(msg["id"])
out["done"] = {"status": done["status"], "kind": done["kind"], "title": done["title"],
               "findings": [f["id"] for f in done["result"]["findings"]],
               "edits": [(e["id"], e["applies"]) for e in done["result"]["edits"]],
               "changed": done["planChanged"]}
out["prompt_has_plan"] = "Price: $49 a month." in asked[0] and "<business_notes>" in asked[0]
again = agent_api.start_check(msg["id"], {})
out["again_calls"] = (again["status"], len(asked))   # a finished test isn't run twice

applied = agent_api._checks(checks.apply, msg["id"], ["e1", "e3"])
out["applied"] = (applied["applied"], applied["skipped"], "plants and care included" in plans.body(applied["plan"]),
                  plans.versions(applied["plan"])[0]["who"])
out["after_apply_changed"] = checks.view(msg["id"])["planChanged"]
try:
    agent_api._checks(checks.apply, msg["id"], ["e1"])
except agent_api.ApiError as e:
    out["reapply"] = str(e)

# A reply without a plan: the test runs on the reply; there's no plan to change.
jev_said.update(choice="pushback", confidence=0.9)
decide._jev = fake_jev
bridge.ask_claude = turn(LONG)
bridge.converse("Should I raise prices?", channel=bridge.APP)
m2 = agent_api.chat()[-1]
agent_api.start_check(m2["id"], {"kind": "pushback"})
for _ in range(100):
    if checks.view(m2["id"])["status"] != "running":
        break
    time.sleep(0.05)
out["reply_test"] = checks.view(m2["id"])["status"]
try:
    agent_api._checks(checks.apply, m2["id"], ["e1"])
except agent_api.ApiError as e:
    out["no_plan"] = str(e)
try:
    agent_api.start_check(m2["id"], {"kind": "bogus"})
except agent_api.ApiError as e:
    out["bad_kind"] = str(e)
try:
    agent_api.start_check("abcdef123456", {})
except agent_api.ApiError as e:
    out["missing"] = e.status
print(json.dumps(out))
"""


class ChecksTest(unittest.TestCase):
    def test_offer_run_and_apply(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\nCOO_NAME=Juno\n")
            (root / "memory" / "company.md").write_text("# Leafy\n\nPlants for cafes. Customers: busy cafe owners.\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp)},
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)

            self.assertEqual(out["short"], [None, 0])
            self.assertEqual(out["long"], {"kind": "customers"})
            self.assertIsNone(out["none"])
            self.assertIsNone(out["telegram"])
            self.assertEqual(out["plan_offer"], {"kind": "customers"})  # a marketing plan: customers go through it

            self.assertEqual(out["started"], "running")
            d = out["done"]
            self.assertEqual((d["status"], d["kind"], d["title"]), ("done", "customers", "Marketing plan"))
            self.assertEqual(d["findings"], ["f1"])  # one voice, or no moment: dropped
            self.assertEqual(d["edits"], [["e1", True], ["e3", False]])  # e2's finding was dropped
            self.assertFalse(d["changed"])
            self.assertTrue(out["prompt_has_plan"])
            self.assertEqual(out["again_calls"], ["done", 1])

            self.assertEqual(out["applied"], [["e1"], ["e3"], True, "you"])
            self.assertFalse(out["after_apply_changed"])
            self.assertIn("don't fit", out["reapply"])
            self.assertEqual(out["reply_test"], "done")
            self.assertIn("no plan", out["no_plan"])
            self.assertIn("Which test", out["bad_kind"])
            self.assertEqual(out["missing"], 404)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
