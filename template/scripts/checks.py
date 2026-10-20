#!/usr/bin/env python3
"""Test a proposal before the owner acts on it: "Test it" under a chat reply that proposes something.

Asked the same thing in other words, the COO can talk itself into a different answer. A test gives it
something to stand on instead: a fixed point of view and a checklist, run once, apart from the chat.

1. After each chat turn, `offer()` asks Jev (fractions of a cent, input only) whether the reply
   proposes something worth testing, and which test fits. A reply that saved a plan is always offered
   one. Without Jev, only plans are offered (by the plan's kind), so no model runs on every reply.
2. The owner taps the button: `start()` runs one plain API call (not a Claude Code turn, so none of the
   chat's context or tools), with the proposal, a short summary of the business and, for a live web page
   in a customer test, pictures of it from a real browser. A few cents of the plan's included AI.
3. The result keeps the proposal unless something concrete broke: each finding names a moment, and in
   customer and pushback tests it counts only when two voices hit it. Edits are exact replacements the
   owner picks; `apply()` saves them as a new version of the plan (no AI), and for a reply without a
   plan the dashboard asks the COO in the chat.

Results are kept per message in .cache/checks/, so tapping again shows the same one; a plan that has
changed since can be tested again.

    .venv/bin/python scripts/checks.py shots <url> <folder>     # pictures of a page (a burst Job runs it)
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from datetime import date
from pathlib import Path

from common import CACHE, ROOT, log_run, now_iso

FOLDER = CACHE / "checks"
PER_DAY = 30
STALE = 600  # seconds: a test still "running" after this died with its process
MAX_FINDINGS, MAX_EDITS, MAX_SHOTS = 5, 3, 4

KINDS = {
    "customers": "Customers go through it: a landing page, website, offer, ad, email, menu, flyer or anything else "
                 "customers will see or read",
    "numbers": "Check the numbers: prices, a budget, costs, margins, a forecast, a financial plan",
    "week": "Run a normal week through it: a process, an operations, hiring or launch plan with steps people will carry out",
    "pushback": "Hear the pushback: a strategy, positioning, a sales pitch, a big business choice or a plan to convince someone",
}
# A saved plan's kind (plans.KINDS) when Jev can't say.
BY_PLAN_KIND = {"marketing": "customers", "customer": "customers", "product": "customers", "sales": "pushback",
                "business": "pushback", "financial": "numbers", "operations": "week", "hiring": "week", "launch": "week"}
NEEDS_TWO = ("customers", "pushback")  # several voices: a problem counts when two of them hit it

_running: set[str] = set()
_lock = threading.Lock()


# ---------- offering one ----------

def offer(said: str, reply: str, saved: list[dict] | None = None) -> dict | None:
    """After a chat turn: {"kind"} when the reply proposes something worth testing, else None.
    Never raises, and never runs more than one Jev call."""
    try:
        saved = saved or []
        if not saved and len(reply or "") < 400:
            return None  # short answers don't propose anything worth a test
        kind = _jev_kind(said, reply)
        if kind is None and saved:
            import plans

            p = plans.find(saved[-1]["id"])
            kind = BY_PLAN_KIND.get(p["kind"] if p else "", "pushback")
        return {"kind": kind} if kind else None
    except Exception as e:  # noqa: BLE001 - never break the chat over it
        log_run("checks", "error", step="offer", error=repr(e)[:300])
        return None


def _jev_kind(said: str, reply: str) -> str | None:
    """Jev only: when it isn't set up, or isn't sure, nothing is offered (Haiku on every reply would cost
    more than it's worth)."""
    import decide

    target = decide._jev_target()
    if not target:
        return None
    options = {**KINDS, "none": "Not a proposal: an answer, a status update, a question, a small task done, a quick "
                                "fact, or a list of options without a recommendation (the safe answer when unsure)"}
    try:
        d = decide._jev("This is a business owner's chat with their COO. Does the COO's reply propose something the "
                        "owner would act on (a page, an offer, a plan, a price, a process) that's worth testing before "
                        "they do? If so, which test fits it best?",
                        options, f"Owner: {(said or '').strip()[:1500]}\n\nCOO: {(reply or '').strip()[:3000]}", target)
    except Exception:  # noqa: BLE001 - unsure, over budget or unreachable: no button
        return None
    return d.choice if d.choice in KINDS else None


# ---------- the test ----------

def _path(message: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{6,40}", message or ""):
        raise CheckError("Which message?")
    return FOLDER / f"{message}.json"


class CheckError(Exception):
    """Something to tell the owner, in plain words."""


def load(message: str) -> dict | None:
    path = _path(message)
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if state.get("status") == "running" and message not in _running and time.time() - state.get("startedTs", 0) > STALE:
        state = {**state, "status": "failed", "error": "The test stopped before it finished. Try again."}
    return state


def _save(message: str, state: dict) -> None:
    FOLDER.mkdir(exist_ok=True)
    tmp = _path(message).with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(_path(message))


def view(message: str) -> dict:
    """The test for a message, for the app: {"status": "none"|"running"|"done"|"failed", ...}, and whether
    its plan has changed since (so it can be tested again)."""
    state = load(message)
    if not state:
        return {"status": "none"}
    out = {k: v for k, v in state.items() if k not in ("startedTs", "subject")}
    plan = state.get("plan")
    if plan and state.get("status") == "done":
        import plans

        p = plans.find(plan["id"])
        out["planChanged"] = bool(p and p["version"] != plan["version"])
    return out


def _today_count() -> int:
    today = date.today().isoformat()
    n = 0
    for f in FOLDER.glob("*.json") if FOLDER.exists() else []:
        try:
            n += json.loads(f.read_text()).get("startedAt", "").startswith(today)
        except (OSError, ValueError):
            continue
    return n


def start(message: str, entry: dict, said: str, kind: str, coo: str = "your business manager") -> dict:
    """Start testing a reply (a chat log entry) in the background; the app polls view(). A finished test
    is returned as it is, unless its plan has changed since."""
    if kind not in KINDS:
        raise CheckError("Which test?")
    with _lock:
        state = load(message)
        if state and state.get("status") == "running":
            return view(message)
        if state and state.get("status") == "done" and not view(message).get("planChanged"):
            return view(message)
        if _today_count() >= PER_DAY:
            raise CheckError(f"That's {PER_DAY} tests today. Try again tomorrow.")
        subject, plan, title = _subject(entry)
        _save(message, {"status": "running", "kind": kind, "startedAt": now_iso(), "startedTs": time.time(),
                        "title": title, **({"plan": plan} if plan else {})})
        _running.add(message)
    threading.Thread(target=_run, args=(message, kind, subject, plan, title, said, entry, coo), daemon=True).start()
    return view(message)


def _subject(entry: dict) -> tuple[str, dict | None, str]:
    """What to test: the plan the reply saved (its current version), else the reply itself."""
    saved = ((entry.get("artifacts") or {}).get("plans") or [])
    if saved:
        import plans

        p = plans.find(saved[-1]["id"])
        if p:
            return plans.body(p["id"]), {"id": p["id"], "version": p["version"]}, p["title"]
    return entry.get("text") or "", None, ""


def _business() -> str:
    """Who the business sells to, what it charges, what it's after: the COO's notes, briefly."""
    parts = []
    for name, cap in (("company.md", 3000), ("decisions.md", 800)):
        try:
            text = (ROOT / "memory" / name).read_text().strip()
        except OSError:
            continue
        if text:
            parts.append(text[:cap])
    return "\n\n".join(parts) or "(No notes about the business yet.)"


def _url(*texts: str) -> str | None:
    """The first web page named in the owner's message or the reply."""
    for text in texts:
        m = re.search(r"https?://[^\s)\]>\"'`]+", text or "")
        if m:
            return m.group(0).rstrip(".,;:!?")
    return None


def shots(url: str, folder: Path) -> list[Path]:
    """Pictures of a page as a first-time visitor sees it, top to bottom (up to MAX_SHOTS), and its text
    in text.txt. Only reads: everything but GET is refused, nothing is clicked or typed."""
    from playwright.sync_api import sync_playwright

    import browser

    folder.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    with sync_playwright() as pw:
        context = browser.launch(pw, viewport={"width": 1280, "height": 860})
        try:
            context.set_default_timeout(25_000)
            context.route("**/*", lambda r: r.continue_() if r.request.method in ("GET", "HEAD", "OPTIONS")
                          else r.fulfill(status=204, body=""))
            page = browser.first_page(context)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            (folder / "text.txt").write_text(page.inner_text("body")[:6000])
            height = page.evaluate("document.body.scrollHeight") or 860
            for i in range(MAX_SHOTS):
                if i and i * 860 >= height:
                    break
                page.evaluate(f"window.scrollTo(0, {i * 860})")
                page.wait_for_timeout(400)
                path = folder / f"{i + 1}.jpg"
                page.screenshot(path=str(path), type="jpeg", quality=55)
                out.append(path)
        finally:
            browser.close(context)
    return out


def _page(url: str, message: str) -> tuple[list[Path], str]:
    """Pictures and text of the page, taken in a burst Job when the platform has them (Chromium is heavy)."""
    import burst

    folder = FOLDER / f"{message}-page"
    proc = burst.run([sys.executable, str(Path(__file__)), "shots", url, str(folder)], kind="browser", timeout=180)
    if proc.returncode != 0:
        log_run("checks", "error", step="page", url=url[:200], error=(proc.stderr or "")[-300:])
        return [], ""
    pics = sorted(folder.glob("*.jpg"), key=lambda p: int(p.stem))
    try:
        text = (folder / "text.txt").read_text()
    except OSError:
        text = ""
    return pics, text


INSTRUCTIONS = {
    "customers": ("Be three real potential customers of this business, each different (for example: someone in a hurry "
                  "on a phone, a skeptic comparing alternatives, someone careful about price). Go through it as each "
                  "would, in order, and say what they notice, what they understand, and where they hesitate, get "
                  "confused or leave."),
    "numbers": ("Be a careful bookkeeper. Recompute every figure: totals, margins, prices against costs, what has to "
                "be true for the numbers to work. Check them against what the notes say about the business. Use "
                "two more voices only if a figure depends on how customers behave."),
    "week": ("Be the people who will carry this out (the owner and whoever helps them), running an ordinary week "
             "through it step by step: who does what, when, with what. Find where it stalls, who's overloaded, what's "
             "missing, what nobody owns."),
    "pushback": ("Be three people who'd push back on this for real (for example: a doubtful customer, a competitor, "
                 "a cautious partner or banker). Each makes their strongest objection to the specific proposal."),
}

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "voices": {"type": "array", "items": {"type": "object", "properties": {
            "who": {"type": "string"}, "went": {"type": "string"}, "stuck": {"type": "string"}},
            "required": ["who", "went", "stuck"], "additionalProperties": False}},
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "moment": {"type": "string"}, "problem": {"type": "string"},
            "voices": {"type": "array", "items": {"type": "string"}}, "fix": {"type": "string"}},
            "required": ["id", "moment", "problem", "voices", "fix"], "additionalProperties": False}},
        "held": {"type": "array", "items": {"type": "string"}},
        "edits": {"type": "array", "items": {"type": "object", "properties": {
            "finding": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"}, "why": {"type": "string"}},
            "required": ["finding", "find", "replace", "why"], "additionalProperties": False}},
    },
    "required": ["summary", "voices", "findings", "held", "edits"],
    "additionalProperties": False,
}


def _prompt(kind: str, subject: str, title: str, said: str, reply: str, page_text: str, pictures: int) -> str:
    what = f"the plan “{title}”" if title else "the COO's proposal"
    parts = [
        f"A small business owner is about to act on {what}. Test it before they do. {INSTRUCTIONS[kind]}",
        "Rules, so the test is worth more than a second opinion:\n"
        "- Ground every voice in what the notes say about this business: its real customers, prices and goals.\n"
        "- A finding names one concrete moment (\"reached the price and couldn't tell if setup is extra\"), not a "
        "vague doubt (\"the headline could be stronger\"). No moment, no finding.\n"
        + ("- A finding counts only when at least two of the voices hit it. List them by name in `voices`.\n"
           if kind in NEEDS_TWO else "- Quote the figure or step a finding is about.\n")
        + f"- At most {MAX_FINDINGS} findings, most important first. None is a fine answer: if it holds up, say so.\n"
        "- `held`: up to 3 short things that worked and should stay.\n"
        f"- `edits` (at most {MAX_EDITS}), only for findings: `find` is text copied exactly from the proposal below "
        "(a line or a sentence, under 300 characters), and `replace` is what goes there instead. To add something, "
        "`find` is the line it goes after and `replace` is that line followed by the addition. Keep everything else.\n"
        "- `summary`: one or two plain sentences for the owner: did it hold up, and the one thing to change if any.\n"
        "- Plain words for a non-technical owner. No jargon. Write in the language of the proposal.",
        f"<business_notes>\n{_business()}\n</business_notes>",
        f"<owner_asked>\n{(said or '').strip()[:2000]}\n</owner_asked>",
    ]
    if title:
        parts.append(f"<coo_reply>\n{(reply or '').strip()[:3000]}\n</coo_reply>")
    parts.append(f"<proposal>\n{subject[:40_000]}\n</proposal>")
    if page_text:
        parts.append(f"<live_page_text>\n{page_text}\n</live_page_text>\n"
                     f"The {pictures} pictures are this live page from top to bottom, as a first-time visitor on a "
                     "laptop sees it. The voices go through the real page; edits still apply to the proposal text.")
    return "\n\n".join(parts)


def _tidy(kind: str, data: dict, subject: str) -> dict:
    """Hold the model to the rules: concrete findings only, two voices where it takes two, edits only for
    the findings that stand, and whether each edit's text is really in the proposal."""
    voices = data.get("voices") or []
    findings = []
    for f in (data.get("findings") or [])[:MAX_FINDINGS]:
        if not (f.get("moment") or "").strip():
            continue
        if kind in NEEDS_TWO and len(voices) > 1 and len({v.strip().lower() for v in f.get("voices") or []}) < 2:
            continue
        findings.append(f)
    kept = {f["id"] for f in findings}
    edits = []
    for i, e in enumerate(data.get("edits") or []):
        if e.get("finding") not in kept or not (e.get("replace") or "").strip() or len(edits) >= MAX_EDITS:
            continue
        edits.append({"id": f"e{i + 1}", **e, "applies": bool(e.get("find")) and e["find"] in subject})
    return {"summary": data.get("summary", ""), "voices": voices[:4], "findings": findings,
            "held": (data.get("held") or [])[:3], "edits": edits}


def _run(message: str, kind: str, subject: str, plan: dict | None, title: str, said: str, entry: dict, coo: str) -> None:
    import supervise
    from ops_db import record_event

    state = load(message) or {}
    try:
        pictures, page_text = [], ""
        url = _url(said, entry.get("text") or "") if kind == "customers" else None
        if url:
            pictures, page_text = _page(url, message)
        data = supervise._ask(_prompt(kind, subject, title, said, entry.get("text") or "", page_text, len(pictures)),
                              pictures, SCHEMA, "check", cap_usd="0.40", max_tokens=3000)
        result = _tidy(kind, data, subject)
        state = {**state, "status": "done", "finishedAt": now_iso(), "result": result,
                 **({"page": url} if pictures else {})}
        what = f"“{title}”" if title else "a proposal from the chat"
        record_event(f"Tested {what}: {result['summary'][:200]}", who="COO")
        log_run("checks", "done", kind=kind, findings=len(result["findings"]), edits=len(result["edits"]), page=bool(pictures))
    except Exception as e:  # noqa: BLE001 - the owner sees it didn't work, and can try again
        log_run("checks", "error", step="run", error=repr(e)[:300])
        why = str(e) if e.__class__.__name__ == "BudgetExceeded" else "The test didn't finish. Try again in a minute."
        state = {**state, "status": "failed", "error": why}
    finally:
        _save(message, state)
        _running.discard(message)
        import shutil

        shutil.rmtree(FOLDER / f"{message}-page", ignore_errors=True)


# ---------- using the result ----------

def apply(message: str, edit_ids: list[str]) -> dict:
    """The owner's picks of a finished test's edits, saved as a new version of the plan it tested (no AI).
    Returns {"plan", "version", "applied": [ids], "skipped": [ids]}: an edit whose text the plan no longer
    has is skipped."""
    import plans

    state = load(message)
    if not state or state.get("status") != "done":
        raise CheckError("That test isn't finished.")
    plan = state.get("plan")
    if not plan:
        raise CheckError("This reply has no plan to change. Ask in the chat instead.")
    edits = [e for e in state["result"]["edits"] if e["id"] in set(edit_ids)]
    if not edits:
        raise CheckError("Pick at least one change.")
    p = plans.find(plan["id"])
    if not p:
        raise CheckError("That plan was removed.")
    text, applied, skipped = plans.body(p["id"]), [], []
    for e in edits:
        if e["find"] and e["find"] in text:
            text = text.replace(e["find"], e["replace"], 1)
            applied.append(e["id"])
        else:
            skipped.append(e["id"])
    if not applied:
        raise CheckError("The plan has changed since the test, so these changes don't fit any more. Test it again.")
    note = "From the test: " + "; ".join(e["why"] for e in edits if e["id"] in applied)
    saved = plans.save(p["title"], text, note=note[:300], who="you", plan_id=p["id"])
    version = saved["plan"]["version"]
    state["applied"] = sorted({*state.get("applied", []), *applied})
    state["plan"] = {"id": p["id"], "version": version}  # the plan as changed by the test: not "changed since"
    _save(message, state)
    log_run("checks", "applied", plan=p["id"], version=version, edits=applied)
    return {"plan": p["id"], "version": version, "applied": applied, "skipped": skipped}


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "shots":
        shots(sys.argv[2], Path(sys.argv[3]))
    else:
        print(__doc__)
        sys.exit(1)
