"""Heartbeat: run from cron. Checks tasks.md for due work and runs only what's needed.

No model call happens here. If there's no runnable task, it logs "idle" and exits.
A task runs only if it is open, due, tagged @workflow:<name> with workflows/<name>.py
present, and not waiting for approval or paused. The engine's own jobs (common.SYSTEM_JOBS:
learning from the day, tidying skills) aren't tasks: they run on a built-in schedule, kept in
.cache/system_jobs.json. Each workflow runs as its own subprocess:
    exit 0  success (one-off tasks get ticked done)
    exit 2  ran, but its own quality check failed (stdout says why)
    other   crash
On exit 2 or a crash, the playbook kicks in: the task is paused (contain) and an
incident opens, which wakes Claude to diagnose and prepare a fix (scripts/incident.py).
A system job that fails is only logged and tried again next time: its code is the engine's,
so the fix is an engine update, not a patch made here.

    python scripts/heartbeat.py            # run due work
    python scripts/heartbeat.py --dry-run  # show what would run
"""
import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import builder
import burst
from alert import alert
import incident
import runtrace
import supervise
from incident import open_incident
from ops_db import record_event
from budget import BudgetExceeded, check
from common import (CACHE, ROOT, RUN_LOG, STEPS, SYSTEM_JOBS, TASKS, due_again, edit_tasks, library_counts, log_run, new_run_id,
                    now_iso, replace_task_line, stamp)

WORKFLOWS = ROOT / "workflows"
SCRIPTS = ROOT / "scripts"
LOCK = ROOT / ".heartbeat.lock"
SYSTEM_STATE = CACHE / "system_jobs.json"
NOW = CACHE / "heartbeat_now.json"  # what this heartbeat is busy with, for the app's status panel
TASK_RE = re.compile(r"^- \[ \] (.+)$")


def uses_browser(script: Path) -> bool:
    """Routines that drive a website (Playwright) run in a burst Job when there are any."""
    try:
        source = script.read_text()
    except OSError:
        return False
    return "site_browser" in source or "playwright" in source


def tag(text: str, name: str) -> str | None:
    m = re.search(rf"{name}:(\S+)", text)
    return m.group(1) if m else None


def runnable_tasks(lines: list[str]) -> tuple[list[tuple[int, str, str]], list[str], list[tuple[str, str]]]:
    """(ready to run, waiting, approved but not built yet as (workflow, task))."""
    today, now, ready, waiting, unbuilt = date.today().isoformat(), datetime.now(), [], [], []
    for i, line in enumerate(lines):
        m = TASK_RE.match(line)
        if not m:
            continue
        text = m.group(1)
        workflow = tag(text, "@workflow")
        if not workflow:
            continue  # manual task for a human or a Claude session
        if workflow in SYSTEM_JOBS:
            continue  # the engine's own job, from an older tasks.md: it runs on the built-in schedule
        if "paused:" in text:
            continue  # contained, waiting on an incident
        if "needs:approval" in text:
            waiting.append(text)
            continue
        if (due := tag(text, "due")) and due > today:
            continue
        if tag(text, "every") and not due_again(text, now):
            continue  # recurring, and it already ran this time round
        if not (WORKFLOWS / f"{workflow}.py").exists():
            waiting.append(f"{text}  (missing workflows/{workflow}.py)")
            unbuilt.append((workflow, text))
            continue
        ready.append((i, text, workflow))
    return ready, waiting, unbuilt


def _system_state() -> dict:
    try:
        return json.loads(SYSTEM_STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def adopt_system_tasks() -> None:
    """Older companies have the engine's own jobs as lines in tasks.md. Take them out, keeping
    when each last ran, so they carry on from the built-in schedule."""
    state, found = _system_state(), False

    def without(lines: list[str]) -> list[str]:
        nonlocal found
        kept = []
        for line in lines:
            name = tag(line, "@workflow") if TASK_RE.match(line) else None
            if name in SYSTEM_JOBS:
                found = True
                if (last := tag(line, "last")) and last > state.get(name, {}).get("last", ""):
                    state[name] = {**state.get(name, {}), "last": last}
            else:
                kept.append(line)
        return kept

    if any(f"@workflow:{name}" in TASKS.read_text() for name in SYSTEM_JOBS):
        edit_tasks(without)
    if found:
        SYSTEM_STATE.write_text(json.dumps(state))


def doing(**what) -> None:
    """Note what the heartbeat is working on (agent_api's status() shows it); no arguments clears it."""
    if what:
        NOW.write_text(json.dumps({**what, "since": now_iso()}))
    else:
        NOW.unlink(missing_ok=True)


def due_system_jobs() -> list[str]:
    today, state = date.today(), _system_state()
    due = []
    for name, days in SYSTEM_JOBS.items():
        last, tried = state.get(name, {}).get("last"), state.get(name, {}).get("tried")
        on_schedule = not last or today - date.fromisoformat(last) >= timedelta(days=days)
        # After a failure it's tried again the next day, not the next week.
        if on_schedule and tried != today.isoformat() and (SCRIPTS / f"{name}.py").exists():
            due.append(name)
    return due


def run_system_jobs() -> None:
    """Run the engine's own jobs that are due. A failure is logged and tried again tomorrow."""
    for name in due_system_jobs():
        try:
            check()
        except BudgetExceeded:
            return  # they wait for next month's allowance, like everything else
        today = date.today().isoformat()
        doing(system=name)
        try:
            proc = subprocess.run([sys.executable, str(SCRIPTS / f"{name}.py")], cwd=ROOT,
                                  capture_output=True, text=True, timeout=1800, env={**os.environ, "STEERABLE_CONTEXT": "system"})
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            code, out, err = -1, "", "timed out"
        state = _system_state()
        mine = state.get(name, {})
        if code == 0:
            state[name] = {"last": today}
            log_run("heartbeat", "ok", system=name, workflow=name, stdout=out[-2000:])
            # Not on the owner's board: the engine's own jobs aren't work done for them (the run log keeps it).
        else:
            # Exit 2 (its own quality check) or a crash: not the company's to fix, and not the
            # owner's to hear about. status.py shows it to whoever runs the engine.
            state[name] = {**mine, "tried": today, "failures": mine.get("failures", 0) + 1, "error": (err or out).strip()[-500:]}
            log_run("heartbeat", "system_error", system=name, workflow=name, exit=code, stdout=out[-2000:], stderr=err[-2000:])
            burst.report_problem("system_job", name, (err or out).strip())  # in Steerable Cloud: to whoever runs it
        SYSTEM_STATE.write_text(json.dumps(state))


def catch_up_brief() -> None:
    """If the machine slept through 09:00, send today's brief on the first heartbeat after."""
    now = datetime.now()
    if not 9 <= now.hour < 22 or not RUN_LOG.exists():
        return
    today = now.date().isoformat()
    if any('"script": "brief"' in line and today in line
           for line in RUN_LOG.read_text().splitlines()[-500:]):
        return
    subprocess.run([sys.executable, str(ROOT / "scripts/brief.py")], cwd=ROOT, timeout=120)


def main(dry_run: bool) -> int:
    if not dry_run:
        catch_up_brief()
        adopt_system_tasks()
        builder.recover_stale()  # background work a restart killed: never "working on it" forever
        builder.retry_failed()  # failed builds are the system's: tried again on their own, never the owner's
        incident.recover_stale()
    lines = TASKS.read_text().splitlines()
    ready, waiting, unbuilt = runnable_tasks(lines)
    if unbuilt and not dry_run:
        builder.ensure_builds(unbuilt)  # approved routines nobody has started building
    if dry_run:
        for name in due_system_jobs():
            print(f"would run {name} (system job)")
        for _, text, wf in ready:
            print(f"would run {wf}: {text}")
        return 0
    run_system_jobs()
    if not ready:
        log_run("heartbeat", "idle", waiting=waiting)
        return 0
    try:
        check()
    except BudgetExceeded as e:
        log_run("heartbeat", "budget_stop", error=str(e))
        alert("budget_stop", "Monthly budget cap hit, workflows paused", str(e))
        return 1

    today = date.today().isoformat()
    for i, text, workflow in ready:
        run_routine(lines[i], text, workflow, today)
    return 0


def run_routine(line: str, text: str, workflow: str, today: str, manual: bool = False) -> bool:
    """Run one routine as the schedule does: its context, its steps, its log, a problem opened if it
    fails. A manual run ("Run now") doesn't move the schedule. Returns whether it went fine."""
    # The owner approved this routine, so its changes through connected services go
    # through without asking again (integrations.py marks its calls).
    script = WORKFLOWS / f"{workflow}.py"
    doing(routine=workflow)
    (STEPS / f"{workflow}.json").unlink(missing_ok=True)  # a step from the last run isn't this run's
    run = new_run_id()  # what it changes in the library is kept under this, for the run's change table
    routine_env = {**os.environ, "STEERABLE_CONTEXT": "routine", "STEERABLE_WORKFLOW": workflow, "STEERABLE_RUN": run}
    watched = supervise.watching(workflow)  # its first live runs: what it can't undo is checked first
    if watched:
        runtrace.start(run, workflow=workflow, kind="watched", task=text)
        routine_env.update(STEERABLE_WATCH="1", STEERABLE_TRACE=run)
    if uses_browser(script):  # Chromium needs a burst Job's memory, not the small agent's
        proc = burst.run([sys.executable, str(script), text], kind="browser", timeout=1800, env=routine_env)
    else:
        proc = subprocess.run([sys.executable, str(script), text], cwd=ROOT, capture_output=True, text=True,
                              timeout=1800, env=routine_env)
    ok = proc.returncode == 0
    # A watched run the supervisor stopped (common.Held) isn't a crash: the owner hears what was held.
    held = watched and not ok and "common.Held:" in (proc.stderr or "")
    (STEPS / f"{workflow}.json").unlink(missing_ok=True)
    changes = library_counts(run)
    log_run("heartbeat", "ok" if ok or held else "error", workflow=workflow, task=text, **({"manual": True} if manual else {}),
            run=run, **({"changes": changes} if changes else {}), **({"trace": run} if watched else {}),
            **({"held": True} if held else {}), stdout=proc.stdout[-2000:], stderr=proc.stderr[-2000:])
    doing()
    if watched:
        lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
        runtrace.update(run, finished=now_iso(), ok=ok or held, summary=(lines[-1][:200] if lines else ""))
        supervise.after_run(workflow, run, ok or held)
        held = held or any(e["kind"] == "held" for e in (runtrace.load(run) or {}).get("events", []))
    if not ok and not held:
        kind = "quality" if proc.returncode == 2 else "crash"
        what = "failed its quality check" if kind == "quality" else "crashed"
        iid = open_incident(kind, f"workflow:{workflow}", f"Workflow '{workflow}' {what}",
                            f"Task: {text}\nExit code: {proc.returncode}\n"
                            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}",
                            workflow=workflow, task=text)
        if iid:  # contain: no reruns until the incident is resolved
            replace_task_line(line, line + f"  paused:{iid}")
        supervise.start(workflow, why="problem")  # however it's resolved, its next runs are checked again
        return False
    if ok:  # a watched run is on the timeline through supervise.after_run too
        record_event(f"Ran OK{' (you asked)' if manual else ''}: {proc.stdout.strip()[-150:] or workflow}", workflow=workflow, ref=run)
    if tag(text, "every"):
        if not manual:
            new = re.sub(r"\s*last:\S+", "", line) + f"  last:{stamp(text, datetime.now())}"
            replace_task_line(line, new)
    elif held:  # a one-off that was held back isn't done: it waits for the owner's answer
        replace_task_line(line, line + "  paused:owner")
    else:
        # Edit just this line in the current file: approvals or pauses made while it ran must survive.
        replace_task_line(line, line.replace("- [ ]", "- [x]", 1) + f"  done:{today}")
    return ok


MANUAL = CACHE / "manual-runs"
JUST_RAN = timedelta(minutes=5)  # a run asked for sooner than this after one finished only repeats it


def start_manual(workflow: str) -> None:
    """ "Run now": start one run of an approved routine in the background. Raises ValueError, in
    plain words, when it can't (not running, already running or about to)."""
    import common

    found = next((m.group(1) for line in TASKS.read_text().splitlines() if (m := TASK_RE.match(line))
                  and tag(m.group(1), "@workflow") == workflow), None)
    if not found or "needs:approval" in found or "paused:" in found or not (WORKFLOWS / f"{workflow}.py").exists():
        raise ValueError("Only a routine that's switched on can be run now: not one waiting for approval, paused or being set up.")
    try:
        running = json.loads(NOW.read_text()).get("routine") == workflow
    except (OSError, ValueError):
        running = False
    if running:
        raise ValueError("It's running right now.")
    MANUAL.mkdir(exist_ok=True)
    marker = MANUAL / f"{workflow}.pid"
    try:
        waiting = common.alive(int(marker.read_text()))
    except (OSError, ValueError):
        waiting = False
    if waiting:
        raise ValueError("It's about to run.")
    recent = [json.loads(l) for l in RUN_LOG.read_text().splitlines()[-300:]] if RUN_LOG.exists() else []
    last = next((r for r in reversed(recent) if r.get("script") == "heartbeat"
                 and r.get("workflow") == workflow and r.get("status") in ("ok", "error")), None)
    if last and datetime.now(timezone.utc) - datetime.fromisoformat(last["ts"]) < JUST_RAN:
        said = (last.get("stdout") or "").strip().splitlines()
        outcome = f" It said: {said[-1][:300]}" if last["status"] == "ok" and said else (
            " It hit a problem." if last["status"] == "error" else "")
        raise ValueError(f"It finished a few minutes ago, so there's nothing new to find yet.{outcome}")
    proc = subprocess.Popen([sys.executable, str(Path(__file__)), "--run", workflow], cwd=ROOT, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    marker.write_text(str(proc.pid))
    log_run("run_now", "started", workflow=workflow)


def run_now(workflow: str) -> int:
    """The background half of start_manual: wait for the heartbeat if it's busy (runs never overlap),
    then run the routine once, as the schedule would."""
    try:
        with LOCK.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                check()
            except BudgetExceeded as e:
                log_run("run_now", "budget_stop", workflow=workflow, error=str(e))
                return 1
            for line in TASKS.read_text().splitlines():
                m = TASK_RE.match(line)
                if m and tag(m.group(1), "@workflow") == workflow and "needs:approval" not in line and "paused:" not in line:
                    return 0 if run_routine(line, m.group(1), workflow, date.today().isoformat(), manual=True) else 1
            return 1
    finally:
        (MANUAL / f"{workflow}.pid").unlink(missing_ok=True)
        doing()

if __name__ == "__main__":
    if sys.argv[1:2] == ["--run"] and len(sys.argv) == 3:
        sys.exit(run_now(sys.argv[2]))
    with LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit(0)  # previous heartbeat still running
        try:
            sys.exit(main("--dry-run" in sys.argv))
        except Exception as e:
            log_run("heartbeat", "crash", error=repr(e))
            alert("heartbeat_crash", "Heartbeat crashed", repr(e))
            raise
        finally:
            doing()
