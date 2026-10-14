"""Things only the owner can give the COO: a private feed link, an API key, an account number.

The owner never edits files. When a routine needs such a value, the COO asks for it:

    .venv/bin/python scripts/vault.py ask REDDIT_INBOX_RSS --label "your Reddit inbox link" \\
        --why "So the reply tracker sees replies to your answers." --url https://old.reddit.com/prefs/feeds

The request shows up in the owner's Decisions with an "Add it" button: a small form in the app,
with where to find it. The value is kept in .cache/vault.json (readable by this user only; no
agent can read .cache), and routines read it like any setting: env("REDDIT_INBOX_RSS")
(common.env falls back to the vault). Values never appear in the chat, the export or the logs.

    .venv/bin/python scripts/vault.py list      # what's been asked for and what's saved (never values)
"""
import argparse
import fcntl
import json
import re
import sys
from contextlib import contextmanager

from common import CACHE, log_run, now_iso
from ops_db import record_event

FILE = CACHE / "vault.json"
NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
# The engine's own settings, never set this way.
RESERVED = re.compile(r"^(ANTHROPIC_|STEERABLE_|AGENT_API_|TELEGRAM_|COMPANY_|DASHBOARD_|CLAUDE|PATH$|HOME$)")


class VaultError(ValueError):
    """Something the owner can be shown as is."""


def check_name(name: str) -> str:
    name = name.strip().upper()
    if not NAME.match(name) or RESERVED.match(name):
        raise VaultError("That can't be set here.")
    return name


@contextmanager
def _store():
    CACHE.mkdir(exist_ok=True)
    with (CACHE / "vault.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data.setdefault("values", {})
        data.setdefault("requests", {})
        yield data
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.chmod(0o600)
        tmp.replace(FILE)


def human(name: str) -> str:
    return name.replace("_", " ").lower()


def ask(name: str, label: str, why: str, url: str | None = None, hint: str | None = None) -> dict:
    """Ask the owner for a value. Asking again for the same one just updates the request."""
    name = check_name(name)
    request = {"label": label.strip()[:80] or human(name), "why": why.strip()[:300],
               "url": (url or "").strip()[:300] or None, "hint": (hint or "").strip()[:200] or None, "at": now_iso()}
    if request["url"] and not request["url"].startswith(("https://", "http://")):
        request["url"] = None
    with _store() as data:
        new = name not in data["requests"]
        data["requests"][name] = request
    if new:
        record_event(f"Asked you for {request['label']}.", who="COO")
    log_run("vault", "asked", name=name)
    return request


def requests() -> dict[str, dict]:
    with _store() as data:
        return dict(data["requests"])


def request(name: str) -> dict:
    """What the form shows: the label, why, where to find it, and whether it's saved."""
    name = check_name(name)
    with _store() as data:
        r = data["requests"].get(name) or {"label": human(name), "why": "", "url": None, "hint": None}
        return {"name": name, **{k: r.get(k) for k in ("label", "why", "url", "hint")}, "saved": name in data["values"]}


def save(name: str, value: str) -> dict:
    name = check_name(name)
    value = value.strip()
    if not value:
        raise VaultError("Paste it in first.")
    if len(value) > 4000:
        raise VaultError("That's too long.")
    with _store() as data:
        data["values"][name] = value
        label = (data["requests"].pop(name, None) or {}).get("label") or human(name)
    record_event(f"You added {label}.", who="CEO")
    log_run("vault", "saved", name=name)
    return {"name": name, "saved": True}


def drop(name: str) -> None:
    """The owner said not now."""
    with _store() as data:
        data["requests"].pop(check_name(name), None)


def saved() -> list[str]:
    with _store() as data:
        return sorted(data["values"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the owner for a value only they have.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("name", help="what routines read it as, like REDDIT_INBOX_RSS")
    a.add_argument("--label", required=True, help="what it is, in the owner's words: 'your Reddit inbox link'")
    a.add_argument("--why", required=True, help="one sentence: what it's for")
    a.add_argument("--url", help="where they find it")
    a.add_argument("--hint", help="a short tip for finding or copying it")
    sub.add_parser("list")
    args = parser.parse_args()
    try:
        if args.cmd == "ask":
            ask(args.name, args.label, args.why, args.url, args.hint)
            print(f"Asked. It's in the owner's Decisions with a one-step form; routines read it as env(\"{check_name(args.name)}\").")
        else:
            print(json.dumps({"asked": sorted(requests()), "saved": saved()}, indent=1))
    except VaultError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
