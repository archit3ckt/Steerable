"""Watching a routine until it's earned trust.

A new or changed routine never goes live untested and unseen:
1. Practice run. The builder runs it once with STEERABLE_DRY_RUN=1 and a trace (runtrace.py): every
   step, page and click with pictures, and everything it would do that can't be undone. review()
   reads that trace and the routine's code and tells the owner, in plain words, what it will do and
   which situations it doesn't seem to handle. The owner switches it on, asks for a change, or drops it.
2. Watched runs. Switched on, it's watched for its first runs: each thing it can't undo (common.act,
   and the engine's own guard around connected services and posts) is looked at first by check(),
   with the page as it is right then, the routine's records and what the owner said before. A doubt
   holds that one thing back; the owner hears what was held and why, and picks: fix the routine so
   it handles it, it was fine (remembered for next time), or leave it.
3. Trust. After WATCH_RUNS watched runs in a row with nothing held and no problems, the owner is asked
   whether it can run on its own. They can also stop watching it, or start again, on its page.

State in .cache/supervision.json, per routine: {"since", "runs", "clean", "notes": [the owner's
"that was fine" answers], "reviews": {trace id: {"at", "held": [...], "status"}}}.

    python scripts/supervise.py                 # what's watched
"""
import ast
import base64
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from budget import BudgetExceeded, check as budget_check, record, record_usage
from common import CACHE, ROOT, env, log_run, now_iso, task_title

STATE = CACHE / "supervision.json"
WATCH_RUNS = 3
CHECKS_PER_RUN = 30  # past this, the rest are held: a run shouldn't do that much unwatched by the owner
MODEL = "claude-sonnet-5-5"
NOTES_KEPT = 30

_checks = 0


# ---------- state ----------

def load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


@contextmanager
def _state():
    with (CACHE / "supervision.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        s = load()
        yield s
        STATE.write_text(json.dumps(s, indent=1))


def watching(workflow: str) -> bool:
    return workflow in load()


def status(workflow: str) -> dict | None:
    """For the routine's page: watched runs so far, and how many in a row went clean."""
    w = load().get(workflow)
    return ({"since": w["since"], "why": w.get("why", "new"), "runs": w.get("runs", 0), "clean": w.get("clean", 0),
             "needed": WATCH_RUNS} if w else None)


def start(workflow: str, why: str = "new") -> None:
    """Watch it from its next run. `why`: new (a new or changed routine was switched on), owner (they
    asked), problem (it hit one: whatever happens next, it's checked again) or fixed (a fix went in).
    Already watched: the count of clean runs starts again, what was held stays."""
    with _state() as s:
        old = s.get(workflow, {})
        s[workflow] = {"since": old.get("since") or now_iso(), "why": why if not old else old.get("why", why),
                       "runs": old.get("runs", 0), "clean": 0, "notes": old.get("notes", []), "reviews": old.get("reviews", {})}
    log_run("supervise", "watching", workflow=workflow, why=why)


def stop(workflow: str) -> None:
    with _state() as s:
        s.pop(workflow, None)
    log_run("supervise", "trusted", workflow=workflow)


# ---------- asking the AI ----------

def _ask(prompt: str, images: list[Path], schema: dict, source: str, cap_usd: str = "0.30", max_tokens: int = 1500) -> dict:
    """One question to Claude, with pictures. Through the API when there's a key (the gateway in
    Steerable Cloud), else Claude Code signed in with the owner's Claude account."""
    budget_check()
    if env("ANTHROPIC_API_KEY"):
        import anthropic

        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(p.read_bytes()).decode()}} for p in images]
        content.append({"type": "text", "text": prompt})
        response = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": schema}})
        record_usage(source, MODEL, response.usage)
        return json.loads(next(b.text for b in response.content if b.type == "text"))
    where = ""
    if images:
        where = "\n\nLook at these pictures of the page first (Read them): " + ", ".join(str(p) for p in images)
    allowed = [f"Read({p})" for p in images]
    proc = subprocess.run(["claude", "-p", prompt + where, "--model", "sonnet", "--output-format", "json",
                           "--json-schema", json.dumps(schema), "--max-budget-usd", cap_usd,
                           *(["--allowedTools", *allowed] if allowed else [])],
                          capture_output=True, text=True, timeout=300, cwd=tempfile.gettempdir())
    try:
        out = json.loads(proc.stdout)
        data = out.get("structured_output") or json.loads(out["result"])
    except (ValueError, KeyError, TypeError):
        raise RuntimeError(f"No answer: {(proc.stderr or proc.stdout)[-200:]}") from None
    record(source, float(out.get("total_cost_usd") or 0), "sonnet", note="claude account")
    return data


def _routine_about(workflow: str) -> str:
    """What the routine is for: its task line, its docstring and its steps."""
    import flow

    parts = []
    task = next((line for line in (ROOT / "tasks.md").read_text().splitlines() if f"@workflow:{workflow}" in line), "")
    if task:
        parts.append(f"Routine: {task_title(task)}")
    try:
        doc = ast.get_docstring(ast.parse((ROOT / "workflows" / f"{workflow}.py").read_text())) or ""
        if doc:
            parts.append(f"What its code says it does:\n{doc[:1500]}")
    except (OSError, SyntaxError):
        pass
    steps = flow.load(workflow) or []
    if steps:
        parts.append("Its steps: " + "; ".join(f"{i}. {s.get('label', '')}" for i, s in enumerate(steps)))
    return "\n".join(parts)


def _records(detail) -> str:
    """Rows in the owner's library that mention what this is about (an application already sent,
    an invoice already chased), searched by the short values in its detail."""
    import library

    values = []
    if isinstance(detail, dict):
        values = [str(v) for v in detail.values() if isinstance(v, (str, int)) and 2 < len(str(v)) <= 120]
    elif isinstance(detail, str) and len(detail) <= 120:
        values = [detail]
    found = []
    try:
        for t in library.tables()[:15]:
            table = library.table(t["name"])
            for v in values[:3]:
                for row in table.query(search=v, limit=4)["rows"]:
                    found.append(f"- {t['name']}: " + json.dumps(row["cells"], ensure_ascii=False, default=str)[:400]
                                 + f" (updated {row['updated'][:10]})")
    except Exception as e:  # noqa: BLE001
        return f"(Couldn't search the records: {e})"
    return "\n".join(list(dict.fromkeys(found))[:12]) or "(No records mention it.)"


def _page_text() -> str:
    import runtrace

    try:
        return runtrace._page.evaluate("document.body ? document.body.innerText : ''")[:4000] if runtrace._page else ""
    except Exception:  # noqa: BLE001
        return ""


def _recent() -> str:
    """The last things this run did, from its trace."""
    import runtrace

    tid = runtrace.current()
    t = runtrace.load(tid) if tid else None
    lines = []
    for e in (t or {}).get("events", [])[-15:]:
        if e["kind"] in ("browse", "did", "held", "would"):
            lines.append(f"- {e['kind']}: {e.get('what', '')} {e.get('url', '')}".rstrip())
        elif e["kind"] == "step":
            lines.append(f"- step {e.get('step')}")
    return "\n".join(lines) or "(nothing yet)"


CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "go": {"type": "boolean"},
        "why": {"type": "string", "description": "for a busy owner who isn't technical: one plain sentence saying what you saw (\"The page says you already applied on Oct 3.\"), not an instruction"},
    },
    "required": ["go", "why"],
    "additionalProperties": False,
}


def check(what: str, kind: str, detail, shot: str | None) -> dict:
    """Should a watched routine go ahead with this, right now? {"go": bool, "why": sentence}. Holds
    when unsure, over budget, or when the check itself fails: a held thing can be done later, a
    done one can't be undone."""
    global _checks
    import runtrace

    workflow = os.environ.get("STEERABLE_WORKFLOW") or "?"
    _checks += 1
    if _checks > CHECKS_PER_RUN:
        return {"go": False, "why": f"It wanted to do more than {CHECKS_PER_RUN} things in one run, so I held the rest for you to see."}
    notes = load().get(workflow, {}).get("notes", [])
    page = _page_text()
    prompt = f"""You supervise a business routine that an AI built for a small business owner. It's in its first live
runs, so before it does anything it can't undo, you check it. Decide whether it should go ahead with this one
thing, right now.

{_routine_about(workflow)}

What it's about to do ({kind}): {what}
Details: {json.dumps(detail, ensure_ascii=False, default=str)[:2000] if detail else "(none)"}

What it did just before, this run:
{_recent()}

The owner's records that mention it:
{_records(detail)}

{"What the owner said about earlier things you held:" + chr(10) + chr(10).join("- " + n for n in notes[-10:]) if notes else ""}

{"The page right now (text):" + chr(10) + page if page else ""}
{"A picture of the page right now is attached." if shot else ""}

Go ahead only if it's clearly what the routine is for and nothing suggests it's wrong now. Hold it if anything
is off, for example: it was already done (the page or the records say so: "already applied", "submitted",
"paid", a record marked done), the page isn't what the routine expects (an error, a different item, a login
page, a form with missing or wrong answers), it's a duplicate of something this run just did, it goes to
someone or somewhere unexpected, or the details look wrong (empty, placeholder, garbled). When unsure, hold:
a held thing can be done later, a done thing can't be taken back."""
    prompt = re.sub(r"\n{3,}", "\n\n", prompt)
    images = []
    if shot and (tid := runtrace.current()):
        try:
            images.append(runtrace.shot_path(tid, shot))
        except ValueError:
            pass
    try:
        verdict = _ask(prompt, images, CHECK_SCHEMA, "supervisor")
        go, why = bool(verdict.get("go")), str(verdict.get("why") or "").strip()[:300]
    except BudgetExceeded:
        go, why = False, "This month's AI allowance is used up, so I couldn't check it and held it back."
    except Exception as e:  # noqa: BLE001
        log_run("supervise", "check_error", workflow=workflow, error=repr(e)[:300])
        go, why = False, "I couldn't check it just then, so I held it back to be safe."
    log_run("supervise", "go" if go else "held", workflow=workflow, what=what[:120], why=why)
    return {"go": go, "why": why or ("Looks right." if go else "Something looked off.")}


# ---------- the practice run, reviewed ----------

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "what it will do each time it runs, at most 3 short plain sentences for the owner"},
        "concerns": {"type": "array", "items": {"type": "string"},
                     "description": "situations it doesn't seem to handle, or things in the practice run that look wrong; one plain sentence each; empty if none"},
    },
    "required": ["summary", "concerns"],
    "additionalProperties": False,
}


def _event_line(e: dict, names: list[str] | None = None) -> str:
    kind = e["kind"]
    if kind == "step":
        n = int(e.get("step") or 0)
        name = names[n] if names and 0 <= n < len(names) else ""
        return f"[step {n}{': ' + name if name else ''}]"
    if kind == "browse":
        return f"browse: {e.get('what', '')} ({e.get('url', '')})"
    if kind in ("would", "did", "held"):
        d = json.dumps(e.get("detail"), ensure_ascii=False, default=str)[:300] if e.get("detail") else ""
        return f"{kind.upper()} ({e.get('action', '')}): {e.get('what', '')} {d}".strip() + (" (the engine caught it: the routine didn't ask first)" if e.get("auto") else "")
    if kind == "record":
        return f"library {e.get('change')} in {e.get('table')}: {json.dumps(e.get('cells'), ensure_ascii=False, default=str)[:200]}"
    if kind == "message":
        return f"message to the owner: {e.get('text', '')[:300]}"
    if kind == "draft":
        return f"draft {e.get('name')}: {e.get('text', '')[:200]}"
    if kind == "network":
        return f"SENT TO A WEBSITE WITHOUT ASKING: {e.get('method')} {e.get('url')} {json.dumps(e.get('fields'), ensure_ascii=False)[:200]}"
    return kind


def review(tid: str, workflow: str, code: str, task: str) -> dict:
    """Read a practice run's trace and the routine's code; tell the owner what it will do and what
    it doesn't seem to handle. Never fails: without a review the trace still speaks for itself."""
    import flow
    import runtrace

    t = runtrace.load(tid) or {"events": []}
    events = t["events"]
    names = t.get("steps") or [s["label"] for s in (flow.load(workflow) or [])]
    lines = [_event_line(e, names) for e in events][:300]
    printed = str(t.get("printed") or "").strip()
    pictures = [e["shot"] for e in events if e["kind"] == "would" and e.get("shot")][:4]
    pictures += [e["shot"] for e in events if e["kind"] == "browse" and e.get("shot")][-2:]
    images = []
    for name in dict.fromkeys(pictures):
        try:
            images.append(runtrace.shot_path(tid, name))
        except ValueError:
            pass
    prompt = f"""An AI built a routine for a small business owner and just ran it once as a practice run: nothing was
sent, submitted, paid or posted; things it can't undo were noted as WOULD instead. Before the owner switches it
on, explain what it will do, and check it for gaps.

Routine: {task_title(task)}
Task line: {task}

Its code:
```python
{code[:20000]}
```

What happened in the practice run, in order (reading pages and data isn't listed one by one, only clicks,
typing, things it would do, records and messages):
{chr(10).join(lines) or "(nothing listed)"}

What it printed at the end (its own account of what it found and did):
{printed or "(nothing)"}

{"Pictures of the pages at the moments that matter are attached." if images else ""}

summary: what it will do each time it runs, at most 3 short sentences in plain words (no code words, no file names), with numbers from
the practice run ("It would have applied to 3 jobs and skipped 2 you'd already applied to").
concerns: real gaps only, at most 5, the most important first, each a plain sentence the owner understands. Look especially at things it can't undo:
does it check its own records and the page before acting (already done, closed, changed, a duplicate)? Does it
make sure it worked afterwards? What happens when a page looks different from what it expects: does it stop and
ask, or carry on? Anything sent to a website without asking first? Anything in the practice run that looks
wrong (empty fields, wrong recipients, placeholder text)? No concerns about style or code quality."""
    try:
        out = _ask(prompt, images, REVIEW_SCHEMA, "supervisor", cap_usd="0.60")
        return {"summary": str(out.get("summary") or "")[:1200],
                "concerns": [str(c)[:300] for c in (out.get("concerns") or [])][:5]}
    except Exception as e:  # noqa: BLE001
        log_run("supervise", "review_error", workflow=workflow, error=repr(e)[:300])
        return {"summary": "", "concerns": []}


# ---------- after a watched run ----------

def after_run(workflow: str, tid: str, ok: bool) -> dict | None:
    """Count a watched run (the heartbeat, after it): what was held goes to the owner; enough clean
    runs in a row, and the owner is asked whether it can run on its own."""
    import runtrace
    from ops_db import record_event

    t = runtrace.load(tid) or {"events": []}
    held = [{"what": e.get("what", ""), "why": e.get("why", ""), "shot": e.get("shot"), "detail": e.get("detail")}
            for e in t["events"] if e["kind"] == "held"]
    did = sum(1 for e in t["events"] if e["kind"] == "did")
    unasked = [e for e in t["events"] if e["kind"] == "network"]
    with _state() as s:
        w = s.get(workflow)
        if w is None:
            return None
        w["runs"] = w.get("runs", 0) + 1
        clean = ok and not held and not unasked
        w["clean"] = w.get("clean", 0) + 1 if clean else 0
        if held or unasked:
            w.setdefault("reviews", {})[tid] = {"at": now_iso(), "held": held, "unasked": len(unasked), "status": "open"}
        snapshot = dict(w)
    bits = [f"did {did} thing{'s' if did != 1 else ''} after checking"] if did else []
    if held:
        bits.append(f"held back {len(held)}")
    record_event(f"Watched run {snapshot['runs']}: " + (", ".join(bits) if bits else "nothing needed checking") + ".",
                 who="COO", workflow=workflow, ref=tid)
    return snapshot


def reviews() -> list[dict]:
    """Watched runs with something held, waiting for the owner."""
    out = []
    for workflow, w in load().items():
        for tid, r in (w.get("reviews") or {}).items():
            if r.get("status") == "open":
                out.append({"workflow": workflow, "trace": tid, **r})
    return out


def trust_asks() -> list[dict]:
    """Routines that ran WATCH_RUNS times in a row without a doubt: may they run on their own?"""
    return [{"workflow": wf, **w} for wf, w in load().items() if w.get("clean", 0) >= WATCH_RUNS]


def answer_review(workflow: str, tid: str, choice: str, note: str = "") -> str:
    """The owner's answer about held things: "fix" (change the routine so it handles them), "fine"
    (they were right: remembered for the next checks) or "leave". Returns what happens, in words."""
    import builder

    with _state() as s:
        w = s.get(workflow) or {}
        r = (w.get("reviews") or {}).get(tid)
        if not r or r.get("status") != "open":
            raise KeyError(tid)
        r["status"] = choice
        if choice == "fine":
            for h in r["held"]:
                w.setdefault("notes", []).append(f"Held “{h['what']}” because: {h['why']} The owner said it was fine"
                                                 + (f": {note}" if note else "."))
            w["notes"] = w["notes"][-NOTES_KEPT:]
        held = list(r["held"])
    if choice != "fix":
        return "Noted for next time." if choice == "fine" else "Left as it is."
    task = next((line[6:] for line in (ROOT / "tasks.md").read_text().splitlines()
                 if f"@workflow:{workflow}" in line and line.startswith("- [ ] ")), "")
    change = ("While it was watched, these were held back before it did them:\n"
              + "\n".join(f"- {h['what']}: {h['why']}" for h in held)
              + "\nMake it handle these situations itself: check its records and the page before acting, and skip and "
              "tell the owner when something is off, instead of going ahead." + (f"\nThe owner says: {note}" if note else ""))
    if not task or not builder.start_change(workflow, task, change):
        return "It's already being changed; I'll add this when that's done."
    return "I'll change it so it handles this, and show you the practice run before it's used."


def answer_trust(workflow: str, trust: bool) -> None:
    with _state() as s:
        w = s.get(workflow)
        if w is None:
            return
        if trust:
            s.pop(workflow)
        else:
            w["clean"] = 0  # asked again after the next clean runs
    log_run("supervise", "trusted" if trust else "keep_watching", workflow=workflow)


if __name__ == "__main__":
    for wf, w in load().items():
        print(f"{wf}: {w.get('runs', 0)} watched runs, {w.get('clean', 0)} clean in a row, "
              f"{sum(1 for r in (w.get('reviews') or {}).values() if r.get('status') == 'open')} waiting for the owner")
    if not load():
        print("Nothing is being watched.")
    sys.exit(0)
