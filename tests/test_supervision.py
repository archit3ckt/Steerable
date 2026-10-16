"""A new routine is seen before it's trusted: the practice run's trace and review (builder._practice,
runtrace.py), the owner switching it on from Decisions, watched runs where the supervisor checks
everything it can't undo (common.act, supervise.check), a hold the owner answers, and being asked to
let it run on its own after clean runs. A fake `claude` stands in for the AI.

    python3 -m unittest tests.test_supervision -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
schema = json.loads(args[args.index("--json-schema") + 1])
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(prompt) + "\n")
if "severity" in schema["properties"]:
    import subprocess
    wt = args[args.index("--add-dir") + 1]
    path = os.path.join(wt, "workflows", "apply_jobs.py")
    fixed = open(path).read().replace("raise SystemExit(3)\n", "")
    open(path, "w").write(fixed + "\n# fixed: skip a job when its page says it's closed\n")
    subprocess.run(["git", "-C", wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "Fix"], check=True)
    out = {"severity": "ceo", "summary": "It crashed on a closed job. I fixed it to skip closed jobs.", "root_cause": "x",
           "fix_ready": True, "fix_summary": "Skips jobs whose page says they're closed.", "recommendation": "Apply the fix.",
           "needs_connection": "", "actions": []}
elif "concerns" in schema["properties"]:
    out = {"summary": "It would apply to 1 job and skip 1 you already applied to.",
           "concerns": ["It doesn't check that a job is still open before applying."]}
else:
    about = prompt.split("What it's about to do")[1].split("What it did just before")[0]
    out = {"go": "HoldCo" not in about, "why": "That company's page says the job is closed." if "HoldCo" in about else "Looks right."}
print(json.dumps({"structured_output": out, "total_cost_usd": 0.01}))
"""

ROUTINE = r'''"""Apply to new jobs the owner would want."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import library
from budget import record
from common import act, log_run, step, tell_owner

JOBS = [("acme-1", "Data Analyst", "Acme"), ("beta-2", "BI Developer", "Beta"), ("hold-3", "Analyst", "HoldCo")]
skip = set(Path(__file__).with_name("skip.txt").read_text().split()) if Path(__file__).with_name("skip.txt").exists() else set()
apps = library.table("Applications", columns="Job:text, Company:text, Status:status(Applied|Check this)")
step(1)
done = 0
for key, title, company in JOBS:
    if key in skip:
        continue
    row = apps.get(key)
    if row and row["cells"].get("Status") == "Applied":
        print(f"Skipped {title}: already applied")
        continue
    if act(f"Send the application for {title} at {company}", {"job": key, "company": company}, kind="submit"):
        apps.add({"Job": title, "Company": company, "Status": "Applied"}, key=key)
        done += 1
log_run("apply_jobs", "checked", jobs=len(JOBS))
record("apply_jobs", 0.01, note="judging jobs")
tell_owner(f"Applied to {done} jobs")
print(f"Applied to {done} jobs")
'''

PRACTICE = r"""
import json, os, subprocess, sys
sys.path.insert(0, "scripts")
import builder, library, runtrace
apps = library.table("Applications", columns="Job:text, Company:text, Status:status(Applied|Check this)")
apps.add({"Job": "Data Analyst", "Company": "Acme", "Status": "Applied"}, key="acme-1")  # applied before
wt = builder.WORKTREES / "b1234abcd"
wt.parent.mkdir(parents=True, exist_ok=True)
builder.git("worktree", "add", "-q", str(wt), "-b", "build/apply_jobs", "HEAD")
for shared in (".env", ".venv"):
    os.symlink(builder.ROOT / shared, wt / shared)
(wt / "workflows/apply_jobs.py").write_text(open(".cache/routine.py").read())
import shutil; shutil.rmtree(wt / "logs", ignore_errors=True)  # a company repo may not track logs/ at all
(wt / "workflows/apply_jobs.flow.json").write_text(json.dumps({"steps": [
    {"kind": "trigger", "label": "Every 3 hours"}, {"kind": "send", "label": "Apply to new jobs"}]}))
builder.git("-C", str(wt), "add", "workflows/")
builder.git("-C", str(wt), "commit", "-q", "-m", "Build apply_jobs")
task = "Apply to jobs  @workflow:apply_jobs  every:3h"
with builder._state() as s:
    s["b1234abcd"] = {"id": "b1234abcd", "workflow": "apply_jobs", "task": task, "title": "Apply to jobs",
                      "status": "building", "opened": "2026-10-13T08:00:00+00:00"}
p = builder._practice("b1234abcd", builder.load()["b1234abcd"], wt)
builder._cleanup("b1234abcd", "apply_jobs", keep_branch=True)
builder.update("b1234abcd", status="ready", trace=p["trace"], review=p["review"], summary="Applies to jobs", finished="2026-10-13T08:05:00+00:00")
spent = [json.loads(l) for l in open("logs/spend.jsonl")] if os.path.exists("logs/spend.jsonl") else []
print(json.dumps({"practice": p, "trace": runtrace.load(p["trace"]), "rows": apps.count(), "spent": spent}))
"""

AUTO_FIX = r"""
import json, os, subprocess, sys
sys.path.insert(0, "scripts")
import builder
started = []
real_popen = subprocess.Popen
def popen(cmd, *a, **k):  # the next attempt isn't run here; everything else (git) is
    if "build" in cmd and str(cmd[1]).endswith("builder.py"):
        return started.append(cmd)
    return real_popen(cmd, *a, **k)
builder.subprocess.Popen = popen
wt = builder.WORKTREES / "b5678abcd"
wt.parent.mkdir(parents=True, exist_ok=True)
builder.git("worktree", "add", "-q", str(wt), "-b", "build/apply_jobs", "HEAD")
(wt / "workflows/apply_jobs.py").write_text(open(".cache/routine.py").read())
builder.git("-C", str(wt), "add", "workflows/")
builder.git("-C", str(wt), "commit", "-q", "-m", "Build apply_jobs")
task = "Apply to jobs  @workflow:apply_jobs  every:3h"
with builder._state() as s:
    s["b5678abcd"] = {"id": "b5678abcd", "workflow": "apply_jobs", "task": task, "title": "Apply to jobs",
                      "status": "building", "opened": "2026-10-13T08:00:00+00:00"}
review = {"summary": "Applies to jobs", "fixes": ["It reads no jobs when the board's page changes; stop and report instead."], "concerns": []}
builder._auto_fix("b5678abcd", builder.load()["b5678abcd"], {"trace": "p1"}, review, 0, 0.5)
builds = builder.load()
new = next(b for b in builds.values() if b["id"] != "b5678abcd")
branches = builder.git("branch", "--list", "build/*")
print(json.dumps({"old": builds["b5678abcd"]["status"], "new": {k: new.get(k) for k in ("status", "fixes", "rounds", "base")},
                  "branches": branches, "started": len(started), "prompt": builder._prompt(new, str(wt))}))
"""

API = r"""
import json, sys
sys.path.insert(0, "scripts")
import agent_api
cmd = json.loads(sys.argv[1])
out = {}
if cmd.get("decide"):
    try:
        out["decided"] = agent_api.decide(*cmd["decide"])
    except agent_api.ApiError as e:
        out["error"] = [e.status, str(e)]
out["decisions"] = agent_api.decisions()
if cmd.get("trace"):
    out["trace"] = agent_api.trace_view(cmd["trace"])
if cmd.get("routine"):
    out["routine"] = agent_api.routine_detail(cmd["routine"])
print(json.dumps(out, default=str))
"""

RUN = r"""
import json, sys
sys.path.insert(0, "scripts")
import heartbeat
line = next(l for l in open("tasks.md").read().splitlines() if "@workflow:apply_jobs" in l)
ok = heartbeat.run_routine(line, line[6:], "apply_jobs", "2026-10-13", manual=True)
print(json.dumps({"ok": ok}))
"""


class SupervisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root, ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / ".env").write_text("COMPANY_NAME=SuperviseCo\nMONTHLY_BUDGET_USD=20\n")
        (self.root / ".venv/bin").mkdir(parents=True)
        os.symlink(sys.executable, self.root / ".venv/bin/python")
        (self.root / "tasks.md").write_text("# Tasks\n\n## Open\n- [ ] Apply to jobs  @workflow:apply_jobs  every:3h  approved\n")
        (self.root / ".cache").mkdir(exist_ok=True)
        (self.root / ".cache/routine.py").write_text(ROUTINE)
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        (bin_ / "claude").write_text(FAKE_CLAUDE)
        (bin_ / "claude").chmod(0o755)
        self.log = self.tmp / "prompts.jsonl"
        self.env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "STEERABLE_GATEWAY_URL", "STEERABLE_JOBS_URL")}
        self.env.update(PATH=f"{bin_}:{os.environ['PATH']}", FAKE_LOG=str(self.log), HOME=str(self.tmp))
        git = lambda *a: subprocess.run(["git", *a], cwd=self.root, check=True, capture_output=True)  # noqa: E731
        git("init", "-q")
        git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "start")
        subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=self.root, check=True, capture_output=True, env=self.env)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def py(self, script: str, *args) -> dict:
        proc = subprocess.run([sys.executable, "-c", script, *args], cwd=self.root, capture_output=True, text=True,
                              timeout=120, env={**self.env, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def api(self, **cmd) -> dict:
        return self.py(API, json.dumps(cmd))

    def test_review_gaps_go_back_to_the_builder(self):
        # The owner hears the big picture only: what the review found is fixed in another attempt, unseen.
        out = self.py(AUTO_FIX)
        self.assertEqual(out["old"], "revised")
        self.assertEqual(out["new"], {"status": "building", "fixes": ["It reads no jobs when the board's page changes; stop and report instead."],
                                      "rounds": 1, "base": "build/apply_jobs-was"})
        self.assertIn("build/apply_jobs-was", out["branches"])
        self.assertEqual(out["started"], 1)
        self.assertIn("the owner never sees", out["prompt"])
        self.assertIn("stop and report instead", out["prompt"])
        decisions = self.api()["decisions"]
        self.assertFalse([d for d in decisions if d["id"].startswith("build:")])  # nothing for the owner yet

    def test_practice_switch_on_watch_hold_and_trust(self):
        # 1. Practice run: nothing done, everything noted, and reviewed.
        out = self.py(PRACTICE)
        self.assertTrue(out["practice"]["ok"], out["practice"]["output"])
        events = out["trace"]["events"]
        kinds = [e["kind"] for e in events]
        would = [e["what"] for e in events if e["kind"] == "would"]
        self.assertEqual(would, ["Send the application for BI Developer at Beta", "Send the application for Analyst at HoldCo"])
        self.assertIn("step", kinds)
        self.assertIn({"kind": "message", "text": "Applied to 0 jobs"}, [{k: e[k] for k in ("kind", "text")} for e in events if e["kind"] == "message"])
        self.assertEqual(out["rows"], 1)  # the practice run changed nothing
        self.assertEqual([[e["source"], e["cost_usd"]] for e in out["spent"] if e["source"] == "apply_jobs"], [["apply_jobs", 0.01]])
        self.assertEqual(out["practice"]["review"]["concerns"], ["It doesn't check that a job is still open before applying."])
        review_prompt = json.loads(self.log.read_text().splitlines()[-1])
        self.assertIn("Send the application for BI Developer at Beta", review_prompt)  # the reviewer saw the trace
        self.assertIn("act(", review_prompt)  # and the code
        # A build isn't merged yet: its own flow chart names the steps, and the review sees what it printed.
        self.assertIn("[step 1: Apply to new jobs]", review_prompt)
        self.assertIn("Applied to 0 jobs", review_prompt.split("What it printed at the end")[1])
        self.assertEqual(out["trace"]["steps"], ["Every 3 hours", "Apply to new jobs"])

        # 2. The owner sees it in Decisions, with the trace, before anything runs.
        tid = out["practice"]["trace"]
        res = self.api(trace=tid, routine="apply_jobs")
        self.assertEqual(res["routine"]["stage"], "ready")
        self.assertNotIn("record", res["routine"])
        d = next(d for d in res["decisions"] if d["id"] == "build:b1234abcd")
        self.assertEqual(d["trace"], tid)
        self.assertEqual(d["recommendation"]["optionId"], "")  # it has a concern: the owner chooses
        self.assertEqual([o["id"] for o in d["options"]], ["switch_on", "change", "drop"])
        self.assertEqual(d["concerns"], ["It doesn't check that a job is still open before applying."])
        self.assertEqual(d["facts"][0], {"label": "Would do", "value": "2 things it can't undo"})
        view = res["trace"]
        self.assertEqual(view["kind"], "practice")
        self.assertEqual([e["kind"] for e in view["events"] if e["kind"] != "step"], ["would", "would", "message"])
        self.assertEqual([e["title"] for e in view["events"] if e["kind"] == "step"], ["Apply to new jobs"])
        self.assertIn("Job: beta-2", view["events"][1]["detail"])
        self.assertFalse((self.root / "workflows/apply_jobs.py").exists())  # not switched on yet

        # "Change something" needs words.
        res = self.api(decide=["build:b1234abcd", "change", ""])
        self.assertEqual(res["error"][0], 400)

        # 3. Switch it on: merged, and watched from its first run.
        res = self.api(decide=["build:b1234abcd", "switch_on"])
        self.assertNotIn("error", res)
        self.assertTrue((self.root / "workflows/apply_jobs.py").exists())
        self.assertFalse(any(d["id"].startswith("build:") for d in res["decisions"]))
        self.assertTrue(json.loads((self.root / ".cache/supervision.json").read_text())["apply_jobs"])

        # 4. A watched run: Beta is checked and done, HoldCo held, Acme skipped by the routine itself.
        self.assertTrue(self.py(RUN)["ok"])
        rows = self.py("import json,sys; sys.path.insert(0,'scripts'); import library; "
                       "print(json.dumps(sorted(r['key'] for r in library.table('Applications').rows())))")
        self.assertEqual(rows, ["acme-1", "beta-2"])
        check_prompts = [json.loads(line) for line in self.log.read_text().splitlines() if "You supervise" in line]
        self.assertEqual(len(check_prompts), 2)
        res = self.api(routine="apply_jobs")
        self.assertEqual(res["routine"]["stage"], "watched")
        self.assertEqual(res["routine"]["watch"]["why"], "new")
        self.assertEqual({k: res["routine"]["record"][k] for k in ("runs", "problems", "held", "lastProblem", "onItsOwnSince")},
                         {"runs": 1, "problems": 0, "held": 1, "lastProblem": None, "onItsOwnSince": None})
        run = res["routine"]["runs"][0]
        self.assertTrue(run["trace"])
        self.assertTrue(res["routine"]["watching"])
        self.assertEqual(res["routine"]["watch"]["runs"], 1)
        hold = next(d for d in res["decisions"] if d["id"].startswith("watch:"))
        self.assertEqual(hold["title"], "I held back 1 thing in “Apply to jobs”")
        self.assertEqual(hold["concerns"], ["Send the application for Analyst at HoldCo: That company's page says the job is closed."])
        trace = self.api(trace=hold["trace"])["trace"]
        self.assertEqual([e["kind"] for e in trace["events"] if e["kind"] in ("did", "held")], ["did", "held"])

        # The owner says it was fine: remembered for the next checks.
        res = self.api(decide=[hold["id"], "fine", "It reopened"])
        self.assertFalse(any(d["id"].startswith("watch:") for d in res["decisions"]))
        notes = json.loads((self.root / ".cache/supervision.json").read_text())["apply_jobs"]["notes"]
        self.assertIn("It reopened", notes[0])

        # 5. Three clean runs in a row: asked whether it can run on its own.
        (self.root / "workflows/skip.txt").write_text("hold-3")
        for _ in range(3):
            self.assertTrue(self.py(RUN)["ok"])
        res = self.api()
        trust = next(d for d in res["decisions"] if d["id"] == "trust:apply_jobs")
        self.assertIn("4 times while watched, the last 3", trust["context"])
        self.py("import json, os, sys; sys.path.insert(0, 'scripts'); os.environ['STEERABLE_WORKFLOW'] = 'apply_jobs'; "
                "import supervise; print(json.dumps(supervise.check('Send the application for X at Acme', 'submit', {'company': 'Acme'}, None)))")
        last_check = [json.loads(line) for line in self.log.read_text().splitlines() if "You supervise" in line][-1]
        self.assertIn("The owner said it was fine: It reopened", last_check)  # what they said reaches later checks
        self.assertIn("Applications: ", last_check)  # and the records that mention it (Acme, applied before)
        res = self.api(decide=["trust:apply_jobs", "trust"])
        self.assertFalse(any(d["id"].startswith("trust:") for d in res["decisions"]))
        self.assertNotIn("apply_jobs", json.loads((self.root / ".cache/supervision.json").read_text()))
        res = self.api(routine="apply_jobs")
        self.assertNotIn("watching", res["routine"])
        self.assertEqual(res["routine"]["stage"], "trusted")
        self.assertTrue(res["routine"]["record"]["onItsOwnSince"])

        # 6. A problem puts it back under watch, and the fix is tried in a practice run before the owner is asked.
        (self.root / "workflows/skip.txt").unlink()
        broken = (self.root / "workflows/apply_jobs.py").read_text().replace("step(1)", "step(1)\nraise SystemExit(3)")
        (self.root / "workflows/apply_jobs.py").write_text(broken)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "break it"], cwd=self.root, check=True)
        self.assertFalse(self.py(RUN)["ok"])
        res = self.api(routine="apply_jobs")
        self.assertEqual((res["routine"]["stage"], res["routine"]["watch"]["why"]), ("watched", "problem"))
        self.assertEqual(res["routine"]["status"], "paused")
        iid = json.loads(next(line for line in reversed((self.root / "logs/runs.jsonl").read_text().splitlines())
                              if '"opened"' in line and "incident" in line))["incident"]
        for _ in range(120):  # the investigation runs in the background
            if json.loads((self.root / ".cache/incidents.json").read_text())[iid]["status"] != "investigating":
                break
            time.sleep(0.5)
        res = self.api()
        fix = next(d for d in res["decisions"] if d["id"] == f"incident:{iid}")
        self.assertTrue(fix["trace"].startswith("f"))  # the fixed version's practice run
        self.assertEqual(fix["concerns"], ["It doesn't check that a job is still open before applying."])
        self.assertIn("Its next runs are watched", fix["options"][0]["outcome"])
        practice = self.api(trace=fix["trace"])["trace"]
        self.assertEqual(practice["kind"], "practice")
        self.assertTrue(practice["ok"])
        # Applying it: the fixed version runs, still watched (the count of clean runs starts again).
        res = self.api(decide=[fix["id"], "apply"], routine="apply_jobs")
        self.assertNotIn("error", res)
        self.assertIn("# fixed", (self.root / "workflows/apply_jobs.py").read_text())
        self.assertEqual((res["routine"]["stage"], res["routine"]["status"], res["routine"]["watch"]["clean"]), ("watched", "running", 0))

    def test_a_build_sees_the_owners_website_logins(self):
        """Logins the owner saved (live, or from the extension) are there when a build tests its routine."""
        script = r"""
import json, sys
sys.path.insert(0, "scripts")
import builder, sites, subprocess
sites._save("yad2.co.il", "Yad2", "https://www.yad2.co.il/", {"cookies": [], "origins": []}, source="browser")
wt = builder.WORKTREES / "bsites"
wt.parent.mkdir(parents=True, exist_ok=True)
builder.git("worktree", "add", "-q", str(wt), "-b", "build/x", "HEAD")
builder.link_shared(wt)
found = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import sites; "
                        "print(bool(sites.find('www.yad2.co.il')))"], cwd=wt, capture_output=True, text=True)
print(json.dumps([found.stdout.strip(), found.stderr[-300:]]))
"""
        self.assertEqual(self.py(script)[0], "True")

    def test_practice_runs_let_the_login_stay_alive(self):
        """A practice run blocks everything but reads, except the site renewing the owner's login."""
        script = r"""
import json, sys
sys.path.insert(0, "scripts")
import browser
k = lambda url: browser.keeps_login(url, "www.yad2.co.il")
print(json.dumps([k("https://gw.yad2.co.il/auth/token/refresh"), k("https://www.yad2.co.il/api/session/keepalive"),
                  k("https://accounts.google.com/token/refresh"), k("https://gw.yad2.co.il/auth/logout"),
                  k("https://gw.yad2.co.il/session/submit"), k("https://www.yad2.co.il/ad/publish"),
                  k("https://www.yad2.co.il/collect")]))
"""
        self.assertEqual(self.py(script), [True, True, False, False, False, False, False])

    def test_act_outside_practice_and_watch(self):
        """A trusted routine's act() just says yes and keeps no trace; a dry run without a trace says no."""
        script = ("import json, os, sys; sys.path.insert(0, 'scripts'); import common; "
                  "a = common.act('Send it'); os.environ['STEERABLE_DRY_RUN'] = '1'; b = common.act('Send it'); "
                  "print(json.dumps([a, b, os.path.exists('.cache/traces')]))")
        self.assertEqual(self.py(script), [True, False, False])

    def test_guard_holds_unasked_changes_in_a_watched_run(self):
        script = r"""
import json, os, sys
sys.path.insert(0, "scripts")
import common, runtrace
runtrace.start("r1", workflow="apply_jobs", kind="watched")
os.environ.update(STEERABLE_WATCH="1", STEERABLE_TRACE="r1", STEERABLE_WORKFLOW="apply_jobs")
out = []
try:
    common.guard("Post to LinkedIn for HoldCo", {"text": "hi"}, kind="post")
    out.append("went")
except common.Held as e:
    out.append(str(e))
common.guard("Post to LinkedIn for Beta", {"text": "hi"}, kind="post")
out.append(common.acting())
common.guard("Post again", {"text": "inside the same act window: not asked again"})
out.append([e["kind"] for e in runtrace.load("r1")["events"]])
print(json.dumps(out))
"""
        out = self.py(script)
        self.assertEqual(out, ["Held back: Post to LinkedIn for HoldCo", True, ["held", "did"]])


if __name__ == "__main__":
    unittest.main()
