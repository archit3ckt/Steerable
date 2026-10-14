"""Website logins, self-hosted: the owner logs in to a site through a live browser on their
dashboard, and routines then get a browser that's already logged in (integrations.site_browser).

Steerable Cloud does the same with its own browser service and keeps the session in its gateway.
Here the engine runs the browser (the Chromium already in it): the dashboard shows a picture of
the page and forwards clicks and typing through the agent API. Saving keeps only the logged-in
session (cookies and storage, Playwright's storage state) and the browser profile it was made
in (browser.py) in .cache/sites/, which no agent can read, never a password. Only approved
routines and dry runs get them, never the chat. Logging in again uses the same profile, so the
site sees the device it already knows.

A live login can also be the sign-up for an account of the COO's own (accounts.py): then the
owner gets buttons that type its email, password, their phone, or the code from its mail, so
the password never passes through the dashboard or the AI.

Playwright's sync API belongs to the thread that started it, so one worker thread owns the
browser and every request is handed to it. One live login at a time; it closes after 10 idle
minutes, and the browser with it.
"""
import ipaddress
import json
import queue
import re
import threading
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

import browser
from browser import site_key
from common import CACHE, log_run

DIR = CACHE / "sites"
VIEWPORT = browser.VIEWPORT
IDLE_SECONDS = 10 * 60
KEYS = {"Enter", "Tab", "Backspace", "Escape", "ArrowDown", "ArrowUp"}
FILLS = ("email", "password", "phone", "company", "code")

# Sites whose terms forbid automating an account (as in Steerable Cloud's browser/policy.ts).
BLOCKED = ["linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "threads.net",
           "amazon.com", "amazon.co.uk", "amazon.de", "ebay.com", "craigslist.org", "indeed.com", "glassdoor.com",
           "google.com", "accounts.google.com", "microsoft.com", "live.com", "apple.com", "icloud.com",
           "paypal.com", "chase.com", "bankofamerica.com", "wellsfargo.com", "hsbc.com", "barclays.co.uk"]


class SiteError(RuntimeError):
    """Something the owner can be shown as is."""


def _local(host: str) -> bool:
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return host == "localhost" or host.endswith((".local", ".lan", ".internal", ".home")) or "." not in host


def check_url(url: str) -> str:
    """The URL if the owner may log in there: https, or http on their own network (it's their
    machine); never a site whose terms forbid automated use."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if not host or parts.scheme not in ("https", "http") or (parts.scheme == "http" and not _local(host)):
        raise SiteError("Use the site's https:// address.")
    blocked = next((d for d in BLOCKED if host == d or host.endswith("." + d)), None)
    if blocked:
        raise SiteError(f"{blocked} doesn't allow automated logins. Connect it through its official app on "
                        "the Connections page if it's there.")
    return url.strip()


# ---------- saved logins ----------

def _file(host: str) -> Path:
    return DIR / (re.sub(r"[^a-z0-9.-]", "_", site_key(host)) + ".json")


def saved() -> list[dict]:
    """[{"site", "name", "startUrl", "savedAt", "status", "source"}], without the sessions themselves.
    source: "browser" for a login the owner's own browser keeps in step (extension.py)."""
    out = []
    for f in sorted(DIR.glob("*.json")) if DIR.exists() else []:
        try:
            s = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        out.append({k: s.get(k) for k in ("site", "name", "startUrl", "savedAt")}
                   | {"status": s.get("status", "ACTIVE"), "source": s.get("source") or "live"})
    return out


def find(host: str) -> dict | None:
    """The saved login for a site (or one of its subdomains' parent), with its storage state."""
    key = site_key(host)
    for candidate in [key] + [key.split(".", n)[-1] for n in range(1, key.count("."))]:
        f = _file(candidate)
        if f.exists():
            return json.loads(f.read_text())
    return None


def _save(site: str, name: str, start_url: str, state: dict, source: str = "live") -> None:
    DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    f = _file(site)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"site": site_key(site), "name": name, "startUrl": start_url, "storageState": state,
                               "savedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "ACTIVE",
                               "source": source}))
    tmp.chmod(0o600)
    tmp.replace(f)


# ---------- a login from the owner's own browser (extension.py) ----------

SAME_SITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}
MAX_COOKIES = 300


def _cookie(c: dict, host: str) -> dict | None:
    """One of Chrome's cookies (chrome.cookies) as Playwright keeps them, or None if it isn't one
    the site's pages would get: its domain must be the site's host or a parent of it."""
    name, value, domain = c.get("name"), c.get("value"), str(c.get("domain") or "").lower()
    bare = domain.lstrip(".")
    if not isinstance(name, str) or not name or not isinstance(value, str) or len(value) > 8192 or not bare:
        return None
    if not (host == bare or host.endswith("." + bare)):
        return None
    expires = c.get("expirationDate")
    if c.get("session") or not isinstance(expires, (int, float)):
        expires = -1  # lasts for the browsing session
    elif expires < time.time():
        return None
    out = {"name": name, "value": value, "domain": bare if c.get("hostOnly") else "." + bare, "path": str(c.get("path") or "/"),
           "expires": expires, "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure"))}
    if same_site := SAME_SITE.get(str(c.get("sameSite") or "").lower()):
        out["sameSite"] = same_site
    return out


def import_login(start_url: str, name: str, cookies: list) -> dict:
    """Keep the login the owner has in their own browser: the cookies their browser sends that
    site (from the extension). Replaces what was saved for the site, and its browser profile, so
    routines use exactly this session. {"site"}"""
    start_url = check_url(start_url)
    host = (urlsplit(start_url).hostname or "").lower()
    site = site_key(host)
    kept = [k for c in (cookies if isinstance(cookies, list) else [])[:MAX_COOKIES] if isinstance(c, dict) and (k := _cookie(c, host))]
    if not kept:
        raise SiteError("Your browser has no login for that site yet. Log in there first.")
    with browser.profile_lock(site, wait=20):
        _save(site, (name or site).strip()[:60], start_url, {"cookies": kept, "origins": []}, source="browser")
        browser.remove_profile(site)
    log_run("sites", "imported", site=site, cookies=len(kept))
    return {"site": site}


def mark_expired(host: str) -> None:
    if (s := find(host)) is not None:
        s["status"] = "EXPIRED"
        _file(s["site"]).write_text(json.dumps(s))


def remove(host: str) -> None:
    f = _file(host)
    if not f.exists():
        raise SiteError("That login isn't saved.")
    f.unlink()
    browser.remove_profile(host)
    log_run("sites", "removed", site=site_key(host))


# ---------- the live login ----------

class _Worker:
    """Owns Playwright and the one live login; runs everything on its own thread."""

    def __init__(self):
        self.jobs: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.pw = self.context = self.page = None
        self.held = ExitStack()  # the profile's lock, while the live login uses it
        self.session: str | None = None
        self.start_url = ""
        self.profile_site = ""
        self.account: str | None = None  # the COO's account this session signs up or logs in to
        self.opened = 0.0
        self.seen = 0.0

    def run(self, fn, timeout: float = 60):
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, daemon=True, name="site-login")
                self.thread.start()
        done: queue.Queue = queue.Queue()
        self.jobs.put((fn, done))
        ok, value = done.get(timeout=timeout)
        if not ok:
            raise value
        return value

    def _loop(self):
        while True:
            try:
                fn, done = self.jobs.get(timeout=30)
            except queue.Empty:
                if self.session and time.time() - self.seen > IDLE_SECONDS:
                    self._close()
                continue
            try:
                done.put((True, fn()))
            except Exception as e:  # handed back to the caller's thread
                done.put((False, e))

    def _close(self, keep_profile: bool = False):
        """End the live login. A profile that never became a saved login is thrown away."""
        try:
            if self.context:
                browser.close(self.context)
        except Exception:
            pass
        if self.pw:
            self.pw.stop()
        if self.profile_site and not keep_profile and find(self.profile_site) is None:
            browser.remove_profile(self.profile_site)
        self.held.close()
        self.pw = self.context = self.page = None
        self.session, self.profile_site, self.account = None, "", None

    def _page(self, sid: str):
        if not self.session or sid != self.session:
            raise SiteError("That login session has ended. Start again.")
        self.seen = time.time()
        return self.page

    # Each of these runs on the worker thread.

    def start(self, url: str, account: str | None = None) -> str:
        from playwright.sync_api import sync_playwright

        self._close()  # one at a time: a new one replaces the old
        site = site_key(urlsplit(url).hostname or "")
        if account:
            import accounts
            a = accounts.load(account)
            if not a or a["status"] not in ("APPROVED", "ACTIVE"):
                raise SiteError("That account isn't approved yet.")
            site = a["site"]
        try:
            self.held.enter_context(browser.profile_lock(site, wait=20))
        except browser.ProfileBusy:
            raise SiteError("A routine is using this site right now. Try again in a minute.") from None
        self.profile_site = site
        self.pw = sync_playwright().start()
        try:
            self.context = browser.launch(self.pw, browser.profile_dir(site))
        except Exception:
            self._close()
            raise
        self.page = browser.first_page(self.context)
        self.session, self.start_url, self.seen = uuid.uuid4().hex, url, time.time()
        self.account, self.opened = site if account else None, time.time()
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            pass  # show whatever loaded; the owner sees the problem on screen
        return self.session

    def frame(self, sid: str) -> bytes:
        return self._page(sid).screenshot(type="jpeg", quality=70)

    def info(self, sid: str) -> dict:
        page = self._page(sid)
        try:
            title = page.title()
        except Exception:
            title = ""
        out = {"url": page.url, "title": title}
        if self.account:
            out["mail"] = self._mail()
        return out

    def _mail(self) -> dict | None:
        """The sign-up's code or link from the COO's mail, once it arrives."""
        import mailbox
        try:
            import accounts
            return mailbox.for_signup(self.account, self.opened, (accounts.load(self.account) or {}).get("name", ""))
        except Exception:
            return None  # no mailbox, or it's briefly unreachable: nothing to offer yet

    def _fill(self, page, field: str) -> None:
        import accounts
        if not self.account:
            raise SiteError("Filling in is only for the COO's own accounts.")
        if field == "code":
            mail = self._mail()
            if not mail or not mail.get("code"):
                raise SiteError("No code has arrived in the mailbox yet. Give it a minute.")
            value = mail["code"]
        else:
            try:
                value = accounts.kit(self.account).get(field) or ""
            except accounts.AccountError as e:
                raise SiteError(str(e)) from None
            if not value:
                raise SiteError({"email": "Set up the COO's mailbox on the Accounts page first.",
                                 "phone": "Add your phone number on the Accounts page first."}.get(field, "There's nothing to fill in."))
        browser.replay_typing(page, value, browser.typing_gaps(value))  # at a person's uneven pace

    def input(self, sid: str, body: dict) -> dict:
        page = self._page(sid)
        x = max(0, min(VIEWPORT["width"], int(body.get("x") or 0)))
        y = max(0, min(VIEWPORT["height"], int(body.get("y") or 0)))
        kind = body.get("kind")
        if kind == "move":  # the owner's pointer path over the picture, as they made it
            browser.replay_moves(page, body.get("points") if isinstance(body.get("points"), list) else [])
        elif kind == "click":  # held as long as they held it
            browser.replay_click(page, x, y, body.get("hold") or 0)
        elif kind == "type":  # in their rhythm
            browser.replay_typing(page, str(body.get("text") or "")[:500], body.get("gaps") if isinstance(body.get("gaps"), list) else None)
        elif kind == "key" and body.get("key") in KEYS:
            page.keyboard.press(body["key"])
        elif kind == "scroll":
            page.mouse.wheel(0, max(-2000, min(2000, int(body.get("dy") or 0))))
        elif kind == "fill" and body.get("field") in FILLS:
            self._fill(page, body["field"])
        elif kind == "open-link":
            mail = self._mail() if self.account else None
            if not mail or not mail.get("link"):
                raise SiteError("No link has arrived in the mailbox yet.")
            try:
                page.goto(mail["link"], wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                pass  # show whatever loaded
        else:
            raise SiteError("Unknown input.")
        return {"ok": True}

    def save(self, sid: str, name: str) -> dict:
        self._page(sid)
        state = self.context.storage_state()
        if not state.get("cookies"):
            raise SiteError("It doesn't look like you're logged in yet: the site hasn't set a session. Log in, then save.")
        site = site_key(urlsplit(self.page.url).hostname or urlsplit(self.start_url).hostname or "")
        account, start_url = self.account, self.start_url
        if account:  # the COO's own account: the profile and login are kept under its site, and
            import accounts  # routines start where the sign-up ended (its account page), not at the sign-up
            site, start_url = account, self.page.url
            activated = accounts.activate(account, self.page.url)
            name = name or activated["name"]
        _save(site, (name or site).strip()[:60], start_url, state)
        started_at = self.profile_site
        self._close(keep_profile=True)
        if started_at != site:
            try:
                with browser.profile_lock(site, wait=20):
                    browser.move_profile(started_at, site)
            except browser.ProfileBusy:
                pass  # a routine has it; the next login there makes a new one
        log_run("sites", "saved", site=site)
        return {"site": site}

    def cancel(self, sid: str) -> dict:
        if sid == self.session:
            self._close()
        return {"ok": True}


_worker = _Worker()


def start(url: str, account: str | None = None) -> dict:
    url = check_url(url)
    return {"id": _worker.run(lambda: _worker.start(url, account), timeout=90)}


def frame(sid: str) -> bytes:
    return _worker.run(lambda: _worker.frame(sid))


def info(sid: str) -> dict:
    return _worker.run(lambda: _worker.info(sid))


def send_input(sid: str, body: dict) -> dict:
    return _worker.run(lambda: _worker.input(sid, body))


def save(sid: str, name: str) -> dict:
    return _worker.run(lambda: _worker.save(sid, name))


def cancel(sid: str) -> dict:
    return _worker.run(lambda: _worker.cancel(sid))
