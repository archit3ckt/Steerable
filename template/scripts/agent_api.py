"""Agent API: the web app's window into this company. HTTP and JSON, standard library only.

Steerable Cloud (the hosted web app) calls it to show the owner their decisions, timeline,
routines, to-dos, goals and chat, and to act on them. It reads the same files as everything
else (tasks.md, ops.db, logs/, .cache/incidents.json) and acts through the same code paths as
the Telegram buttons, so the two channels never disagree.

It also translates. The engine says workflow, incident and heartbeat; the API answers in the
owner's words: routine, something came up, running. The JSON shapes match `CompanyBackend` in
the web app (src/lib/backend/types.ts).

    AGENT_API_TOKEN=<32+ chars> .venv/bin/python scripts/agent_api.py   # 127.0.0.1:8787
    AGENT_API_HOST=0.0.0.0 AGENT_API_PORT=8787 ...                      # inside a container

Every request except GET /health needs `Authorization: Bearer <AGENT_API_TOKEN>`.

    GET  /health                       liveness, no auth
    GET  /v1/overview                  health, brief, spend, stats
    GET  /v1/decisions                 everything waiting on the owner
    POST /v1/decisions/<id>            {"optionId": "...", "note"?: "..."}  (note: the owner's words, for options that ask for them)
    GET  /v1/timeline?limit=50         what happened, newest first
    GET  /v1/routines                  workflows, as routines
    GET  /v1/routines/<id>             one, with its steps (flow chart), its code and which lines do each step, and recent runs
    POST /v1/routines/<id>/paused      {"paused": true|false}
    POST /v1/routines/<id>/run         run it once now ("Run now"); the schedule stays as it was
    POST /v1/routines/<id>/watch       {"watch": true|false}  check what it can't undo before each run does it (supervise.py), or stop
    GET  /v1/traces/<id>               a practice or watched run, step by step (runtrace.py)
    GET  /v1/traces/<id>/shots/<n>.jpg a picture from it
    GET  /v1/todos
    POST /v1/todos/<id>/toggle
    GET  /v1/goals                     goals with their projects (missions)
    GET  /v1/chat                      the conversation, shared with Telegram
    POST /v1/chat                      {"text": "...", "files": [ids]}  the reply, or null if it's still coming
    GET  /v1/chat/page?before=|after=|around=<id>&limit=50   a page of the conversation (scrolling, what's new, a message in context)
    GET  /v1/chat/search?q=            messages in the whole history with every word, newest first (up to 50)
    POST /v1/chat/new                  start a fresh conversation (the history stays, with a divider)
    GET  /v1/chat/activity             what the COO is doing for the reply it's working on
    GET  /v1/checks/<message>          the test of a reply that proposed something ({"status": "none"} before one)
    POST /v1/checks/<message>          {"kind"}  start it (checks.py): one AI call, in the background
    POST /v1/checks/<message>/apply    {"edits": [ids]}  the owner's picks, as a new version of the plan it tested
    GET  /v1/ai                        how the COO reaches its AI: Claude account or key, and Jev (scripts/ai_access.py)
    POST /v1/ai/claude/login|code|cancel|logout   sign Claude Code in with the owner's Claude account
    POST /v1/ai/jev  /v1/ai/jev/remove  the owner's Jev key, checked before it's kept
    POST /v1/files?name=<name>         a file attached in the chat (raw bytes, up to 20 MB) -> {id, name, kind, size}
    GET  /v1/files/<id>                that file (pictures inline, the rest as downloads)
    GET  /v1/library                   the library's tables (records the owner looks up: library.py)
    GET  /v1/library/tables/<id>       a table: columns and a page of rows (?q&sort&dir&where.<column>&archived&offset&limit)
    POST /v1/library/tables/<id>/rows  {cells, key?} add a row; .../rows/<row> {cells} change it; .../archive, .../restore
    GET  /v1/library/tables/<id>/rows/<row>   a row and its history
    GET  /v1/library/tables/<id>/export?format=csv|xlsx (+ the same filters)  the rows as a spreadsheet
    POST /v1/library/import?name=<file>&into=<table>&title=<name>  a CSV or Excel file (raw bytes) as a new table or into one
    POST /v1/library/tables/<id>/views {name, type, config}; .../views/<view> {name?, config?}; .../views/<view>/delete
    POST /v1/library/tables/<id>/rows/<row>/comments {text, ask}  a comment; ask: the COO acts on it and replies there
    GET  /v1/books; POST /v1/books {file, why, title?, author?}  books the owner teaches the COO (books.py)
    GET  /v1/books/<id>?q=  a book: its notes, ideas waiting for the owner, and passages matching q
    POST /v1/books/<id>/proposals/<idea> {approve}; .../paused {paused}; .../retry; .../delete
    GET  /v1/plans; GET /v1/plans/<id>   the business's plans (plans.py), one per subject, with their versions
    GET  /v1/plans/<id>/versions/<n>     a version's text and what it changed
    POST /v1/plans/<id> {body, note}; POST /v1/plans/<id>/restore {version}; POST /v1/plans/<id>/delete
    GET  /v1/dashboards; GET /v1/dashboards/<id>   dashboards over the library (dashboards.py); a dashboard with what
                                       each chart shows now, the tables it can count, and requests to the COO about it
    POST /v1/dashboards {name}; /v1/dashboards/<id> {name?, description?}; .../delete
    POST /v1/dashboards/<id>/widgets {widget}; .../widgets/<w> {widget}; .../widgets/<w>/<remove|up|down>
    GET  /v1/dashboards/asks; POST /v1/dashboards/asks {text, dashboard?}  ask the COO for a dashboard (in the background)
    GET  /v1/runs/<run>/changes        what a routine run or chat turn changed in the library (?table&after&limit)
    GET  /v1/status                    what's running in the background (routines, chat, builds, fixes, its own jobs)
    GET  /v1/export                    the company's files as a .tar.gz (no secrets, caches or sessions)
    GET  /v1/onboarding                {"done": bool, "started": bool}
    POST /v1/onboarding/start          the COO opens the onboarding interview, if it hasn't yet
    GET  /v1/tools                     services the owner can connect themselves, and what's connected
    POST /v1/tools/connect             {"id"} or {"url", "name"}, with "redirectUri" and/or "key":
                                       {"authorizeUrl"} to sign in, or {"connected"}
    POST /v1/tools/callback            {"state", "code"} from the sign-in's return
    POST /v1/tools/<id>/disconnect
    POST /v1/tools/always              {"tool"}: stop always allowing it
    GET  /v1/extension                 the browser extension: paired, since when
    POST /v1/extension/code            a one-time pairing code for the dashboard to show
    POST /v1/extension/unpair
    POST /v1/extension/pair            {"code", "browser"}: from the extension; {"token"}
    POST /v1/extension/logins          {"token", "startUrl", "name", "cookies"}: a login from the owner's browser
    POST /v1/extension/status          {"token"}: the logins it keeps in step, and whether they still work
    GET  /v1/telegram                  the owner's own Telegram bot: connected, linked, the link to open
    POST /v1/telegram/token            {"token"} from @BotFather: checked, kept, and a link made
    POST /v1/telegram/link             a fresh one-time link
    POST /v1/telegram/disconnect       unlink the chat and forget the token
    GET  /v1/values/<NAME>             what the COO asked the owner for (never the value)
    POST /v1/values/<NAME>             {"value"}: the owner gives it
    GET  /v1/sites                     website logins saved here (never the sessions themselves)
    POST /v1/sites/sessions            {"url"}: open a live login; {"id"}
    GET  /v1/sites/sessions/<id>/frame a JPEG of the page now
    GET  /v1/sites/sessions/<id>       {"url", "title"}
    POST /v1/sites/sessions/<id>/input {"kind": move|click|type|key|scroll, ...}
    POST /v1/sites/sessions/<id>/save  {"name"}: keep the logged-in session; {"site"}
    POST /v1/sites/sessions/<id>/cancel
    POST /v1/sites/<site>/remove
    GET  /v1/accounts                  the COO's own accounts (never passwords), its mailbox, the owner's phone
    GET  /v1/accounts/<site>           one account
    POST /v1/accounts/<site>/password  {"password"}: for the owner to see
    POST /v1/accounts/<site>/remove    forget it here (it still exists on the site)
    POST /v1/accounts/phone            {"phone"}: the owner's number, for codes sent by text
    POST /v1/mailbox                   {"address", "imapHost", "imapPort", "user", "password", "security"}: the COO's mailbox
    POST /v1/mailbox/disconnect
"""
import hashlib
import hmac
import io
import json
import re
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import accounts
import ai_access
import approvals
import owner_words
import bridge
import browser
import builder
import change
import checks
import extension
import files
import flow
import heartbeat
import incident
import integrations
import books
import dashboards
import plans
import library
import library_io
import mailbox
import runtrace
import sites
import social
import supervise
import telegram
import tools
import vault
from alert import BRIEF_QUEUE
from brief import pending_approvals
from budget import SPEND_LOG, limit, month_spend
from common import (CACHE, COMPANY, CORE_WORKFLOWS, ROOT, RUN_LOG, STEPS, SYSTEM_JOBS, TASKS, next_run, edit_tasks, env, log_run, now_iso,
                    replace_task_line, task_title)
from ops_db import connect, record_event

WORKFLOWS = ROOT / "workflows"
DRAFTS = ROOT / "drafts"
CHAT_WAIT_SECONDS = 45  # past this, POST /v1/chat returns and the reply lands in the log later


class ApiError(Exception):
    """An error the web app can show the owner as is, so `message` is in plain words."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------- reading the engine's files ----------

def iso(ts: str | None) -> str | None:
    """SQLite CURRENT_TIMESTAMP ("2026-10-07 09:00:00", UTC) or ISO text, as ISO 8601 UTC."""
    if not ts:
        return None
    if "T" not in ts:
        return ts.replace(" ", "T") + "Z"
    return ts


def tail_jsonl(path: Path, max_bytes: int = 4_000_000) -> list[dict]:
    """The last part of a JSONL log. Logs grow forever, so never read them whole."""
    if not path.exists():
        return []
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read().decode("utf-8", "replace")
    lines = data.splitlines()
    if size > max_bytes:
        lines = lines[1:]  # the first line is probably cut in half
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def since(entries: list[dict], days: float) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [e for e in entries if datetime.fromisoformat(e["ts"]) >= cutoff]


def tag(text: str, name: str) -> str | None:
    m = re.search(rf"(?:^|\s){re.escape(name)}:(\S+)", text)
    return m.group(1) if m else None


def parse_task(line: str) -> dict | None:
    m = re.match(r"^- \[( |x)\] (.+)$", line)
    if not m:
        return None
    text = m.group(2)
    note = re.search(r"\(goal:\s*((?:[^;()]|\([^()]*\))+?)\s*(?:;\s*metric:\s*((?:[^()]|\([^()]*\))+?)\s*)?\)", text)
    saves = tag(text, "saves")
    return {
        "line": line,
        "done": m.group(1) == "x",
        "text": text,
        "title": task_title(text),
        "workflow": tag(text, "@workflow"),
        "every": tag(text, "every"),
        "at": tag(text, "at"),
        "due": tag(text, "due"),
        "done_on": tag(text, "done"),
        "paused": tag(text, "paused"),
        "rejected": tag(text, "rejected") is not None,
        "needs_approval": bool(re.search(r"(?:^|\s)needs:approval(?:\s|$)", text)),
        "you": bool(re.search(r"(?:^|\s)@you(?:\s|$)", text)),
        "saves": float(saves.rstrip("h")) if saves and re.fullmatch(r"\d+(\.\d+)?h?", saves) else 0.0,
        "goal": note.group(1) if note else None,
    }


def tasks() -> list[dict]:
    return [t for t in map(parse_task, TASKS.read_text().splitlines()) if t]


def routine_names() -> dict[str, str]:
    return {t["workflow"]: t["title"] for t in tasks() if t["workflow"]}


def routine_name(workflow: str | None, names: dict[str, str] | None = None) -> str:
    if not workflow:
        return "a routine"
    names = names if names is not None else routine_names()
    return names.get(workflow) or workflow.replace("_", " ").capitalize()


def schedule(t: dict) -> str:
    if t["at"]:
        slots = sorted(set(t["at"].split(",")))
        return "Every day at " + (slots[0] if len(slots) == 1 else ", ".join(slots[:-1]) + " and " + slots[-1])
    if t["every"] and (m := re.fullmatch(r"(\d+)h", t["every"])):
        return "Every hour" if m.group(1) == "1" else f"Every {m.group(1)} hours"
    if t["every"] == "daily":
        return "Every day"
    if t["every"] == "weekly":
        return "Every week"
    if t["due"]:
        return f"Once, on {date.fromisoformat(t['due']):%b %-d}"
    return "Once"


def when(at: datetime, now: datetime, about: bool = False) -> str:
    """A time ahead, as the owner reads it: "Today at 13:00", "Tomorrow, early morning", "Friday at 08:00"."""
    if at <= now + timedelta(minutes=1):
        return "In the next few minutes"
    days = (at.date() - now.date()).days
    day = "Today" if days == 0 else "Tomorrow" if days == 1 else f"{at:%A}" if days < 7 else f"{at:%b} {at.day}"
    if at.time() == datetime.min.time():
        return f"{day}, early morning"
    return f"{day} {'around' if about else 'at'} {at:%H:%M}"


def next_run_label(t: dict, status: str) -> str | None:
    if status == "needs-approval":
        return "Once you approve it"
    if status == "setting-up":
        return "Once it's set up"
    if status == "paused":
        return "Not while it's paused"
    if t["done"]:
        return None
    now = datetime.now()  # the company's time zone (TZ), like the heartbeat
    every = t["every"] or ""
    return when(next_run(t["line"][6:], now), now, about=every.endswith("h"))


PLAIN_WORDS = [(r"\bworkflows\b", "routines"), (r"\bworkflow\b", "routine"),
               (r"\bincidents\b", "problems"), (r"\bincident\b", "problem"),
               (r"\bheartbeat\b", "schedule check"), (r"\bexit code \d+\b", "an error")]


def plain(text: str) -> str:
    """Text written for the CEO, in the owner's words: the engine's terms swapped, and anything
    technical rewritten in plain words (owner_words.py: the owner hears the big picture only)."""
    for pattern, word in PLAIN_WORDS:
        text = re.sub(pattern, word, text or "", flags=re.IGNORECASE)
    return owner_words.say(text)


def sentence(text: str) -> str:
    """Text that ends like a sentence, so parts can be joined into a paragraph."""
    text = text.strip()
    return text if not text or text[-1] in ".!?…" else text + "."


def first_sentence(text: str, limit: int = 140) -> tuple[str, str]:
    """Split text into a title and the rest."""
    m = re.match(r"(.+?[.!?])(\s+|$)(.*)", text, re.S)
    head, rest = (m.group(1), m.group(3)) if m else (text, "")
    if len(head) > limit:
        head, rest = head[:limit].rsplit(" ", 1)[0] + "…", text
    return head.rstrip("."), rest.strip()


def missions_by_workflow(con: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = con.execute("""SELECT m.*, g.goal AS goal_name FROM missions m
                          LEFT JOIN goals g ON g.id = m.goal_id
                          WHERE m.workflow IS NOT NULL ORDER BY m.id DESC""").fetchall()
    return {r["workflow"]: r for r in rows}


# ---------- decisions ----------

def incident_decision(inc: dict, names: dict[str, str]) -> dict:
    v = inc.get("verdict") or {}
    workflow = inc.get("workflow")
    routine = routine_name(workflow, names)
    options, facts = [], []

    if v:
        title, rest = first_sentence(plain(v.get("summary") or inc["summary"]))
        context = [rest] if rest else []
        if inc.get("fix_applied"):
            context.insert(0, "The fix is in. What's left is below.")
        elif v.get("fix_ready") and v.get("fix_summary"):
            context.append(f"I've prepared a fix: {plain(v['fix_summary'])}")
    else:
        title = f"{routine} hit a problem I couldn't get to the bottom of"
        context = ["I couldn't work out the cause on my own, so this needs a look together."]
    if workflow and inc.get("kind") != "request" and not inc.get("fix_applied"):  # nothing paused now
        context.append(f"I've paused {routine} so nothing goes wrong in the meantime.")

    if v.get("fix_ready"):
        options.append({"id": "apply", "label": "Apply the fix", "tone": "primary",
                        "outcome": f"Puts the fix in place and restarts {routine}. Its next runs are watched"})
    # It needs something only the owner can give: a connected service or a website login.
    ask = connection_ask(v.get("needs_connection"))
    if ask and not v.get("fix_ready"):
        options.append({"id": "retry", "label": "Done, try again", "tone": "primary",
                        "outcome": f"Restarts {routine}" if workflow else "I'll pick it up from there"})
    done = set(inc.get("done_actions", []))
    for n, action in enumerate(v.get("actions", [])):
        if n not in done:
            options.append({"id": f"action-{n}", "label": plain(action["label"])[:80],
                            "tone": "neutral" if options else "primary"})
    if v.get("fix_ready"):
        options.append({"id": "discard", "label": "Don't apply it", "tone": "quiet",
                        "outcome": f"{routine} stays paused, and you can restart it from Work"})
    elif inc.get("fix_applied") or inc.get("kind") == "request":
        options.append({"id": "keep-paused", "label": "That's all", "tone": "quiet", "outcome": "Closes this"})
    else:
        options.append({"id": "keep-paused", "label": "Keep it paused for now", "tone": "quiet",
                        "outcome": f"You can restart {routine} from Work when you're ready"})

    if workflow:
        facts.append({"label": "Routine", "value": routine})
    if inc.get("repeats", 1) > 1:
        facts.append({"label": "This week", "value": f"Happened {inc['repeats']} times"})

    draft = None
    for f in sorted(DRAFTS.glob(f"{inc['id']}-*.txt")) if DRAFTS.exists() else []:
        draft = {"label": "What I drafted", "body": f.read_text()[:4000]}
        break

    decision = {
        "id": f"incident:{inc['id']}",
        "kind": "problem",
        "urgent": v.get("severity") == "urgent",
        "title": title,
        "context": " ".join(sentence(c) for c in context),
        "recommendation": {"optionId": options[0]["id"],
                           "why": f"{ask['label']} (one tap, above), then try again." if ask
                           else plain(v.get("recommendation", ""))},
        "options": options,
        "facts": facts,
        "draft": draft,
        **({"connect": ask} if ask else {}),
        "createdAt": inc["opened"],
    }
    if v.get("fix_ready") and v.get("practice"):  # the fixed version, tried in a practice run
        decision["trace"] = v["practice"]
        if (v.get("review") or {}).get("concerns"):
            decision["concerns"] = v["review"]["concerns"]
    return decision


def approval_decision(tid: str, t: dict, mission: sqlite3.Row | None, asked_at: str) -> dict:
    when = schedule(t).lower()
    to_build = t["workflow"] and builder.missing(t["workflow"])
    context = (mission["definition_of_done"] if mission and mission["definition_of_done"]
               else None)
    context = (f"I'd like to start this as a routine, running {when}. When it's working: {context}."
               if context else f"I'd like to start this as a routine, running {when}. It won't run until you say yes.")
    goal = t["goal"] or (mission["goal_name"] if mission else None)
    facts = [{"label": "How often", "value": schedule(t)}]
    if t["saves"]:
        facts.append({"label": "Saves you", "value": f"About {t['saves']:g}h a week"})
    if mission and mission["budget"]:
        facts.append({"label": "Budget", "value": f"${mission['budget']:.2f}"})
    return {
        "id": f"task:{tid}",
        "kind": "approval",
        "urgent": False,
        "title": t["title"],
        "context": context,
        "recommendation": {"optionId": "approve", "why": f"It moves your goal: {goal}." if goal else ""},
        "options": [
            {"id": "approve", "label": "Start it", "tone": "primary",
             "outcome": f"I'll build it, test it safely, then run it {when}" if to_build else f"Runs {when} from now on"},
            {"id": "reject", "label": "Not now", "tone": "quiet", "outcome": "It won't run, and I'll note why"},
        ],
        "facts": facts,
        "goal": goal,
        "createdAt": asked_at,
    }


def mission_options(m: sqlite3.Row) -> list[dict]:
    try:
        return json.loads(m["options"]) if m["options"] else []
    except (json.JSONDecodeError, TypeError):
        return []


def mission_decision(m: sqlite3.Row) -> dict:
    context = m["outcome"] or m["definition_of_done"] or "I'm waiting on you before going further with this."
    asked = mission_options(m)
    if asked:
        # A real question (scripts/ask.py): the COO's options and pick.
        options = [{**o, "tone": "primary" if o["id"] == m["recommendation"] else "neutral"} for o in asked]
        recommendation = {"optionId": m["recommendation"] or "", "why": m["recommendation_why"] or ""}
    else:
        # Only "waiting on you": no pick to claim, so the owner chooses.
        options = [
            {"id": "go", "label": "Go ahead", "tone": "neutral", "outcome": "I'll pick it back up today"},
            {"id": "hold", "label": "Not now", "tone": "quiet", "outcome": "It goes back on the shelf"},
        ]
        recommendation = {"optionId": "", "why": ""}
    return {
        "id": f"mission:{m['id']}",
        "kind": "choice",
        "urgent": m["priority"] == "P0",
        "title": m["mission"],
        "context": context,
        "recommendation": recommendation,
        "options": options,
        "facts": [{"label": "Budget", "value": f"${m['budget']:.2f}"}] if m["budget"] else [],
        "goal": m["goal_name"],
        "createdAt": iso(m["updated"]),
    }


def connection_ask(service: str | None) -> dict | None:
    """The button that lets the owner give the COO what it needs: connect a service, or log in
    to a website (site:<host>). None if it isn't something they can connect."""
    service = (service or "").strip()
    if service.startswith("value:") and len(service) > 6:  # something only the owner has (vault.py)
        try:
            return {"provider": service, "label": f"Add {vault.request(service[6:])['label']}"}
        except vault.VaultError:
            return None
    if service.startswith("site:") and len(service) > 5:
        own = accounts.load(service[5:])
        if own and own["status"] == "ACTIVE":  # the COO's own account: log it back in, with its details
            return {"provider": f"account:{own['site']}", "label": f"Log {coo_name()} back in to {own['name']}"}
        return {"provider": service, "label": f"Log in to {service[5:]}"}
    names = {s["id"]: s["name"] for s in integrations.available()}
    return {"provider": service, "label": f"Connect {names[service]}"} if service in names else None


def needs_what(ask: dict) -> str:
    """"Google", or "your login to portal.yoursupplier.com", for a title like "<routine> needs ..."."""
    if ask["provider"].startswith("account:"):
        return f"to log back in to {ask['provider'][8:]}"
    return f"your login to {ask['provider'][5:]}" if ask["provider"].startswith("site:") else ask["label"].removeprefix("Connect ")


def coo_name() -> str:
    return env("COO_NAME") or "Your COO"


def account_decision(a: dict) -> dict:
    """The COO asks for an account of its own (scripts/accounts.py propose)."""
    box = mailbox.status()["address"]
    phone = accounts.settings().get("phone")
    facts = [{"label": "Site", "value": a["site"]},
             {"label": "Signs up as", "value": box or "Its mailbox, once you set it up"},
             {"label": "Codes by text", "value": f"Your phone, ending {phone[-2:]}" if phone else "Your phone (add it on Accounts)"}]
    return {
        "id": f"account:{a['site']}", "kind": "approval", "urgent": False,
        "title": f"{coo_name()} would like its own account on {a['name']}",
        "context": (f"{sentence(plain(a['why']))} It's the business's account, run by {coo_name()}: you can see it, "
                    "its password and everything it does there on the Accounts page, and take it over anytime."),
        "recommendation": {"optionId": "create",
                           "why": "Signing up takes a couple of minutes together: it fills in its details, you handle "
                                  "anything that checks you're human, and any code sent to your phone."},
        "options": [
            {"id": "create", "label": "Sign it up", "tone": "primary", "outcome": "Opens the sign-up, with its details ready to fill in"},
            {"id": "decline", "label": "Not now", "tone": "quiet", "outcome": "No account, and it'll find another way"},
        ],
        "facts": facts,
        "createdAt": a["proposedAt"],
    }


def build_decision(b: dict) -> dict:
    """A routine being set up that needs something only the owner can give (a connected service, a
    login, an answer). Just that, in plain words: how it's being built is the system's business."""
    ask = connection_ask(b.get("needs_connection"))
    changing = bool(b.get("change"))
    if ask:
        context = f"To {'update' if changing else 'set up'} {b['title']}, {ask['label'][:1].lower()}{ask['label'][1:]} (one tap, above)."
    else:
        context = sentence(f"To {'update' if changing else 'set up'} {b['title']}, I need {plain(b.get('needs') or 'a word with you')}")
    context += " Then I'll pick it up from there." + (" It keeps running as it was meanwhile." if changing else "")
    decision = {
        "id": f"build:{b['id']}",
        "kind": "problem",
        "urgent": False,
        "title": f"{b['title']} needs {needs_what(ask)}" if ask else f"{b['title']} needs something from you",
        "context": context,
        "recommendation": {"optionId": "retry", "why": f"{ask['label']}, then I'll carry on." if ask else "Once that's sorted, I'll carry on."},
        "options": [
            {"id": "retry", "label": "Done, carry on", "tone": "primary", "outcome": "I'll finish setting it up"},
            {"id": "drop", "label": "Keep it as it was" if changing else "Don't set it up", "tone": "quiet",
             "outcome": "It keeps running as it is" if changing else "It's taken off your list"},
        ],
        "facts": [],
        "createdAt": b.get("finished") or b["opened"],
    }
    if ask:
        decision["connect"] = ask
    return decision


def _detail_lines(detail, limit: int = 10) -> str:
    if not detail:
        return ""
    if isinstance(detail, dict):
        return "\n".join(f"{approvals.human(str(k)).capitalize()}: {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)}"[:300]
                         for k, v in list(detail.items())[:limit])
    return str(detail)[:1500]


def ready_decision(b: dict) -> dict:
    """A finished build, tried once in a practice run: the owner looks before it's switched on."""
    review = b.get("review") or {}
    t = runtrace.load(b["trace"]) if b.get("trace") else None
    events = (t or {}).get("events", [])
    would = [e for e in events if e["kind"] == "would"]
    records = [e for e in events if e["kind"] == "record"]
    pages = sum(1 for e in events if e["kind"] == "browse")
    unasked = sum(1 for e in events if e["kind"] == "network") + sum(1 for e in would if e.get("auto"))
    changing = bool(b.get("change"))
    task = parse_task("- [ ] " + b["task"]) or {}
    when = schedule(task).lower() if task else "on its schedule"
    facts = [{"label": "Would do", "value": f"{len(would)} thing{'s' if len(would) != 1 else ''} it can't undo" if would else "Nothing it can't undo"}]
    if records:
        adds = sum(1 for e in records if e["change"] == "add")
        ups = sum(1 for e in records if e["change"] == "update")
        facts.append({"label": "Your records", "value": ", ".join(x for x in [f"{adds} new" if adds else "", f"{ups} updated" if ups else ""] if x) or f"{len(records)} changed"})
    if pages:
        facts.append({"label": "Pages it went through", "value": str(pages)})
    concerns = list(review.get("concerns") or [])
    if unasked:
        concerns.insert(0, f"It sent something to a website {unasked} time{'s' if unasked != 1 else ''} without saying what first. "
                           "Look at those steps before switching it on.")
    name = short_title(b["title"])
    return {
        "id": f"build:{b['id']}",
        "kind": "approval",
        "urgent": False,
        "title": f"The update to \u201c{name}\u201d is ready: see what changes" if changing
                 else f"See what \u201c{name}\u201d will do, then switch it on",
        "context": (sentence(plain(review["summary"])) if review.get("summary") else
                    "I tried it once in a practice run, where nothing is sent.")
                   + " Nothing was sent, submitted or paid in the practice run." + (" It keeps running as it was until you decide." if changing else ""),
        "recommendation": {"optionId": "" if concerns else "switch_on",
                           "why": "Look at what I noticed first: you can switch it on anyway, or tell me what to change."
                           if concerns else "The practice run did what it's for."},
        "options": [
            {"id": "switch_on", "label": "Switch it on" if not changing else "Use the new version", "tone": "primary",
             "outcome": f"Runs {when}. Its first runs are watched: anything it can't undo is checked before it happens"},
            {"id": "change", "label": "Change something", "tone": "neutral",
             "outcome": "I'll change it and show you a new practice run",
             "input": {"placeholder": "What should it do differently?"}},
            {"id": "drop", "label": "Keep it as it was" if changing else "Don't build it", "tone": "quiet",
             "outcome": "It keeps running as it is" if changing else "It's taken off your list"},
        ],
        "facts": facts,
        **({"concerns": concerns} if concerns else {}),
        **({"trace": b["trace"]} if b.get("trace") else {}),
        "createdAt": b.get("finished") or b["opened"],
    }


def watch_decision(r: dict, names: dict[str, str]) -> dict:
    """A watched run where the supervisor held something back."""
    name = short_title(routine_name(r["workflow"], names))
    n = len(r["held"])
    concerns = [f"{h['what']}: {h['why']}" for h in r["held"]]
    if r.get("unasked"):
        concerns.append(f"It also sent something to a website {r['unasked']} time{'s' if r['unasked'] != 1 else ''} without saying what first.")
    return {"id": f"watch:{r['trace']}", "kind": "problem", "urgent": False,
            "title": f"I held back {n} thing{'s' if n != 1 else ''} in \u201c{name}\u201d" if n
                     else f"\u201c{name}\u201d did something it didn't say first",
            "context": "It's still being watched in its first runs. Before it did these, I looked, and something seemed off, "
                       "so they weren't done." if n else "It's still being watched in its first runs.",
            "recommendation": {"optionId": "fix", "why": "Then it handles this itself next time."},
            "options": [
                {"id": "fix", "label": "Fix it so it handles this", "tone": "primary",
                 "outcome": "I'll change it, and show you a practice run before it's used",
                 "input": {"placeholder": "Anything I should know? (optional)", "optional": True}},
                {"id": "fine", "label": "It was fine", "tone": "neutral",
                 "outcome": "Next time it goes ahead in cases like this. This time it stays undone",
                 "input": {"placeholder": "Why was it fine? (optional)", "optional": True}},
                {"id": "leave", "label": "Leave it", "tone": "quiet", "outcome": "Nothing changes"},
            ],
            "facts": [], "concerns": concerns, "trace": r["trace"], "createdAt": r["at"]}


def trust_decision(w: dict, names: dict[str, str]) -> dict:
    name = short_title(routine_name(w["workflow"], names))
    return {"id": f"trust:{w['workflow']}", "kind": "choice", "urgent": False,
            "title": f"Let \u201c{name}\u201d run on its own?",
            "context": f"It's run {w['runs']} times while watched, the last {w['clean']} without anything held back or going wrong. "
                       "On its own, it no longer waits for a check before each thing it can't undo.",
            "recommendation": {"optionId": "trust", "why": "It's handled everything so far."},
            "options": [{"id": "trust", "label": "Let it run on its own", "tone": "primary",
                         "outcome": "You can watch it again any time, on its page"},
                        {"id": "keep", "label": "Keep watching it", "tone": "quiet",
                         "outcome": f"I'll ask again after {supervise.WATCH_RUNS} more clean runs"}],
            "facts": [], "createdAt": w["since"]}


def value_decision(name: str, r: dict) -> dict:
    """The COO needs something only the owner has: a private link, a key. One step in the app."""
    coo = env("COO_NAME") or "Your COO"
    return {"id": f"value:{name}", "kind": "choice", "urgent": False,
            "title": f"{coo} needs {r['label']}",
            "context": " ".join(c for c in [sentence(plain(r.get("why") or "")),
                                            "It's kept private: only your routines use it, and no AI reads it."] if c),
            "recommendation": {"optionId": "", "why": f"Add {r['label']} (one step, above)."},
            "options": [{"id": "skip", "label": "Not now", "tone": "quiet", "outcome": "I'll manage without it for now"}],
            "facts": [], "connect": {"provider": f"value:{name}", "label": f"Add {r['label']}"}, "createdAt": r["at"]}


def tool_decision(p: dict) -> dict:
    """A change the COO wanted to make in one of the owner's services, from the chat."""
    server, tool = approvals.split(p["tool"])
    service, what = approvals.service_name(server), approvals.human(tool)
    coo = env("COO_NAME") or "Your COO"
    args = p["input"] if isinstance(p["input"], dict) else {}
    facts = [{"label": approvals.human(k).capitalize(),
              "value": (v if isinstance(v, str) else json.dumps(v))[:80]} for k, v in list(args.items())[:6]]
    options = [{"id": "once", "label": "Allow this once", "tone": "primary", "outcome": "Runs now. You'll see what happened."}]
    if not approvals.destructive(server, tool):
        options.append({"id": "always", "label": "Always allow this", "tone": "neutral",
                        "outcome": f"{coo} can {what} in {service} without asking"})
    options.append({"id": "decline", "label": "Don't", "tone": "quiet"})
    return {"id": f"tool:{p['id']}", "kind": "approval", "urgent": False,
            "title": f"{coo} wants to {what} in {service}",
            "context": f"It came up in your chat. It changes something in {service}, so it waits for your OK.",
            "recommendation": {"optionId": "once", "why": ""}, "options": options, "facts": facts,
            "draft": {"label": "Exactly what it sends", "body": json.dumps(p["input"], indent=2, ensure_ascii=False)},
            "createdAt": p["at"]}


def short_title(title: str, limit: int = 70) -> str:
    """A routine's name for a headline: up to its first aside or sentence end, and not too long."""
    first = re.split(r"\s[(\u2014\u2013-]\s?|[.;:](?:\s|$)", title.strip(), maxsplit=1)[0]
    return first if len(first) <= limit else first[: limit - 1].rsplit(" ", 1)[0] + "\u2026"


def change_decision(c: dict) -> dict:
    """A change to a running routine, waiting for the owner's OK (change.py)."""
    return {"id": f"change:{c['id']}", "kind": "approval", "urgent": False,
            "title": f"Update \u201c{short_title(c['title'])}\u201d?",
            "context": (sentence(plain(c.get("why") or "")) + " It keeps running as it is until the new version is tested.").strip(),
            "recommendation": {"optionId": "approve", "why": ""},
            "options": [{"id": "approve", "label": "Update it", "tone": "primary",
                         "outcome": "I'll change it, test it in a practice run, then switch to it"},
                        {"id": "decline", "label": "Keep it as it is", "tone": "quiet"}],
            "facts": [], "draft": {"label": "What changes", "body": c["change"]}, "createdAt": c["at"]}


def social_decision(d: dict) -> dict:
    """A post the COO drafted in the chat, waiting for the owner's OK before it goes out."""
    where = " and ".join(social.NAMES[n] for n in d["networks"])
    facts = [{"label": "Where", "value": where}]
    if d.get("subreddit"):
        facts.append({"label": "Subreddit", "value": f"r/{d['subreddit']}"})
    if d.get("title"):
        facts.append({"label": "Title", "value": d["title"][:80]})
    if d.get("image"):
        facts.append({"label": "Picture", "value": Path(d["image"]).name.partition("-")[2] or Path(d["image"]).name})
    if d.get("link"):
        facts.append({"label": "Link", "value": d["link"][:80]})
    context = d.get("why") or "It came up in your chat."
    if d.get("rules"):
        context += f" r/{d['subreddit']}'s rules: " + "; ".join(r for r in d["rules"] if r) + "."
    if d.get("by_hand"):
        # Reddit doesn't let apps post any more: the owner posts it, and tells the COO they did.
        return {"id": f"social:{d['id']}", "kind": "approval", "urgent": False,
                "title": f"Post this on r/{d['subreddit']}?",
                "context": f"{context} Reddit doesn't let apps post, so this one is yours: on reddit.com/r/{d['subreddit']}, "
                           "start a post and paste the title and text below.",
                "recommendation": {"optionId": "post", "why": ""},
                "options": [{"id": "post", "label": "I posted it", "tone": "primary", "outcome": "I'll note it in your timeline."},
                            {"id": "skip", "label": "Don't post", "tone": "quiet"}],
                "facts": facts, "draft": {"label": "Title and text to paste", "body": f"{d['title']}\n\n{d['text']}"},
                "createdAt": d["at"]}
    return {"id": f"social:{d['id']}", "kind": "approval", "urgent": False,
            "title": f"Post this to {where}?",
            "context": context,
            "recommendation": {"optionId": "post", "why": ""},
            "options": [{"id": "post", "label": "Post it", "tone": "primary", "outcome": f"Goes out on {where} now."},
                        {"id": "skip", "label": "Don't post", "tone": "quiet"}],
            "facts": facts, "draft": {"label": "Exactly what goes out", "body": d["text"]}, "createdAt": d["at"]}


def decisions() -> list[dict]:
    names = routine_names()
    awaiting = incident.awaiting()
    out = [incident_decision(i, names) for i in awaiting]
    out += [tool_decision(p) for p in approvals.pending()]
    out += [social_decision(d) for d in social.pending()]
    out += [change_decision(c) for c in change.pending()]
    # Reddit app keys were asked for before Reddit stopped giving them out (posts are by hand now).
    retired = {k[0] for k in social.NEEDS["reddit"]}
    out += [value_decision(name, r) for name, r in vault.requests().items() if name not in retired]
    if not accounts.remote():  # in Steerable Cloud the app asks the owner itself
        out += [account_decision(a) for a in accounts.listing() if a["status"] == "PROPOSED"]
    covered = {i.get("workflow") for i in awaiting}
    for b in builder.load().values():
        # Only what the owner can do something about: a build that failed is the system's (it tries
        # again on its own, builder.retry_failed), so it never reaches them.
        if b["status"] == "needs_owner":
            out.append(build_decision(b))
            covered.add(b["workflow"])
        elif b["status"] == "ready":
            out.append(ready_decision(b))
            covered.add(b["workflow"])
    out += [watch_decision(r, names) for r in supervise.reviews()]
    out += [trust_decision(w, names) for w in supervise.trust_asks()]
    asked_at = datetime.fromtimestamp(TASKS.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")

    with connect() as con:
        by_workflow = missions_by_workflow(con)
        for tid, text in pending_approvals():
            t = parse_task("- [ ] " + text)
            covered.add(t["workflow"])
            out.append(approval_decision(tid, t, by_workflow.get(t["workflow"]), asked_at))
        for m in con.execute("""SELECT m.*, g.goal AS goal_name FROM missions m
                                LEFT JOIN goals g ON g.id = m.goal_id
                                WHERE m.status NOT IN ('Done', 'Cancelled')
                                AND (m.status = 'Waiting on CEO' OR m.needs_ceo_approval)
                                ORDER BY m.priority, m.id"""):
            if not (m["workflow"] and m["workflow"] in covered):
                out.append(mission_decision(m))
    return out


def hand_pause_to_owner(iid: str) -> None:
    """A resolved problem shouldn't leave its routine locked: the owner can restart it now."""
    edit_tasks(lambda lines: [line.replace(f"paused:{iid}", "paused:owner") for line in lines])


def decide(decision_id: str, option_id: str, words: str = "") -> dict:
    """`words`: what the owner wrote, for an option that asks for it (Change something)."""
    match = next((d for d in decisions() if d["id"] == decision_id), None)
    option = next((o for o in match["options"] if o["id"] == option_id), None) if match else None
    if not match or not option:
        raise ApiError(410, "That decision is no longer open.")
    words = " ".join((words or "").split())[:2000]
    if option.get("input") and not option["input"].get("optional") and not words:
        raise ApiError(400, "Say what you'd like changed.")
    kind, ref = decision_id.split(":", 1)
    note = f"You decided: {option['label']}. ({match['title']})"

    next_page = None
    if kind == "value":
        vault.drop(ref)
        record_event(note, who="CEO")
    elif kind == "account":
        a = accounts.decide(ref, option_id == "create")
        record_event(note, who="CEO")
        if option_id == "create":
            next_page = f"/accounts/signup?site={a['site']}"
        else:
            bridge._log_chat("coo", f"OK, no account on {a['name']}. I'll find another way.")
    elif kind == "change":
        if change.resolve(ref, option_id == "approve") is None:
            raise ApiError(410, "That decision is no longer open.")
        record_event(note, who="CEO")
    elif kind == "social":
        results = social.resolve(ref, option_id == "post")
        if results is None:
            raise ApiError(410, "That decision is no longer open.")
        record_event(note, who="CEO")
        bridge._log_chat("coo", social.summary(results) if results else "OK, I won't post it.")
    elif kind == "tool":
        p = approvals.resolve(ref, option_id)
        if p is None:
            raise ApiError(410, "That decision is no longer open.")
        server, tool = approvals.split(p["tool"])
        what, service = approvals.human(tool), approvals.service_name(server)
        if option_id == "decline":
            bridge._log_chat("coo", f"OK, I won't {what} in {service}.")
        else:  # the same call again, which now matches its grant
            prompt = (f"The owner allowed it: {what} in {service}. Do it now: call {p['tool']} with exactly this "
                      f"input: {json.dumps(p['input'], ensure_ascii=False)}. Then tell them in a sentence how it went.")
            threading.Thread(target=bridge.converse, args=(prompt, bridge.APP, False), daemon=True).start()
        record_event(note, who="CEO")
    elif kind == "task":
        if bridge.set_approval(ref, option_id == "approve") is None:
            raise ApiError(410, "That decision is no longer open.")
    elif kind == "incident":
        inc = incident.load()[ref]
        if option_id == "apply":
            result = incident.apply_fix(ref)
            if result.startswith("merge conflict"):
                raise ApiError(409, "The fix didn't go in cleanly. I'll sort it out and come back to you.")
        elif option_id == "discard":
            incident.discard_fix(ref)
            hand_pause_to_owner(ref)
        elif option_id == "retry":
            incident.resolve(ref, "the owner connected what it needed")
            hand_pause_to_owner(ref)
            if inc.get("workflow"):
                try:
                    set_routine_paused(inc["workflow"], False)
                except ApiError:
                    pass  # waiting for approval or gone: nothing to restart
            record_event(note, who="CEO", workflow=inc.get("workflow"))
        elif option_id == "keep-paused":
            incident.resolve(ref, "kept paused by the owner")
            hand_pause_to_owner(ref)
            record_event(note, who="CEO", workflow=inc.get("workflow"))
        else:
            n = int(option_id.split("-", 1)[1])
            result = incident.run_action(ref, n)
            record_event(f"{note} {result.capitalize()}.", who="CEO", workflow=inc.get("workflow"))
            actions = (inc.get("verdict") or {}).get("actions", [])
            if len(set(incident.load()[ref].get("done_actions", []))) >= len(actions):
                incident.resolve(ref, "actions done")
                if not (inc.get("verdict") or {}).get("fix_ready"):
                    hand_pause_to_owner(ref)
    elif kind == "build":
        if option_id == "retry":
            builder.retry(ref)
        elif option_id == "switch_on":
            try:
                builder.switch_on(ref)
            except RuntimeError as e:
                raise ApiError(409, str(e)) from None
        elif option_id == "change":
            builder.revise(ref, words)
        else:
            builder.drop(ref)
    elif kind == "watch":
        r = next((r for r in supervise.reviews() if r["trace"] == ref), None)
        if not r:
            raise ApiError(410, "That decision is no longer open.")
        said = supervise.answer_review(r["workflow"], ref, option_id, words)
        record_event(f"{note} {said}", who="CEO", workflow=r["workflow"])
    elif kind == "trust":
        supervise.answer_trust(ref, option_id == "trust")
        record_event(note, who="CEO", workflow=ref)
    elif kind == "mission":
        with connect() as con:
            row = con.execute("SELECT options FROM missions WHERE id = ?", (int(ref),)).fetchone()
            if row and row["options"]:
                # An answered question: record the choice for the COO, and carry on.
                con.execute("""UPDATE missions SET status = 'In progress', needs_ceo_approval = 0,
                               outcome = COALESCE(outcome, '') || ? , options = NULL, updated = CURRENT_TIMESTAMP
                               WHERE id = ?""", (f"\nOwner chose: {option['label']}.", int(ref)))
            elif option_id == "go":
                con.execute("""UPDATE missions SET needs_ceo_approval = 0, updated = CURRENT_TIMESTAMP,
                               status = CASE WHEN status = 'Waiting on CEO' THEN 'In progress' ELSE status END
                               WHERE id = ?""", (int(ref),))
            else:
                con.execute("""UPDATE missions SET needs_ceo_approval = 0, status = 'Backlog',
                               updated = CURRENT_TIMESTAMP WHERE id = ?""", (int(ref),))
        record_event(note, who="CEO", mission=match["title"])

    log_run("agent_api", "decided", decision=decision_id, option=option_id)
    return {"id": f"decided-{decision_id}", "at": now_iso(), "kind": "decided", "actor": "you",
            "title": f"You decided: {option['label']}", "detail": match["title"], "goal": match.get("goal"),
            **({"next": next_page} if next_page else {})}


# ---------- timeline ----------

UPKEEP_OUTPUT = r"\d+ active, \d+ stale, \d+ archived|Quality check failed.*"  # curate_skills / learn


def timeline_event(row: sqlite3.Row, names: dict[str, str], changes: dict[str, list] | None = None) -> dict | None:
    """`changes`: what runs changed in the library, by run id (from the run log)."""
    what, who, workflow = row["what"], row["who"], row["workflow"]
    routine = routine_name(workflow, names) if workflow else None
    event = {"id": f"a{row['id']}", "at": iso(row["ts"]), "goal": row["goal_name"],
             "costUsd": round(row["cost"], 4) or None}
    ref = row["ref"] if "ref" in row.keys() else None
    if ref and (changes or {}).get(ref):
        event.update(run=ref, changes=changes[ref])

    def make(kind: str, actor: str, title: str, detail: str | None = None) -> dict:
        return {**event, "kind": kind, "actor": actor, "title": plain(title)[:200],
                "detail": plain(detail)[:600] if detail else None}

    if who == "CEO":
        if m := re.match(r"You decided: (.+?)\. \((.+)\)(.*)$", what, re.S):
            return make("decided", "you", f"You decided: {m.group(1)}", (m.group(2) + m.group(3)).strip())
        if what.startswith("CEO discarded the fix"):
            return make("decided", "you", "You chose not to apply a fix", f"{routine} stays paused." if routine else None)
        return make("decided", "you", what)
    if m := re.match(r"Started building (.+?)\.$", what):
        return make("heads-up", "coo", f"Started building {m.group(1)}", "I'll test it safely before it runs for real.")
    if m := re.match(r"Built (.+?)\. (.*)$", what, re.S):
        return make("milestone", "coo", f"Built {m.group(1)}", m.group(2) or None)
    if m := re.match(r"Couldn't (?:finish )?build(?:ing)? (.+?)\.$", what):
        return make("heads-up", "coo", f"Couldn't finish building {m.group(1)}", "It's in Decisions.")
    if what.startswith("Proposed a new routine: "):
        return make("heads-up", "coo", f"Suggested a new routine: {what[len('Proposed a new routine: '):]}", "It's waiting for you in Decisions.")
    if what.startswith("Updated the library: "):
        return make("done", "coo", "Updated the library", what[len("Updated the library: "):])
    if what.startswith("Ran OK: "):
        out = what[len("Ran OK: "):].strip()
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        summary = lines[-1] if lines and lines[-1] != workflow else None
        # The COO's upkeep (learn.py, curate_skills.py) usually has no mission, so it's known by
        # what it prints. Only actual learning reaches the owner.
        if summary and summary.startswith("Learned: "):
            return make("learned", "coo", f"Got better at: {summary.removeprefix('Learned: ')}")
        if workflow in CORE_WORKFLOWS or summary in ("Nothing new to learn", *CORE_WORKFLOWS) or re.fullmatch(UPKEEP_OUTPUT, summary or ""):
            return None
        return make("done", "autopilot", summary or f"Ran {routine}", routine if summary else None)
    if what.startswith("Incident opened: Fix requested for "):
        return make("heads-up", "coo", f"Working on a change to {routine}" if routine else "Working on a change",
                    "When it's ready and tested, it's in Decisions.")
    if what.startswith("Incident opened: "):
        return make("heads-up", "coo", f"Paused {routine} after a problem" if routine else "Something came up",
                    "I'm looking into it now.")
    if what.startswith("Diagnosed"):
        return None  # internal step; the outcome follows as its own event
    if what.startswith("Needs CEO: "):
        return make("heads-up", "coo", "Asked for your call on a problem", what[len("Needs CEO: "):])
    if what.startswith("Fix applied: "):
        return make("fixed", "coo", f"Fixed {routine} and restarted it" if routine else "Fixed a problem",
                    what[len("Fix applied: "):] or None)
    if what.startswith("Resolved, no change needed: "):
        return make("heads-up", "coo", "Looked into a problem: nothing needed changing",
                    what[len("Resolved, no change needed: "):])
    return make("done", "autopilot" if who == "Workflow" else "coo", what)


def timeline(limit: int = 50) -> list[dict]:
    names, out = routine_names(), []
    changes = {r["run"]: r["changes"] for r in tail_jsonl(RUN_LOG) if r.get("run") and r.get("changes")}
    with connect() as con:
        rows = con.execute("""SELECT a.*, m.workflow, g.goal AS goal_name FROM activity a
                              LEFT JOIN missions m ON m.id = a.mission_id
                              LEFT JOIN goals g ON g.id = m.goal_id
                              ORDER BY a.id DESC LIMIT ?""", (limit * 2,)).fetchall()
    for row in rows:
        if (e := timeline_event(row, names, changes)) is not None:
            out.append({k: v for k, v in e.items() if v is not None})
        if len(out) >= limit:
            break
    return out


# ---------- routines and to-dos ----------

def routines() -> list[dict]:
    runs = [r for r in tail_jsonl(RUN_LOG) if r.get("workflow") and r.get("script") == "heartbeat"
            and r.get("status") in ("ok", "error")]
    last_run = {}
    for r in runs:
        last_run[r["workflow"]] = r
    spend = {}
    for e in since(tail_jsonl(SPEND_LOG), 30):
        spend[e["source"]] = spend.get(e["source"], 0) + e["cost_usd"]
    with connect() as con:
        by_workflow = missions_by_workflow(con)
    watched = supervise.load()

    out = []
    for t in tasks():
        if not t["workflow"] or t["done"] or t["workflow"] in CORE_WORKFLOWS:
            continue  # the COO's own upkeep isn't one of the owner's routines
        mission = by_workflow.get(t["workflow"])
        if t["needs_approval"]:
            status = "needs-approval"
        elif t["paused"]:
            status = "paused"
        elif builder.missing(t["workflow"]):
            status = "setting-up"  # approved, still being built (or waiting on the owner in Decisions)
        else:
            status = "running"
        # How far along it is: proposed, being set up, ready for the owner to look at, watched, on its own.
        if t["needs_approval"]:
            stage = "proposed"
        elif builder.missing(t["workflow"]):
            b = builder.current(t["workflow"])
            stage = "ready" if b and b["status"] == "ready" else "building"
        else:
            stage = "watched" if t["workflow"] in watched else "trusted"
        goal = t["goal"] or (mission["goal_name"] if mission else None)
        routine = {
            "id": t["workflow"],
            "name": t["title"],
            "description": (mission["definition_of_done"] if mission and mission["definition_of_done"]
                            else f"Moves your goal: {goal}." if goal else ""),
            "schedule": schedule(t),
            "status": status,
            **({"nextRun": label} if (label := next_run_label(t, status)) else {}),
            "monthlyCostUsd": round(spend.get(t["workflow"], 0), 2),
            "hoursSavedPerWeek": t["saves"],
            **({"watching": True} if t["workflow"] in watched else {}),
            "stage": stage,
        }
        if status == "paused":
            routine["pausedBy"] = "you" if t["paused"] == "owner" else "coo"
        if goal:
            routine["goal"] = goal
        if r := last_run.get(t["workflow"]):
            routine["lastRun"] = run_summary(r)
        out.append(routine)
    return out


def run_summary(r: dict) -> dict:
    """One run, as the owner sees it: when, whether it went fine, and what it did."""
    ok = r["status"] == "ok"
    lines = [line.strip() for line in (r.get("stdout") or "").splitlines() if line.strip()]
    summary = lines[-1][:120] if ok and lines else ("Ran fine" if ok else "Hit a problem")
    if r.get("held"):
        summary = "Held back something it was about to do, for you to look at"
    out = {"at": r["ts"], "ok": ok, "summary": plain(summary)}
    if r.get("run"):
        out["id"] = r["run"]
    if r.get("trace"):
        out["trace"] = r["trace"]
    if r.get("changes"):
        out["changes"] = r["changes"]
    return out


_describing: set[str] = set()


def routine_detail(rid: str) -> dict:
    """A routine's page: what routines() says, its steps for the flow chart, and its last runs.
    A routine without written steps gets them described once, in the background."""
    routine = next((r for r in routines() if r["id"] == rid), None)
    if not routine:
        raise ApiError(404, "There's no such routine.")
    entries = tail_jsonl(RUN_LOG)
    runs = [run_summary(r) for r in entries
            if r.get("workflow") == rid and r.get("script") == "heartbeat" and r.get("status") in ("ok", "error")]
    steps = flow.load(rid)
    if steps is None and not builder.missing(rid) and not flow.pending(rid) and rid not in _describing:
        _describing.add(rid)

        def work():
            try:
                flow.describe(rid, routine["schedule"])
            finally:
                _describing.discard(rid)
        threading.Thread(target=work, daemon=True).start()
    out = {**routine, "flow": steps, "flowPending": steps is None and (rid in _describing or flow.pending(rid)),
           "runs": runs[::-1][:20]}
    # The code view (a toggle on the steps): the routine's code, and which lines do each step,
    # worked out once in the background (and again when the code changes).
    code = flow.code_of(rid)
    if steps and code is not None:
        out["code"] = "\n".join(code.splitlines()[:flow.MAX_LINES])
        out["codeMap"] = flow.code_map(rid)
        if out["codeMap"] is None and not flow.map_pending(rid) and f"{rid}.map" not in _describing:
            _describing.add(f"{rid}.map")

            def mark():
                try:
                    flow.map_code(rid)
                finally:
                    _describing.discard(f"{rid}.map")
            threading.Thread(target=mark, daemon=True).start()
        out["codeMapPending"] = out["codeMap"] is None and (f"{rid}.map" in _describing or flow.map_pending(rid))
    b = builder.current(rid)
    if b and b["status"] == "ready" and b.get("trace"):
        out["ready"] = {"trace": b["trace"], "decision": f"build:{b['id']}", **({"change": b["change"]} if b.get("change") else {})}
    if w := supervise.status(rid):
        out["watch"] = w
    if routine["stage"] in ("watched", "trusted"):
        out["record"] = track_record(rid, entries, watched=bool(w))
    if b and b["status"] == "building":
        # What the builder has done so far, in the owner's words (not its remarks: those are for engineers).
        words = lambda tool, args: builder.step_words(tool, args) or bridge.step_label(tool, args)  # noqa: E731
        done = [s for s in bridge.live_steps(builder.live_path(b["id"]), label=words) if isinstance(s, str)]
        out["building"] = {"since": b["opened"], "steps": done, **({"change": b["change"]} if b.get("change") else {})}
    doing = _heartbeat_doing()
    if doing.get("routine") == rid:
        at = None
        try:
            marker = json.loads((STEPS / f"{rid}.json").read_text())
            at = int(marker["step"]) if marker["at"] >= doing["since"] else None
        except (OSError, ValueError, KeyError, TypeError):
            pass
        out["runningNow"] = {"since": doing["since"], "step": at}
    return out


RECORD_DAYS = 30


def track_record(rid: str, entries: list[dict], watched: bool) -> dict:
    """How a routine has done lately (the run log): runs and problems in the last RECORD_DAYS days,
    things held back while watched, its last problem, and since when it's run on its own."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECORD_DAYS)).isoformat()
    mine = [r for r in entries if r.get("workflow") == rid]
    runs = [r for r in mine if r.get("script") == "heartbeat" and r.get("status") in ("ok", "error")]
    recent = [r for r in runs if r["ts"] >= cutoff]
    held = sum(1 for r in mine if r.get("script") == "supervise" and r.get("status") == "held" and r["ts"] >= cutoff)
    last_problem = next((r["ts"] for r in reversed(runs) if r["status"] == "error"), None)
    own = None
    if not watched:  # since it was last let off watch, or (never watched) since its first run
        own = next((r["ts"] for r in reversed(mine) if r.get("script") == "supervise" and r.get("status") == "trusted"),
                   runs[0]["ts"] if runs else None)
    return {"days": RECORD_DAYS, "runs": len(recent), "problems": sum(1 for r in recent if r["status"] == "error"),
            "held": held, "lastProblem": last_problem, "onItsOwnSince": own}


def _heartbeat_doing() -> dict:
    """What the heartbeat is running right now, from its note; a note older than its longest run is left over."""
    try:
        doing = json.loads(heartbeat.NOW.read_text())
        if datetime.now(timezone.utc) - datetime.fromisoformat(doing["since"]) > timedelta(minutes=35):
            return {}
        return doing
    except (OSError, ValueError, KeyError):
        return {}


def watch_routine(rid: str, watch: bool) -> None:
    """The owner starts or stops watching a routine that's switched on (its page)."""
    if not any(r["id"] == rid for r in routines()) or builder.missing(rid):
        raise ApiError(404, "There's no such routine.")
    if watch:
        supervise.start(rid, why="owner")
        record_event("You asked for its next runs to be watched: anything it can't undo is checked first.", who="CEO", workflow=rid)
    else:
        supervise.stop(rid)
        record_event("You let it run on its own.", who="CEO", workflow=rid)


def trace_view(tid: str) -> dict:
    """A practice or watched run for the owner, step by step (runtrace.py), in their words."""
    try:
        t = runtrace.load(tid)
    except ValueError:
        t = None
    if not t:
        raise ApiError(404, "That run's record is gone. Practice and watched runs are kept 30 days.")
    workflow = t.get("workflow") or ""
    steps = flow.load(workflow) or []
    if t.get("steps"):  # a practice run of a build: the names from that version's flow chart
        steps = [{"label": label} for label in t["steps"]]
    out = []
    for e in t["events"]:
        kind, item = e["kind"], {"n": e.get("n"), "at": e.get("at")}
        if kind == "step":
            n = int(e.get("step") or 0)
            item.update(kind="step", title=steps[n]["label"] if 0 <= n < len(steps) else f"Step {n}")
        elif kind == "browse":
            item.update(kind="browse", title=e.get("what") or "Looked at the page", url=e.get("url") or None)
        elif kind in ("would", "did", "held"):
            item.update(kind=kind, title=e.get("what", ""), detail=_detail_lines(e.get("detail")) or None,
                        why=e.get("why") or None, unasked=bool(e.get("auto")))
        elif kind == "record":
            verb = {"add": "Add a row to", "update": "Update a row in", "archive": "Archive a row in"}.get(e.get("change"), "Change")
            item.update(kind="record", title=f"{verb} {e.get('table')}", detail=_detail_lines(e.get("cells"), 8) or None)
        elif kind == "message":
            item.update(kind="message", title="Tell you", detail=(e.get("text") or "")[:2000])
        elif kind == "draft":
            item.update(kind="draft", title="Save a report" if e.get("name") == "report" else f"Save a draft: {e.get('name')}",
                        detail=(e.get("text") or "")[:2000])
        elif kind == "network":
            host = re.sub(r"^https?://([^/]+).*", r"\1", e.get("url") or "")
            item.update(kind="unasked", title=f"Sent something to {host} without saying what first",
                        detail=_detail_lines(e.get("fields")) or None, url=e.get("url") or None)
        else:
            continue
        if e.get("shot"):
            item["shot"] = e["shot"]
            if isinstance(e.get("box"), list) and len(e["box"]) == 4:
                item["box"] = e["box"]  # the element it clicked, typed into or is about to press
        out.append(item)
    review = t.get("review") or {}
    return {"id": t["id"], "routineId": workflow, "routine": routine_name(workflow), "kind": t.get("kind", "practice"),
            "startedAt": t.get("started"), "finishedAt": t.get("finished"), "ok": t.get("ok"),
            "summary": plain(t.get("summary") or "") or None,
            "review": {"summary": review.get("summary", ""), "concerns": review.get("concerns", [])} if review.get("summary") or review.get("concerns") else None,
            "events": out}


def run_routine(rid: str) -> dict:
    """ "Run now": one run of an approved routine, in the background (heartbeat.start_manual)."""
    try:
        heartbeat.start_manual(rid)
    except ValueError as e:
        raise ApiError(409, str(e)) from None
    return {"started": True}


def set_routine_paused(workflow: str, paused: bool) -> None:
    t = next((t for t in tasks() if t["workflow"] == workflow and not t["done"]), None)
    if not t:
        raise ApiError(404, "That routine isn't there anymore.")
    if t["needs_approval"]:
        raise ApiError(409, "This routine hasn't been approved yet. You'll find it in Decisions.")
    if t["paused"] and t["paused"] != "owner":
        raise ApiError(409, "It's paused while I fix a problem. You'll find it in Decisions.")
    if paused == bool(t["paused"]):
        return
    new = t["line"] + "  paused:owner" if paused else t["line"].replace("  paused:owner", "").replace(" paused:owner", "")
    if not replace_task_line(t["line"], new):
        raise ApiError(409, "Something changed at the same moment. Try again.")
    record_event(f"You {'paused' if paused else 'restarted'} {t['title']}.", who="CEO", workflow=workflow)
    log_run("agent_api", "paused" if paused else "resumed", workflow=workflow)


def todo_id(t: dict) -> str:
    return hashlib.sha1(t["title"].encode()).hexdigest()[:10]


def todos() -> list[dict]:
    recent = (date.today() - timedelta(days=14)).isoformat()
    out = []
    for t in tasks():
        if t["workflow"] or t["rejected"] or (t["done"] and (t["done_on"] or "") < recent):
            continue
        item = {"id": todo_id(t), "title": t["title"], "owner": "you" if t["you"] else "coo", "done": t["done"]}
        if t["due"]:
            item["due"] = t["due"]
        if t["goal"]:
            item["goal"] = t["goal"]
        out.append(item)
    return out


def toggle_todo(tid: str) -> None:
    t = next((t for t in tasks() if not t["workflow"] and todo_id(t) == tid), None)
    if not t:
        raise ApiError(404, "That to-do isn't there anymore.")
    if t["done"]:
        new = re.sub(r"\s+done:\S+", "", t["line"].replace("- [x]", "- [ ]", 1))
    else:
        new = t["line"].replace("- [ ]", "- [x]", 1) + f"  done:{date.today()}"
    if not replace_task_line(t["line"], new):
        raise ApiError(409, "Something changed at the same moment. Try again.")


# ---------- goals ----------

def number(text: str | None) -> tuple[float | None, str]:
    """"$8k" -> (8000, "$"), "40%" -> (40, "%"), "31 cafes" -> (31, "")."""
    if not text:
        return None, ""
    m = re.search(r"(\$)?\s*(-?\d[\d,]*(?:\.\d+)?)\s*([kKmM])?\s*(%)?", text)
    if not m:
        return None, ""
    value = float(m.group(2).replace(",", "")) * {"k": 1e3, "m": 1e6}.get((m.group(3) or "").lower(), 1)
    return value, "$" if m.group(1) else "%" if m.group(4) else ""


PROJECT_STATUS = {"Backlog": "planned", "Todo": "planned", "In progress": "in-progress",
                  "Recurring": "in-progress", "Waiting on CEO": "waiting-on-you", "Blocked": "blocked",
                  "Done": "done"}
PROJECT_OWNER = {"CEO": "you", "COO": "coo", "Workflow": "autopilot"}


def pace(current: float, target: float, created: str, due: str | None) -> str:
    if not due or target <= 0:
        return "on-track"
    start = datetime.fromisoformat(iso(created).replace("Z", "+00:00")).date()
    end = date.fromisoformat(due[:10])
    span = (end - start).days
    expected = 1.0 if span <= 0 else min(1.0, max(0.0, (date.today() - start).days / span))
    progress = current / target
    return "ahead" if progress >= expected + 0.1 else "behind" if progress < expected - 0.1 else "on-track"


def goals() -> list[dict]:
    out = []
    with connect() as con:
        for g in con.execute("""SELECT * FROM goals WHERE status != 'Dropped'
                                ORDER BY status != 'Active', priority, id"""):
            target, unit = number(g["target"])
            current, current_unit = number(g["current"])
            current, target = current or 0.0, target or 0.0
            projects = []
            for m in con.execute("""SELECT * FROM missions WHERE goal_id = ? AND parent_id IS NULL
                                    AND status != 'Cancelled' ORDER BY id""", (g["id"],)):
                status = PROJECT_STATUS.get(m["status"], "planned")
                project = {"id": f"m{m['id']}", "title": m["mission"], "status": status,
                           "owner": PROJECT_OWNER.get(m["owner"], "coo"),
                           "doneWhen": m["definition_of_done"] or "", "startedAt": iso(m["created"])}
                if m["due"]:
                    project["due"] = m["due"]
                if status == "done":
                    project["finishedAt"] = iso(m["updated"])
                projects.append(project)
            goal = {
                "id": f"g{g['id']}",
                "title": g["goal"],
                "why": g["why"] or "",
                "metric": {"label": g["metric"] or "", "current": current, "target": target,
                           "unit": unit or current_unit},
                "pace": "ahead" if g["status"] == "Achieved" else pace(current, target, g["created"], g["due"]),
                "projects": projects,
            }
            if g["created"]:  # a date, or a SQLite timestamp
                goal["startedAt"] = g["created"] if len(g["created"]) == 10 else iso(g["created"])
            if g["due"]:
                goal["due"] = g["due"]
            out.append(goal)
    return out


# ---------- overview ----------

def overview() -> dict:
    waiting = decisions()
    rs = routines()
    spent, cap = month_spend(), limit()  # cap None: a Claude subscription, no limit
    urgent = any(d["urgent"] for d in waiting)
    paused_by_coo = [r for r in rs if r.get("pausedBy") == "coo"]
    runs = tail_jsonl(RUN_LOG, 1_000_000)
    beats = [r for r in runs if r.get("script") == "heartbeat"]
    stale = bool(beats) and (datetime.now(timezone.utc) - datetime.fromisoformat(beats[-1]["ts"])) > timedelta(minutes=45)

    if not ai_access.has_ai():
        health = {"state": "problem", "summary": "Not signed in to its AI yet"}
    elif urgent:
        health = {"state": "problem", "summary": "Something urgent needs you"}
    elif cap is not None and spent >= cap:
        health = {"state": "problem", "summary": "This month's AI budget is used up"}
    elif stale:
        health = {"state": "attention", "summary": "Routines haven't run on schedule lately"}
    elif paused_by_coo:
        n = len(paused_by_coo)
        health = {"state": "attention", "summary": f"{n} routine{'s' if n > 1 else ''} paused while I fix {'them' if n > 1 else 'it'}"}
    elif waiting:
        n = len(waiting)
        health = {"state": "good", "summary": f"{n} thing{'s' if n > 1 else ''} waiting on you"}
    else:
        health = {"state": "good", "summary": "Everything's running smoothly"}

    names = routine_names()
    # The owner's routines only: the engine's own jobs (learning, upkeep) aren't news.
    day = [r for r in since(runs, 1) if r.get("workflow") and r.get("script") == "heartbeat"
           and not r.get("system") and r["workflow"] not in CORE_WORKFLOWS]
    ok = list(dict.fromkeys(routine_name(r["workflow"], names) for r in day if r["status"] == "ok"))
    failed = list(dict.fromkeys(routine_name(r["workflow"], names) for r in day if r["status"] == "error"))
    queued = json.loads(BRIEF_QUEUE.read_text()) if BRIEF_QUEUE.exists() else []

    points = []
    if ok:
        more = f", and {len(ok) - 2} more" if len(ok) > 2 else ""
        points.append(f"Ran on schedule: {', '.join(ok[:2])}{more}.")
    points += [f"{name} hit a problem, so I paused it." for name in failed[:2]]
    points += [plain(q).rstrip(".") + "." for q in queued[-3:]]
    if cap is not None and spent >= cap * 0.8:
        points.append(f"AI spend is at {spent / cap:.0%} of this month's ${cap:.0f}.")

    n = len(waiting)
    if urgent:
        headline = "Something urgent needs you. Everything else is under control."
    elif n:
        headline = f"{n} thing{'s' if n > 1 else ''} need{'' if n > 1 else 's'} your call today."
    elif ok:
        headline = "A quiet day. Everything ran on schedule, and nothing needs you."
    else:
        headline = "All quiet. Nothing needs you right now."

    with connect() as con:
        week = con.execute("""SELECT what, who FROM activity WHERE ts >= datetime('now', '-7 days')""").fetchall()
    done_week = sum(1 for a in week if a["who"] in ("Workflow", "COO")
                    and not a["what"].startswith(("Incident opened", "Diagnosed", "Needs CEO")))

    return {
        "company": {"id": re.sub(r"[^a-z0-9]+", "-", COMPANY.lower()).strip("-"), "name": COMPANY,
                    "ownerFirstName": "", "cooName": ""},
        "health": health,
        "brief": {"headline": headline, "points": points[:4]},
        "spend": {"monthToDateUsd": round(spent, 2), "monthlyCapUsd": cap or 0},
        "stats": {"doneThisWeek": done_week,
                  "hoursSavedThisWeek": sum(r["hoursSavedPerWeek"] for r in rs if r["status"] == "running")},
    }


# ---------- chat ----------

def _message(e: dict) -> dict:
    """A chat log entry as the app shows it. Its id comes from the message itself (time, sender,
    text), so it stays the same however much history is around it."""
    return {"id": hashlib.sha1(f"{e['ts']}|{e['from']}|{(e.get('text') or '')[:200]}".encode()).hexdigest()[:12],
            "from": e["from"], "text": e.get("text") or "", "at": e["ts"],
            **({"steps": e["steps"]} if e.get("steps") else {}), **({"files": e["files"]} if e.get("files") else {}),
            **({"artifacts": e["artifacts"]} if e.get("artifacts") else {})}


def _newest_first(path: Path = None, chunk: int = 1 << 16):
    """The chat log's entries from the newest back, reading the file from its end, so the cost
    is the messages read, not the size of the whole history."""
    path = path or bridge.CHAT_LOG
    if not path.exists():
        return
    with path.open("rb") as f:
        f.seek(0, 2)
        pos, rest = f.tell(), b""
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            f.seek(pos)
            lines = (f.read(step) + rest).split(b"\n")
            rest = lines[0]
            for line in reversed(lines[1:]):
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        if rest.strip():
            try:
                yield json.loads(rest)
            except json.JSONDecodeError:
                pass


def chat(limit: int = 200) -> list[dict]:
    """The latest messages, oldest first."""
    entries = []
    for e in _newest_first():
        entries.append(e)
        if len(entries) >= limit:
            break
    return [_message(e) for e in reversed(entries)]


def chat_page(before: str = "", after: str = "", around: str = "", limit: int = 50) -> dict:
    """A page of the conversation, oldest first: the latest messages, those before or after one
    (scrolling up, or what's new since), or those around one (a search result, in context).
    hasEarlier and hasLater say whether there's more beyond the page. If the message asked
    about isn't there (an id from before an engine update), you get the latest page with reset."""
    limit = max(1, min(int(limit), 200))
    newer: list[dict] = []  # seen before reaching the message asked about
    older: list[dict] = []
    target = before or after or around
    found = not target
    for e in _newest_first():
        if not found:
            if _message(e)["id"] == target:
                found = True
                if after:
                    return {"messages": [_message(x) for x in reversed(newer)], "hasEarlier": True, "hasLater": False}
                if around:
                    older.append(e)
                continue
            newer.append(e)
            if after and len(newer) > 1000:
                break  # far behind: start again from the latest
            continue
        older.append(e)
        if len(older) > (limit // 2 + 1 if around else limit):
            break  # one more than the page, to know whether there's more
    if not found:
        return {**chat_page(limit=limit), "reset": True}
    if around:
        half = limit // 2
        later = newer[-half:] if half else []
        page = list(reversed(older[: half + 1])) + list(reversed(later))
        return {"messages": [_message(x) for x in page], "hasEarlier": len(older) > half + 1, "hasLater": len(newer) > half}
    return {"messages": [_message(x) for x in reversed(older[:limit])], "hasEarlier": len(older) > limit, "hasLater": False}


def search_chat(query: str, limit: int = 50) -> list[dict]:
    """Messages in the whole conversation history containing every word of the query (any case),
    newest first. File names count as text."""
    words = [w for w in query.lower().split() if w][:10]
    if not words or len(query) > 200:
        return []
    found = []
    for e in _newest_first():
        if e.get("from") not in ("you", "coo"):
            continue
        hay = (e.get("text") or "").lower() + " " + " ".join(f.get("name", "").lower() for f in e.get("files") or [])
        if all(w in hay for w in words):
            message = _message(e)
            message.pop("steps", None)
            found.append(message)
            if len(found) >= limit:
                break
    return found


def _check_target(message: str) -> tuple[dict, str]:
    """A COO reply by its id, and what the owner had said just before it."""
    found = None
    for e in _newest_first():
        if found is None:
            if e.get("from") == "coo" and _message(e)["id"] == message:
                found = e
            continue
        if e.get("from") == "you":
            return found, e.get("text") or ""
        if e.get("from") == bridge.DIVIDER:
            break
    if found is None:
        raise ApiError(404, "That message isn't in the conversation any more.")
    return found, ""


def _checks(fn, *args):
    try:
        return fn(*args)
    except checks.CheckError as e:
        raise ApiError(400, str(e)) from None
    except plans.PlanError as e:
        raise ApiError(400, str(e)) from None


def start_check(message: str, body: dict) -> dict:
    entry, said = _check_target(message)
    kind = str(body.get("kind") or ((entry.get("artifacts") or {}).get("check") or {}).get("kind") or "")
    return _checks(checks.start, message, entry, said, kind, coo_name())


def new_chat() -> dict:
    try:
        return {"started": bridge.new_conversation()}
    except bridge.Busy:
        raise ApiError(409, f"{coo_name()} is still answering. Try again in a moment.") from None


def chat_activity() -> dict:
    """Whether the COO is working on a reply, and what it has done so far, in plain words.
    A live file older than the longest turn is left over from a restart, so it doesn't count."""
    try:
        working = time.time() - bridge.LIVE.stat().st_mtime < 900
    except OSError:
        working = False
    return {"working": working, "steps": bridge.live_steps() if working else []}


# What the engine's own jobs are called for the owner (common.SYSTEM_JOBS).
SYSTEM_JOB_NAMES = {"learn": "Learning from the day", "curate_skills": "Tidying up what it knows",
                    "upkeep": "Clearing out what's no longer needed"}


def _quoted(names: list[str]) -> str:
    more = f" and {len(names) - 1} more" if len(names) > 1 else ""
    return f"\u201c{names[0]}\u201d{more}"


def status() -> dict:
    """What the COO is doing in the background, for the status panel behind the health line:
    each helper with its state (working now, idle, attention, or waiting on the owner), one
    plain sentence, and when it last did something. Reads only notes and logs, no model."""
    now = datetime.now(timezone.utc)
    names = routine_names()
    runs = tail_jsonl(RUN_LOG, 1_000_000)
    doing = _heartbeat_doing()
    helpers = []

    # Routines: the heartbeat runs whatever's due every few minutes.
    beats = [r for r in runs if r.get("script") == "heartbeat" and not r.get("system")]
    last = beats[-1] if beats else None
    active = [t for t in tasks() if t["workflow"] and not t["done"] and not t["paused"]
              and not t["needs_approval"] and not t["rejected"] and t["workflow"] not in CORE_WORKFLOWS
              and not builder.missing(t["workflow"])]
    today = [r for r in since(beats, 1) if r.get("workflow")]
    failed = sum(r["status"] == "error" for r in today)
    if doing.get("routine"):
        state, summary = "working", f"Running \u201c{routine_name(doing['routine'], names)}\u201d now"
    elif last and last["status"] == "budget_stop":
        state, summary = "attention", "Waiting for more AI allowance before running anything"
    elif last and now - datetime.fromisoformat(last["ts"]) > timedelta(minutes=45):
        state, summary = "attention", "Hasn't run on schedule lately"
    elif not active:
        state, summary = "idle", "No routines yet"
    else:
        n, ran = len(active), sum(r["status"] == "ok" for r in today)
        summary = f"{n} routine{'s' if n > 1 else ''} on schedule"
        if ran:
            summary += f", {ran} run{'s' if ran > 1 else ''} today"
        if failed:
            summary += f", {failed} hit a problem"
        state = "idle"
    helpers.append({"id": "routines", "name": "Routines", "state": state, "summary": summary,
                    "lastAt": last["ts"] if last else None})

    # Chat: a reply being written right now.
    act = chat_activity()
    replies = [r for r in runs if r.get("script") == "bridge" and r["status"] in ("ok", "error")]
    steps = [s for s in act["steps"] if isinstance(s, str)]
    helpers.append({"id": "chat", "name": "Chat", "state": "working" if act["working"] else "idle",
                    "summary": (steps[-1] if steps else "Writing a reply") if act["working"] else "Ready when you are",
                    "lastAt": replies[-1]["ts"] if replies else None})

    # New routines being built after the owner approved them.
    builds = sorted(builder.load().values(), key=lambda b: b.get("finished") or b.get("opened") or "")
    active = [b for b in builds if b["status"] in ("building", "failed")]  # failed: trying again on its own
    building = [b["title"] for b in active if not b.get("change")]
    updating = list(dict.fromkeys(b["title"] for b in active if b.get("change")))
    stuck = [b["title"] for b in builds if b["status"] == "needs_owner"]
    ready = [b["title"] for b in builds if b["status"] == "ready"]
    if building or updating:
        parts = ([f"Setting up {_quoted(building)}"] if building else []) + \
                ([f"Updating {_quoted(updating)} (the current version keeps running)"] if updating else [])
        state, summary = "working", "; ".join(parts)
    elif stuck:
        state, summary = "needsYou", f"{_quoted(stuck)} needs you in Decisions"
    elif ready:
        state, summary = "needsYou", f"{_quoted(ready)} is ready: see its practice run in Decisions"
    else:
        state, summary = "idle", "Nothing to set up"
    helpers.append({"id": "builder", "name": "Setting up routines", "state": state, "summary": summary,
                    "lastAt": (builds[-1].get("finished") or builds[-1].get("opened")) if builds else None})

    # Problems with routines: looked into, and fixed or brought to the owner.
    incs = sorted(incident.load().values(), key=lambda i: i.get("resolved") or i.get("opened") or "")
    looking = [routine_name(i.get("workflow"), names) for i in incs if i["status"] == "investigating"]
    waiting = [i for i in incs if i["status"] == "awaiting_ceo"]
    if looking:
        state, summary = "working", f"Looking into a problem with {_quoted(looking)}"
    elif waiting:
        n = len(waiting)
        state, summary = "needsYou", f"{n} fix{'es' if n > 1 else ''} waiting for you in Decisions"
    else:
        state, summary = "idle", "Nothing needs fixing"
    helpers.append({"id": "fixer", "name": "Fixing problems", "state": state, "summary": summary,
                    "lastAt": (incs[-1].get("resolved") or incs[-1].get("opened")) if incs else None})

    # Books the owner asked it to learn
    studying = [b for b in books.books() if b["status"] == "studying"]
    if studying:
        b = studying[0]
        helpers.append({"id": "books", "name": "Studying a book", "state": "working",
                        "summary": f"“{b['title']}”: {(b.get('progress') or 'reading').lower()}", "lastAt": b["added"]})

    # The engine's own jobs. A failure is retried and is ours, not the owner's, so it never shows as a problem.
    try:
        done = json.loads(heartbeat.SYSTEM_STATE.read_text())
    except (OSError, ValueError):
        done = {}
    for job, days in SYSTEM_JOBS.items():
        last_day = done.get(job, {}).get("last")
        helpers.append({"id": job, "name": SYSTEM_JOB_NAMES.get(job, job.replace("_", " ").capitalize()),
                        "state": "working" if doing.get("system") == job else "idle",
                        "summary": "Working on it now" if doing.get("system") == job
                        else ("Once a day" if days == 1 else f"Once every {days} days" if days != 7 else "Once a week"),
                        "lastAt": f"{last_day}T00:00:00Z" if last_day else None})

    return {"now": now_iso(), "helpers": helpers}


def _turn(text: str, show_prompt: bool = True, attached: list | None = None) -> dict | None:
    """One chat turn in the background. Waits up to CHAT_WAIT_SECONDS for the reply; past
    that it returns None and the reply lands in the chat log when it's ready."""
    result: list[str] = []
    worker = threading.Thread(target=lambda: result.append(bridge.converse(text, bridge.APP, show_prompt, attached)), daemon=True)
    worker.start()
    worker.join(CHAT_WAIT_SECONDS)
    if not result:
        return None
    # The reply as the log has it, so its id is the one every later page uses.
    latest = next((e for e in _newest_first() if e.get("from") == "coo"), None)
    return _message(latest) if latest else None


MAX_MESSAGE = 20_000  # characters; long notes and pasted documents are fine


def send(text: str, file_ids: list | None = None) -> dict | None:
    text = text.strip()
    if len(text) > MAX_MESSAGE:
        raise ApiError(400, f"That's too long for one message ({len(text):,} characters). Keep it under {MAX_MESSAGE:,}, or attach it as a file.")
    if not isinstance(file_ids, list) or len(file_ids) > 10 or not all(isinstance(f, str) for f in file_ids):
        raise ApiError(400, "Attach up to 10 files at a time.")
    try:
        attached = [files.describe(files.find(f)) for f in file_ids]
    except files.FileError as e:
        raise ApiError(400, str(e)) from None
    if not text and not attached:
        raise ApiError(400, "Write a message first.")
    return _turn(text, attached=attached)


# ---------- onboarding ----------

ONBOARDING_HEADING = "## First session: onboarding"
ONBOARDING_STARTED = CACHE / "onboarding_started"
KICKOFF = ("start onboarding. This is the owner's first visit to the Steerable app. Greet them by "
           "name if you know it, say in one or two sentences what you'll do together, then ask your "
           "first question. One question per message.")
_kickoff_lock = threading.Lock()


def onboarding() -> dict:
    """Onboarding is done once its section is gone from CLAUDE.md: the COO deletes it as its last
    step, and the engine does it when the owner approves a routine while it's still there (decide),
    for a COO that forgot. It has started once there's any conversation."""
    done = ONBOARDING_HEADING not in (ROOT / "CLAUDE.md").read_text()
    started = done or ONBOARDING_STARTED.exists() or bool(tail_jsonl(bridge.CHAT_LOG, 100_000))
    return {"done": done, "started": started}


def start_onboarding() -> dict:
    """The COO opens the conversation. Does nothing if it's done or already under way."""
    with _kickoff_lock:  # two tabs opening the page at once start it once
        if onboarding()["started"]:
            return {"reply": None, "started": False}
        ONBOARDING_STARTED.touch()
    return {"reply": _turn(KICKOFF, show_prompt=False), "started": True}


# ---------- the owner's own tools ----------

_account: dict = {}


def claude_account() -> bool:
    """Is Claude Code signed in with a Claude account (so the owner's claude.ai connectors work)?"""
    if _account.get("at", 0) > datetime.now().timestamp() - 300:
        return _account["yes"]
    try:
        out = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=15)
        yes = json.loads(out.stdout).get("authMethod") == "claude.ai"
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, AttributeError):
        yes = False
    _account.update(yes=yes, at=datetime.now().timestamp())
    return yes


def tools_overview() -> dict:
    return {
        "catalog": [{"id": k, "name": v["name"], "description": v["description"], "category": v["category"],
                     "uses": v.get("uses", []),
                     "auth": {x: v["auth"][x] for x in ("type", "keyLabel", "keyHint", "optional") if x in v["auth"]},
                     **({"tested": v["tested"]} if v.get("tested") else {}),
                     **({"popular": v["popular"]} if v.get("popular") else {})}
                    for k, v in tools.catalog().items()],
        "connected": tools.connected(),
        "alwaysAllowed": [{"tool": t, "service": approvals.service_name(approvals.split(t)[0]),
                           "what": approvals.human(approvals.split(t)[1])} for t in approvals.always_allowed()],
        "claudeAccount": claude_account(),
        "throughSteerable": bool(integrations._gateway()),
    }


def _tools(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except tools.ToolError as e:
        raise ApiError(400, str(e)) from None


def _ai(fn, *args):
    try:
        return fn(*args)
    except ai_access.AiError as e:
        raise ApiError(400, str(e)) from None


# ---------- dashboards over the library ----------

def _dash(fn, *args):
    try:
        return fn(*args)
    except dashboards.DashboardError as e:
        raise ApiError(404 if "no such dashboard" in str(e) else 400, str(e)) from None


def dashboard_detail(did: str) -> dict:
    found = dashboards.detail(did)
    if not found or found["id"] != did:
        raise ApiError(404, "There's no such dashboard.")
    return {**found, "sources": dashboards.sources(), "asks": dashboards.asks(did)}


def dashboard_edit(did: str, b: dict) -> dict:
    name = b.get("name") if isinstance(b.get("name"), str) else None
    description = b.get("description") if isinstance(b.get("description"), str) else None
    return _dash(dashboards.rename, did, name, description, "you")


def dashboard_widget(did: str, b: dict, wid: str | None = None) -> dict:
    return _dash(dashboards.save_widget, did, wid, body_field(b, "widget", dict), "you")


def dashboard_ask(b: dict) -> dict:
    """The owner asks the COO for a dashboard, or a change to one. The COO works on it in the
    background, through the chat (where the owner sees it too); its reply lands in the Library."""
    did = b.get("dashboard") if isinstance(b.get("dashboard"), str) and b.get("dashboard") else None
    made = _dash(dashboards.ask, body_field(b, "text", str), did)
    threading.Thread(target=_ask_dashboard, args=(made,), daemon=True).start()
    return made


def _ask_dashboard(made: dict) -> None:
    bridge._log_chat("you", f"A dashboard: {made['text']}")
    try:
        reply, status = bridge.converse(dashboards.ask_prompt(made), bridge.APP, show_prompt=False), "answered"
    except Exception as e:  # noqa: BLE001 - the owner sees that it didn't work, in the Library
        log_run("agent_api", "error", step="dashboard ask", error=repr(e)[:300])
        reply, status = "I couldn't get to this just now. Ask again in a minute.", "failed"
    dashboards.answered(made["id"], reply or "Done.", status)


# ---------- the library (records), for the app ----------

def _lib(fn):
    try:
        with library.acting("you"):  # through the app: the owner's own change
            return fn()
    except library.LibraryError as e:
        raise ApiError(404 if "There's no table" in str(e) or "has no row" in str(e) else 400, str(e)) from None


def run_changes(run: str, q: dict) -> dict:
    """A run's change table, a page at a time."""
    arg = lambda k, d: (q.get(k) or [d])[0] or d  # noqa: E731
    try:
        after, limit = int(arg("after", "0")), int(arg("limit", "50"))
    except ValueError:
        raise ApiError(400, "after and limit are numbers.") from None
    return _lib(lambda: library.run_changes(run, arg("table", "") or None, after, limit))


def _books(fn, *args):
    try:
        return fn(*args)
    except books.BookError as e:
        raise ApiError(404 if "no such book" in str(e) else 400, str(e)) from None


def _plans(fn, *args):
    try:
        return fn(*args)
    except plans.PlanError as e:
        raise ApiError(404 if "no such plan" in str(e) else 400, str(e)) from None


def plan_detail(pid: str) -> dict:
    found = plans.detail(pid)
    if not found:
        raise ApiError(404, "There's no such plan.")
    return found


def plan_version(pid: str, n: str) -> dict:
    found = plans.version(pid, int(n))
    if not found:
        raise ApiError(404, "There's no such version.")
    return found


def edit_plan(pid: str, b: dict) -> dict:
    """The owner's own edit: a new version, by "you". A shorter plan is fine when they write it."""
    note = (b.get("note") or "") if isinstance(b.get("note"), str) else ""
    out = _plans(plans.save, "", body_field(b, "body", str), note.strip()[:500] or "Edited by you", "you", pid, None, False, True)
    if out["changed"]:
        record_event(f"You changed “{out['plan']['title']}”", who="CEO")
    return out["plan"]


def restore_plan(pid: str, b: dict) -> dict:
    n = body_field(b, "version", int)
    p = _plans(plans.restore, pid, n, "you")
    record_event(f"You brought “{p['title']}” back to version {n}", who="CEO")
    return p


def book_detail(bid: str, q: dict) -> dict:
    found = _books(books.detail, bid)
    if not found:
        raise ApiError(404, "There's no such book.")
    query = ((q.get("q") or [""])[0] or "").strip()[:200]
    return {**found, "passages": books.search(query, bid, 12) if query else []}


def teach_book(b: dict) -> dict:
    text = lambda k: b.get(k) if isinstance(b.get(k), str) else ""  # noqa: E731
    return _books(books.add, body_field(b, "file", str), text("why"), text("title"), text("author"))


def library_table(tid: str, q: dict) -> dict:
    """A page of a table for the app: ?q (search) &sort=<column>&dir=desc &where.<column>=<value>
    &archived=1 &offset&limit (up to 500)."""
    arg = lambda k, d="": (q.get(k) or [d])[0] or d  # noqa: E731
    try:
        offset, limit = int(arg("offset", "0")), int(arg("limit", "100"))
    except ValueError:
        raise ApiError(400, "offset and limit are numbers.") from None
    def get():
        t = library.table(tid)
        with library.connect() as con:
            info = con.execute("SELECT description FROM tables WHERE id = ?", (t.id,)).fetchone()
        page = t.query(**_library_query(q), limit=limit, offset=offset)
        return {"table": {"id": t.id, "name": t.name, "description": info["description"] if info else ""},
                "columns": t.columns, "views": t.views(), **page}
    return _lib(get)


def _library_query(q: dict) -> dict:
    """A table query from the address: ?q &sort &dir &where.<column> &archived=1 &group
    &between=<date column>,<from>,<to>."""
    arg = lambda k: (q.get(k) or [""])[0] or ""  # noqa: E731
    between = arg("between").split(",") if arg("between") else None
    if between and len(between) != 3:
        raise ApiError(400, "between is column,from,to.")
    return {"search": arg("q"), "where": {k[len("where."):]: v[0] for k, v in q.items() if k.startswith("where.") and v},
            "sort": arg("sort"), "desc": arg("dir") == "desc", "archived": arg("archived") == "1",
            "group": arg("group"), "between": tuple(between) if between else None}


def library_view(tid: str, b: dict, vid: str = "", action: str = "") -> dict | None:
    def write():
        t = library.table(tid)
        if action == "delete":
            return t.delete_view(vid)
        name = b.get("name") if isinstance(b.get("name"), str) else None
        config = b.get("config") if isinstance(b.get("config"), dict) else None
        kind = b.get("type") if isinstance(b.get("type"), str) else None
        return t.save_view(vid or None, name, kind, config)
    return _lib(write)


def library_comment(tid: str, rid: str, b: dict) -> dict:
    """The owner's comment on a row. With ask, the COO works on it in the background, through the
    chat (where the owner sees it too), and its reply lands under the comment."""
    text, ask = body_field(b, "text", str), b.get("ask") is True

    def write():
        t = library.table(tid)
        return t, t.comment(rid, text, ask), t.get(rid)
    t, made, row = _lib(write)
    if ask:
        threading.Thread(target=_ask_coo, args=(t.id, t.name, row, made), daemon=True).start()
    return made


def _ask_coo(table_id: str, table_name: str, row: dict, made: dict) -> None:
    values = "; ".join(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}"
                       for k, v in row["cells"].items() if v not in (None, "", []))[:2000]
    label = next((str(v) for v in row["cells"].values() if isinstance(v, str) and v.strip()), "a row")[:80]
    bridge._log_chat("you", f"About “{label}” in {table_name}: {made['text']}")
    prompt = (f"The owner commented on a row of the library table “{table_name}” (row {row['id']}"
              f"{', key ' + row['key'] if row.get('key') else ''}) and asked you to act on it. Its values: {values}\n\n"
              f"Their comment: {made['text']}\n\n"
              f"Do what they ask. To change the row: .venv/bin/python scripts/library.py update \"{table_name}\" {row['id']} "
              "--set Column=value. Reply in a sentence or two about this request only (no other topics): your reply is shown "
              "under their comment on that row, and here.")
    try:
        reply, status = bridge.converse(prompt, bridge.APP, show_prompt=False), "answered"
    except Exception as e:  # noqa: BLE001 - the owner sees that it didn't work, under the comment
        log_run("agent_api", "error", step="library comment", error=repr(e)[:300])
        reply, status = "I couldn't get to this just now. Ask again in a minute.", "failed"
    with library.acting("coo"):
        t = library.table(table_id)
        t.comment(row["id"], (reply or "Done.")[:5000])
        t.answered(made["id"], status)


def library_row(tid: str, rid: str) -> dict:
    def get():
        t = library.table(tid)
        row = t.get(rid)
        if not row:
            raise library.LibraryError(f"{t.name} has no row {rid}.")
        return {**row, "history": t.history(rid), "comments": t.comments(rid),
                "files": library._file_names(f for v in row["cells"].values() if isinstance(v, list) for f in v
                                             if isinstance(f, str) and re.fullmatch(r"[0-9a-f]{8,}", f))}
    return _lib(get)


def library_write(tid: str, b: dict, rid: str = "", action: str = "") -> dict:
    def write():
        t = library.table(tid)
        if action == "archive":
            t.archive(rid)
        elif action == "restore":
            t.restore(rid)
        elif rid:
            t.update(rid, body_field(b, "cells", dict))
        else:
            key = b.get("key") if isinstance(b.get("key"), str) else None
            return t.get(t.add(body_field(b, "cells", dict), key=key))
        return t.get(rid)
    return _lib(write)


def connect_tool(b: dict) -> dict:
    opt = lambda k: b.get(k) if isinstance(b.get(k), str) and b.get(k).strip() else None
    return _tools(tools.start, opt("id") or "", opt("redirectUri") or "", url=opt("url"), name=opt("name"), key=opt("key"))


# ---------- Telegram ----------

def _telegram(fn, *args):
    try:
        return fn(*args)
    except telegram.TelegramError as e:
        raise ApiError(400, str(e)) from None


def telegram_disconnect() -> dict:
    telegram.disconnect()
    return telegram.status()


# ---------- values only the owner has ----------

def _vault(fn, *args):
    try:
        return fn(*args)
    except vault.VaultError as e:
        raise ApiError(400, str(e)) from None


# ---------- website logins ----------

def _sites(fn, *args):
    try:
        return fn(*args)
    except sites.SiteError as e:
        raise ApiError(400 if "ended" not in str(e) else 404, str(e)) from None
    except ImportError:
        raise ApiError(503, "This server can't run a browser. Website logins need the Docker version of Steerable.") from None


# ---------- export ----------

# What belongs to the owner. Never .env (secrets), .cache (internal state, tokens), .home (the
# Claude session), .venv, .git internals or lock files.
EXPORT_PATHS = ["CLAUDE.md", "tasks.md", "memory", "workflows", ".claude/skills", "logs", "drafts", "files"]


def export_archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in EXPORT_PATHS:
            path = ROOT / rel
            if path.exists():
                tar.add(path, arcname=f"company/{rel}", filter=lambda info: None if info.issym() else info)
        # A consistent copy of the mission board, even while something is writing to it.
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "ops.db"
            with connect() as src, sqlite3.connect(copy) as dst:
                src.backup(dst)
            tar.add(copy, arcname="company/ops.db")
            if library.DB.exists():
                lib = Path(tmp) / "library.db"
                with sqlite3.connect(library.DB) as src, sqlite3.connect(lib) as dst:
                    src.backup(dst)
                tar.add(lib, arcname="company/library.db")
    return buf.getvalue()


# ---------- HTTP ----------

def _accounts(fn, *args):
    try:
        return fn(*args)
    except (accounts.AccountError, mailbox.MailboxError, sites.SiteError) as e:
        raise ApiError(400, str(e)) from None


def accounts_overview() -> dict:
    return {"accounts": accounts.listing(), "mailbox": mailbox.status(), "phone": accounts.settings().get("phone") or "",
            "cooName": coo_name()}


def account(site: str) -> dict:
    a = accounts.load(site)
    if not a or a["status"] == "DECLINED":
        raise ApiError(404, "That account isn't saved.")
    return accounts.public(a)


def _extension(fn, *args):
    try:
        return fn(*args)
    except (extension.ExtensionError, sites.SiteError) as e:
        raise ApiError(400, str(e)) from None
    except browser.ProfileBusy:
        raise ApiError(409, "A routine is using that site right now. It'll be picked up next time.") from None


def _paired(body: dict) -> None:
    if not extension.valid(str(body.get("token") or "")):
        raise ApiError(401, "This browser isn't paired with your dashboard any more. Pair it again.")


def extension_login(body: dict) -> dict:
    _paired(body)
    return _extension(sites.import_login, str(body.get("startUrl") or ""), str(body.get("name") or ""), body.get("cookies"))


def extension_sites(body: dict) -> dict:
    _paired(body)
    return {"sites": [{k: s[k] for k in ("site", "name", "status")} for s in sites.saved() if s["source"] == "browser"]}


def body_field(body: dict, name: str, kind: type):
    value = body.get(name)
    if not isinstance(value, kind):
        raise ApiError(400, f"Missing {name}.")
    return value


ROUTES = [
    ("GET", r"/v1/overview", lambda q, b: overview()),
    ("GET", r"/v1/decisions", lambda q, b: decisions()),
    ("POST", r"/v1/decisions/(?P<id>[^/]+)", lambda q, b, id: decide(id, body_field(b, "optionId", str), str(b.get("note") or ""))),
    ("GET", r"/v1/timeline", lambda q, b: timeline(max(1, min(200, int(q.get("limit", ["50"])[0]))))),
    ("GET", r"/v1/routines", lambda q, b: routines()),
    ("GET", r"/v1/routines/(?P<id>[\w-]+)", lambda q, b, id: routine_detail(id)),
    ("POST", r"/v1/routines/(?P<id>[^/]+)/paused", lambda q, b, id: set_routine_paused(id, body_field(b, "paused", bool))),
    ("POST", r"/v1/routines/(?P<id>[\w-]+)/run", lambda q, b, id: run_routine(id)),
    ("POST", r"/v1/routines/(?P<id>[\w-]+)/watch", lambda q, b, id: watch_routine(id, body_field(b, "watch", bool))),
    ("GET", r"/v1/traces/(?P<id>[\w-]{1,60})", lambda q, b, id: trace_view(id)),
    ("GET", r"/v1/todos", lambda q, b: todos()),
    ("POST", r"/v1/todos/(?P<id>[^/]+)/toggle", lambda q, b, id: toggle_todo(id)),
    ("GET", r"/v1/goals", lambda q, b: goals()),
    ("GET", r"/v1/chat", lambda q, b: chat()),
    ("GET", r"/v1/chat/page", lambda q, b: chat_page(**{k: (q.get(k) or [""])[0] for k in ("before", "after", "around")},
                                                     limit=int((q.get("limit") or ["50"])[0] or 50))),
    ("POST", r"/v1/chat", lambda q, b: {"reply": send(body_field(b, "text", str), b.get("files") or [])}),
    ("GET", r"/v1/chat/activity", lambda q, b: chat_activity()),
    ("GET", r"/v1/checks/(?P<mid>[0-9a-f]{6,40})", lambda q, b, mid: _checks(checks.view, mid)),
    ("POST", r"/v1/checks/(?P<mid>[0-9a-f]{6,40})", lambda q, b, mid: start_check(mid, b)),
    ("POST", r"/v1/checks/(?P<mid>[0-9a-f]{6,40})/apply",
     lambda q, b, mid: _checks(checks.apply, mid, [str(x) for x in (b.get("edits") or [])][:10])),
    ("GET", r"/v1/status", lambda q, b: status()),
    ("POST", r"/v1/chat/new", lambda q, b: new_chat()),
    ("GET", r"/v1/chat/search", lambda q, b: search_chat((q.get("q") or [""])[0])),
    ("GET", r"/v1/onboarding", lambda q, b: onboarding()),
    ("POST", r"/v1/onboarding/start", lambda q, b: start_onboarding()),
    ("GET", r"/v1/tools", lambda q, b: tools_overview()),
    ("POST", r"/v1/tools/connect", lambda q, b: connect_tool(b)),
    ("POST", r"/v1/tools/callback", lambda q, b: {"connected": _tools(tools.finish, body_field(b, "state", str), body_field(b, "code", str))}),
    ("POST", r"/v1/tools/always", lambda q, b: approvals.stop_always(body_field(b, "tool", str))),
    ("POST", r"/v1/tools/(?P<id>[^/]+)/disconnect", lambda q, b, id: _tools(tools.disconnect, id)),
    ("GET", r"/v1/extension", lambda q, b: extension.status()),
    ("POST", r"/v1/extension/code", lambda q, b: extension.new_code()),
    ("POST", r"/v1/extension/unpair", lambda q, b: extension.unpair()),
    ("POST", r"/v1/extension/pair", lambda q, b: _extension(extension.pair, str(b.get("code") or ""), str(b.get("browser") or ""))),
    ("POST", r"/v1/extension/logins", lambda q, b: extension_login(b)),
    ("POST", r"/v1/extension/status", lambda q, b: extension_sites(b)),
    ("GET", r"/v1/telegram", lambda q, b: telegram.status()),
    ("GET", r"/v1/library", lambda q, b: library.tables()),
    ("GET", r"/v1/dashboards", lambda q, b: dashboards.dashboards()),
    ("POST", r"/v1/dashboards", lambda q, b: _dash(dashboards.create, body_field(b, "name", str), "", "you")),
    ("GET", r"/v1/dashboards/asks", lambda q, b: dashboards.asks()),
    ("POST", r"/v1/dashboards/asks", lambda q, b: dashboard_ask(b)),
    ("GET", r"/v1/dashboards/(?P<did>db[0-9a-f]+)", lambda q, b, did: dashboard_detail(did)),
    ("POST", r"/v1/dashboards/(?P<did>db[0-9a-f]+)", lambda q, b, did: dashboard_edit(did, b)),
    ("POST", r"/v1/dashboards/(?P<did>db[0-9a-f]+)/delete", lambda q, b, did: (_dash(dashboards.remove, did), {"ok": True})[1]),
    ("POST", r"/v1/dashboards/(?P<did>db[0-9a-f]+)/widgets", lambda q, b, did: dashboard_widget(did, b)),
    ("POST", r"/v1/dashboards/(?P<did>db[0-9a-f]+)/widgets/(?P<wid>w[0-9a-f]+)", lambda q, b, did, wid: dashboard_widget(did, b, wid)),
    ("POST", r"/v1/dashboards/(?P<did>db[0-9a-f]+)/widgets/(?P<wid>w[0-9a-f]+)/(?P<action>remove|up|down)",
     lambda q, b, did, wid, action: (_dash(dashboards.change_widget, did, wid, action, "you"), {"ok": True})[1]),
    ("GET", r"/v1/plans", lambda q, b: plans.plans()),
    ("GET", r"/v1/plans/(?P<pid>pl[0-9a-f]+)", lambda q, b, pid: plan_detail(pid)),
    ("GET", r"/v1/plans/(?P<pid>pl[0-9a-f]+)/versions/(?P<n>[0-9]{1,6})", lambda q, b, pid, n: plan_version(pid, n)),
    ("POST", r"/v1/plans/(?P<pid>pl[0-9a-f]+)", lambda q, b, pid: edit_plan(pid, b)),
    ("POST", r"/v1/plans/(?P<pid>pl[0-9a-f]+)/restore", lambda q, b, pid: restore_plan(pid, b)),
    ("POST", r"/v1/plans/(?P<pid>pl[0-9a-f]+)/delete", lambda q, b, pid: (_plans(plans.remove, pid), {"ok": True})[1]),
    ("GET", r"/v1/books", lambda q, b: books.books()),
    ("GET", r"/v1/books/search", lambda q, b: books.search(((q.get("q") or [""])[0] or "")[:200], None, 12)),
    ("POST", r"/v1/books", lambda q, b: teach_book(b)),
    ("GET", r"/v1/books/(?P<bid>b[0-9a-f]+)", lambda q, b, bid: book_detail(bid, q)),
    ("POST", r"/v1/books/(?P<bid>b[0-9a-f]+)/proposals/(?P<pid>p[0-9a-f]+)",
     lambda q, b, bid, pid: _books(books.answer, bid, pid, body_field(b, "approve", bool))),
    ("POST", r"/v1/books/(?P<bid>b[0-9a-f]+)/paused", lambda q, b, bid: _books(books.set_paused, bid, body_field(b, "paused", bool))),
    ("POST", r"/v1/books/(?P<bid>b[0-9a-f]+)/retry", lambda q, b, bid: _books(books.retry, bid)),
    ("POST", r"/v1/books/(?P<bid>b[0-9a-f]+)/delete", lambda q, b, bid: _books(books.remove, bid)),
    ("POST", r"/v1/library/tables/(?P<tid>[^/]+)/views", lambda q, b, tid: library_view(tid, b)),
    ("POST", r"/v1/library/tables/(?P<tid>[^/]+)/views/(?P<vid>[\w-]+)", lambda q, b, tid, vid: library_view(tid, b, vid)),
    ("POST", r"/v1/library/tables/(?P<tid>[^/]+)/views/(?P<vid>[\w-]+)/delete", lambda q, b, tid, vid: library_view(tid, b, vid, "delete")),
    ("POST", r"/v1/library/tables/(?P<tid>[^/]+)/rows/(?P<rid>[^/]+)/comments", lambda q, b, tid, rid: library_comment(tid, rid, b)),
    ("GET", r"/v1/runs/(?P<run>[\w-]{1,60})/changes", lambda q, b, run: run_changes(run, q)),
    ("GET", r"/v1/library/tables/(?P<tid>[^/]+)", lambda q, b, tid: library_table(tid, q)),
    ("POST", r"/v1/library/tables/(?P<tid>[^/]+)/rows", lambda q, b, tid: library_write(tid, b)),
    ("GET", r"/v1/library/tables/(?P<tid>[^/]+)/rows/(?P<rid>[^/]+)", lambda q, b, tid, rid: library_row(tid, rid)),
    ("POST", r"/v1/library/tables/(?P<tid>[^/]+)/rows/(?P<rid>[^/]+)", lambda q, b, tid, rid: library_write(tid, b, rid)),
    ("POST", r"/v1/library/tables/(?P<tid>[^/]+)/rows/(?P<rid>[^/]+)/(?P<action>archive|restore)",
     lambda q, b, tid, rid, action: library_write(tid, b, rid, action)),
    ("GET", r"/v1/ai", lambda q, b: ai_access.status()),
    ("POST", r"/v1/ai/claude/login", lambda q, b: _ai(ai_access.start_login)),
    ("POST", r"/v1/ai/claude/code", lambda q, b: _ai(ai_access.finish_login, body_field(b, "code", str))),
    ("POST", r"/v1/ai/claude/cancel", lambda q, b: ai_access.cancel_login() or ai_access.status()),
    ("POST", r"/v1/ai/claude/logout", lambda q, b: _ai(ai_access.sign_out)),
    ("POST", r"/v1/ai/jev", lambda q, b: _ai(ai_access.save_jev, body_field(b, "key", str))),
    ("POST", r"/v1/ai/jev/remove", lambda q, b: _ai(ai_access.remove_jev)),
    ("POST", r"/v1/telegram/token", lambda q, b: _telegram(telegram.set_token, body_field(b, "token", str))),
    ("POST", r"/v1/telegram/link", lambda q, b: _telegram(telegram.new_link)),
    ("POST", r"/v1/telegram/disconnect", lambda q, b: telegram_disconnect()),
    ("GET", r"/v1/values/(?P<name>[A-Za-z0-9_]+)", lambda q, b, name: _vault(vault.request, name)),
    ("POST", r"/v1/values/(?P<name>[A-Za-z0-9_]+)", lambda q, b, name: _vault(vault.save, name, body_field(b, "value", str))),
    ("GET", r"/v1/sites", lambda q, b: sites.saved()),
    ("POST", r"/v1/sites/sessions", lambda q, b: _sites(sites.start, body_field(b, "url", str), b.get("account") or None)),
    ("GET", r"/v1/sites/sessions/(?P<id>[0-9a-f]+)", lambda q, b, id: _sites(sites.info, id)),
    ("POST", r"/v1/sites/sessions/(?P<id>[0-9a-f]+)/input", lambda q, b, id: _sites(sites.send_input, id, b)),
    ("POST", r"/v1/sites/sessions/(?P<id>[0-9a-f]+)/save", lambda q, b, id: _sites(sites.save, id, str(b.get("name") or ""))),
    ("POST", r"/v1/sites/sessions/(?P<id>[0-9a-f]+)/cancel", lambda q, b, id: _sites(sites.cancel, id)),
    ("POST", r"/v1/sites/(?P<site>[^/]+)/remove", lambda q, b, site: _sites(sites.remove, site)),
    ("GET", r"/v1/accounts", lambda q, b: accounts_overview()),
    ("POST", r"/v1/accounts/phone", lambda q, b: _accounts(accounts.set_phone, str(b.get("phone") or ""))),
    ("GET", r"/v1/accounts/(?P<site>[a-z0-9.-]+)", lambda q, b, site: account(site)),
    ("POST", r"/v1/accounts/(?P<site>[a-z0-9.-]+)/password", lambda q, b, site: {"password": _accounts(accounts.password, site)}),
    ("POST", r"/v1/accounts/(?P<site>[a-z0-9.-]+)/remove", lambda q, b, site: _accounts(accounts.remove, site)),
    ("POST", r"/v1/mailbox", lambda q, b: _accounts(mailbox.connect, str(b.get("address") or ""), str(b.get("imapHost") or ""),
                                                   str(b.get("password") or ""), str(b.get("user") or ""), int(b.get("imapPort") or 993),
                                                   str(b.get("security") or ""))),
    ("POST", r"/v1/mailbox/disconnect", lambda q, b: mailbox.disconnect()),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "steerable-agent/1"
    token = ""

    def _send_file(self, data: bytes, filename: str, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        plain = re.sub(r'[^\w.\- ]', "_", filename.encode("ascii", "replace").decode()) or "download"
        self.send_header("Content-Disposition", f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(filename)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send(self, status: int, payload) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method: str) -> None:
        url = urlparse(self.path)
        if method == "GET" and url.path == "/health":
            return self._send(200, {"ok": True})
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.encode(), f"Bearer {self.token}".encode()):
            return self._send(401, {"error": "Not signed in."})
        if method == "POST" and env("STEERABLE_READ_ONLY") == "1":
            # Paused, running only so the owner can download their data: nothing changes.
            return self._send(409, {"error": "Your COO is paused, so nothing can change right now. Choose a plan to start again."})
        if method == "GET" and url.path == "/v1/export":
            log_run("agent_api", "export")
            return self._send_file(export_archive(), "company.tar.gz", "application/gzip")
        if method == "POST" and url.path == "/v1/files":
            # A file the owner attaches in the chat: the raw bytes, its name in ?name=.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > files.MAX_BYTES:
                    raise files.FileError("That file is too big. Attach files up to 20 MB.")
                name = (parse_qs(url.query, keep_blank_values=True).get("name") or [""])[0]
                return self._send(200, files.save(name, self.rfile.read(length)))
            except files.FileError as e:
                return self._send(400, {"error": str(e)})
        if method == "GET" and (m := re.fullmatch(r"/v1/files/([0-9a-f]+)", url.path)):
            try:
                path = files.find(m.group(1))
            except files.FileError as e:
                return self._send(404, {"error": str(e)})
            data, info = path.read_bytes(), files.describe(path)
            self.send_response(200)
            self.send_header("Content-Type", files.content_type(path))
            self.send_header("Content-Length", str(len(data)))
            # Pictures show in the chat; everything else downloads, so nothing runs in the browser.
            how = "inline" if info["kind"] == "image" else "attachment"
            self.send_header("Content-Disposition", f"{how}; filename*=UTF-8''{quote(info['name'])}")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, max-age=86400")
            self.end_headers()
            return self.wfile.write(data)
        if method == "GET" and (m := re.fullmatch(r"/v1/traces/([\w-]{1,60})/shots/(\d{1,4}\.jpg)", url.path)):
            try:
                data = runtrace.shot_path(m.group(1), m.group(2)).read_bytes()
            except ValueError as e:
                return self._send(404, {"error": str(e)})
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, max-age=86400")
            self.end_headers()
            return self.wfile.write(data)
        if method == "GET" and (m := re.fullmatch(r"/v1/library/tables/([^/]+)/export", url.path)):
            q = parse_qs(url.query, keep_blank_values=True)
            try:
                with library.acting("you"):
                    data, name, kind = library_io.export(unquote(m.group(1)), (q.get("format") or ["csv"])[0], **_library_query(q))
            except library.LibraryError as e:
                return self._send(404 if "There's no table" in str(e) else 400, {"error": str(e)})
            except ApiError as e:
                return self._send(e.status, {"error": e.message})
            log_run("agent_api", "library_export", table=name)
            return self._send_file(data, name, kind)
        if method == "POST" and url.path == "/v1/library/import":
            q = parse_qs(url.query, keep_blank_values=True)
            arg = lambda k: (q.get(k) or [""])[0] or None  # noqa: E731
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > library_io.MAX_BYTES:
                    raise library.LibraryError("That file is too big. Import spreadsheets up to 20 MB.")
                with library.acting("you"):
                    got = library_io.import_sheet(arg("name") or "import.csv", self.rfile.read(length), arg("into"), arg("title"))
            except library.LibraryError as e:
                return self._send(404 if "There's no table" in str(e) else 400, {"error": str(e)})
            log_run("agent_api", "library_import", table=got["table"]["name"], rows=got["added"])
            return self._send(200, got)
        if method == "GET" and (m := re.fullmatch(r"/v1/sites/sessions/([0-9a-f]+)/frame", url.path)):
            try:
                image = _sites(sites.frame, m.group(1))
            except ApiError as e:
                return self._send(e.status, {"error": e.message})
            except Exception:
                return self._send(503, {"error": "The page isn't ready."})
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(image)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(image)
        try:
            body = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                # A site's cookies (from the browser extension) can be a few hundred kilobytes.
                if length > (1_500_000 if url.path == "/v1/extension/logins" else 64_000):
                    raise ApiError(413, "That's too long.")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ApiError(400, "Expected a JSON object.")
            for verb, pattern, fn in ROUTES:
                if verb == method and (m := re.fullmatch(pattern, url.path)):
                    params = {k: unquote(v) for k, v in m.groupdict().items()}
                    result = fn(parse_qs(url.query, keep_blank_values=True), body, **params)
                    return self._send(200, result if result is not None else {"ok": True})
            raise ApiError(404, "Not found.")
        except ApiError as e:
            return self._send(e.status, {"error": e.message})
        except (json.JSONDecodeError, ValueError):
            return self._send(400, {"error": "That request didn't make sense."})
        except Exception as e:
            log_run("agent_api", "error", path=url.path, error=repr(e)[:500])
            return self._send(500, {"error": "Something went wrong on my side. It's logged."})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def log_message(self, fmt: str, *args) -> None:
        if env("AGENT_API_DEBUG"):
            super().log_message(fmt, *args)


def main() -> None:
    token = env("AGENT_API_TOKEN")
    if len(token) < 32:
        sys.exit("Set AGENT_API_TOKEN in .env (32+ characters) before starting the agent API.")
    Handler.token = token
    host, port = env("AGENT_API_HOST", "127.0.0.1"), int(env("AGENT_API_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Agent API for {COMPANY} on http://{host}:{port}")
    log_run("agent_api", "started", host=host, port=port)
    server.serve_forever()


if __name__ == "__main__":
    main()
