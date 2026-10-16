"""Routine builder: when the owner approves a routine that doesn't exist yet, the COO builds it.

The chat agent can't write workflows (on purpose: it reads untrusted text all day). So an
approval of a task whose workflows/<name>.py is missing starts this instead, the same way an
incident starts a fix:
  1. Headless Claude builds the workflow in a git worktree on branch build/<name>, so the
     live project is never touched, following the Workflow standard in CLAUDE.md.
  2. It tests it with STEERABLE_DRY_RUN=1, which every workflow must honor: do everything
     except contacting anyone, publishing, paying or deleting.
  3. The engine runs a tested build once more as a practice run, keeping a trace (runtrace.py:
     every step and page, with pictures, and what it would do that can't be undone), and an AI
     reviews it (supervise.review). The owner looks at that and switches it on, asks for a change
     (a new attempt from this one, with their words) or drops it: nothing new runs unseen.
  4. Switched on, it's merged and runs on schedule, watched for its first runs (supervise.py).
     If it needs something only the owner can give (a login, a decision), or can't be made to
     work, the owner gets a decision with a plain explanation, and nothing half-built runs.

    python scripts/builder.py build <id>   # used internally, runs in the background
    python scripts/builder.py list
"""
import fcntl
import json
from contextlib import contextmanager
import os
import secrets
import subprocess
import sys
from pathlib import Path

import burst
import flow
import integrations
import routine_check
import runtrace
import supervise
from budget import BudgetExceeded, check, record
from common import CACHE, COMPANY, ENGINE_CODE, ROOT, alive, edit_tasks, log_run, now_iso, task_title
from ops_db import record_event

STATE = CACHE / "builds.json"
LIVE = CACHE / "build-live"  # each build's Claude events as they happen, for the routine page
WORKFLOWS = ROOT / "workflows"
# Outside the project and free of spaces, so tool-permission patterns match cleanly; and not
# under a .cache folder, which the agents are denied (Read(./.cache/**) matches it at any depth).
WORKTREES = Path.home() / ".steerable-worktrees" / "builds" / "".join(c for c in COMPANY.lower() if c.isalnum())
PY = str(ROOT / ".venv/bin/python")
PER_BUILD_CAP_USD = "2.00"
OPEN = ("building", "needs_owner", "failed", "ready")

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["built", "needs_owner", "failed"]},
        "summary": {"type": "string", "description": "for the owner, plain words, max 300 chars: what it does and when, or what went wrong"},
        "needs": {"type": "string", "description": "if needs_owner: exactly what the owner must provide or decide, plain words"},
        "needs_connection": {"type": "string", "description": "if needs_owner because a service isn't connected: its id from the list of services you can ask for, else empty"},
        "test_output": {"type": "string", "description": "the last lines of the dry-run test"},
    },
    "required": ["status", "summary", "needs", "needs_connection", "test_output"],
}


# ---------- state ----------

def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


@contextmanager
def _state():
    """Read-modify-write the build list under a lock: the agent API and background builds
    both change it, and must not overwrite each other."""
    with (CACHE / "builds.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        s = load()
        yield s
        STATE.write_text(json.dumps(s, indent=1))


def update(bid: str, **fields) -> dict:
    with _state() as s:
        s[bid].update(fields)
        return dict(s[bid])


def git(*args, cwd=ROOT, check_=True) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check_).stdout.strip()


def missing(workflow: str) -> bool:
    return not (WORKFLOWS / f"{workflow}.py").exists()


def current(workflow: str) -> dict | None:
    """The open build for this workflow, if any."""
    return next((b for b in load().values() if b["workflow"] == workflow and b["status"] in OPEN), None)


# ---------- start ----------

def _open(workflow: str, task: str, exists: bool, **extra) -> str | None:
    """Open a build and start it in the background. None if the workflow isn't as expected (missing
    for a new routine, there for a change) or a build is already open for it."""
    bid = "b" + secrets.token_hex(4)  # unique even for two attempts in the same second
    with _state() as s:
        if missing(workflow) == exists or any(b["workflow"] == workflow and b["status"] in OPEN for b in s.values()):
            return None
        s[bid] = {"id": bid, "workflow": workflow, "task": task, "title": task_title(task),
                  **{k: v for k, v in extra.items() if v}, "status": "building", "opened": now_iso()}
    log_run("builder", "started", build=bid, workflow=workflow, **({"change": True} if exists else {}))
    subprocess.Popen([PY, str(ROOT / "scripts/builder.py"), "build", bid], cwd=ROOT, start_new_session=True,
                     stdout=open(ROOT / "logs/builds.log", "a"), stderr=subprocess.STDOUT)
    return bid


def start_build(workflow: str, task: str) -> str | None:
    """Start building an approved routine. Returns the build id, or None if there's nothing to
    build (the workflow exists) or a build is already open for it."""
    bid = _open(workflow, task, exists=False)
    if bid:
        record_event(f"Started building {task_title(task)}.", who="COO", workflow=workflow, status="In progress")
    return bid


def start_change(workflow: str, task: str, change: str) -> str | None:
    """Start changing a routine that's running (change.py, after the owner approved). It keeps
    running as it is until the changed version is tested, seen and switched on. None if it doesn't
    exist or something is already being built for it."""
    bid = _open(workflow, task, exists=True, change=change)
    if bid:
        record_event(f"Started updating {task_title(task)}.", who="COO", workflow=workflow)
    return bid


STALE_MINUTES = 60  # a build gives up at 40; past this, nothing is working on it any more


def recover_stale() -> list[str]:
    """Builds that died (a restart kills background work) never finish on their own. Run by the
    heartbeat: one whose process is gone is picked up again once, automatically, since the owner
    already approved it; a second time, or one stuck past its time, becomes "interrupted", which
    the owner can try again from Decisions."""
    from datetime import datetime, timezone

    done = []
    for b in list(load().values()):
        if b["status"] != "building":
            continue
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(b["opened"])).total_seconds() / 60
        except ValueError:
            continue
        dead = b.get("pid") and not alive(b["pid"]) and age > 2
        if not dead and age < STALE_MINUTES:
            continue
        changing = bool(b.get("change"))
        if dead and not b.get("resumed"):
            update(b["id"], status="retried")
            live_path(b["id"]).unlink(missing_ok=True)
            git("worktree", "remove", "--force", str(WORKTREES / b["id"]), check_=False)
            new = _open(b["workflow"], b["task"], exists=changing, change=b.get("change"),
                        feedback=b.get("feedback"), base=b.get("base"), fixes=b.get("fixes"), rounds=b.get("rounds"))
            if new:
                update(new, resumed=True)
                done.append(f"{b['id']}: started again as {new}")
                continue
        update(b["id"], status="failed", finished=now_iso(), needs="",
               summary="I was interrupted while working on it, so nothing changed yet. Try again and I'll start over."
               + (" It keeps running as it was." if changing else ""))
        live_path(b["id"]).unlink(missing_ok=True)
        git("worktree", "remove", "--force", str(WORKTREES / b["id"]), check_=False)
        record_event(f"Was interrupted while {'updating' if changing else 'building'} {b['title']}.", who="COO", workflow=b["workflow"])
        done.append(f"{b['id']}: interrupted")
    if done:
        log_run("builder", "recovered", items=done)
    return done


def ensure_builds(approved: list[tuple[str, str]]) -> None:
    """Safety net for the heartbeat: approved routines with no workflow file and no build record
    at all get one. A build that failed or needs the owner waits for them, so it never loops."""
    known = {b["workflow"] for b in load().values()}
    for workflow, task in approved:
        if missing(workflow) and workflow not in known:
            start_build(workflow, task)


# ---------- build ----------

def _accounts() -> str:
    """What the routine can use: the owner's connected accounts, and what they could connect."""
    have = integrations.connected()
    could = [s for s in integrations.available() if s["id"] not in {c["provider"] for c in have}]
    if not have and not could:
        return "Connected accounts: none (this company can't connect accounts)."
    lines = ["Connected accounts (call them with scripts/integrations.py, which adds the credentials):"]
    apps = [c for c in have if not c.get("site")]
    sites = [c for c in have if c.get("site")]
    lines += [f"- {c['provider']}: {c['name']}, as {c.get('account') or 'the owner'}"
              + ("" if c["status"] == "ACTIVE" else " (needs reconnecting)") for c in apps] or ["- none yet"]
    if sites:
        lines.append("Websites without an API where the owner saved a login (drive them with Playwright; prefer an "
                     "API or MCP tool when one exists):")
        lines += [f"- {c['site']}: {c['name']}" + ("" if c["status"] == "ACTIVE" else " (login expired)") for c in sites]
        lines.append('  from integrations import site_browser; with site_browser("<site>", logged_in="<selector seen only '
                     'when logged in>") as page: ...  (already logged in. Use stable selectors (get_by_role, get_by_label), '
                     'click and type through browser.Human: h = Human(page); h.click(locator); h.type(locator, text); '
                     'h.scroll(dy), which moves the pointer and types as a person does; open further pages with h.goto(url) and '
                     'call h.read() after a click that loads a page, so it never rushes from page to page; read what the page says with plain Playwright; '
                     'keep it to what the task needs, never change the account\'s password or settings. In this dry run '
                     'every non-GET request is blocked, so look but expect submits to do nothing.)')
    lines.append("A website the routine needs to be logged in to (no API or MCP tool for it, or the data is only in the "
                 "owner's account there): set needs_owner and needs_connection to \"site:<host>\" (like site:portal.yoursupplier.com); "
                 "the owner logs in once on their dashboard, and the routine uses site_browser(\"<host>\"). Never ask "
                 "the owner for passwords, tokens, feed links or .env edits: they don't use a terminal. A value only "
                 "they have (a private link, an API key): read it with env(\"<NAME>\") and set needs_connection to "
                 "\"value:<NAME>\"; they add it in a one-step form.")
    if could:
        lines.append("Services the owner could connect (ask with needs_connection): "
                     + ", ".join(f"{s['id']} ({s['name']})" for s in could))
    mcp = [c["provider"] for c in have if c.get("mcp")]
    if mcp:
        lines.append(f"These have MCP tools you can use now to look at real data (dry run: tools that change things "
                     f"won't run): {', '.join(mcp)}. In the routine, call the same tools with "
                     'mcp_call("<service>", "<tool>", {...}) from integrations.')
    lines.append("Steerable playbooks (mcp__steerable__find_playbooks, mcp__steerable__read_playbook): proven know-how for "
                 "this kind of work (chasing invoices, reorder reminders, review requests...). Check them before designing "
                 "the routine, and follow them, adapted to this company.")
    lines.append('For services without MCP tools: from integrations import call; call("google", "GET", '
                 '"https://gmail.googleapis.com/gmail/v1/users/me/messages", params={"q": "is:unread"})')
    return "\n".join(lines)


def _feedback(b: dict) -> str:
    out = ""
    if b.get("feedback"):
        out += f"""
The owner looked at the practice run of your last version and asked for this: {b['feedback']}
Your last version is already in the worktree (committed on the branch). Change it to do what they asked, keep
what they didn't mention, test it again and commit.
"""
    if b.get("fixes"):
        gaps = "\n".join(f"- {f}" for f in b["fixes"])
        out += f"""
Your last version ran once as a practice run, and a review of it found these gaps:
{gaps}
Your last version is already in the worktree (committed on the branch). Fix them yourself: the owner never sees this
list, so don't ask them about any of it unless it truly needs something only they can give. Keep what works, test
again and commit.
"""
    return out


def _change_prompt(b: dict, wt: str) -> str:
    """For changing a routine that's running: what the owner approved, and the same standards."""
    name = b["workflow"]
    return f"""You are the COO. The owner approved a change to a routine that's already running, and you're making it now.

Routine: {b['title']}
Task line: {b['task']}
The change: {b['change']}
{_feedback(b)}
{_accounts()}

Its code is workflows/{name}.py (and its flow chart workflows/{name}.flow.json) in the worktree below. Make the
change and keep everything else it does working. It must meet every point of the Workflow standard in CLAUDE.md,
point 7 especially: records the owner looks up go in a library table with a key (library.py), working state in
state.State() with an expiry, lasting lessons through common.lesson(), drafts and reports through
common.save_draft() and common.save_report(); never write, move or delete files itself. If it kept its own files
until now, it may read them (not delete them) to carry what's in them over on its first run. News the owner
should act on (new matches, something that needs them) goes to them with common.tell_owner(markdown): at most
one message per run, only when there's news. Update the flow chart if the steps changed, and call
common.step(n) at each step. Anything it can't undo goes through common.act() (point 8 of the Workflow standard).

How to work:
- A git worktree for the change is at: {wt} (branch build/{name}). Edit files ONLY inside it. Change only
  workflows/{name}.py, workflows/{name}.flow.json and a helper module next to them if it truly needs one.
- Test it only in dry-run mode: cd {wt} && STEERABLE_DRY_RUN=1 .venv/bin/python workflows/{name}.py "{b['task']}"
- Run cd {wt} && .venv/bin/python scripts/routine_check.py workflows/{name}.py and fix everything it reports.
- Commit with `git -C {wt} add workflows/` and `git -C {wt} commit -m "Update {name}"`. Do not merge.
- If it needs something only the owner can give, set status "needs_owner" and say what, in plain words. If you
  can't make it work, set status "failed" and say why. Otherwise "built".
- Write summary and needs for a busy owner who isn't technical: what changed, in a sentence or two.
"""


def _prompt(b: dict, wt: str) -> str:
    if b.get("change"):
        return _change_prompt(b, wt)
    name, task = b["workflow"], b["task"]
    return f"""You are the COO. The owner just approved a new routine, and you're building it now.

Routine: {b['title']}
Task line: {task}
{_feedback(b)}
{_accounts()}

Build it as workflows/{name}.py, starting from workflows/_template.py and meeting every point of
the Workflow standard in CLAUDE.md. Read memory/ (company.md, processes.md, decisions.md) and the
mission board (`.venv/bin/python scripts/ops_db.py --show`) to understand the business.

How to work:
- A git worktree for the build is at: {wt} (branch build/{name}). Create and edit files ONLY inside
  that worktree, never in the main project. Only add workflows/{name}.py (and a helper module next to
  it if it truly needs one) and workflows/{name}.flow.json. Never touch .env, memory/, tasks.md or scripts/.
- workflows/{name}.flow.json is the owner's flow chart of it: {{"steps": [{{"kind", "label", "service",
  "detail"}}, ...]}}. {flow.GUIDE}
- As it starts each step of the flow chart, the workflow calls step(n) (from common import step), n being the
  step's index in workflows/{name}.flow.json (0 is the trigger, so start at step(1)). The owner's routine
  page shows the step it's on while it runs.
- News the owner should act on goes to them with common.tell_owner(markdown): at most one message per run,
  only when there's news (new matches, something that needs them). Not a run report: the timeline has that.
- The workflow must honor the STEERABLE_DRY_RUN=1 environment variable: do everything except
  contacting anyone, publishing, paying, or deleting data, and print what it would have done instead.
- Anything it can't undo (submitting a form, sending, posting, paying, deleting) goes through
  common.act("<what, specific, in the owner's words>", {{<the ids, addresses, names it's about>}}, kind=...,
  target=<on a website: the button it's about to press, so the owner sees it marked>): do it only when act()
  returns True. Before that, check the routine's own records (the library table where it
  keeps what it did, by key) and the page itself: already done, closed, changed, a duplicate? Then skip it.
  Afterwards make sure it worked (a confirmation on the page, a reply) before recording it as done; if you can't
  tell, record it as "check this", never as done, and never retry it blindly. When a page doesn't look as
  expected, skip that item and tell the owner instead of guessing. In a practice run act() returns False and
  notes it; in the first live runs an AI looks at each one first, with the page as it is.
- When you're done, the engine runs it once more as a practice run with pictures of every step, and the owner
  sees exactly what it would do before switching it on. Make what it prints and passes to act() read well there.
- Test it, only ever in dry-run mode:
  cd {wt} && STEERABLE_DRY_RUN=1 .venv/bin/python workflows/{name}.py "{task}"
  Fix it until it exits 0 with output that shows it did the right thing.
- The last line it prints is shown to the owner as what it did, so make it a short plain sentence
  (e.g. "Reminded 3 clients about unpaid invoices").
- Before you commit, run `cd {wt} && .venv/bin/python scripts/routine_check.py workflows/{name}.py` and fix
  everything it reports until it says it meets the engine's standards: the engine runs it again and won't
  switch on a routine that fails. Save drafts with common.save_draft(name, text) and the latest results with
  common.save_report(markdown); never write, move or delete files yourself.
- Commit with `git -C {wt} add workflows/` and `git -C {wt} commit -m "Build {name}"`. Do not merge.
- Keep each piece of data in its place (point 7 of the Workflow standard): records the owner would look
  up or change go in a library table (import library; library.table(name, columns=...).add(cells, key=...),
  with a key so re-runs update instead of duplicating, and never overwriting what the owner changed);
  working state only to avoid repeating work goes in state.State() with an expiry (seen(key, keep_days=60)),
  never in a JSON file of your own; a lasting lesson about how the owner wants it done goes to
  common.lesson(text). Nothing it keeps may grow forever.
- To post to social networks, call social.post(networks, text, image=..., link=...) from scripts/social.py:
  it posts in an approved routine (Reddit still waits for the owner) and only prints in a dry run.
- Reach the owner's tools only through scripts/integrations.py, never with your own credentials or
  passwords. Prefer an API over a website.
- If it needs a service that isn't connected, set status "needs_owner" and needs_connection to its
  id. If it needs something else only the owner can give (a choice you can't make for them), don't
  fake it or hard-code a guess: set status "needs_owner" and say exactly what, in plain words. If
  you can't make it work, set status "failed" and say why.
- Write summary and needs for a busy owner who isn't technical: no file names, no code words.
- Run every test in the foreground and wait for it (never in the background): the build ends when you do.
"""


AUTO_FIX_ROUNDS = 2  # attempts that fix what a practice run's review found, before the owner sees it


def _auto_fix(bid: str, b: dict, fields: dict, review: dict, rounds: int, cost: float) -> None:
    """A new attempt from this one, with the review's fixes as its brief. Nothing reaches the owner."""
    name = b["workflow"]
    branch, base = f"build/{name}", f"build/{name}-was"
    _cleanup(bid, name, keep_branch=True)
    if b.get("base"):
        git("branch", "-D", b["base"], check_=False)
    git("branch", "-D", base, check_=False)
    git("branch", "-m", branch, base)
    update(bid, status="revised", finished=now_iso(), review=review, **fields)
    live_path(bid).unlink(missing_ok=True)
    log_run("builder", "auto_fix", cost_usd=cost, build=bid, workflow=name, round=rounds + 1, fixes=review["fixes"])
    _open(name, b["task"], exists=bool(b.get("change")), change=b.get("change"), feedback=b.get("feedback"),
          fixes=review["fixes"], base=base, rounds=rounds + 1)


def build(bid: str) -> None:
    b = update(bid, pid=os.getpid())  # so recover_stale can tell a build a restart killed from a slow one
    try:
        check()
    except BudgetExceeded:
        update(bid, status="failed", summary="This month's AI budget is used up, so I couldn't build it yet.", needs="")
        return

    name = b["workflow"]
    wt = WORKTREES / bid
    branch = f"build/{name}"
    WORKTREES.mkdir(parents=True, exist_ok=True)
    _free_branch(branch)
    git("branch", "-D", branch, check_=False)  # a leftover from an earlier attempt
    git("worktree", "add", "-q", str(wt), "-b", branch, b.get("base") or "HEAD")
    link_shared(wt)

    # Connected services as MCP tools, always in dry-run mode: exploring can't change anything.
    mcp_args, mcp_tools = integrations.claude_mcp_args(dry_run=True)
    cmd = ["claude", "-p", _prompt(b, str(wt)), "--output-format", "stream-json", "--verbose",
           "--model", "sonnet", "--max-budget-usd", PER_BUILD_CAP_USD,
           "--json-schema", json.dumps(RESULT_SCHEMA), *mcp_args, "--add-dir", str(wt),
           # Reads: project and worktree. Writes: the worktree only. Runs: python and git there. Secrets denied.
           "--allowedTools", *mcp_tools, "Read(./**)", f"Read(/{wt}/**)", "Glob", "Grep", "WebFetch", "WebSearch",
           f"Edit(/{wt}/**)", f"Write(/{wt}/**)", "Bash(.venv/bin/python scripts/ops_db.py*)",
           f"Bash(cd {wt} && STEERABLE_DRY_RUN=1 .venv/bin/python *)", f"Bash(git -C {wt} *)",
           f"Bash(cd {wt} && .venv/bin/python scripts/routine_check.py *)",
           "--disallowedTools", "Read(./.env)", f"Read(/{wt}/.env)", "Read(./.cache/**)", f"Read(/{wt}/.cache/**)"]
    LIVE.mkdir(exist_ok=True)
    proc = burst.run(cmd, kind="claude", timeout=2400, stream=live_path(bid))
    try:
        out = _result(proc.stdout)
        result = out.get("structured_output") or json.loads(out["result"])
    except (json.JSONDecodeError, KeyError, TypeError):
        _cleanup(bid, name)
        update(bid, status="failed", summary="Something went wrong while I was building it.", needs="",
               error=(proc.stderr or proc.stdout)[-1500:])
        record_event(f"Couldn't build {b['title']}.", who="COO", workflow=name, status="Blocked")
        return

    cost = float(out.get("total_cost_usd") or 0)
    record("builder", cost, model="sonnet", note=bid)
    built = git("rev-list", "--count", f"HEAD..{branch}") not in ("", "0") and (wt / f"workflows/{name}.py").exists()
    status = result["status"] if (result["status"] != "built" or built) else "failed"
    # Whatever it was told, a build that changes the engine's own code is never merged.
    touched = [f for f in git("diff", "--name-only", f"HEAD...{branch}", check_=False).splitlines() if f.startswith(ENGINE_CODE)]
    if status == "built" and touched:
        status = "failed"
        result["summary"] = "I built it, but it needed changes I'm not allowed to make. I'll try another way."
        log_run("builder", "engine_code", build=bid, workflow=name, files=touched)
        burst.report_problem("engine_code", f"build of {name}", result.get("summary", ""), touched)
    # Nor is a routine that doesn't meet the engine's standards (routine_check.py): it reads the code.
    problems = routine_check.check(wt / f"workflows/{name}.py") if status == "built" else []
    if problems:
        status = "failed"
        result["summary"] = ("It works, but it keeps its data in ways the engine doesn't allow, so I didn't switch it on. "
                             "Try again and I'll fix that.")
        log_run("builder", "standards", build=bid, workflow=name, problems=problems)
    fields = {"summary": result.get("summary", ""), "needs": result.get("needs", ""),
              "needs_connection": result.get("needs_connection", "") if result["status"] == "needs_owner" else "",
              "test_output": result.get("test_output", "")[-1500:], "cost_usd": cost}

    if status == "built":  # the owner sees a practice run before anything is switched on
        practice = _practice(bid, b, wt)
        fields["trace"] = practice["trace"]
        rounds = int(b.get("rounds") or 0)
        if practice["ok"] and practice["review"].get("fixes") and rounds < AUTO_FIX_ROUNDS:
            # The owner hears the big picture only: gaps the review found are ours to fix, then practise again.
            _auto_fix(bid, b, fields, practice["review"], rounds, cost)
            return
        if practice["ok"]:
            status, fields["review"] = "ready", practice["review"]
        else:
            status = "failed"
            fields["summary"] = "It passed my tests, but its practice run didn't work. Try again and I'll look into why."
            fields["test_output"] = practice["output"]
    _cleanup(bid, name, keep_branch=status == "ready")
    if b.get("base"):
        git("branch", "-D", b["base"], check_=False)
    update(bid, status=status, finished=now_iso(), **fields)
    live_path(bid).unlink(missing_ok=True)
    log_run("builder", status, cost_usd=cost, build=bid, workflow=name)
    changing = bool(b.get("change"))
    if status == "ready":
        record_event(f"{'Updated' if changing else 'Built'} {b['title']} and tried it in a practice run. {fields['summary']}",
                     who="COO", workflow=name, cost=cost)
    elif changing:
        record_event(f"Couldn't finish updating {b['title']}; it keeps running as it was.", who="COO", workflow=name, cost=cost)
    else:
        record_event(f"Couldn't finish building {b['title']}.", who="COO", workflow=name, cost=cost, status="Blocked")


# What a build's worktree shares with the company, for its tests: settings and Python (.env, .venv, both
# gitignored), the owner's own services (tools.py), values (vault.py) and website logins with their browser
# profiles (sites.py, extension.py). The AI building it may run the routine with them but never read them.
SHARED = (".env", ".venv", ".cache/tools", ".cache/vault.json", ".cache/sites")


def link_shared(wt: Path) -> None:
    for rel in SHARED:
        if (ROOT / rel).exists() and not (wt / rel).exists():
            (wt / rel).parent.mkdir(parents=True, exist_ok=True)
            os.symlink(ROOT / rel, wt / rel)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _practice(bid: str, b: dict, wt: Path) -> dict:
    return practice_run(wt, b["workflow"], b["task"], f"p{bid[1:]}{secrets.token_hex(2)}", build=bid)


def practice_run(wt: Path, name: str, task: str, tid: str, **about) -> dict:
    """Run a routine in a worktree (a build, or a prepared fix: incident.py) once as a practice run
    (nothing sent) with a trace, against the company's records, and have it reviewed.
    {"ok", "trace", "review", "output"}."""
    runtrace.start(tid, workflow=name, kind="practice", task=task, **about)
    # What the routine reads: the library and its working state (both read-only in a practice run), and
    # where its trace goes. Not ops.db: what a practice run notes there isn't the company's history.
    for rel, target in {"library.db": ROOT / "library.db", ".cache/state.db": CACHE / "state.db",
                        ".cache/traces": runtrace.TRACES}.items():
        if target.exists() and not (wt / rel).exists():
            (wt / rel).parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, wt / rel)
    script = wt / "workflows" / f"{name}.py"
    source = script.read_text()
    env = {**os.environ, "STEERABLE_DRY_RUN": "1", "STEERABLE_TRACE": tid, "STEERABLE_WORKFLOW": name,
           "STEERABLE_CONTEXT": "routine"}
    cmd = [PY, str(script), task]
    try:
        if "site_browser" in source or "playwright" in source:
            proc = burst.run(cmd, kind="browser", cwd=wt, timeout=1800, env=env)
        else:
            proc = subprocess.run(cmd, cwd=wt, capture_output=True, text=True, timeout=1800, env=env)
        code, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        code, out, err = -1, "", "It took longer than 30 minutes."
    lines = [line for line in out.splitlines() if line.strip()]
    ok = code == 0
    # The step names from this version's flow chart (a build isn't merged yet, so the app and the review
    # can't read them from the company folder), and the end of what it printed: what it found and did.
    steps = [str(s.get("label") or "") for s in (flow.valid(_read_json(wt / "workflows" / f"{name}.flow.json")) or [])]
    runtrace.update(tid, finished=now_iso(), ok=ok, summary=lines[-1][:200] if lines else "",
                    steps=steps, printed="\n".join(lines[-30:])[-3000:])
    review = supervise.review(tid, name, source, task) if ok else {}
    runtrace.update(tid, review=review)
    log_run("builder", "practice", workflow=name, trace=tid, ok=ok, exit=code, **about)
    return {"ok": ok, "trace": tid, "review": review, "output": (out + "\n" + err)[-1500:]}


def live_path(bid: str) -> Path:
    return LIVE / f"{bid}.jsonl"


def step_words(tool: str, args: dict) -> str | None:
    """A builder's tool call as the owner reads it on the routine page; None leaves it to the
    chat's wording (bridge.step_label)."""
    path = str(args.get("file_path") or "")
    cmd = str(args.get("command") or "")
    if tool == "Read" and path.endswith("workflows/_template.py"):
        return "Starting from the routine template"
    if tool == "Read" and "/workflows/" in path:
        return "Looking at how your other routines work"
    if tool in ("Write", "Edit", "MultiEdit") and path.endswith(".flow.json"):
        return "Drawing how it works"
    if tool in ("Write", "Edit", "MultiEdit") and "/workflows/" in path:
        return "Writing the routine" if tool == "Write" else "Improving the routine"
    if tool in ("Grep", "Glob"):
        return "Looking through the code"
    if tool == "Bash" and "routine_check.py" in cmd:
        return "Checking it meets the engine's standards"
    if tool == "Bash" and "scripts/" in cmd:
        return "Looking at how the engine works"
    if tool == "Bash" and "STEERABLE_DRY_RUN=1" in cmd:
        return "Testing it in a practice run (nothing is sent)"
    if tool == "Bash" and " commit" in cmd:
        return "Saving the finished routine"
    if tool == "Bash" and cmd.startswith("git"):
        return "Checking its changes"
    if tool == "Bash" and "ops_db.py" in cmd:
        return "Checking your goals"
    return None


def _result(stdout: str) -> dict:
    """The final event of a stream-json run (the one with the result)."""
    found = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "result" in event:
            found = event
    if found is None:
        raise json.JSONDecodeError("no result", stdout, 0)
    return found


def _free_branch(branch: str) -> None:
    """An attempt that was killed leaves its worktree holding the branch; remove it, or a new
    attempt can't make the branch again."""
    git("worktree", "prune", check_=False)
    path = None
    for line in git("worktree", "list", "--porcelain", check_=False).splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}" and path and Path(path) != ROOT:
            git("worktree", "remove", "--force", path, check_=False)


def _cleanup(bid: str, name: str, keep_branch: bool = False) -> None:
    """Remove a build's worktree, and its branch unless it waits to be switched on."""
    live_path(bid).unlink(missing_ok=True)
    git("worktree", "remove", "--force", str(WORKTREES / bid), check_=False)
    if not keep_branch:
        git("branch", "-D", f"build/{name}", check_=False)


# ---------- owner actions (agent API) ----------

def retry(bid: str) -> str | None:
    """Close this attempt and start a new one."""
    b = load()[bid]
    update(bid, status="retried")
    return _open(b["workflow"], b["task"], exists=bool(b.get("change")), change=b.get("change"), feedback=b.get("feedback"))


def switch_on(bid: str) -> None:
    """The owner looked at the practice run and said yes: merge it, and watch its first runs.
    Raises RuntimeError, in plain words, when it can't."""
    b = load()[bid]
    if b["status"] != "ready":
        raise RuntimeError("That's no longer waiting to be switched on.")
    name, branch = b["workflow"], f"build/{b['workflow']}"
    merged = subprocess.run(["git", "merge", "--no-edit", branch], cwd=ROOT, capture_output=True, text=True)
    if merged.returncode != 0:
        git("merge", "--abort", check_=False)
        log_run("builder", "merge_error", build=bid, workflow=name, error=(merged.stderr or merged.stdout)[-500:])
        raise RuntimeError("It didn't go in cleanly. Pick “Change something” and I'll build it again from here.")
    git("branch", "-D", branch, check_=False)
    update(bid, status="built", switched_on=now_iso())
    supervise.start(name)
    changing = bool(b.get("change"))
    record_event(f"You switched on {'the update to ' if changing else ''}{b['title']}. Its first runs are watched: "
                 "anything it can't undo is checked first.", who="CEO", workflow=name,
                 **({} if changing else {"status": "Recurring" if "every:" in b["task"] else "In progress"}))


def revise(bid: str, note: str) -> str | None:
    """The owner looked at the practice run and wants something changed: a new attempt that starts
    from this one, with their words."""
    b = load()[bid]
    if b["status"] != "ready":
        return None
    note = " ".join((note or "").split())[:2000]
    if not note:
        raise ValueError("Say what to change.")
    branch, base = f"build/{b['workflow']}", f"build/{b['workflow']}-was"
    git("branch", "-D", base, check_=False)
    git("branch", "-m", branch, base)
    update(bid, status="revised")
    bid2 = _open(b["workflow"], b["task"], exists=bool(b.get("change")), change=b.get("change"), feedback=note, base=base)
    if bid2:
        record_event(f"You asked for a change to {b['title']}: {note}", who="CEO", workflow=b["workflow"])
    return bid2


def drop(bid: str) -> None:
    """The owner doesn't want it after all: close the build and reject its task line. A change
    that's dropped just closes: the routine keeps running as it was."""
    b = load()[bid]
    if b["status"] == "ready":
        git("branch", "-D", f"build/{b['workflow']}", check_=False)
    update(bid, status="dropped")
    if b.get("change"):
        record_event(f"Kept {b['title']} as it was.", who="CEO", workflow=b["workflow"])
        return
    from datetime import date

    def change(lines: list[str]) -> list[str]:
        return [(line.replace("- [ ]", "- [x]", 1).replace("  approved", "") + f"  rejected:{date.today()}")
                if line.startswith("- [ ]") and f"@workflow:{b['workflow']}" in line else line for line in lines]

    edit_tasks(change)
    record_event(f"You decided: Don't build it. ({b['title']})", who="CEO", workflow=b["workflow"], status="Cancelled")


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        bid = sys.argv[2]
        try:
            build(bid)
        except Exception as e:  # never leave a build stuck in "building"
            update(bid, status="failed", summary="Something went wrong while I was building it.", needs="", error=repr(e))
            _cleanup(bid, load()[bid]["workflow"])
            log_run("builder", "error", build=bid, error=repr(e))
            raise
    elif sys.argv[1:2] == ["list"]:
        for b in load().values():
            print(b["id"], b["status"], b["workflow"], b.get("summary", "")[:70])
