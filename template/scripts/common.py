"""Shared helpers: paths, env loading, the run log (audit trail), and safe edits to tasks.md."""
import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
CACHE = ROOT / ".cache"
RUN_LOG = LOGS / "runs.jsonl"
TASKS = ROOT / "tasks.md"
# The engine's own jobs, with how many days apart they run (scripts/<name>.py, engine code like the
# rest of scripts/). They're part of the system, not routines of the company: the heartbeat runs them on
# this schedule, not from tasks.md; nobody approves, pauses or edits them; a failure is retried
# next time and reported to whoever runs the engine, never handed to the problem-fixer; and the
# owner never sees them (Work, Decisions, the brief), only what was learned, on the timeline.
SYSTEM_JOBS = {"learn": 1, "curate_skills": 7, "upkeep": 1}
CORE_WORKFLOWS = set(SYSTEM_JOBS)
# The engine's own code (container/entrypoint.py ENGINE_FILES): changed only by engine updates.
ENGINE_CODE = ("scripts/", "workflows/_template.py")

load_dotenv(ROOT / ".env")
LOGS.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)


COMPANY = os.environ.get("COMPANY_NAME", "Company")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    """An id for one routine run or chat turn: what it changes in the library is kept under it."""
    import secrets

    return f"r{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"


def library_counts(run: str) -> list[dict]:
    """What a run changed in the library, per table (never raises: a run's log must not break over it)."""
    try:
        import library

        return library.run_counts(run)
    except Exception as e:  # noqa: BLE001
        log_run("library", "error", error=repr(e)[:300])
        return []


def counts_words(changes: list[dict]) -> str:
    """run_counts as words: "Job openings: 12 added, 3 changed"."""
    parts = []
    for c in changes:
        bits = [f"{c[k]} {k}" for k in ("added", "changed", "archived", "restored") if c.get(k)]
        parts.append(f"{c['table']}: {', '.join(bits)}")
    return "; ".join(parts)


def env(name: str, default: str = "") -> str:
    """A setting: from the environment, else a value the owner gave in the app (vault.py). An
    empty variable counts as unset (docker-compose passes every setting, filled in or not)."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        return json.loads((CACHE / "vault.json").read_text())["values"].get(name, default)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return default


def log_run(script: str, status: str, cost_usd: float = 0.0, **details) -> None:
    """Append one line per run to logs/runs.jsonl. Every script calls this."""
    entry = {"ts": now_iso(), "script": script, "status": status,
             "cost_usd": round(cost_usd, 6), **details}
    RUN_LOG.parent.mkdir(exist_ok=True)  # a build's worktree has no logs/ (it's git-ignored)
    with RUN_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def edit_tasks(change) -> bool:
    """Read-modify-write tasks.md under a lock, so the heartbeat, the bridge and the agent API
    never overwrite each other's edits. `change` gets the current lines and returns the new
    ones. Returns True if the file changed."""
    with (CACHE / "tasks.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lines = TASKS.read_text().splitlines()
        new = change(list(lines))
        if new == lines:
            return False
        TASKS.write_text("\n".join(new) + "\n")
        return True


def replace_task_line(old: str, new: str) -> bool:
    """Swap one exact line in tasks.md. False if that line is no longer there."""
    return edit_tasks(lambda lines: [new if line == old else line for line in lines])


_TAGS = re.compile(r"\s+(?:@workflow|due|every|at|last|done|paused|rejected|saves):\S+"
                   r"|\s+(?:needs:approval|approved|@you)(?=\s|$)")
_GOAL_NOTE = re.compile(r"\s*\(goal:(?:[^()]|\([^()]*\))*\)")  # a goal may hold one (aside)


# ---------- schedules ----------
# A recurring routine's task line says how often it runs:
#   every:daily  every:weekly        once a day / once a week (last: holds the date it ran)
#   every:3h                         every N hours, 1 to 12 (last: holds the time it ran)
#   every:daily at:08:00,13:00,18:00 at those times each day, in the company's time zone
EVERY = re.compile(r"daily|weekly|([1-9]|1[0-2])h")
AT = re.compile(r"(?:(?:[01]\d|2[0-3]):[0-5]\d)(?:,(?:[01]\d|2[0-3]):[0-5]\d){0,11}")
SLACK = timedelta(minutes=10)  # the heartbeat comes round every few minutes, not on the dot


def _tag(text: str, name: str) -> str | None:
    m = re.search(rf"(?:^|\s){re.escape(name)}:(\S+)", text)
    return m.group(1) if m else None


def check_schedule(every: str | None, at: str | None) -> str | None:
    """Why a schedule isn't one the heartbeat runs, in a sentence, or None if it's fine."""
    if every and not EVERY.fullmatch(every):
        return "How often: daily, weekly, or every 1 to 12 hours (like 3h)."
    if at and not AT.fullmatch(at):
        return "Times of day as HH:MM, 24-hour, separated by commas (like 08:00,13:00,18:00), up to 12."
    if at and every not in (None, "daily"):
        return "Times of day go with a daily routine."
    return None


def times(at: str | None) -> list[str]:
    return sorted(set(at.split(","))) if at else []


def precise(text: str) -> bool:
    """Does this routine run more than once a day, so its last run is kept to the minute?"""
    every = _tag(text, "every") or ""
    return every.endswith("h") or bool(_tag(text, "at"))


def stamp(text: str, now: datetime) -> str:
    """What goes in last: after a run."""
    return now.strftime("%Y-%m-%dT%H:%M") if precise(text) else now.date().isoformat()


def due_again(text: str, now: datetime) -> bool:
    """Has a recurring routine waited long enough since its last run? (No last: it never ran.)"""
    last_text, every, at = _tag(text, "last"), _tag(text, "every") or "daily", _tag(text, "at")
    if not last_text:
        return True
    try:
        last = datetime.fromisoformat(last_text)  # a date alone is that day's midnight
    except ValueError:
        return True
    if at:
        slots = [datetime.combine(now.date() - timedelta(days=d), datetime.strptime(t, "%H:%M").time())
                 for d in (1, 0) for t in times(at)]
        passed = [s for s in slots if s <= now + SLACK]
        return bool(passed) and last < max(passed) - SLACK
    if m := re.fullmatch(r"(\d+)h", every):
        return now - last >= timedelta(hours=int(m.group(1))) - SLACK
    return (now.date() - last.date()).days >= (7 if every == "weekly" else 1)


def next_run(text: str, now: datetime) -> datetime:
    """When the heartbeat will next run this routine (to within its 15 minutes), by the rules
    due_again() applies. A routine that's due now: now."""
    every, at, last_text = _tag(text, "every"), _tag(text, "at"), _tag(text, "last")
    start = now
    if due := _tag(text, "due"):
        try:
            start = max(now, datetime.fromisoformat(due))
        except ValueError:
            pass
    if not every or due_again(text, start):
        return start
    last = datetime.fromisoformat(last_text)
    if at:
        slots = [datetime.combine(start.date() + timedelta(days=d), datetime.strptime(t, "%H:%M").time())
                 for d in (0, 1) for t in times(at)]
        return min(s for s in slots if s > start)
    if m := re.fullmatch(r"(\d+)h", every):
        return last + timedelta(hours=int(m.group(1)))
    return datetime.combine(last.date() + timedelta(days=7 if every == "weekly" else 1), datetime.min.time())


# ---------- what a routine noticed ----------
LESSONS = CACHE / "lessons.jsonl"


def kill_tree(pid, token: str | None = None, children_only: bool = False) -> int:
    """Stop a process and everything it started (an AI session, the tests it ran, a browser), however
    they were grouped: asked to stop, then made to after a few seconds. Only that very process (`token`).
    children_only: what it started, not itself. Returns how many it stopped."""
    import signal

    if not alive(pid, token):
        return 0
    parents: dict[int, list[int]] = {}
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            ppid = int(stat.read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        parents.setdefault(ppid, []).append(int(stat.parent.name))
    tree, todo = [], [int(pid)]
    while todo:
        p = todo.pop()
        tree.append(p)
        todo += parents.get(p, [])
    if children_only:
        tree = tree[1:]
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for p in tree:
            try:
                os.kill(p, sig)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.monotonic() + 5
        while sig == signal.SIGTERM and time.monotonic() < deadline and any(alive(p) for p in tree):
            time.sleep(0.2)
    return len(tree)


def lesson(text: str) -> None:
    """A routine noticed something worth learning about how the owner wants this work done
    ("Maya marked three leads from outside the delivery area as not interesting"). The daily
    learning review (learn.py) weighs it and keeps what's lasting. Not for run results or facts
    you'd look up: those are records (library.py). Skipped in dry runs; never fails."""
    if os.environ.get("STEERABLE_DRY_RUN") == "1" or not (text or "").strip():
        return
    name = os.environ.get("STEERABLE_WORKFLOW") or Path(sys.argv[0]).stem
    try:
        with LESSONS.open("a") as f:
            f.write(json.dumps({"ts": now_iso(), "workflow": name, "text": text.strip()[:500]}) + "\n")
    except OSError:
        pass


def proc_token(pid: int | None = None) -> str:
    """What tells this one process apart from a later one with the same pid: the machine's boot and
    the process's start time. A restarted container hands out small pids again, so a dead build's pid
    may belong to something else entirely; "" where /proc can't say."""
    try:
        start = Path(f"/proc/{int(pid or os.getpid())}/stat").read_text().rsplit(")", 1)[1].split()[19]
        return f"{Path('/proc/sys/kernel/random/boot_id').read_text().strip()}:{start}"
    except (OSError, IndexError, ValueError):
        return ""


def alive(pid, token: str | None = None) -> bool:
    """Is this process still running? (Background work records its pid, so a restart that
    killed it can be told apart from work that's simply slow.) With the `token` it recorded
    (proc_token), a different process that got the same pid doesn't count."""
    if token and (now := proc_token(pid)) and now != token:
        return False
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    try:  # a finished child its parent never waited for still answers: it's a zombie, not alive
        return Path(f"/proc/{int(pid)}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except (OSError, IndexError):
        return True


ONBOARDING = "## First session: onboarding"


def finish_onboarding() -> bool:
    """Take the onboarding section out of CLAUDE.md (the engine does it, so it doesn't depend on
    the COO remembering its last step), and commit. Returns whether there was one."""
    path = ROOT / "CLAUDE.md"
    text = path.read_text()
    if ONBOARDING not in text:
        return False
    start = text.index(ONBOARDING)
    nxt = text.find("\n## ", start + len(ONBOARDING))
    path.write_text(text[:start] + (text[nxt + 1:] if nxt != -1 else "").lstrip("\n"))
    import subprocess

    subprocess.run(["git", "-c", "user.name=COO", "-c", "user.email=coo@steerable.local", "commit", "-q",
                    "-m", "Onboarding done", "--", "CLAUDE.md"], cwd=ROOT, capture_output=True)
    log_run("onboarding", "done")
    return True


# ---------- telling the owner ----------
TOLD = CACHE / "told.json"
TELL_PER_DAY = 3  # per routine: news, not a stream


def tell_owner(markdown: str) -> bool:
    """News from a routine the owner should act on ("2 new wholesale orders: ..."), as a message from
    the COO in the chat (and on Telegram, if they linked it). At most TELL_PER_DAY a day per routine;
    a dry run only prints it. Returns whether it went out."""
    text = (markdown or "").strip()[:4000]
    if not text:
        return False
    name = _routine_name()
    if os.environ.get("STEERABLE_DRY_RUN") == "1":
        print(f"Would tell the owner: {text[:300]}")
        import runtrace

        runtrace.event("message", text=text)
        return False
    today = datetime.now().date().isoformat()
    try:
        told = json.loads(TOLD.read_text()) if TOLD.exists() else {}
    except ValueError:
        told = {}
    mine = told.get(name, {})
    if mine.get("day") == today and mine.get("n", 0) >= TELL_PER_DAY:
        log_run("tell_owner", "capped", workflow=name)
        return False
    told[name] = {"day": today, "n": (mine.get("n", 0) if mine.get("day") == today else 0) + 1}
    TOLD.write_text(json.dumps(told))
    with (LOGS / "chat.jsonl").open("a") as f:
        f.write(json.dumps({"ts": now_iso(), "from": "coo", "text": text, "routine": name}) + "\n")
    try:
        import telegram

        if telegram.configured():
            import dashboards

            telegram.send(dashboards.charts_as_words(text))
    except Exception as e:  # noqa: BLE001 - the chat has it either way
        log_run("tell_owner", "telegram_error", workflow=name, error=repr(e)[:200])
    log_run("tell_owner", "ok", workflow=name)
    return True


# ---------- what a routine may save ----------

def _routine_name() -> str:
    return os.environ.get("STEERABLE_WORKFLOW") or Path(sys.argv[0]).stem


def _safe(name: str) -> str:
    return re.sub(r"[^\w-]+", "-", name).strip("-")[:60] or "draft"


def save_draft(name: str, text: str) -> Path:
    """A draft for the owner to look at (an email, a reply, a quote): drafts/<routine>-<name>.md.
    In a dry run it only says so. Routines save files only this way, or with save_report()."""
    path = ROOT / "drafts" / f"{_safe(_routine_name())}-{_safe(name)}.md"
    if os.environ.get("STEERABLE_DRY_RUN") == "1":
        print(f"Would save a draft: {path.relative_to(ROOT)}")
        import runtrace

        runtrace.event("draft", name=name, text=text[:4000])
        return path
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return path


def save_report(text: str) -> Path:
    """The routine's latest results, in Markdown, replacing the last ones: files/reports/<routine>.md."""
    path = ROOT / "files" / "reports" / f"{_safe(_routine_name())}.md"
    if os.environ.get("STEERABLE_DRY_RUN") == "1":
        print(f"Would save the report: {path.relative_to(ROOT)}")
        import runtrace

        runtrace.event("draft", name="report", text=text[:4000])
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text[:200_000])
    return path


# ---------- what can't be undone ----------
ACT_WINDOW = 90  # seconds after act() said yes in which the thing itself may happen
_acting_until = 0.0


class Held(RuntimeError):
    """In a watched run, the supervisor held back a change the engine checked on its own (through a
    connected service, or a post) because the routine hadn't asked with act() first. The run stops
    there; the owner hears what was held and why."""


def acting() -> bool:
    """Is the routine inside something act() just said yes to?"""
    return time.monotonic() < _acting_until


def _brief(detail):
    if detail is None or isinstance(detail, str):
        return (detail or "")[:1500] or None
    try:
        return json.loads(json.dumps(detail, default=str)[:3000])
    except ValueError:
        return json.dumps(detail, default=str)[:1500]


def act(what: str, detail=None, kind: str = "change", target=None, _auto: bool = False) -> bool:
    """Ask before anything that can't be undone: submitting a form, sending, posting, paying,
    deleting. Do it only if this returns True.

        submit = page.get_by_role("button", name="Submit application")
        if act(f"Send the application for {job['title']} at {job['company']}", {"job": job["url"]}, kind="submit", target=submit):
            h.click(submit)
        else:
            print(f"Would apply to {job['title']} at {job['company']}")

    A practice run (STEERABLE_DRY_RUN=1) notes what it would do, with a picture of the page, and
    returns False. A watched run (a new routine's first live runs, supervise.py) has an AI look at
    it first, with the page as it is and the routine's records, and returns whether to go ahead.
    Otherwise True. `what` is for the owner: plain, specific words (who, what). `kind`: submit,
    send, post, pay, delete or change. `target`: on a website, the button it's about to press (a
    Playwright locator), marked in the picture the owner sees."""
    global _acting_until
    import runtrace

    what = " ".join(str(what or "").split())[:200] or "Do something it can't undo"
    fields = {"what": what, "action": kind, "detail": _brief(detail), **({"auto": True} if _auto else {})}
    if where := runtrace.box(target):
        fields["box"] = where
    if os.environ.get("STEERABLE_DRY_RUN") == "1":
        runtrace.event("would", **fields, shot=runtrace.shot(force=True))
        return False
    if os.environ.get("STEERABLE_WATCH") == "1":
        import supervise

        picture = runtrace.shot(force=True)
        verdict = supervise.check(what, kind, fields["detail"], picture)
        runtrace.event("did" if verdict["go"] else "held", **fields, why=verdict["why"], shot=picture)
        if not verdict["go"]:
            return False
    _acting_until = time.monotonic() + ACT_WINDOW
    return True


def guard(what: str, detail=None, kind: str = "change") -> None:
    """The engine's own check around a change it can see coming (a write through a connected
    service, a post), for routines that didn't call act() first. A practice run only notes it (the
    gateway doesn't send it); in a watched run a hold raises Held."""
    if acting():
        return
    if not act(what, detail, kind, _auto=True) and os.environ.get("STEERABLE_DRY_RUN") != "1":
        raise Held(f"Held back: {what}")


# ---------- where a running routine is ----------
STEPS = CACHE / "running"


_flow: dict = {}  # this run's note of where it is: {"step", "at", "counts", "progress"}


def _count(items) -> int | None:
    if isinstance(items, bool) or items is None:
        return None
    if isinstance(items, int):
        return max(0, items)
    try:
        return len(items)
    except TypeError:
        return None


def _note_flow(force: bool = True) -> None:
    """Write the run's note (STEPS/<routine>.json) for the routine page, which reads it while it runs and
    the heartbeat keeps its counts in the run log afterwards. Whole, never half-written. Never fails."""
    if not force and time.monotonic() - _flow.get("_written", 0) < 0.5:
        return
    _flow["_written"] = time.monotonic()
    name = os.environ.get("STEERABLE_WORKFLOW") or Path(sys.argv[0]).stem
    try:
        STEPS.mkdir(exist_ok=True)
        tmp = STEPS / f".{name}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps({k: v for k, v in _flow.items() if not k.startswith("_")}))
        tmp.replace(STEPS / f"{name}.json")
    except (OSError, ValueError):
        pass


def step(n: int, items=None) -> None:
    """A routine calls this as it starts step n of its flow chart (workflows/<name>.flow.json,
    where 0 is the trigger), so the owner's routine page shows the step it's on. `items`: what reaches
    this step (a list, or how many), shown on the arrow into it, like "150". Never fails."""
    _flow.update(step=int(n), at=now_iso())
    _flow.setdefault("counts", {})
    _flow.pop("progress", None)
    count = _count(items)
    if count is not None:
        _flow["counts"][str(int(n))] = count
    _note_flow()
    import runtrace

    runtrace.event("step", step=n, **({"count": count} if count is not None else {}))


def each(items, step: int | None = None):
    """Go through items one by one, showing how far it's got on the step it's in ("37 of 150"):
        for post in each(posts):
            ...
    It also counts them onto the arrow into that step, when step() wasn't told already. `step`: which
    step they belong to (default: the one it's on)."""
    at = int(step if step is not None else _flow.get("step", 0))
    total = _count(items)
    counts = _flow.setdefault("counts", {})
    if total is not None:
        counts.setdefault(str(at), total)
    done = 0
    _flow["progress"] = {"step": at, "done": 0, "total": total}
    _note_flow()
    for item in items:
        yield item
        done += 1
        _flow["progress"] = {"step": at, "done": done, "total": total}
        _note_flow(force=False)
    _flow["progress"] = {"step": at, "done": done, "total": total if total is not None else done}
    if total is None:
        counts.setdefault(str(at), done)
    _note_flow()


def task_title(text: str) -> str:
    """A task line in the owner's words: no checkbox, tags or (goal: ...) note."""
    text = re.sub(r"^- \[[ x]\] ", "", text)
    return re.sub(r"\s+", " ", _GOAL_NOTE.sub("", _TAGS.sub("", text))).strip()
