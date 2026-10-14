"""Accounts the COO has of its own: on a design tool, a supplier's shop, a directory listing.

The COO signs up with its own mailbox (mailbox.py) and the owner's phone for any code sent by
text. It's the business's account, run by the COO, and the owner can see and take over every
one on the Accounts page.

    .venv/bin/python scripts/accounts.py propose canva.com --name Canva \\
        --why "To make the weekly Instagram posts from our templates." --signup https://www.canva.com/signup
    .venv/bin/python scripts/accounts.py list

A proposal waits in the owner's Decisions. Once they say yes, they open the sign-up on their
dashboard: a live browser where one tap fills in the COO's email, password or the code from its
mail, and they handle anything that checks for a human, and the codes that come to their phone.
Passwords are made here and kept in .cache/accounts/, which no agent can read: the AI never
sees them, and the browser types them in. Sites whose terms forbid automated accounts are
refused, as for website logins.

In Steerable Cloud (STEERABLE_HOSTING=cloud) the accounts live with the platform, not here: the
gateway keeps them and makes their passwords, which never enter this container, and the owner
approves and signs up in the app. Here the COO can only propose and list them (/x/accounts).
"""
import argparse
import json
import os
import re
import secrets
import string
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from browser import site_key
from common import CACHE, COMPANY, log_run
from ops_db import record_event

DIR = CACHE / "accounts"
SETTINGS = DIR / "_settings.json"
STATUSES = ("PROPOSED", "APPROVED", "ACTIVE", "DECLINED")


class AccountError(RuntimeError):
    """Something the owner (or the COO) can be shown as is."""


def remote() -> bool:
    """Steerable Cloud keeps the accounts (and their passwords) on the platform."""
    return os.environ.get("STEERABLE_HOSTING") == "cloud"


def _gateway(method: str, path: str, body: dict | None = None):
    import integrations
    try:
        return integrations._request(method, path, json.dumps(body).encode() if body is not None else None,
                                     {"Content-Type": "application/json"} if body is not None else None)
    except integrations.IntegrationError as e:
        if e.status == 404:
            return None
        raise AccountError(str(e)) from None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _file(site: str) -> Path:
    return DIR / (re.sub(r"[^a-z0-9.-]", "_", site_key(site)) + ".json")


def _write(path: Path, data: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.chmod(0o600)
    tmp.replace(path)


def load(site: str) -> dict | None:
    """An account with its password (for the browser only), or None. Matches a subdomain's parent.
    In Steerable Cloud, without the password."""
    if remote():
        from urllib.parse import quote
        return _gateway("GET", f"/x/accounts/{quote(site_key(site), safe='')}")
    key = site_key(site)
    for candidate in [key] + [key.split(".", n)[-1] for n in range(1, key.count("."))]:
        try:
            return json.loads(_file(candidate).read_text())
        except (OSError, json.JSONDecodeError):
            continue
    return None


def public(a: dict) -> dict:
    """What the dashboard and the COO may see: everything but the password."""
    return {k: a.get(k) for k in ("site", "name", "why", "signupUrl", "loginUrl", "email", "status",
                                  "proposedAt", "createdAt", "lastUsed")}


def listing() -> list[dict]:
    if remote():
        return [public(a) for a in _gateway("GET", "/x/accounts") or []]
    out = []
    for f in sorted(DIR.glob("*.json")) if DIR.exists() else []:
        if f.name.startswith("_"):
            continue
        try:
            a = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if a.get("status") != "DECLINED":
            out.append(public(a))
    return out


def new_password() -> str:
    """20 characters with every kind most sites ask for."""
    kinds = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "!#%+-_=?"]
    chars = [secrets.choice(k) for k in kinds] + [secrets.choice("".join(kinds)) for _ in range(16)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


# ---------- the owner's phone ----------

def settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def set_phone(phone: str) -> dict:
    phone = re.sub(r"[^\d+]", "", phone or "")
    if phone and not re.fullmatch(r"\+?\d{7,15}", phone):
        raise AccountError("Enter the phone number with its country code, like +44 7700 900123.")
    _write(SETTINGS, {**settings(), "phone": phone})
    return {"phone": phone}


# ---------- proposing, signing up ----------

def propose(site: str, name: str, why: str, signup_url: str) -> dict:
    """The COO asks for an account of its own. It waits in the owner's Decisions."""
    import sites
    signup_url = sites.check_url(signup_url if "://" in signup_url else f"https://{signup_url}")
    site = site_key(site or urlsplit(signup_url).hostname or "")
    sites.check_url(f"https://{site}/")
    if not why.strip():
        raise AccountError("Say what the account is for, in a sentence.")
    existing = load(site)
    if existing and existing["status"] in ("ACTIVE", "APPROVED"):
        raise AccountError(f"There's already an account on {site} ({existing['status'].lower()}).")
    if remote():  # the platform makes its password and asks the owner in the app
        a = _gateway("POST", "/x/accounts", {"site": site, "name": (name or site).strip()[:60], "why": why.strip()[:300],
                                             "signupUrl": signup_url})
        record_event(f"Asked you for an account of its own on {a['name']}", who="COO")
        log_run("accounts", "proposed", site=site)
        return public(a)
    account = {"site": site, "name": (name or site).strip()[:60], "why": why.strip()[:300], "signupUrl": signup_url,
               "loginUrl": None, "email": None, "password": new_password(), "status": "PROPOSED",
               "proposedAt": _now(), "createdAt": None, "lastUsed": None}
    _write(_file(site), account)
    record_event(f"Asked you for an account of its own on {account['name']}", who="COO")
    log_run("accounts", "proposed", site=site)
    return public(account)


def decide(site: str, create: bool) -> dict:
    a = load(site)
    if not a or a["status"] != "PROPOSED":
        raise AccountError("That account isn't waiting for you.")
    a["status"] = "APPROVED" if create else "DECLINED"
    _write(_file(a["site"]), a)
    log_run("accounts", a["status"].lower(), site=a["site"])
    return public(a)


def kit(site: str) -> dict:
    """What the live sign-up types in for the owner. Engine only: it holds the password."""
    import mailbox
    a = load(site)
    if not a or a["status"] not in ("APPROVED", "ACTIVE"):
        raise AccountError("That account isn't approved.")
    return {"email": a.get("email") or mailbox.address(), "password": a["password"],
            "phone": settings().get("phone") or "", "company": COMPANY}


def activate(site: str, login_url: str) -> dict:
    """The sign-up (or a new login) worked: the account is the COO's from now on."""
    import mailbox
    a = load(site)
    if not a:
        raise AccountError("That account isn't saved.")
    first = a["status"] != "ACTIVE"
    a.update(status="ACTIVE", loginUrl=a.get("loginUrl") or login_url, email=a.get("email") or mailbox.address(),
             createdAt=a.get("createdAt") or _now())
    _write(_file(a["site"]), a)
    if first:
        record_event(f"Opened its own account on {a['name']}", who="COO")
    log_run("accounts", "active", site=a["site"])
    return public(a)


def touch(site: str) -> None:
    if remote():
        return  # the gateway notes when a login is handed out
    a = load(site)
    if a and a["status"] == "ACTIVE":
        a["lastUsed"] = _now()
        _write(_file(a["site"]), a)


def password(site: str) -> str:
    """For the owner, on the Accounts page."""
    a = load(site)
    if not a or a["status"] not in ("APPROVED", "ACTIVE"):
        raise AccountError("That account isn't saved.")
    return a["password"]


def remove(site: str) -> dict:
    """Forget an account here, with its saved login. (It still exists on the site.)"""
    import sites
    a = load(site)
    if not a:
        raise AccountError("That account isn't saved.")
    _file(a["site"]).unlink()
    try:
        sites.remove(a["site"])
    except sites.SiteError:
        pass  # never signed in
    log_run("accounts", "removed", site=a["site"])
    return {"ok": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", help="ask the owner for an account of your own on a site")
    p.add_argument("site", help="the site, like canva.com")
    p.add_argument("--name", default="", help="what it's called, like Canva")
    p.add_argument("--why", required=True, help="what you need it for, one sentence")
    p.add_argument("--signup", required=True, help="the sign-up page's address")
    sub.add_parser("list", help="your accounts (never their passwords)")
    args = parser.parse_args()

    if args.cmd == "list":
        accounts = listing()
        if not accounts:
            print("No accounts of my own yet.")
        for a in accounts:
            print(f"- {a['name']} ({a['site']}): {a['status'].lower()}. For: {a['why']}")
        return 0
    try:
        import sites
        a = propose(args.site, args.name, args.why, args.signup)
    except (AccountError, sites.SiteError) as e:
        print(e, file=sys.stderr)
        return 1
    print(f"Asked. It's waiting for the owner in Decisions: an account on {a['name']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
