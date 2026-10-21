"""Decisions shown for what they are: a direction to choose (ask.py options with pros and cons, as cards),
and things the owner authorizes by signing (switching a routine on, letting it run on its own), as a
document with what it will do, its limits, what it won't do and how to undo it. What they signed is kept
in "Signed by you" (signed.py), and undoing it switches the routine off, or back under watch.

    python3 -m unittest tests.test_signing -v
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402

API = r"""
import json, re, sys
import agent_api
def route(method, path, body=None):
    for verb, pattern, fn in agent_api.ROUTES:
        if verb == method and (m := re.fullmatch(pattern, path)):
            return fn({}, body or {}, **m.groupdict())
    raise AssertionError(f"no route for {method} {path}")
"""


class SigningTest(unittest.TestCase):
    def setUp(self):
        self.co = Company()
        self.co.py("import json, ops_db; ops_db.connect(); print(json.dumps(1))")

    def tearDown(self):
        self.co.close()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.co.root, check=True, capture_output=True, env=self.co.env())

    def test_a_question_with_pros_and_cons_is_a_choice(self):
        proc = subprocess.run([sys.executable, "scripts/ask.py", "Where should Juno look for consultants?",
                               "--context", "For the first goal: talk to 20 of them.",
                               "--option", "reddit=Reddit communities", "--option", "both=Both, Reddit first",
                               "--pro", "reddit=No login needed", "--con", "reddit=Many are employees",
                               "--pro", "both=A fast start", "--tag", "both=Starts tomorrow",
                               "--recommend", "both", "--why", "Fast start, more names later."],
                              cwd=self.co.root, capture_output=True, text=True, env=self.co.env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.co.py(API + "print(json.dumps(route('GET', '/v1/decisions')))")
        d = next(d for d in out if d["id"].startswith("mission:"))
        self.assertEqual(d["display"], "choice")
        opts = {o["id"]: o for o in d["options"]}
        self.assertEqual(opts["reddit"]["pros"], ["No login needed"])
        self.assertEqual(opts["reddit"]["cons"], ["Many are employees"])
        self.assertEqual(opts["both"]["tags"], ["Starts tomorrow"])
        self.assertEqual(d["recommendation"]["optionId"], "both")

    def test_switching_on_is_signed_and_can_be_undone(self):
        (self.co.root / "tasks.md").write_text("# Tasks\n\n## Open\n- [ ] Nudge proposals  @workflow:nudges  every:weekdays  approved\n")
        self.git("add", "tasks.md")
        self.git("commit", "-qm", "task")
        self.git("checkout", "-qb", "build/nudges")
        (self.co.root / "workflows/nudges.py").write_text('print("Nudged 0 proposals")\n')
        self.git("add", "workflows/nudges.py")
        self.git("commit", "-qm", "Build nudges")
        self.git("checkout", "-q", "master")
        self.co.builds({"bready": {"id": "bready", "workflow": "nudges", "task": "Nudge proposals  @workflow:nudges  every:weekdays",
                                   "title": "Nudge proposals", "status": "ready", "opened": "2026-10-21T08:00:00+00:00",
                                   "review": {"summary": "Each weekday it nudges people who haven't answered a proposal.",
                                              "limits": ["At most 2 nudges per proposal"], "wont": ["It never attaches files"],
                                              "concerns": []}}})
        d = next(d for d in self.co.py(API + "print(json.dumps(route('GET', '/v1/decisions')))") if d["id"] == "build:bready")
        self.assertEqual(d["display"], "authorize")
        a = d["authorize"]
        self.assertEqual(a["title"], "Let “Nudge proposals” run")
        self.assertIn("Each weekday it nudges people who haven't answered a proposal.", a["does"])
        self.assertIn("At most 2 nudges per proposal.", a["limits"])
        self.assertEqual(a["wont"], ["It never attaches files."])
        self.assertEqual(a["optionId"], "switch_on")
        out = self.co.py(API + """
route('POST', '/v1/decisions/build:bready', {"optionId": "switch_on"})
signed = route('GET', '/v1/decisions/signed')
route('POST', f"/v1/decisions/signed/{signed[0]['id']}/undo")
print(json.dumps({"signed": signed, "after": route('GET', '/v1/decisions/signed'), "tasks": open('tasks.md').read()}))
""")
        self.assertEqual([(s["title"], s["kind"]) for s in out["signed"]], [("Let “Nudge proposals” run", "switch_on")])
        self.assertIn("undone", out["after"][0])
        self.assertIn("paused:owner", out["tasks"])  # switched off again

    def test_running_on_its_own_is_signed_and_undone_back_to_watching(self):
        (self.co.root / "tasks.md").write_text("# Tasks\n\n## Open\n- [ ] Weekly numbers  @workflow:weekly  every:weekly  approved\n")
        (self.co.root / "workflows/weekly.py").write_text('print("ok")\n')
        out = self.co.py(API + """
import supervise
with supervise._state() as s:
    s["weekly"] = {"since": "2026-10-01T08:00:00+00:00", "why": "new", "runs": 3, "clean": 3, "asked": True}
trust = next(d for d in route('GET', '/v1/decisions') if d["id"] == "trust:weekly")
route('POST', '/v1/decisions/trust:weekly', {"optionId": "trust"})
watching_after_sign = supervise.watching("weekly")
signed = route('GET', '/v1/decisions/signed')
route('POST', f"/v1/decisions/signed/{signed[0]['id']}/undo")
print(json.dumps({"trust": trust, "signed": signed, "watching_after_sign": watching_after_sign,
                  "watching_after_undo": supervise.watching("weekly")}))
""")
        self.assertEqual(out["trust"]["display"], "authorize")
        self.assertIn("3 times while watched", out["trust"]["authorize"]["record"])
        self.assertEqual(out["signed"][0]["kind"], "trust")
        self.assertFalse(out["watching_after_sign"])
        self.assertTrue(out["watching_after_undo"])


if __name__ == "__main__":
    unittest.main()
