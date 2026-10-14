"""Changing a routine that's already running. The COO (or the daily upkeep, for a routine below
the engine's standards) proposes the change; it waits in the owner's Decisions ("Update Job
scan?"); when they approve, the builder changes the routine in its own worktree, tests it in a
practice run, checks it against the standards and only then switches to it (builder.start_change).
Until then, and if it can't be done, the routine keeps running as it is.

    .venv/bin/python scripts/change.py job_scan "Send the new matches to the owner in the chat" --why "They don't see the list"
"""
import argparse
import fcntl
import json
import secrets
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from common import CACHE, ROOT, TASKS, log_run, now_iso, task_title
from ops_db import record_event

STORE = CACHE / "changes.json"
STANDARDS = ("Keep what it finds in a proper table instead of files of its own, remember what it already checked only "
             "as long as it needs to, and show which step it's on while it runs. What it does stays the same.")


class ChangeError(Exception):
    """Something to tell the COO, in plain words."""


@contextmanager
def _store():
    CACHE.mkdir(exist_ok=True)
    with (CACHE / "changes.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(STORE.read_text()) if STORE.exists() else {}
        yield data
        STORE.write_text(json.dumps(data, indent=1))


def _task(workflow: str) -> str | None:
    """The routine's approved, open task line."""
    for line in TASKS.read_text().splitlines():
        if line.startswith("- [ ]") and f"@workflow:{workflow}" in line and "needs:approval" not in line:
            return line[6:]
    return None


def propose(workflow: str, what: str, why: str = "", auto: str = "") -> dict:
    """Put a change to an existing routine to the owner. One waiting change per routine: a new
    one replaces it. `auto` marks one the engine proposed itself (like "standards")."""
    what = (what or "").strip()
    if not what or len(what) > 2000:
        raise ChangeError("Say what to change, in a sentence or a few (up to 2,000 characters).")
    if not (ROOT / "workflows" / f"{workflow}.py").exists():
        raise ChangeError(f"There's no routine {workflow} to change. New routines are proposed with propose.py.")
    task = _task(workflow)
    if not task:
        raise ChangeError(f"{workflow} isn't an approved routine, so there's nothing running to change.")
    with _store() as data:
        for c in data.values():
            if c["workflow"] == workflow and c["status"] == "waiting":
                c["status"] = "replaced"
        cid = "c" + secrets.token_hex(4)
        data[cid] = {"id": cid, "workflow": workflow, "title": task_title(task), "task": task, "change": what,
                     "why": why.strip()[:500], "auto": auto, "status": "waiting", "at": now_iso()}
    log_run("change", "proposed", workflow=workflow, auto=auto or None)
    if not auto:
        record_event(f"Proposed a change to {task_title(task)}: {what[:150]}", who="COO", workflow=workflow)
    return data[cid]


def pending() -> list[dict]:
    if not STORE.exists():
        return []
    return [c for c in json.loads(STORE.read_text()).values() if c["status"] == "waiting"]


def recently(workflow: str, auto: str, days: int = 30) -> bool:
    """Was an automatic change like this proposed for this routine lately (waiting, or answered)?"""
    if not STORE.exists():
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    return any(c["workflow"] == workflow and c.get("auto") == auto and (c["status"] == "waiting" or c["at"] >= cutoff)
               for c in json.loads(STORE.read_text()).values())


def resolve(cid: str, approve: bool) -> dict | None:
    """The owner's answer. Approving starts the update (builder.start_change). None if it isn't waiting."""
    import builder

    with _store() as data:
        c = data.get(cid)
        if not c or c["status"] != "waiting":
            return None
        c["status"] = "approved" if approve else "declined"
        c["answered"] = now_iso()
    if approve:
        bid = builder.start_change(c["workflow"], c["task"], c["change"])
        if not bid:
            record_event(f"Couldn't start updating {c['title']}: it's being worked on already.", who="COO", workflow=c["workflow"])
    else:
        record_event(f"Kept {c['title']} as it is.", who="CEO", workflow=c["workflow"])
    return c


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workflow")
    parser.add_argument("what", help="what to change, in the owner's words")
    parser.add_argument("--why", default="", help="one sentence: why it's worth it")
    args = parser.parse_args()
    try:
        c = propose(args.workflow, args.what, args.why)
    except ChangeError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"It's in the owner's Decisions: update {c['title']}? It keeps running as it is until the new version is tested.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
