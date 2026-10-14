"""Nightly learning review: the COO turns the day's lessons into skills (.claude/skills/).

Goal:    a COO that gets better at this company's work over time.
Metric:  skills created or improved per week; fewer repeated CEO corrections.
Task:    - [ ] Learn from the day's conversations  @workflow:learn  every:daily

Modeled on Hermes Agent's background skill review, programs-first:
  1. Collect (no model): CEO <-> COO conversations since the last run (Claude Code transcripts,
     Telegram included), incident diagnoses, and approvals the CEO rejected.
  2. Gate (cheap): decide() asks whether anything is worth learning. Most days: no, for ~$0.
  3. Learn (Sonnet, capped): only on "learn". It may read the project and write only inside
     .claude/skills/. It has no shell, so it can't delete anything.
  4. Check: every touched skill keeps valid frontmatter and isn't gutted; otherwise all changes
     are rolled back. Good changes are committed to git as "COO" and mentioned in the brief.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import library  # noqa: E402
import skills  # noqa: E402
from brief import add_extra  # noqa: E402
from budget import BudgetExceeded, check, record  # noqa: E402
from common import CACHE, LESSONS, ROOT, RUN_LOG, log_run, now_iso  # noqa: E402
from decide import decide  # noqa: E402

NAME = Path(__file__).stem
STATE = CACHE / "learn_state.json"
CAP_USD = "0.30"
MAX_DIGEST = 50_000  # characters; the most recent part wins
INCIDENT_MARK = "You are the COO handling an incident"
LEARN_MARK = "You are the COO's learning review"
TAGS = re.compile(r"<(ide_[a-z_]+|system-reminder|command-[a-z-]+|local-command-[a-z]+)>.*?</\1>", re.S)

CHANGES_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {"type": "array", "items": {
            "type": "object",
            "properties": {"skill": {"type": "string"}, "action": {"type": "string", "enum": ["created", "updated"]},
                           "summary": {"type": "string", "description": "what was learned, one short sentence"}},
            "required": ["skill", "action", "summary"]}},
        "notes": {"type": "string", "description": "skills that should be merged or removed, if any"},
    },
    "required": ["changes", "notes"],
}

PROMPT = LEARN_MARK + """. Below is what happened since the last review: conversations between \
the CEO and you (the COO), incident diagnoses, approvals the CEO rejected, things your routines noticed, \
and changes the CEO made in the library (what they marked Rejected, Applied or Interesting shows what they \
want). Update the skill library in \
.claude/skills/ so future sessions do this company's work the way the CEO wants, first time.

A skill is how to do a CLASS of task for this CEO: the steps in order, the decision points, the CEO's \
preferences for the result, and the pitfalls that cost time.

Signals that warrant a change (any one is enough):
- The CEO corrected your style, format, tone, length or approach ("not like that", "too long", "stop doing X", \
rewrote your draft). This is the strongest signal: embed the preference in the skill that governs that task.
- The CEO rejected a proposal. Learn what they don't want, and why if they said.
- A technique, fix or way of working emerged that a future session would benefit from.
- A skill that was used turned out wrong, missing a step, or outdated. Fix it.

How to change, in order of preference:
1. Update the skill that governs this class of task. Read it first and build on what's there.
2. Add a short labeled section to a broader existing skill.
3. Create a new skill named for the class (customer-outreach, pricing-quotes), never for the session \
(fix-tuesday-email, acme-call).

Format: .claude/skills/<name>/SKILL.md starting with frontmatter:
---
name: <name>
description: Use when <the class of task>. <what it covers>
---
Keep the trigger in the first 60 characters of the description: that's how the skill gets found. Body: \
steps first, then rules. Each rule is an instruction plus one clause of why. No dates, no stories, no quoted \
chatter unless the quote is the rule. The same lesson twice is one rule. Fix a wrong line in place; don't \
append "update: actually...".

Do NOT save:
- Facts about the company or the CEO: those belong in memory/, which you must leave alone.
- One-off tasks, task progress, or a summary of what happened.
- Claims that a tool or feature "doesn't work", or errors caused by setup (missing keys, installs).
- Attempts that never worked, written up as a method.
- Procedures that need no judgment: those should become workflows, so just mention them in notes.

Never delete or empty a skill or file. If skills overlap or one looks obsolete, say so in notes.
If nothing qualifies, change nothing and return an empty changes list. Doing nothing on a quiet day is right.

Existing skills:
{skills}

<since_last_review>
{digest}
</since_last_review>"""


def _ts(raw: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _text(content, role: str) -> str:
    """Readable text of a transcript message: no tool calls/results, thinking or IDE tags."""
    if isinstance(content, str):
        parts = [content]
    else:
        parts = [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]
    return TAGS.sub("", "\n".join(parts)).strip()


def transcripts_dir() -> Path:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return base / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))


def conversations(since: datetime) -> list[str]:
    out = []
    folder = transcripts_dir()
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if folder.exists() else []
    for path in files:
        if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < since:
            continue
        lines, first_user = [], None
        for raw in path.read_text(errors="replace").splitlines():
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if e.get("type") not in ("user", "assistant") or e.get("isSidechain"):
                continue
            text = _text((e.get("message") or {}).get("content"), e["type"])
            if not text:
                continue
            if e["type"] == "user" and first_user is None:
                first_user = text
            ts = _ts(e.get("timestamp", ""))
            if ts and ts >= since:
                lines.append(f"{'CEO' if e['type'] == 'user' else 'COO'}: {text[:2000]}")
        if lines and first_user and not first_user.startswith((INCIDENT_MARK, LEARN_MARK)):
            out.append(f"--- conversation {path.stem[:8]} ---\n" + "\n".join(lines))
    return out


def incidents(since: datetime) -> list[str]:
    try:
        state = json.loads((CACHE / "incidents.json").read_text())
    except (OSError, ValueError):
        return []
    out = []
    for inc in state.values():
        v, opened = inc.get("verdict") or {}, _ts(inc.get("opened", ""))
        if v and opened and opened >= since:
            out.append(f"--- incident {inc['id']} ({inc['status']}) ---\n{inc['summary']}\n"
                       f"Root cause: {v.get('root_cause', '')}\nRecommendation: {v.get('recommendation', '')}"
                       + (f"\nResolution: {inc['resolution']}" if inc.get("resolution") else ""))
    return out


def rejections(since: datetime) -> list[str]:
    out = []
    if RUN_LOG.exists():
        for raw in RUN_LOG.read_text().splitlines():
            e = json.loads(raw)
            if e.get("status") == "rejected" and (ts := _ts(e["ts"])) and ts >= since:
                out.append(f"--- the CEO rejected ---\n{e.get('task', '')}")
    return out


def lessons(since: datetime) -> list[str]:
    """What routines noticed (common.lesson)."""
    out = []
    if LESSONS.exists():
        for raw in LESSONS.read_text().splitlines():
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if (ts := _ts(e.get("ts", ""))) and ts >= since:
                out.append(f"--- noticed by the routine {e.get('workflow', '')} ---\n{e.get('text', '')}")
    return out


def library_changes(since: datetime) -> list[str]:
    """What the CEO changed in the library: their own edits are preferences."""
    changes = library.owner_changes(since.isoformat(timespec="seconds"))
    if not changes:
        return []
    lines = [f"- {c['table']}{(' ' + c['row']) if c['row'] else ''}: {c['what']}" for c in changes[-200:]]
    return ["--- the CEO changed the library ---\n" + "\n".join(lines)]


def snapshot() -> dict[str, str]:
    return {str(p.relative_to(ROOT)): p.read_text(errors="replace")
            for p in skills.SKILLS.rglob("*") if p.is_file()} if skills.SKILLS.exists() else {}


def restore(before: dict[str, str]) -> None:
    for p in [p for p in skills.SKILLS.rglob("*") if p.is_file()]:
        rel = str(p.relative_to(ROOT))
        if rel not in before:
            p.unlink()
        elif p.read_text(errors="replace") != before[rel]:
            p.write_text(before[rel])
    for rel, text in before.items():
        if not (ROOT / rel).exists():
            (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / rel).write_text(text)


def quality_problems(before: dict[str, str]) -> list[str]:
    problems = []
    after = snapshot()
    for rel, text in after.items():
        if not rel.endswith("SKILL.md") or before.get(rel) == text:
            continue
        fm = skills.frontmatter(Path(rel).parent.name)
        if not fm.get("name") or not fm.get("description"):
            problems.append(f"{rel}: frontmatter needs name and description")
        if rel in before and len(text) < 0.4 * len(before[rel]):
            problems.append(f"{rel}: shrank from {len(before[rel])} to {len(text)} characters")
    problems += [f"{rel}: deleted" for rel in before if rel not in after]
    return problems


def main() -> int:
    started = datetime.now(timezone.utc)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    since = _ts(state.get("last_run", "")) or started - timedelta(days=1)

    items = conversations(since) + incidents(since) + rejections(since) + lessons(since) + library_changes(since)
    digest = "\n\n".join(items)[-MAX_DIGEST:]
    if not digest:
        log_run(NAME, "ok", result="nothing new")
        STATE.write_text(json.dumps({"last_run": started.isoformat()}))
        return 0

    gate = decide("Did the CEO correct or teach the COO, reject something, or did a reusable way of working "
                  "emerge that a future session should know?",
                  {"learn": "There is a correction, preference, rejection or reusable technique worth keeping",
                   "skip": "Routine work only; nothing a future session needs to do differently"},
                  context=digest[-30_000:], use_cache=False,
                  rules={k: "learn" for k in ("don't", "stop", "instead", "wrong", "prefer", "always",
                                              "never", "rejected", "too long", "not like")})
    if gate.choice != "learn":
        log_run(NAME, "ok", result="nothing to learn", gate=gate.backend)
        STATE.write_text(json.dumps({"last_run": started.isoformat()}))
        return 0

    try:
        check()
    except BudgetExceeded as e:
        log_run(NAME, "ok", result=f"skipped: {e}")
        return 0
    existing = "\n".join(f"- {n}: {skills.frontmatter(n).get('description', '')}" for n in skills.names()) or "(none yet)"
    before = snapshot()
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", "sonnet", "--max-budget-usd", CAP_USD,
         "--json-schema", json.dumps(CHANGES_SCHEMA),
         "--allowedTools", "Read(./**)", "Glob", "Grep", "Edit(./.claude/skills/**)", "Write(./.claude/skills/**)",
         "--disallowedTools", "Read(./.env)", "Read(./.cache/**)", "Edit(./.claude/skills/.registry.json)",
         "Write(./.claude/skills/.registry.json)"],
        input=PROMPT.format(skills=existing, digest=digest), cwd=ROOT, capture_output=True, text=True,
        timeout=1200)
    try:
        out = json.loads(proc.stdout)
        result = out.get("structured_output") or json.loads(out["result"])
    except (ValueError, KeyError, TypeError):
        restore(before)
        print(f"Quality check failed: the review returned no result. {proc.stderr[-300:]}")
        return 2
    cost = float(out.get("total_cost_usd") or 0)
    record("learn", cost, model="sonnet")

    problems = quality_problems(before)
    if problems:
        restore(before)
        log_run(NAME, "quality_failed", cost_usd=cost, problems=problems)
        print("Quality check failed, changes rolled back: " + "; ".join(problems))
        return 2

    reg = skills.registry()
    for n in skills.names():
        if n not in reg and f".claude/skills/{n}/SKILL.md" not in before:
            reg[n] = {"created_by": "coo", "created": now_iso()}
    skills.save_registry(reg)
    changes = result.get("changes") or []
    summary = "; ".join(f"{c['skill']}: {c['summary']}" for c in changes)
    committed = False
    if changes:
        try:
            committed = skills.commit(f"COO learned: {summary}"[:300])
        except subprocess.CalledProcessError:
            pass  # not a git repo: the files are still saved
        add_extra("learned", "🧠 I learned something yesterday:\n" + "\n".join(f"• {c['skill']}: {c['summary']}"
                                                                         for c in changes))
    if result.get("notes"):
        log_run(NAME, "note", notes=result["notes"][:500])
    log_run(NAME, "ok", cost_usd=cost, gate=gate.backend, changes=len(changes), committed=committed)
    STATE.write_text(json.dumps({"last_run": started.isoformat()}))
    # The last line is what the owner's timeline shows: what got better, in plain words.
    print(("Learned: " + "; ".join(c["summary"] for c in changes))[:140] if changes else "Nothing new to learn")
    return 0


if __name__ == "__main__":
    sys.exit(main())
