"""Incident engine: the playbook (detect, contain, diagnose, prepare, escalate, learn) in code.

Detectors (heartbeat, workflows, inbox watchers) call open_incident(). Containment
is the detector's job (the heartbeat pauses the task) and happens before this runs.
This module then:
  1. Starts headless Claude in the background to diagnose. Claude works in a git
     worktree on branch fix/<id>, so the live project is never touched.
  2. Reads Claude's structured verdict: severity, summary, fix, proposed actions.
  3. Escalates. "quiet": apply the fix automatically and mention it in the brief.
     "ceo": wait in the daily brief with buttons. "urgent": ping now with buttons.
Button handlers (apply, discard, act, discuss) are called by bridge.py.

    python scripts/incident.py investigate <id>   # used internally, runs in the background
    python scripts/incident.py list
"""
import hashlib
import json
import re
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import agent
import burst
import integrations
import telegram
from alert import alert, queue_for_brief
from budget import BudgetExceeded, check, record
from pathlib import Path

from common import CACHE, COMPANY, ENGINE_CODE, ROOT, SYSTEM_JOBS, alive, edit_tasks, kill_tree, log_run, now_iso, proc_token
from ops_db import record_event

STATE = CACHE / "incidents.json"
# Outside the project and free of spaces, so tool-permission patterns match cleanly; and not
# under a .cache folder, which the agents are denied (Read(./.cache/**) matches it at any depth).
WORKTREES = Path.home() / ".steerable-worktrees" / "fixes" / "".join(c for c in COMPANY.lower() if c.isalnum())
PY = str(ROOT / ".venv/bin/python")
PER_INCIDENT_CAP_USD = "1.00"
REPEAT_LIMIT = 3  # incidents per workflow per 7 days before it becomes a CEO-level decision

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": ["quiet", "ceo", "urgent"]},
        "summary": {"type": "string", "description": "CEO-facing, plain words, max 300 chars"},
        "root_cause": {"type": "string"},
        "fix_ready": {"type": "boolean", "description": "true if a tested fix is committed on the branch"},
        "fix_summary": {"type": "string"},
        "recommendation": {"type": "string", "description": "your pick, one sentence"},
        "needs_connection": {"type": "string", "description": "if it can't work until the owner connects a "
                             "service or logs in to a website: the service's id, or site:<host>; else empty"},
        "actions": {
            "type": "array",
            "description": "optional steps that run only when the CEO taps them",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"},
                               "command": {"type": "array", "items": {"type": "string"}}},
                "required": ["label", "command"],
            },
        },
    },
    "required": ["severity", "summary", "root_cause", "fix_ready", "fix_summary",
                 "recommendation", "actions"],
}


# ---------- state ----------

def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1))


def update(iid: str, **fields) -> dict:
    s = load()
    s[iid].update(fields)
    save(s)
    return s[iid]


def git(*args, cwd=ROOT, check_=True) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=check_).stdout.strip()


# ---------- detect / open ----------

def open_incident(kind: str, key: str, summary: str, details: str,
                  workflow: str | None = None, task: str | None = None) -> str | None:
    """Record an incident and start the investigation in the background.
    Returns the incident id, or None if one is already open for this key. The engine's own
    jobs never get one: their code isn't the company's to fix (the heartbeat retries them)."""
    if workflow in SYSTEM_JOBS:
        return None
    s = load()
    if any(i["key"] == key and i["status"] in ("investigating", "awaiting_ceo")
           for i in s.values()):
        return None
    iid = "i" + hashlib.sha1(f"{key}{now_iso()}".encode()).hexdigest()[:8]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    repeats = sum(1 for i in s.values() if workflow and i.get("workflow") == workflow
                  and i["opened"] >= week_ago) + 1
    s[iid] = {"id": iid, "kind": kind, "key": key, "summary": summary, "details": details,
              "workflow": workflow, "task": task, "repeats": repeats,
              "status": "investigating", "opened": now_iso()}
    save(s)
    log_run("incident", "opened", incident=iid, kind=kind, key=key)
    prev = record_event(f"Incident opened: {summary}", workflow=workflow, status="Blocked")
    update(iid, board_prev_status=prev)
    _launch(iid)
    return iid


# ---------- diagnose / prepare ----------

def _services() -> str:
    try:
        return ", ".join(s["id"] for s in integrations.available()) or "none"
    except Exception:
        return "none"


def _prompt(inc: dict, wt: str) -> str:
    repeat_note = ""
    if inc["repeats"] >= REPEAT_LIMIT:
        repeat_note = (f"\nThis is incident #{inc['repeats']} for this workflow in 7 days. "
                       "Per the playbook, set severity to at least 'ceo' and recommend "
                       "keep, rework or stop the workflow.")
    return f"""You are the COO handling an incident. Follow the incident playbook in CLAUDE.md.

Incident {inc['id']} ({inc['kind']}): {inc['summary']}
Workflow: {inc.get('workflow')}   Task: {inc.get('task')}
Details:
{inc['details'][-4000:]}
{repeat_note}

How to work:
- A git worktree for your fix is at: {wt} (branch fix/{inc['id']}). Edit files ONLY inside that
  worktree, never in the main project. Test there, e.g. `cd {wt} && .venv/bin/python workflows/<name>.py "<task line>"`.
  If you change a routine (workflows/*.py), run `cd {wt} && .venv/bin/python scripts/routine_check.py workflows/<name>.py`
  and fix what it reports: the engine won't apply a fix to a routine that doesn't meet its standards (data
  through library.table, state.State with an expiry, lesson(), save_draft() and save_report(); no writing,
  moving or deleting files itself). An older routine that keeps its own files must be moved onto these.
  Commit your fix there with `git -C {wt} add ...` and `git -C {wt} commit -m ...`. Do not merge.
- Only change this company's own routines: files in workflows/. Never touch the engine's own code
  (scripts/ and workflows/_template.py): it's the same
  for every company and only changes with an engine update, so a fix that needs it is not yours
  to make. If the fault is there, say so plainly in `summary`, set fix_ready false, and suggest
  what the routine could do differently meanwhile, if anything. Never touch .env, memory/,
  tasks.md or production systems either.
- Never contact customers, publish, spend money or delete data. If a reply to someone or another
  step is needed, prepare it (write drafts to {ROOT}/drafts/{inc['id']}-*.txt; that folder isn't in git) and list it in
  `actions` as a command, e.g. [".venv/bin/python", "workflows/x.py", "--send", "drafts/{inc['id']}-reply.txt"].
  The command must start with .venv/bin/python and a scripts/ or workflows/ path. It runs only if the CEO taps it.
- Severity: quiet = internal and fixed, no customer, money or publishing impact. ceo = needs a CEO
  decision or touches customers, money or publishing. urgent = a paying customer at risk, revenue
  impact, or something actively harmful right now.
- If it can't work until the owner connects something, set needs_connection: a service's id
  ({_services()}), site:<host> for a website they log in to (like site:portal.yoursupplier.com), or
  value:<NAME> for something only they have (a private feed link, an API key) that the routine reads
  with env("<NAME>"); they add it in a one-step form in the app. They do that
  in one tap on their dashboard, so prepare the fix to use it (some sites, like Reddit, block automated
  browsers outright: then prefer the site's own feeds, API or connector): integrations.site_browser("<host>") gives
  a browser already logged in as them, integrations.mcp_call or call() reach connected services.
- Never tell the CEO to edit files, .env or settings, run commands, or paste passwords, tokens or feed
  links: they don't use a terminal. Ask for a connection instead.
- Write summary and recommendation for a busy CEO: plain words, bite-size.
"""


def investigate(iid: str) -> None:
    # So recover_stale can tell an investigation a restart killed from a slow one (and from another process with its pid).
    inc = update(iid, pid=os.getpid(), proc=proc_token())
    try:
        check()
    except BudgetExceeded as e:
        update(iid, status="awaiting_ceo", verdict=None)
        alert(f"incident:{iid}", f"Incident needs you (budget cap hit): {inc['summary']}", str(e))
        return

    wt = WORKTREES / iid
    branch = f"fix/{iid}"
    WORKTREES.mkdir(parents=True, exist_ok=True)
    (ROOT / "drafts").mkdir(exist_ok=True)
    git("worktree", "add", "-q", str(wt), "-b", branch, "HEAD")
    import builder

    builder.link_shared(wt)  # settings, Python, the owner's services, values and website logins, for testing

    out = agent.run(
        _prompt(inc, str(wt)), budget_usd=PER_INCIDENT_CAP_USD, schema=VERDICT_SCHEMA, add_dirs=[wt],
        # Reads: project and worktree only. Writes: the fix worktree and drafts/ only. Secrets denied.
        allow=["Read(./**)", f"Read(/{wt}/**)", "Glob", "Grep",
               f"Edit(/{wt}/**)", f"Write(/{wt}/**)", "Edit(./drafts/**)", "WebFetch",
               f"Bash(cd {wt} && .venv/bin/python *)", f"Bash(git -C {wt} *)"],
        deny=["Read(./.env)", f"Read(/{wt}/.env)", "Read(./.cache/**)", f"Read(/{wt}/.cache/**)"],
        timeout=1800)
    verdict = out.structured
    if not verdict:
        update(iid, status="awaiting_ceo", verdict=None)
        _cleanup(iid)
        alert(f"incident:{iid}", f"Couldn't diagnose: {inc['summary']}", out.error)
        return

    cost = out.cost
    record("incident", cost, model=out.model, note=iid)
    has_fix = git("rev-list", "--count", f"HEAD..{branch}") not in ("", "0")
    verdict["fix_ready"] = verdict.get("fix_ready") and has_fix
    if has_fix and (touched := engine_code_changed(branch)):
        # Whatever it was told, a fix that changes the engine's own code never goes in: not on its
        # own, and not as an offer to the owner. The routine stays paused and the owner hears it's
        # on our side.
        verdict.update(fix_ready=False, engine_fault=True, severity="ceo" if verdict["severity"] == "quiet" else verdict["severity"],
                       fix_summary="", recommendation="Keep it paused. This one is ours to fix, in an update to Steerable.")
        log_run("incident", "engine_fault", incident=iid, files=touched)  # for whoever runs the engine (status.py)
        burst.report_problem("engine_code", f"fix for {inc.get('workflow') or inc['kind']}", verdict.get("summary", ""), touched)
    workflow = inc.get("workflow")
    if verdict["fix_ready"] and workflow and (wt / "workflows" / f"{workflow}.py").exists() and inc.get("task"):
        # A changed routine is seen before it's used: a practice run of the fixed version, reviewed. One
        # that doesn't work isn't applied, not even quietly.
        practice = builder.practice_run(wt, workflow, inc["task"], f"f{iid[1:]}{os.urandom(2).hex()}", incident=iid)
        verdict["practice"], verdict["review"] = practice["trace"], practice["review"]
        if not practice["ok"]:
            verdict.update(fix_ready=False, severity="ceo" if verdict["severity"] == "quiet" else verdict["severity"],
                           fix_summary="", recommendation="Keep it paused: my fix didn't work in its practice run, so I'll look again.")
            log_run("incident", "fix_failed_practice", incident=iid, output=practice["output"][-500:])
    inc = update(iid, verdict=verdict, session_id=out.session_id, cost_usd=cost)
    log_run("incident", "diagnosed", cost_usd=cost, incident=iid,
            severity=verdict["severity"], fix_ready=verdict["fix_ready"])
    record_event(f"Diagnosed ({verdict['severity']}): {verdict['summary'][:200]}", who="COO",
                 workflow=inc.get("workflow"), cost=cost)
    escalate(inc)


# ---------- escalate ----------

def buttons(inc: dict) -> list:
    v, iid, rows = inc["verdict"] or {}, inc["id"], []
    if v.get("fix_ready"):
        rows.append([("✅ Apply fix", f"fx:{iid}"), ("❌ Discard", f"fd:{iid}")])
    for n, a in enumerate(v.get("actions", [])[:4]):
        rows.append([(f"▶️ {a['label'][:40]}", f"ac:{iid}:{n}")])
    rows.append([("💬 Discuss", f"ds:{iid}")])
    return rows


def message(inc: dict) -> str:
    v = inc["verdict"] or {}
    icon = {"urgent": "🔴", "ceo": "🟡"}.get(v.get("severity"), "🛠")
    text = f"{icon} {v.get('summary', inc['summary'])}"
    if v.get("fix_ready"):
        text += f"\n\nFix ready: {v['fix_summary']}"
    if v.get("recommendation"):
        text += f"\nMy pick: {v['recommendation']}"
    return text


def escalate(inc: dict) -> None:
    v = inc["verdict"]
    if inc["repeats"] >= REPEAT_LIMIT and v["severity"] == "quiet":
        v["severity"] = "ceo"  # repeated problems are never handled quietly
    if v["severity"] == "quiet" and v["fix_ready"] and not v.get("actions"):
        result = apply_fix(inc["id"])
        queue_for_brief(f"Fixed on my own: {v['summary']} ({result})")
        return
    if v["severity"] == "quiet" and not v["fix_ready"] and not v.get("actions"):
        update(inc["id"], status="resolved")
        _cleanup(inc["id"])
        _unpause(inc["id"])
        queue_for_brief(f"Looked into: {v['summary']}")
        record_event(f"Resolved, no change needed: {v['summary'][:200]}", who="COO",
                     workflow=inc.get("workflow"), status=inc.get("board_prev_status"))
        return
    update(inc["id"], status="awaiting_ceo")
    record_event(f"Needs CEO: {v['summary'][:200]}", who="COO", workflow=inc.get("workflow"),
                 status="Waiting on CEO")
    if v["severity"] == "urgent" and telegram.configured():
        telegram.send(message(inc), buttons(inc))  # urgent skips quiet hours and ping limits
    # "ceo" level waits for the daily brief, which lists every awaiting incident


# ---------- CEO actions (called from bridge.py) ----------

def _unpause(iid: str) -> None:
    edit_tasks(lambda lines: [line.replace(f"  paused:{iid}", "") for line in lines])


def _cleanup(iid: str, delete_branch: bool = True) -> None:
    git("worktree", "remove", "--force", str(WORKTREES / iid), check_=False)
    if delete_branch:
        git("branch", "-D", f"fix/{iid}", check_=False)


def engine_code_changed(branch: str) -> list[str]:
    """The engine's own files (common.ENGINE_CODE) that a branch changes."""
    changed = git("diff", "--name-only", f"HEAD...{branch}", check_=False).splitlines()
    return [f for f in changed if f.startswith(ENGINE_CODE)]


def substandard(branch: str) -> list[str]:
    """Routines a branch changes that don't meet the engine's standards (routine_check.py)."""
    import routine_check

    changed = git("diff", "--name-only", f"HEAD...{branch}", check_=False).splitlines()
    out = []
    for f in changed:
        if f.startswith("workflows/") and f.endswith(".py") and not f.startswith("workflows/_"):
            source = git("show", f"{branch}:{f}", check_=False)
            out += [f"{f} {p}" for p in routine_check.check_source(source)]
    return out


def apply_fix(iid: str) -> str:
    if engine_code_changed(f"fix/{iid}"):
        update(iid, status="awaiting_ceo")
        return "not applied: it would change Steerable itself, which only updates do"
    if problems := substandard(f"fix/{iid}"):
        update(iid, status="awaiting_ceo")
        log_run("incident", "standards", incident=iid, problems=problems)
        return "not applied: the fix keeps data in ways the engine doesn't allow"
    merged = subprocess.run(["git", "merge", "--no-edit", f"fix/{iid}"], cwd=ROOT,
                            capture_output=True, text=True)
    if merged.returncode != 0:
        git("merge", "--abort", check_=False)
        update(iid, status="awaiting_ceo")
        return "merge conflict. I'll sort it out in the next session"
    _cleanup(iid)
    _unpause(iid)
    inc = load()[iid]
    if inc.get("workflow"):
        import supervise

        supervise.start(inc["workflow"], why="fixed")  # its next runs are watched: the code changed
    verdict = inc.get("verdict") or {}
    if len(set(inc.get("done_actions", []))) < len(verdict.get("actions", [])):
        # Steps that go with the fix (like re-running something) stay on offer: the decision stays open.
        inc = update(iid, verdict={**verdict, "fix_ready": False}, fix_applied=True)
    else:
        inc = update(iid, status="resolved", resolved=now_iso(), resolution="fix applied")
    log_run("incident", "fix_applied", incident=iid)
    record_event(f"Fix applied: {(inc.get('verdict') or {}).get('fix_summary', '')[:200]}", who="COO",
                 workflow=inc.get("workflow"), status=inc.get("board_prev_status"))
    return "fix applied, workflow resumed"


STALE_MINUTES = 45  # an investigation gives up at 30; past this, nothing is working on it any more


def _minutes_since(ts: str | None) -> float:
    from datetime import datetime, timezone

    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 60
    except (TypeError, ValueError):
        return 0.0


def _launch(iid: str) -> None:
    subprocess.Popen([PY, str(ROOT / "scripts/incident.py"), "investigate", iid],
                     cwd=ROOT, start_new_session=True,
                     stdout=open(ROOT / "logs/incidents.log", "a"), stderr=subprocess.STDOUT)


def recover_stale() -> list[str]:
    """Investigations that died (a restart kills background work) never finish on their own, and
    the owner would see "working on it" forever. Run by the heartbeat: a change asked for in the
    chat becomes a change proposal (change.py, its proper place now); anything else is started
    again once, then brought to the owner. Returns what was done, for the log."""
    done = []
    for inc in list(load().values()):
        age = _minutes_since(inc.get("restarted") or inc["opened"])
        running = bool(inc.get("pid")) and alive(inc["pid"], inc.get("proc"))
        dead = inc.get("pid") and not running and age > 2
        if inc["status"] != "investigating" or (not dead and age < STALE_MINUTES):
            continue
        if running:  # past its time and still going: stopped, so it can't finish later over what's decided now
            kill_tree(inc["pid"], inc.get("proc"))
        iid = inc["id"]
        if inc.get("kind") == "request" and inc.get("workflow"):
            import change

            what = re.search(r"\):\n(.*?)(?:\n\nRecent runs:|\Z)", inc.get("details", ""), re.S)
            try:
                change.propose(inc["workflow"], (what.group(1) if what else inc["summary"]).strip(), why="Asked for in the chat.")
            except change.ChangeError:
                pass
            update(iid, status="resolved", resolved=now_iso(), resolution="moved to a change proposal")
            record_event("Moved the change to your Decisions.", who="COO", workflow=inc.get("workflow"),
                         status=inc.get("board_prev_status"))
            done.append(f"{iid}: became a change proposal")
        elif not inc.get("restarts"):
            update(iid, restarts=1, restarted=now_iso())
            _launch(iid)
            done.append(f"{iid}: started again")
        else:
            update(iid, status="awaiting_ceo", verdict=None)
            done.append(f"{iid}: brought to the owner")
    if done:
        log_run("incident", "recovered", items=done)
    return done


def discard_fix(iid: str) -> str:
    _cleanup(iid)
    inc = update(iid, status="resolved", resolved=now_iso(), resolution="discarded")
    log_run("incident", "discarded", incident=iid)
    record_event("CEO discarded the fix. Workflow stays paused.", who="CEO", workflow=inc.get("workflow"))
    return "fix discarded. The workflow stays paused until we decide what to do"


def run_action(iid: str, n: int) -> str:
    inc = load()[iid]
    action = inc["verdict"]["actions"][n]
    cmd = action["command"]
    if len(cmd) < 2 or cmd[0] != ".venv/bin/python" or not cmd[1].startswith(("scripts/", "workflows/")):
        return "refused: that command isn't an allowed script"
    # drafts and scripts for actions live on the fix branch, so apply it first
    if inc["verdict"].get("fix_ready") and inc["status"] != "resolved":
        apply_fix(iid)
    # The owner tapped this prepared step, so it runs as approved work.
    proc = subprocess.run([PY, *cmd[1:]], cwd=ROOT, capture_output=True, text=True, timeout=600,
                          env={**os.environ, "STEERABLE_CONTEXT": "routine"})
    log_run("incident", "action", incident=iid, action=action["label"], code=proc.returncode)
    done = load()[iid].setdefault("done_actions", [])
    done.append(n)
    update(iid, done_actions=done)
    return ("done: " if proc.returncode == 0 else "failed: ") + action["label"]


def resolve(iid: str, note: str = "closed") -> None:
    update(iid, status="resolved", resolved=now_iso(), resolution=note)


def awaiting() -> list[dict]:
    return [i for i in load().values() if i["status"] == "awaiting_ceo"]


if __name__ == "__main__":
    if sys.argv[1:2] == ["investigate"]:
        iid = sys.argv[2]
        try:
            investigate(iid)
        except Exception as e:  # never leave an incident stuck in "investigating"
            update(iid, status="awaiting_ceo", verdict=None)
            _cleanup(iid)
            log_run("incident", "error", incident=iid, error=repr(e))
            alert(f"incident:{iid}", f"Couldn't investigate: {load()[iid]['summary']}", repr(e))
            raise
    elif sys.argv[1:2] == ["list"]:
        for i in load().values():
            print(i["id"], i["status"], (i.get("verdict") or {}).get("severity", "-"), i["summary"][:70])
