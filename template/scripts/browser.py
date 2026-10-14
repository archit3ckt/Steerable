"""The browser for website logins (sites.py) and the routines that use them (integrations.site_browser).

Sites judge a browser by how ordinary it looks, and an automated one has tells. So it is:
- the full Chromium in its new headless mode, which is the real Chrome, not Playwright's
  headless shell; with Chrome's own user agent, not "HeadlessChrome", and without the flag
  that tells pages it's automated
- one profile per site, kept between visits, so the site sees the same device come back
  rather than a brand-new one each time (and asks to log in, or to verify, less often)
- in the owner's timezone (TZ) and language (BROWSER_LOCALE), with the same window, screen
  and user agent every time; its language list and the details Chrome gives sites that ask
  (the "client hints": the system's version, 64-bit) are what a desktop Chrome sends, where
  an automated one sends a single language and leaves the details empty
- moved like a person moves it: in a live login the owner's own pointer path, click and typing
  rhythm are replayed (replay_moves, replay_typing); in a routine, Human(page) moves the
  pointer along a curve to somewhere inside what it clicks, types at an uneven pace, and
  takes a moment to read a page before acting on it

Profiles live in .cache/sites/profiles/, which no agent can read. A profile is used by one
browser at a time: a routine and a live login on the same site take turns.

    with sync_playwright() as pw, profile_lock("portal.supplier.com"):
        context = launch(pw, profile_dir("portal.supplier.com"))
        ...
        close(context)
"""
import fcntl
import functools
import math
import os
import random
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import runtrace
from common import CACHE, env

PROFILES = CACHE / "sites" / "profiles"
VIEWPORT = {"width": 1280, "height": 800}
SCREEN = {"width": 1440, "height": 900}
ARGS = ["--disable-dev-shm-usage", "--no-first-run", "--disable-blink-features=AutomationControlled"]


class ProfileBusy(RuntimeError):
    """Another browser is using this site's profile."""


# Requests that only keep a login alive (Yad2's POST gw.yad2.co.il/auth/token/refresh, most sites' session
# renewal). A practice run lets them through to the site the login is for: blocked, the site thinks the owner
# logged out. Never one that ends or changes the login or anything else.
KEEPS_LOGIN = re.compile(r"token|refresh|session|keep-?alive|silent|heartbeat", re.I)
NOT_KEEPING = re.compile(r"log-?out|sign-?out|revoke|delete|remove|password|register|sign-?up|verify|otp|code|submit|order|checkout|pay|publish|upload", re.I)


def same_site(a: str, b: str) -> bool:
    """shop.example.co.il and www.example.co.il are the same site; example.com and google.com aren't."""
    def site(host: str) -> str:
        labels = (host or "").lower().split(".")
        if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in ("co", "com", "org", "net", "ac", "gov", "or", "ne"):
            return ".".join(labels[-3:])
        return ".".join(labels[-2:])
    return bool(a and b) and site(a) == site(b)


def keeps_login(url: str, host: str) -> bool:
    """Is this request (not a GET) only the site keeping the owner logged in? (See KEEPS_LOGIN.)"""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return same_site(parts.hostname or "", host) and bool(KEEPS_LOGIN.search(parts.path)) and not NOT_KEEPING.search(parts.path)


def site_key(host: str) -> str:
    """One login (and profile) per site: www. and the rest of the address don't matter."""
    return re.sub(r"^www\.", "", host.lower())


def profile_dir(site: str) -> Path:
    return PROFILES / re.sub(r"[^a-z0-9.-]", "_", site_key(site))


@contextmanager
def profile_lock(site: str, wait: float = 0):
    """Hold a site's profile, waiting up to `wait` seconds for another browser to finish with it."""
    PROFILES.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(profile_dir(site).with_suffix(".lock"), "w") as f:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ProfileBusy(site) from None
                time.sleep(0.5)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def move_profile(old: str, new: str) -> None:
    """The live login started at one address and ended at another site: keep its profile there."""
    src, dst = profile_dir(old), profile_dir(new)
    if src == dst or not src.exists():
        return
    shutil.rmtree(dst, ignore_errors=True)
    src.rename(dst)


def remove_profile(site: str) -> None:
    shutil.rmtree(profile_dir(site), ignore_errors=True)


def timezone() -> str | None:
    tz = env("TZ").lstrip(":")
    return tz if tz and Path("/usr/share/zoneinfo", tz).is_file() else None


@functools.cache
def user_agent(executable: str) -> str | None:
    """Chrome's user agent for this Chromium, as a desktop Chrome sends it (headless says
    "HeadlessChrome"). None if the version can't be read: then the browser's own is used."""
    try:
        out = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    major = re.search(r"(\d+)\.\d+\.\d+", out)
    if not major:
        return None
    return (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major.group(1)}.0.0.0 Safari/537.36")


def context_options(pw) -> dict:
    executable = env("CHROMIUM_PATH") or pw.chromium.executable_path
    options = {"viewport": VIEWPORT, "screen": SCREEN, "color_scheme": "light"}
    if tz := timezone():
        options["timezone_id"] = tz
    if ua := user_agent(executable):
        options["user_agent"] = ua
    return options


def language_args() -> list[str]:
    """The owner's language as Chrome itself sends it: "en-GB,en;q=0.9" and navigator.languages
    ["en-GB", "en"]. (Playwright's own locale option would send the one tag alone.)"""
    locale = env("BROWSER_LOCALE") or "en-US"
    if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", locale):
        locale = "en-US"
    base = locale.split("-")[0]
    return [f"--lang={locale}", f"--accept-lang={locale},{base}" if base != locale else f"--accept-lang={locale}"]


def _hints(pw) -> dict | None:
    """What Chrome tells a site that asks about the system (client hints), filled in as on a
    desktop: this machine's real system version, and 64-bit. Under automation with our user agent
    they'd be empty. The browser's own brand and version lists are left as Chrome makes them."""
    ua = user_agent(env("CHROMIUM_PATH") or pw.chromium.executable_path)
    version = re.match(r"\d+(\.\d+){0,2}", os.uname().release)
    if not ua or not version:
        return None
    return {"userAgent": ua, "userAgentMetadata": {"platform": "Linux", "platformVersion": version.group(0), "architecture": "x86",
                                                   "model": "", "mobile": False, "bitness": "64", "wow64": False}}


def _apply_hints(context, pw) -> None:
    hints = _hints(pw) if os.uname().machine in ("x86_64", "amd64") else None
    if not hints:
        return

    def apply(page) -> None:
        try:
            context.new_cdp_session(page).send("Emulation.setUserAgentOverride", hints)
        except Exception:
            pass  # the page closed first, or this isn't Chromium: the hints stay as they were

    for page in context.pages:
        apply(page)
    context.on("page", apply)


def launch(pw, profile: Path | None = None, **context_extra):
    """A browser context: kept in `profile` when there is one (hold its profile_lock), or a
    fresh one (pass storage_state= to start logged in). Close it with close()."""
    launch_options = {"headless": True, "args": ARGS + language_args()}
    if env("CHROMIUM_PATH"):
        launch_options["executable_path"] = env("CHROMIUM_PATH")
    else:
        launch_options["channel"] = "chromium"  # the full browser's new headless mode
    options = context_options(pw) | context_extra
    if profile is not None:
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        context = pw.chromium.launch_persistent_context(str(profile), **launch_options, **options)
    else:
        context = pw.chromium.launch(**launch_options).new_context(**options)
    _apply_hints(context, pw)
    return context


def add_missing_cookies(context, cookies: list[dict]) -> None:
    """Add the saved cookies the context doesn't have (by name, domain and path)."""
    have = {(c["name"], c["domain"], c["path"]) for c in context.cookies()}
    missing = [c for c in cookies if (c.get("name"), c.get("domain"), c.get("path")) not in have]
    if missing:
        context.add_cookies(missing)


def first_page(context):
    return context.pages[0] if context.pages else context.new_page()


def close(context) -> None:
    """Close a context from launch(), and its browser."""
    browser = context.browser
    try:
        context.close()
    finally:
        if browser is not None:
            browser.close()


# ---------- moving and typing like a person ----------

MAX_GAP_MS = 400    # the longest pause replayed between two keys or two pointer positions
MAX_POINTS = 60     # pointer positions replayed from one message
MAX_HOLD_MS = 600   # the longest a click is held


def _clamp(x: float, y: float) -> tuple[float, float]:
    return max(0.0, min(VIEWPORT["width"] - 1, x)), max(0.0, min(VIEWPORT["height"] - 1, y))


def replay_moves(page, points: list) -> None:
    """The owner's pointer path in a live login: [[x, y, ms since the one before], ...]."""
    for point in (points or [])[:MAX_POINTS]:
        try:
            x, y, gap = float(point[0]), float(point[1]), float(point[2]) if len(point) > 2 else 0
        except (TypeError, ValueError, IndexError):
            continue
        if gap > 0:
            time.sleep(min(gap, 80) / 1000)  # the path's shape matters; long rests would only hold up the picture
        page.mouse.move(*_clamp(x, y))


def replay_click(page, x: float, y: float, hold_ms: float = 0) -> None:
    """A click where the owner clicked, held as long as they held it."""
    page.mouse.move(*_clamp(x, y))
    page.mouse.down()
    time.sleep(max(30.0, min(float(hold_ms or 0) or 70.0, MAX_HOLD_MS)) / 1000)
    page.mouse.up()


def replay_typing(page, text: str, gaps: list | None = None) -> None:
    """What the owner typed, in their rhythm: gaps[i] is the ms to wait before text[i]."""
    for i, char in enumerate(text):
        try:
            gap = float(gaps[i]) if gaps and i < len(gaps) else 0
        except (TypeError, ValueError):
            gap = 0
        if gap > 0:
            time.sleep(min(gap, MAX_GAP_MS) / 1000)
        page.keyboard.type(char)


def pointer_path(start: tuple[float, float], end: tuple[float, float], rng: random.Random | None = None) -> list[tuple[float, float, float]]:
    """A pointer's way from start to end as a hand moves it: [(x, y, ms to wait before it), ...].
    A curve bowed to one side (a cubic Bezier), quick in the middle and slow at both ends, a
    little unsteady, with more points over longer distances. Ends exactly at `end`."""
    rng = rng or random
    (x0, y0), (x1, y1) = start, end
    dist = math.hypot(x1 - x0, y1 - y0)
    if dist < 2:
        return [(x1, y1, 0.0)]
    steps = max(8, min(45, int(dist / 18) + rng.randint(4, 9)))
    # Two control points off the straight line, on the same side, a tenth to a quarter of the way out.
    nx, ny = -(y1 - y0) / dist, (x1 - x0) / dist
    bow = dist * rng.uniform(0.08, 0.25) * rng.choice((-1, 1))
    c1 = (x0 + (x1 - x0) * rng.uniform(0.2, 0.4) + nx * bow, y0 + (y1 - y0) * rng.uniform(0.2, 0.4) + ny * bow)
    c2 = (x0 + (x1 - x0) * rng.uniform(0.6, 0.8) + nx * bow * rng.uniform(0.3, 0.9), y0 + (y1 - y0) * rng.uniform(0.6, 0.8) + ny * bow * rng.uniform(0.3, 0.9))
    total_ms = min(1400.0, 180 + dist * rng.uniform(0.9, 1.6))  # Fitts-like: further takes longer, not in proportion
    path = []
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)  # ease in and out
        a, b, c, d = (1 - e) ** 3, 3 * (1 - e) ** 2 * e, 3 * (1 - e) * e ** 2, e ** 3
        x, y = a * x0 + b * c1[0] + c * c2[0] + d * x1, a * y0 + b * c1[1] + c * c2[1] + d * y1
        if i < steps:  # a hand is never perfectly steady
            x, y = x + rng.uniform(-1.2, 1.2), y + rng.uniform(-1.2, 1.2)
        path.append((*_clamp(x, y), total_ms / steps * rng.uniform(0.6, 1.4)))
    path[-1] = (*_clamp(x1, y1), path[-1][2])
    return path


def typing_gaps(text: str, rng: random.Random | None = None) -> list[float]:
    """Milliseconds to wait before each character, as someone typing: uneven, slower after a
    space or punctuation, with a short think now and then."""
    rng = rng or random
    gaps = []
    for i, char in enumerate(text):
        gap = max(35.0, rng.gauss(115, 40))
        if i and text[i - 1] in " .,;:!?@-_/":
            gap += rng.uniform(40, 180)
        if rng.random() < 0.04:
            gap += rng.uniform(250, 600)
        gaps.append(0.0 if i == 0 else gap)
    return gaps


class Human:
    """Moves the pointer and types the way a person does, for routines that drive a site:

        with site_browser("portal.supplier.com", logged_in="#account") as page:
            h = Human(page)
            h.click(page.get_by_role("link", name="Orders"))
            h.type(page.get_by_label("Search"), "pothos 6 inch")
            h.press("Enter")
            h.read()                                   # look at the results before the next step
            h.goto("https://portal.supplier.com/orders")  # opens it, then reads
            h.scroll(600)

    The pointer travels along a curve to a spot inside the target (not its dead centre), rests,
    then clicks; typing has an uneven pace. It takes a little longer than Playwright's own
    click() and fill(), which jump and paste: use it for what a person would do with the mouse
    and keyboard, and plain Playwright for reading the page."""

    def __init__(self, page, seed: int | None = None):
        self.page = page
        self.rng = random.Random(seed)
        self.at = (self.rng.uniform(200, VIEWPORT["width"] - 200), self.rng.uniform(150, VIEWPORT["height"] - 150))
        page.mouse.move(*self.at)

    def _locator(self, target):
        return self.page.locator(target) if isinstance(target, str) else target

    def pause(self, low: float = 0.25, high: float = 0.9) -> None:
        time.sleep(self.rng.uniform(low, high))

    def move_to(self, x: float, y: float) -> None:
        for px, py, wait_ms in pointer_path(self.at, (x, y), self.rng):
            time.sleep(wait_ms / 1000)
            self.page.mouse.move(px, py)
        self.at = _clamp(x, y)

    def hover(self, target) -> tuple[float, float]:
        """Bring the pointer over the target, scrolling it into view first. Returns where it stopped."""
        locator = self._locator(target).first
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if not box:
            raise RuntimeError("That element isn't on the page to point at.")
        # Somewhere in its middle part, as a person aims: never the exact centre, never the edge.
        x = box["x"] + box["width"] * self.rng.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * self.rng.uniform(0.3, 0.7)
        self.move_to(x, y)
        return self.at

    def click(self, target, _note: bool = True) -> None:
        traced = _note and runtrace.current()
        name = runtrace.describe(self._locator(target)) if traced else ""
        self.hover(target)
        time.sleep(self.rng.uniform(0.06, 0.22))
        if traced:  # the picture just before the click, with what it's about to click marked
            runtrace.browsed(f"Clicked \u201c{name}\u201d" if name else "Clicked", runtrace.box(self._locator(target)), force=True)
        runtrace.mark()
        self.page.mouse.down()
        time.sleep(self.rng.uniform(0.045, 0.13))
        self.page.mouse.up()
        self.pause(0.15, 0.5)

    def type(self, target, text: str) -> None:
        """Click into the field, then type the text key by key."""
        locator = self._locator(target)
        traced = runtrace.current()
        name = runtrace.describe(locator) if traced else ""
        secret = traced and runtrace.secret_field(locator)
        self.click(target, _note=False)
        for char, gap in zip(text, typing_gaps(text, self.rng)):
            time.sleep(gap / 1000)
            self.page.keyboard.type(char)
        self.pause(0.15, 0.4)
        shown = "\u2022" * 6 if secret else (text if len(text) <= 80 else text[:79] + "\u2026")
        runtrace.browsed(f"Typed \u201c{shown}\u201d" + (f" into {name}" if name else ""), runtrace.box(locator) if traced else None)

    def read(self, most: float = 6.0, _what: str = "Looked at the page") -> None:
        """Take in the page before acting on it, as a person does: longer when there's more on
        it to read (a skim, never the whole text), sometimes with a small scroll and back."""
        try:
            words = len(self.page.evaluate("document.body ? document.body.innerText : ''").split())
        except Exception:
            words = 0
        seconds = min(most, 0.7 + words / 180) * self.rng.uniform(0.7, 1.3)
        if words > 150 and self.rng.random() < 0.5:
            down = self.rng.uniform(120, 420)
            time.sleep(seconds * 0.4)
            self.scroll(down)
            time.sleep(seconds * 0.4)
            self.scroll(-down)
        else:
            time.sleep(seconds)
        runtrace.browsed(_what)

    def goto(self, url: str) -> None:
        """Open a page, then take a moment to read it."""
        self.page.goto(url)
        self.read(_what="Opened the page")

    def press(self, key: str) -> None:
        time.sleep(self.rng.uniform(0.08, 0.3))
        runtrace.mark()
        self.page.keyboard.press(key)
        runtrace.browsed(f"Pressed {key}")

    def scroll(self, dy: float) -> None:
        """Scroll by dy pixels in a few uneven turns of the wheel."""
        left = dy
        while abs(left) > 1:
            turn = math.copysign(min(abs(left), self.rng.uniform(80, 220)), left)
            self.page.mouse.wheel(0, turn)
            left -= turn
            time.sleep(self.rng.uniform(0.03, 0.12))
        self.pause(0.2, 0.6)
