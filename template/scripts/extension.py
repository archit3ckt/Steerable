"""The Steerable browser extension: the owner's own logins, straight from their own browser.

Some sites won't let an automated browser log in (a "Sign in with Google" button, a check for a
human every time). So the owner logs in as they always do, in their own Chrome, and the
extension sends that one site's cookies here; routines then use them like any saved login
(integrations.site_browser). It keeps them fresh: when the site renews the session, or the
owner logs in again, the new cookies follow on their own.

Pairing: the dashboard shows a one-time code (10 minutes, a few tries); the extension trades it
for a token, which only its hash is kept of, in .cache/extension.json. The extension only ever
sends sites the owner switched on, and the sites that forbid automated use are refused here
too (sites.check_url).
"""
import hashlib
import json
import secrets
import time

from common import CACHE, log_run

STATE = CACHE / "extension.json"
CODE_MINUTES = 10
CODE_TRIES = 5
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # none that look alike


class ExtensionError(RuntimeError):
    """Something the owner can be shown as is."""


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write(state: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.chmod(0o600)
    tmp.replace(STATE)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_code() -> dict:
    """A one-time pairing code for the dashboard to show: {"code": "ABCD-EFGH", "minutes"}."""
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    state = _load()
    state["code"] = {"hash": _hash(raw), "expires": time.time() + CODE_MINUTES * 60, "tries": 0}
    _write(state)
    return {"code": f"{raw[:4]}-{raw[4:]}", "minutes": CODE_MINUTES}


def pair(code: str, browser_name: str = "") -> dict:
    """The extension trades the code for its token: {"token"}. The code works once."""
    state = _load()
    waiting = state.get("code")
    given = "".join(c for c in (code or "").upper() if c in ALPHABET)
    if not waiting or waiting["expires"] < time.time() or waiting["tries"] >= CODE_TRIES:
        state.pop("code", None)
        _write(state)
        raise ExtensionError("That code has expired. Make a new one on your dashboard's Connections page.")
    if not secrets.compare_digest(_hash(given), waiting["hash"]):
        waiting["tries"] += 1
        _write(state)
        raise ExtensionError("That isn't the code on your dashboard. Check it and try again.")
    token = secrets.token_urlsafe(32)
    state.pop("code")
    # One browser at a time: pairing another replaces it.
    state["token"] = {"hash": _hash(token), "pairedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "browser": (browser_name or "").strip()[:60]}
    _write(state)
    log_run("extension", "paired")
    return {"token": token}


def valid(token: str) -> bool:
    paired = _load().get("token")
    return bool(paired and token and secrets.compare_digest(_hash(token), paired["hash"]))


def status() -> dict:
    paired = _load().get("token")
    return {"paired": bool(paired), "pairedAt": paired["pairedAt"] if paired else None,
            "browser": paired.get("browser") if paired else None}


def unpair() -> dict:
    state = _load()
    state.pop("token", None)
    state.pop("code", None)
    _write(state)
    log_run("extension", "unpaired")
    return status()
