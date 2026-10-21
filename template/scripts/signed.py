"""What the owner authorized from Decisions by signing it (switching a routine on, letting it run on its
own), kept with what it was and how to undo it, for "Signed by you" on the Decisions page. Undoing is
the agent API's (it switches the routine off, or back under watch); this only keeps the list.

    python scripts/signed.py      # the latest, newest first
"""
import fcntl
import json
import secrets
import sys
from contextlib import contextmanager

from common import CACHE, now_iso

FILE = CACHE / "signed.json"
KEEP = 200


def _load() -> list[dict]:
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return []


@contextmanager
def _list():
    with (CACHE / "signed.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        items = _load()
        yield items
        FILE.write_text(json.dumps(items[-KEEP:], ensure_ascii=False, indent=1))


def record(title: str, kind: str, workflow: str, decision: str) -> dict:
    """One signature: `kind` switch_on (a routine switched on) or trust (let it run without checks)."""
    entry = {"id": "s" + secrets.token_hex(4), "title": title, "kind": kind, "workflow": workflow,
             "decision": decision, "at": now_iso()}
    with _list() as items:
        items.append(entry)
    return entry


def recent(limit: int = 20) -> list[dict]:
    return list(reversed(_load()))[:limit]


def get(sid: str) -> dict | None:
    return next((i for i in _load() if i["id"] == sid), None)


def mark_undone(sid: str) -> dict | None:
    with _list() as items:
        for i in items:
            if i["id"] == sid and not i.get("undone"):
                i["undone"] = now_iso()
                return dict(i)
    return None


if __name__ == "__main__":
    for i in recent():
        print(i["at"][:16], i["kind"], i["title"], "(undone)" if i.get("undone") else "", file=sys.stdout)
