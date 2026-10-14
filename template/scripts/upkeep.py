"""Daily upkeep, one of the engine's own jobs (common.SYSTEM_JOBS): keeps what grows from growing
forever. No model, no cost.

- Routines' working state (state.py): what's expired, and everything of routines that are gone.
- logs/runs.jsonl: a year of runs; their full output only for the last 30 days.
- logs/spend.jsonl: about 13 months (this month's spending and last year's, for comparison).
- Lessons routines noted (common.lesson): 30 days, long after the learning review has read them.
- Leftovers: build streams and social drafts that are done, after a week or a month.

And it watches, reporting what it finds (burst.report_problem, and the run log for status.py):
- the databases (ops.db, library.db, state.db) pass SQLite's own integrity check;
- every routine meets the engine's standards (routine_check.py), older ones included;
- nothing outside the managed places grows past 5 MB, and memory stays under 200 KB.

Kept forever on purpose: the chat, the timeline (ops.db), memory/ and skills, files/ and the
library: those are the owner's.

    python scripts/upkeep.py
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlite3

import burst
import routine_check
import state
from common import CACHE, LESSONS, LOGS, ROOT, RUN_LOG, SYSTEM_JOBS, log_run

BIG = 5 * 1024 * 1024
MANAGED = {".git", ".venv", ".home", "files", "logs", "ops.db", "library.db", "node_modules"}
MEMORY_LIMIT = 200_000

RUNS_DAYS, OUTPUT_DAYS, SPEND_DAYS, LESSON_DAYS = 365, 30, 400, 30
BULKY = ("stdout", "stderr", "output", "body")


def _age_days(ts: str, now: datetime) -> float:
    try:
        return (now - datetime.fromisoformat(ts)).total_seconds() / 86400
    except (ValueError, TypeError):
        return 0.0


def trim_jsonl(path: Path, keep_days: int, strip_after: int | None = None) -> int:
    """Drop entries older than keep_days; past strip_after days, drop their bulky output. Lines
    appended while this runs are carried over. Returns how many entries were dropped."""
    if not path.exists():
        return 0
    now = datetime.now(timezone.utc)
    raw = path.read_bytes()
    kept, dropped = [], 0
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        age = _age_days(e.get("ts", ""), now)
        if age > keep_days:
            dropped += 1
            continue
        if strip_after is not None and age > strip_after:
            e = {k: v for k, v in e.items() if k not in BULKY}
        kept.append(json.dumps(e))
    if not dropped and strip_after is None:
        return 0
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(x + "\n" for x in kept))
    with path.open("rb") as f, tmp.open("ab") as out:  # whatever was appended since we read it
        f.seek(len(raw))
        out.write(f.read())
    os.replace(tmp, path)
    return dropped


def tidy_files(folder: Path, pattern: str, older_than_days: float, keep=lambda p: False) -> int:
    if not folder.exists():
        return 0
    cutoff, gone = time.time() - older_than_days * 86400, 0
    for p in folder.glob(pattern):
        if p.is_file() and p.stat().st_mtime < cutoff and not keep(p):
            p.unlink(missing_ok=True)
            gone += 1
    return gone


def watch() -> dict:
    """What's wrong, by kind: databases that fail their check, routines below standard, files that grew too big."""
    found = {"databases": [], "routines": [], "growth": []}
    for db in (ROOT / "ops.db", ROOT / "library.db", CACHE / "state.db"):
        if db.exists():
            try:
                with sqlite3.connect(db, timeout=30) as con:
                    result = con.execute("PRAGMA quick_check").fetchone()[0]
            except sqlite3.DatabaseError as e:
                result = str(e)
            if result != "ok":
                found["databases"].append(f"{db.name}: {result}")
    for path in sorted((ROOT / "workflows").glob("*.py")):
        if not path.name.startswith("_") and (problems := routine_check.check(path)):
            found["routines"].append(f"{path.stem}: {len(problems)} problem(s), first: {problems[0]}")
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] in MANAGED or rel == Path(".cache/state.db") or not path.is_file():
            continue
        try:
            if path.stat().st_size > BIG:
                found["growth"].append(f"{rel}: {path.stat().st_size // (1024 * 1024)} MB")
        except OSError:
            continue
    memory = sum(p.stat().st_size for p in (ROOT / "memory").rglob("*") if p.is_file()) if (ROOT / "memory").exists() else 0
    if memory > MEMORY_LIMIT:
        found["growth"].append(f"memory/: {memory // 1000} KB")
    for kind, items in found.items():
        if items:
            burst.report_problem(f"upkeep_{kind}", kind, "; ".join(items)[:2000])
    propose_standards([i.split(":", 1)[0] for i in found["routines"]])
    return found


def propose_standards(routines: list[str]) -> None:
    """Routines below the engine's standards get a change proposed to the owner (once a month at
    most, each): the builder then moves them onto the library and expiring state."""
    import change

    for name in routines:
        if change.recently(name, auto="standards") or any(c["workflow"] == name for c in change.pending()):
            continue  # asked lately, or another change to it is already waiting
        try:
            change.propose(name, change.STANDARDS, auto="standards",
                           why="It keeps its data in files of its own, which grow forever and you can't look through.")
        except change.ChangeError:
            continue  # not an approved, running routine: nothing to change


def library_details() -> int:
    """Old and new values of library changes past library.DETAIL_DAYS (a damaged library is the watchdog's to report)."""
    import library

    try:
        return library.forget_details()
    except sqlite3.DatabaseError:
        return 0


def traces() -> int:
    """Practice and watched runs' pictures past their keeping, except those the owner still has to look at."""
    import builder
    import runtrace
    import supervise

    keep = {b["trace"] for b in builder.load().values() if b.get("trace") and b["status"] == "ready"}
    keep |= {r["trace"] for r in supervise.reviews()}
    import incident

    keep |= {(i.get("verdict") or {}).get("practice") for i in incident.awaiting()} - {None}
    return runtrace.prune(keep)


def main() -> int:
    routines = {p.stem for p in (ROOT / "workflows").glob("*.py") if not p.name.startswith("_")} | set(SYSTEM_JOBS)
    done = {
        "state": state.prune(keep_routines=routines),
        "runs": trim_jsonl(RUN_LOG, RUNS_DAYS, strip_after=OUTPUT_DAYS),
        "spend": trim_jsonl(LOGS / "spend.jsonl", SPEND_DAYS),
        "lessons": trim_jsonl(LESSONS, LESSON_DAYS),
        "library details": library_details(),
        "build streams": tidy_files(CACHE / "build-live", "*.jsonl", 7),
        "run pictures": traces(),
        "social drafts": tidy_files(CACHE / "social", "*.json", 30,
                                    keep=lambda p: json.loads(p.read_text()).get("status") == "waiting"),
    }
    found = watch()
    log_run("upkeep", "ok", **{k.replace(" ", "_"): v for k, v in done.items()},
            **{f"watch_{k}": v for k, v in found.items() if v})
    cleared = sum(done.values())
    print(f"Cleared {cleared} old item{'s' if cleared != 1 else ''} no longer needed." if cleared else "Nothing old to clear.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
