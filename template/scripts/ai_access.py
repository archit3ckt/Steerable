"""How the COO reaches its AI, set up from the dashboard when you run Steerable yourself.

Claude account: `claude auth login --claudeai` runs in a terminal of its own. It prints a sign-in
link; the owner opens it, signs in at claude.com, and pastes the code Claude shows them back into
the dashboard, which types it into the waiting command. Claude Code keeps the sign-in in its own
config, under HOME in the company folder, so it survives restarts and updates. One sign-in at a
time; a waiting one gives up after 10 minutes.

Jev: the owner's TypeSafe key, tried with one tiny decision before it's kept in the vault, where
decide.py finds it (common.env). With a key, everyday decisions go to Jev first.

Connected to Steerable Cloud (STEERABLE_GATEWAY_URL), the AI comes through its gateway instead,
so neither is needed.

    python scripts/ai_access.py status
"""
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import threading
import time

import decide
import vault
from common import CACHE, env, log_run
from ops_db import record_event

LOGIN_TIMEOUT = 10 * 60
URL = re.compile(r"https://claude\.(?:com|ai)/[^\s\x07\x1b]+")
ESCAPES = re.compile(r"\x1b\][^\x07]*\x07|\x1b\[[0-9;?]*[a-zA-Z]")

_lock = threading.Lock()
_login: dict = {}  # pid, fd, url, started, output


class AiError(Exception):
    """Something to tell the owner, in plain words."""


def _through_steerable() -> bool:
    return bool(env("STEERABLE_GATEWAY_URL"))


_auth: dict = {}  # claude auth status, asked at most once a minute (it takes a second)


def _auth_status() -> dict:
    if _auth.get("at", 0) > time.time() - 60:
        return _auth["status"]
    try:
        out = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=20).stdout
        status = json.loads(out)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        status = {}
    _auth.update(status=status, at=time.time())
    return status


def _forget_cached_auth() -> None:
    """Sign-ins and sign-outs count at once, here and in budget.subscription() (kept 10 minutes)."""
    _auth.clear()
    (CACHE / "auth.json").unlink(missing_ok=True)


def has_ai() -> bool:
    """Can the COO think at all: Steerable, an API key, or a signed-in Claude account?"""
    if _through_steerable() or env("ANTHROPIC_API_KEY"):
        return True
    auth = _auth_status()
    return bool(auth.get("loggedIn"))


def _read(fd: int, seconds: float) -> str:
    out, end = b"", time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    return out.decode(errors="replace")


def _stop_login() -> None:
    if not _login:
        return
    try:
        os.kill(_login["pid"], signal.SIGTERM)
        os.waitpid(_login["pid"], 0)
    except (ProcessLookupError, ChildProcessError):
        pass
    try:
        os.close(_login["fd"])
    except OSError:
        pass
    _login.clear()


def _waiting() -> bool:
    if _login and time.time() - _login["started"] > LOGIN_TIMEOUT:
        _stop_login()
    return bool(_login)


def status() -> dict:
    """Which AI the COO uses, and whether Jev is on, for the dashboard."""
    with _lock:
        waiting = _waiting()
        url = _login.get("url") if waiting else None
    if _through_steerable():
        method, email = "steerable", None
    elif env("ANTHROPIC_API_KEY"):
        method, email = "key", None
    else:
        auth = _auth_status()
        signed_in = auth.get("loggedIn") and auth.get("authMethod") == "claude.ai"
        method = "account" if signed_in else "none"
        email = (auth.get("email") or (auth.get("account") or {}).get("email")) if signed_in else None
    own_jev = bool(env("JEV_API_KEY"))
    return {
        "claude": {"method": method, "email": email, "signingIn": waiting, "url": url},
        "jev": {"on": own_jev or method == "steerable", "ownKey": own_jev,
                "fromSettings": bool(os.environ.get("JEV_API_KEY"))},
    }


def start_login() -> dict:
    """Start signing Claude Code in with the owner's Claude account. Returns the link to open."""
    if _through_steerable():
        raise AiError("Your AI comes through Steerable, so there's nothing to sign in to here.")
    with _lock:
        _stop_login()
        pid, fd = pty.fork()
        if pid == 0:
            os.execvp("claude", ["claude", "auth", "login", "--claudeai"])
        output = _read(fd, 1)
        end = time.time() + 30
        while not URL.search(output) and time.time() < end:
            output += _read(fd, 1)
        match = URL.search(output)
        _login.update(pid=pid, fd=fd, started=time.time(), output=output, url=match.group(0) if match else None)
        if not match:
            _stop_login()
            log_run("ai_access", "error", step="start", output=ESCAPES.sub("", output)[-500:])
            raise AiError("Claude's sign-in didn't start. Try again in a minute.")
    log_run("ai_access", "login_started")
    return {"url": _login["url"]}


def finish_login(code: str) -> dict:
    """Type the code Claude showed the owner into the waiting sign-in."""
    code = code.strip()
    if not code or len(code) > 500 or any(c.isspace() for c in code):
        raise AiError("Paste the code Claude showed you after you signed in.")
    with _lock:
        if not _waiting():
            raise AiError("That sign-in timed out. Start again.")
        fd, pid = _login["fd"], _login["pid"]
        os.write(fd, code.encode() + b"\r")
        output = _read(fd, 45)
        try:
            done, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            done = pid
        if not done:
            output += _read(fd, 15)
        _stop_login()
    _forget_cached_auth()
    if status()["claude"]["method"] != "account":
        log_run("ai_access", "error", step="code", output=ESCAPES.sub("", output)[-500:])
        raise AiError("That code didn't work. Start again, and paste the newest code Claude shows you.")
    record_event("You signed your business manager in with your Claude account.", who="CEO")
    log_run("ai_access", "signed_in")
    return status()


def cancel_login() -> None:
    with _lock:
        _stop_login()


def sign_out() -> dict:
    subprocess.run(["claude", "auth", "logout"], capture_output=True, text=True, timeout=30)
    _forget_cached_auth()
    record_event("You signed your business manager out of your Claude account.", who="CEO")
    log_run("ai_access", "signed_out")
    return status()


def save_jev(key: str) -> dict:
    """Keep the owner's Jev key, after one tiny decision shows it works."""
    key = key.strip()
    if not key:
        raise AiError("Paste your Jev key first.")
    if os.environ.get("JEV_API_KEY"):
        raise AiError("Jev's key is set in this server's settings file, so change it there.")
    target = (env("JEV_ENDPOINT") or decide.JEV_ENDPOINT, key)
    try:
        decide._jev("Is this a test?", {"yes": "it is a test", "no": "it is not"}, "Checking a new key.", target=target)
    except decide.Uncertain:
        pass  # it answered, so the key works
    except Exception as e:  # noqa: BLE001 - any failure means we can't use it
        log_run("ai_access", "error", step="jev", error=str(e)[:300])
        raise AiError("That key didn't work. Check it on your TypeSafe account and paste it again.") from None
    vault.save("JEV_API_KEY", key)
    log_run("ai_access", "jev_on")
    return status()


def remove_jev() -> dict:
    if os.environ.get("JEV_API_KEY"):
        raise AiError("Jev's key is set in this server's settings file, so remove it there.")
    with vault._store() as data:
        data["values"].pop("JEV_API_KEY", None)
    record_event("You turned off Jev.", who="CEO")
    log_run("ai_access", "jev_off")
    return status()


if __name__ == "__main__":
    if sys.argv[1:] == ["status"]:
        print(json.dumps(status(), indent=1))
    else:
        print(__doc__)
