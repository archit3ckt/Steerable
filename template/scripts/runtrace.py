"""What a run did, step by step, with pictures: so the owner sees what a routine will do before
they trust it.

Two kinds of run keep a trace:
- the practice run the engine gives every new or changed routine before the owner switches it on
  (builder.py; STEERABLE_DRY_RUN=1, nothing is sent): what it would do;
- its first live runs, while it's watched (supervise.py): what it did, and what was held back.

The heartbeat and the builder set STEERABLE_TRACE=<id> for those runs; without it, everything here
does nothing, so other runs pay nothing for it. Kept in .cache/traces/<id>/: trace.json (what run it
was, how it went, the AI's review), events.jsonl (one line per thing that happened) and
shots/<n>.jpg (what the page looked like).

Events, by kind:
    step     {step}                   a step of its flow chart started (common.step)
    browse   {what, url, shot}        it clicked, typed or opened a page (browser.Human)
    would    {what, action, detail}   something it can't undo, in a practice run: not done (common.act)
    did      {what, action, detail}   ... in a watched run, checked and done
    held     {what, action, detail, why}  ... in a watched run, held back by the supervisor
    record   {table, change, cells}   a library row it would add or change (practice runs only)
    message  {text}                   news it would send the owner (practice runs only)
    draft    {name, text}             a draft or report it would save (practice runs only)
    network  {method, url, fields}    a website was sent something that wasn't said beforehand
"""
import json
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import CACHE, now_iso

TRACES = CACHE / "traces"
MAX_SHOTS = 80  # then only what it can't undo, and clicks, get a picture
MAX_FORCED = 160
MIN_GAP = 0.5  # seconds between pictures of ordinary browsing
KEEP_PER_ROUTINE = 10
KEEP_DAYS = 30
SECRET = re.compile(r"pass|token|secret|card|cvv|cvc|ssn|otp|code|auth|csrf|nonce|session|key", re.I)
ID = re.compile(r"^[\w-]{1,60}$")

_page = None
_shots = 0
_last_shot = 0.0
_count = 0
_last_action = 0.0  # when browser.Human last clicked, typed or pressed a key
_sent: set[tuple[str, str]] = set()
_background: set[tuple[str, str]] = set()  # requests the page makes on its own (polls, reporting)
AFTER_ACTION = 4.0  # seconds: a site's own request this soon after a click is the routine's doing
NETWORK_MAX = 20
# A site's own background reporting (analytics, logs, ads), not something the routine did.
NOISE = re.compile(r"collect|analytic|track|telemetry|metric|beacon|pixel|/log|logging|event|stats|"
                   r"impression|/ads?[/?]|doubleclick|gtm|sentry|rum|heartbeat|ping|consent", re.I)


def current() -> str | None:
    """This run's trace id, if it keeps one."""
    tid = os.environ.get("STEERABLE_TRACE") or ""
    return tid if ID.fullmatch(tid) else None


def folder(tid: str) -> Path:
    if not ID.fullmatch(tid or ""):
        raise ValueError("Which run?")
    return TRACES / tid


def start(tid: str, **meta) -> None:
    """Open a trace (the heartbeat or builder, before the run)."""
    d = folder(tid)
    shutil.rmtree(d, ignore_errors=True)
    (d / "shots").mkdir(parents=True)
    (d / "trace.json").write_text(json.dumps({"id": tid, "started": now_iso(), **meta}))


def update(tid: str, **fields) -> dict:
    path = folder(tid) / "trace.json"
    meta = {**json.loads(path.read_text()), **fields}
    path.write_text(json.dumps(meta))
    return meta


def event(kind: str, **fields) -> None:
    """Note one thing that happened. Never fails: a run mustn't break over its own trace."""
    global _count
    tid = current()
    if not tid:
        return
    try:
        _count += 1
        line = {"n": _count, "at": now_iso(), "kind": kind, **fields}
        with (folder(tid) / "events.jsonl").open("a") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except (OSError, ValueError):
        pass


def watch(page) -> None:
    """The page pictures come from (integrations.site_browser hands it over). In a trace, a website
    that's sent something with no common.act() just before is noted, so a routine can't change
    things on a site without saying so."""
    global _page
    _page = page
    if not current():
        return
    try:
        page.on("request", _request)
    except Exception:  # noqa: BLE001
        pass


def _site(host: str) -> str:
    """The site an address belongs to: shop.example.co.il and www.example.co.il are both example.co.il."""
    labels = (host or "").lower().split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in ("co", "com", "org", "net", "ac", "gov", "or", "ne"):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _request(request) -> None:
    """Note what the routine sent to the site without act(): a form it submitted, or a request the site
    made right after one of its clicks. Not the page's own background traffic: other sites (analytics,
    ads, chat widgets) and the site's own reporting."""
    import common
    from urllib.parse import urlsplit

    try:
        kind = request.resource_type
        if request.method in ("GET", "HEAD", "OPTIONS") or kind not in ("document", "xhr", "fetch"):
            return
        if common.acting():
            return  # covered by what it said it would do
        url, page_url = urlsplit(request.url), urlsplit(_page.url if _page is not None else "")
        if _site(url.hostname or "") != _site(page_url.hostname or ""):
            return
        import browser

        if browser.keeps_login(request.url, page_url.hostname or ""):
            return  # the site keeping the owner logged in, not the routine's doing
        key = (request.method, _short_url(request.url))
        if kind != "document":
            if time.monotonic() - _last_action > AFTER_ACTION:
                _background.add(key)  # it sends this without being clicked: never the routine's doing
                return
            if key in _background or NOISE.search(url.path):
                return
        if key in _sent or len(_sent) >= NETWORK_MAX:
            return
        _sent.add(key)
        event("network", method=request.method, url=key[1], fields=form_fields(request.post_data or ""))
    except Exception:  # noqa: BLE001
        pass


def _short_url(url: str) -> str:
    return re.sub(r"[?#].*", "", url)[:200]


def form_fields(body: str, limit: int = 12) -> dict:
    """What a form or JSON body said, briefly, with anything secret-looking hidden."""
    pairs: dict = {}
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            pairs = data
    except (ValueError, TypeError):
        from urllib.parse import parse_qsl

        pairs = dict(parse_qsl(body or "", keep_blank_values=True))
    out = {}
    for k, v in list(pairs.items())[:limit]:
        text = v if isinstance(v, str) else json.dumps(v, default=str)
        out[str(k)[:60]] = "••••" if SECRET.search(str(k)) else text[:120]
    return out


def shot(force: bool = False) -> str | None:
    """A picture of the page as it is now, if this run keeps a trace and has a page. Returns its name."""
    global _shots, _last_shot
    tid = current()
    if not tid or _page is None:
        return None
    if _shots >= MAX_FORCED or (not force and (_shots >= MAX_SHOTS or time.monotonic() - _last_shot < MIN_GAP)):
        return None
    try:
        name = f"{_shots + 1}.jpg"
        _page.screenshot(path=str(folder(tid) / "shots" / name), type="jpeg", quality=55, timeout=8000)
        _shots += 1
        _last_shot = time.monotonic()
        return name
    except Exception:  # noqa: BLE001 - a page mid-navigation, a closed browser
        return None


def mark() -> None:
    """browser.Human as it clicks or presses a key: what the site sends next is the routine's doing."""
    global _last_action
    _last_action = time.monotonic()


def box(locator) -> list[float] | None:
    """Where an element is in the picture, as fractions of the page's view [x, y, width, height], so
    the app can mark what was clicked or typed into. None if it isn't in view."""
    if not current() or _page is None or locator is None:
        return None
    try:
        b = locator.first.bounding_box(timeout=1500)
        view = _page.viewport_size
        if not b or not view:
            return None
        x0, y0 = max(b["x"], 0), max(b["y"], 0)
        x1, y1 = min(b["x"] + b["width"], view["width"]), min(b["y"] + b["height"], view["height"])
        if x1 <= x0 or y1 <= y0:
            return None
        return [round(x0 / view["width"], 4), round(y0 / view["height"], 4),
                round((x1 - x0) / view["width"], 4), round((y1 - y0) / view["height"], 4)]
    except Exception:  # noqa: BLE001
        return None


def browsed(what: str, where: list[float] | None = None, force: bool = False) -> None:
    """browser.Human after a click, typing or opening a page; `where`: the element it acted on (box())."""
    global _last_action
    if not current():
        return
    if not what.startswith(("Opened", "Looked")):
        _last_action = time.monotonic()
    url = ""
    try:
        url = _short_url(_page.url) if _page is not None else ""
    except Exception:  # noqa: BLE001
        pass
    picture = shot(force=force)
    event("browse", what=what[:160], url=url, shot=picture, **({"box": where} if picture and where else {}))


def describe(locator) -> str:
    """What a person would call the thing being clicked: its text or label."""
    try:
        text = locator.first.evaluate(
            "e => (e.getAttribute('aria-label') || (e.labels && e.labels[0] && e.labels[0].innerText) || e.innerText"
            " || e.value || e.placeholder || e.name || e.title || '').trim()",
            timeout=1500)
        return re.sub(r"\s+", " ", str(text))[:60]
    except Exception:  # noqa: BLE001
        return ""


def secret_field(locator) -> bool:
    try:
        return bool(locator.first.evaluate(
            "e => e.type === 'password' || /pass|card|cvv|cvc|otp|code/i.test(e.name + ' ' + e.id + ' ' + (e.autocomplete || ''))",
            timeout=1500))
    except Exception:  # noqa: BLE001
        return False


# ---------- reading ----------

def load(tid: str) -> dict | None:
    """A trace for the app: what run it was, and what happened, in order."""
    d = folder(tid)
    try:
        meta = json.loads((d / "trace.json").read_text())
    except (OSError, ValueError):
        return None
    events = []
    try:
        for line in (d / "events.jsonl").read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return {**meta, "events": events}


def shot_path(tid: str, name: str) -> Path:
    if not re.fullmatch(r"\d{1,4}\.jpg", name or ""):
        raise ValueError("No such picture.")
    path = folder(tid) / "shots" / name
    if not path.exists():
        raise ValueError("No such picture.")
    return path


def prune(keep: set[str] = frozenset()) -> int:
    """The last KEEP_PER_ROUTINE traces of each routine, none older than KEEP_DAYS (upkeep), except
    those still in use (`keep`: a practice run waiting for the owner). Returns how many went."""
    if not TRACES.exists():
        return 0
    old = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    by_routine: dict[str, list[tuple[str, Path]]] = {}
    gone = 0
    for d in TRACES.iterdir():
        try:
            meta = json.loads((d / "trace.json").read_text())
        except (OSError, ValueError):
            meta = {"started": ""}
        if d.name in keep:
            continue
        if meta.get("started", "") < old:
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
        else:
            by_routine.setdefault(meta.get("workflow", ""), []).append((meta.get("started", ""), d))
    for items in by_routine.values():
        for _, d in sorted(items, reverse=True)[KEEP_PER_ROUTINE:]:
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
    return gone
