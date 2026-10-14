"""What a routine remembers between runs to avoid repeating work: the job IDs it already checked,
when it last reminded someone, the page it read up to. Working state, not records (those go in
the Library, library.py) and not knowledge (that's learned into memory/ and skills, lesson()).

Everything here expires, so nothing grows forever: keep_days on each entry, and the daily upkeep
(upkeep.py) deletes what's expired and what belongs to routines that no longer exist. In a dry
run (STEERABLE_DRY_RUN=1) reads work and writes are skipped, so a test leaves no trace.

    from state import State
    state = State()                          # this routine's (STEERABLE_WORKFLOW, or the script's name)
    if not state.seen(f"board:{job_id}", keep_days=60):
        ...                                  # first time: judge it
    state.set("last_reminder", "2026-10-13", keep_days=30)
    state.get("last_reminder")

    python scripts/state.py show job_scan
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from common import CACHE

DB = CACHE / "state.db"
DEFAULT_DAYS = 90  # for set() without keep_days: long enough for any schedule, not forever
SCHEMA = """CREATE TABLE IF NOT EXISTS state (
    routine TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
    expires REAL NOT NULL, updated REAL NOT NULL, PRIMARY KEY (routine, key))"""


def _connect() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(SCHEMA)
    return con


def _days(keep_days: float | None) -> float:
    days = DEFAULT_DAYS if keep_days is None else float(keep_days)
    if not 0 < days <= 3650:
        raise ValueError("keep_days must be between 0 and 3650")
    return days


class State:
    def __init__(self, routine: str | None = None):
        self.routine = routine or os.environ.get("STEERABLE_WORKFLOW") or Path(sys.argv[0]).stem
        self.dry = os.environ.get("STEERABLE_DRY_RUN") == "1"

    def get(self, key: str, default=None):
        with _connect() as con:
            row = con.execute("SELECT value FROM state WHERE routine = ? AND key = ? AND expires > ?",
                              (self.routine, key, time.time())).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value, keep_days: float | None = None) -> None:
        if self.dry:
            return
        now = time.time()
        with _connect() as con:
            con.execute("INSERT OR REPLACE INTO state VALUES (?, ?, ?, ?, ?)",
                        (self.routine, key, json.dumps(value), now + _days(keep_days) * 86400, now))

    def seen(self, key: str, keep_days: float = 60) -> bool:
        """True if this key was marked before (and hasn't expired); marks it now either way, for keep_days."""
        known = self.get(key) is not None
        if not known:
            self.set(key, 1, keep_days)
        return known

    def forget(self, key: str) -> None:
        if self.dry:
            return
        with _connect() as con:
            con.execute("DELETE FROM state WHERE routine = ? AND key = ?", (self.routine, key))

    def keys(self, prefix: str = "") -> list[str]:
        with _connect() as con:
            return [r[0] for r in con.execute(
                "SELECT key FROM state WHERE routine = ? AND key LIKE ? AND expires > ? ORDER BY key",
                (self.routine, prefix.replace("%", r"\%") + "%", time.time()))]


def prune(keep_routines: set[str] | None = None) -> int:
    """Delete what's expired, and everything of routines not in keep_routines (when given)."""
    if not DB.exists():
        return 0
    with _connect() as con:
        gone = con.execute("DELETE FROM state WHERE expires <= ?", (time.time(),)).rowcount
        if keep_routines is not None:
            marks = ",".join("?" * len(keep_routines)) or "''"
            gone += con.execute(f"DELETE FROM state WHERE routine NOT IN ({marks})", tuple(keep_routines)).rowcount
    return gone


def main() -> int:
    if sys.argv[1:2] == ["show"] and len(sys.argv) == 3:
        s = State(sys.argv[2])
        print(json.dumps({k: s.get(k) for k in s.keys()}, indent=1, ensure_ascii=False))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
