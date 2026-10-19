"""Telegram bridge: the owner's two-way channel with Claude. Runs as a systemd user service.

Long-polls Telegram, which costs nothing while idle.
- Approve/Reject buttons edit tasks.md directly. No model.
- Incident buttons (Apply fix, Discard, run a prepared action) call incident.py. No model.
  "Discuss" switches the chat into that incident's Claude session.
- /status and /brief run the scripts. No model.
- Any other text goes to headless Claude Code (Sonnet), resuming one ongoing
  partner session, so the thread keeps its context. /new starts a fresh session.
  Each message is budget-checked, capped per call, and logged to spend.
The web app (through scripts/agent_api.py) shares the same session and chat log
(logs/chat.jsonl), so the owner sees one conversation wherever they talk.
"""
import fcntl
import json
import re
import subprocess
import time
from datetime import date

import agent
import builder
import files
import guard
import incident
import telegram
from brief import build, task_id
from budget import BudgetExceeded, check, record
from common import (CACHE, COMPANY, LOGS, ROOT, counts_words, edit_tasks, env, finish_onboarding, library_counts, log_run,
                    new_run_id, now_iso, task_title)
from ops_db import record_event, settle_approval

PER_MESSAGE_CAP_USD = "0.50"
# The chat reads untrusted text all day (emails, web pages), so it gets the least it needs.
# It writes only its own space: its memory, its skills, drafts, and its instructions. The
# system's files (databases, logs, settings, credentials, installed packages, the owner's
# attachments, engine code, routines, the task list) are denied outright. It runs only the
# scripts listed here, each for what it's for. Anything else is refused (approvals.py turns
# down every non-MCP tool no rule allows), never put to the owner as a decision.
# Claude Code applies Edit(...) rules to all file-writing tools, Write included.
PY = ".venv/bin/python scripts/"
CHAT_SCRIPTS = ["propose.py *", "change.py *", "run.py *", "ask.py *", "library.py *", "social.py *", "status.py", "status.py *", "decide.py *",
                "ops_db.py --show", "ops_db.py --seed", "ops_db.py --seed --show", "ops_db.py mission *", "ops_db.py goal *",
                "ops_db.py add-mission *", "vault.py ask *", "accounts.py propose *", "accounts.py list", "integrations.py",
                "mailbox.py *", "brief.py", "skills.py list", "files.py list", "state.py show *",
                "books.py list", "books.py search *", "reddit.py *", "plans.py *", "dashboards.py *"]
OWN_SPACE = ["./memory/**", "./.claude/skills/**", "./drafts/**", "./CLAUDE.md"]
ALLOWED_TOOLS = ["Read(./**)", "Glob", "Grep", "WebSearch", "WebFetch",
                 *(f"{tool}({path})" for path in OWN_SPACE for tool in ("Edit", "Write")),
                 *(f"Bash({PY}{s})" for s in CHAT_SCRIPTS),
                 "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)"]
SYSTEM = ["./.env", "./.env.*", "./.cache/**", "./.home/**", "./.git/**", "./.venv/**", "./*.db", "./*.db-*",
          "./logs/**", "./files/**", "./books/**", "./scripts/**", "./workflows/**", "./tasks.md", "./.claude/settings*.json",
          "./.claude/skills/.registry.json", "./requirements.txt", "./.gitignore"]
DENIED_TOOLS = ["Read(./.env)", "Read(./.env.*)", "Read(./.cache/**)", "Read(./.home/**)",
                *(f"{tool}({path})" for path in SYSTEM for tool in ("Edit", "Write"))]
CHAT_LOG = LOGS / "chat.jsonl"
LIVE = CACHE / "chat_live.jsonl"  # Claude's events while it works on a reply, for the app to follow
APP = "the Steerable app"  # the channel name the agent API uses

APP_NOTES = (
    " The owner uses the Steerable web app, not a terminal or Telegram: its chat is where you talk, "
    "and its Today, Decisions, Timeline, Work and Goals pages show tasks.md, ops.db and logs/ in plain "
    "words. Don't mention files, scripts or commands to them. To propose a routine, run "
    ".venv/bin/python scripts/propose.py; it appears in their Decisions and waits for their approval. "
    "To change a routine that's already running (what it does, how it reports, its schedule), run "
    ".venv/bin/python scripts/change.py <routine> \"what to change\" --why \"...\": it waits for their OK in Decisions. "
    "Routines can run daily, weekly, every 1 to 12 hours (--every 3h), or at set times each day "
    "(--at 08:00,13:00,18:00); to change a proposal they haven't approved yet, propose again with --replace. "
    "If they want a routine to run now, run .venv/bin/python scripts/run.py <routine id>: it runs once, "
    "as its schedule would, and the schedule stays as it was. "
    "To post to their social accounts, use .venv/bin/python scripts/social.py (see CLAUDE.md): it waits for their OK in Decisions. "
    "Records they'd want to look up (leads, orders, job openings) go in the library: .venv/bin/python scripts/library.py "
    "(each table can have views the owner sees as tabs: library.py view <table> <name> --type kanban|calendar|grid). "
    "Books the owner taught you are searchable: .venv/bin/python scripts/books.py search \"<words>\" (cite the book and chapter). "
    "Small choices that are easy to undo (a format, an order, a time, which of two similar options, a working detail) are yours: "
    "decide them, mention them in passing if at all, and get on with it; don't ask. "
    "To put a bigger choice to them (money, people outside the business, anything hard to undo), run "
    ".venv/bin/python scripts/ask.py with options and your pick. If it answers that it's settled, the owner lets you decide "
    "things like that: go with it, and say so in a few words. "
    "If you need an account of your own on a site, propose it with .venv/bin/python scripts/accounts.py propose "
    "(see CLAUDE.md); never ask them in chat for a code sent to their phone. "
    "Tools from their connected services that change something (send, create, refund, delete) go to "
    "them in Decisions first, unless they chose to always allow that tool; when a tool says it's "
    "waiting for their OK, tell them in a sentence and don't retry it. Before advising them on running the business (money, pricing, getting paid, sales, marketing, customers, hiring, operations, planning), check Steerable playbooks with the mcp__steerable tools and follow them, adapted to this company. AI is included in their plan "
    "up to a monthly limit: don't quote AI costs in dollars; if something is heavy, say it uses more "
    "of this month's included work."
    " Never ask the owner to edit files, .env or settings, run commands, or paste secrets in chat: they're not technical. If you need something only they have (a private link, an API key, an account number), run .venv/bin/python scripts/vault.py ask NAME --label \"<what it is, in their words>\" --why \"<one sentence>\" --url <where they find it>; it appears in their Decisions with a one-step form, and routines read it with env(NAME). For a service or website login, ask for the connection instead. Then tell them in one sentence that it's in Decisions, and get on with the rest."
    " To change how a routine works (a bug you found, or something the owner wants done differently), run .venv/bin/python scripts/change.py <routine id> \"<what should change>\" --why \"<why>\": it waits for the owner's OK in Decisions, then I change it, test it and check it before switching. Don't ask the owner to start it."
)


# The app shows these while the owner waits (live_steps), so they know what's happening and why.
SAY_AS_YOU_GO = (
    " The owner sees what you're doing while they wait. Before you look something up or take a step, say "
    "in one short, friendly sentence what you're about to do and why, in their words (\"Let me check last "
    "month's orders first.\"). No file names, commands or jargon, and nothing they'd need to answer: "
    "questions go in your reply."
)


def system_prompt(channel: str) -> str:
    style = ("The app shows Markdown, so use it where it helps (bold, short lists, a small table to "
             "compare), but keep it light: no headings for short answers. When you give them words to copy and paste "
             "(an email, a post, a reply), put them in a ```text block: the app shows it with a Copy button. Code or "
             "settings go in a fenced block with its language." if channel == APP
             else "Reply in plain text (no markdown tables).")
    return (
        f"You are talking to the owner of {COMPANY} through {channel}, as their operations partner. "
        f"{style} Keep replies bite-size, under 800 characters unless asked "
        "for more. Lead with the answer. Give a recommendation when there's a choice. "
        "Follow CLAUDE.md rules: never spend money, contact customers, publish, or delete data "
        "without explicit approval in this chat. Update memory/ after meaningful decisions."
        + (APP_NOTES + SAY_AS_YOU_GO if channel == APP else "")
    )


def _log_chat(sender: str, text: str, steps: list | None = None, attached: list | None = None,
              artifacts: dict | None = None) -> None:
    entry = {"ts": now_iso(), "from": sender, "text": text}
    if steps:
        entry["steps"] = steps
    if artifacts:
        entry["artifacts"] = artifacts
    if attached:
        entry["files"] = [{k: a[k] for k in ("id", "name", "kind", "size")} for a in attached]
    with CHAT_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------- what the COO is doing, in the owner's words ----------

PLACES = [("memory/", "your notes"), ("tasks.md", "the task list"), ("CLAUDE.md", "my instructions"),
          ("workflows/", "your routines"), ("logs/", "the activity log"), ("ops.db", "the activity log")]
SCRIPTS = {"propose.py": "Drafting a routine for your approval", "ask.py": "Putting a decision to you",
           "status.py": "Checking how everything is running", "brief.py": "Putting together your brief"}


def _place(path: str) -> str:
    rel = path.split(str(ROOT) + "/", 1)[-1] if path else ""
    for prefix, words in PLACES:
        if rel.startswith(prefix):
            return words
    return rel.rsplit("/", 1)[-1] or "a file"


def _words(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").strip()


def step_label(tool: str, args: dict) -> str | None:
    """One line about a tool call, like Claude Code shows it, but for a non-technical owner."""
    if tool == "Read":
        return f"Reading {_place(args.get('file_path', ''))}"
    if tool in ("Edit", "Write", "MultiEdit"):
        place = _place(args.get("file_path", ""))
        return "Saving this to memory" if place == "your notes" else f"Updating {place}"
    if tool in ("Grep", "Glob"):
        what = args.get("pattern", "")
        return f"Searching your files for \u201c{what[:60]}\u201d" if tool == "Grep" and what else "Looking through your files"
    if tool == "WebSearch":
        return f"Searching the web for \u201c{args.get('query', '')[:80]}\u201d"
    if tool == "WebFetch":
        host = re.sub(r"^https?://(www\.)?", "", args.get("url", "")).split("/", 1)[0]
        return f"Reading {host}" if host else "Reading a web page"
    if tool == "Bash":
        cmd = args.get("command", "")
        script = re.search(r"scripts/(\w+\.py)", cmd)
        if script:
            return SCRIPTS.get(script.group(1), "Running one of my tools")
        return "Checking recent changes" if cmd.startswith("git") else "Checking the schedule" if "crontab" in cmd else "Running a command"
    if tool in ("Task", "Agent"):
        return f"Working on it in the background: {args.get('description', 'a side task')}"
    if tool == "TodoWrite":
        return "Planning the steps"
    if tool.startswith("mcp__"):
        _, server, name = (tool.split("__", 2) + ["", ""])[:3]
        if server == "steerable":
            return "Checking Steerable playbooks"
        if server == "approvals":
            return None
        service = _words(re.sub(r"^claude_ai_", "", server)).title()
        return f"Using {service}: {_words(name)}" if name else f"Using {service}"
    return f"Using {_words(tool)}"


def _remark(text: str) -> str | None:
    """What the COO said in passing, as one plain line: no Markdown marks, not too long."""
    text = re.sub(r"[*_`#>]+", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text if len(text) <= 220 else text[:217].rsplit(" ", 1)[0] + "…"


def live_steps(path=LIVE, label=None) -> list:
    """What the COO has done so far in the reply it's working on (a stream-json log), in order:
    a string for each thing it did ("Reading your notes"), and {"say": "..."} for what it said
    on the way ("Let me check last month's orders first."). Something it said counts only once it
    goes on to do something: its last words are the reply itself, not a remark."""
    steps: list = []
    said: str | None = None  # waiting to see whether a step follows
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return steps
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # the last line may be half-written
        if not isinstance(event, dict) or event.get("type") != "assistant" or event.get("parent_tool_use_id"):
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                said = _remark(block.get("text", "")) or said
            elif block.get("type") == "tool_use":
                words = (label or step_label)(block.get("name", ""), block.get("input") or {})
                if not words:
                    continue
                if said and {"say": said} not in steps[-2:]:
                    steps.append({"say": said})
                said = None
                if not steps or steps[-1] != words:
                    steps.append(words)
    return steps


DIVIDER = "divider"  # a chat-log entry "from" nobody: where a new conversation starts


class Busy(RuntimeError):
    """The COO is in the middle of a reply."""


def new_conversation() -> bool:
    """Start a fresh conversation, from the app's button or Telegram's /new: the COO forgets the
    thread so far (not the business: that's in memory/), and the history stays, with a divider.
    False if there was nothing to start over from. Raises Busy while a reply is being written."""
    with (CACHE / "chat.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy() from None
        st = telegram.state()
        had_session = st.pop("session_id", None) is not None
        telegram.save_state(st)
        last = None
        if CHAT_LOG.exists():
            lines = CHAT_LOG.read_text().splitlines()
            last = json.loads(lines[-1]) if lines else None
        if not last or last.get("from") == DIVIDER:
            return had_session  # an empty history, or already at a fresh start: no second divider
        _log_chat(DIVIDER, "")
        return True


def converse(text: str, channel: str = "Telegram", show_prompt: bool = True, attached: list | None = None) -> str:
    """One turn with the COO from any channel: log the owner's message, ask Claude in the
    shared session, log the reply. The lock stops two channels using the session at once.
    show_prompt=False sends a prompt the owner didn't type (like the onboarding kickoff)
    without showing it in the conversation. `attached`: files.save() results, named to the COO."""
    if show_prompt:
        _log_chat("you", text, attached=attached)
    with (CACHE / "chat.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run = new_run_id()  # what the turn changes in the library is kept under it
        try:
            reply = ask_claude((text or "(no message, just the files)") + files.for_prompt(attached or []), channel,
                               live=LIVE, run=run)
            steps = live_steps()
        finally:
            LIVE.unlink(missing_ok=True)
            try:  # what the turn changed in its own notes: checked, and committed so it can be undone
                guard.check_and_commit("chat")
            except Exception as e:  # noqa: BLE001 - never break the chat over it
                log_run("guard", "error", error=repr(e)[:300])
            changes, saved = library_counts(run), []
            if changes:
                log_run("bridge", "library", run=run, changes=changes)
                record_event(f"Updated the library: {counts_words(changes)}", who="COO", ref=run)
            try:
                import plans

                saved = plans.run_plans(run)
            except Exception as e:  # noqa: BLE001 - never break the chat over it
                log_run("bridge", "error", error=repr(e)[:300])
    # Does the reply propose something worth testing before the owner acts on it? One Jev call (checks.py).
    check = None
    if channel == APP and show_prompt and text:
        import checks

        check = checks.offer(text, reply, saved)
    # What the turn made or changed in the library, shown with the reply (the chat's "artifacts").
    artifacts = {"run": run, **({"changes": changes} if changes else {}), **({"plans": saved} if saved else {}),
                 **({"check": check} if check else {})}
    _log_chat("coo", reply, steps, artifacts=artifacts if changes or saved or check else None)
    if show_prompt and text:
        # Did this turn finish a project on the Goals page? A cheap check (Jev), in the background.
        import threading

        from ops_db import notice_done

        threading.Thread(target=notice_done, args=(text, reply), daemon=True).start()
    return reply


def ask_claude(text: str, channel: str = "Telegram", live=None, run: str | None = None) -> str:
    """One turn in the shared session. With `live`, Claude's events are written to that file
    as they happen, so the app can show what it's doing."""
    try:
        check()
    except BudgetExceeded as e:
        return f"I can't think right now. {e}"
    st = telegram.state()
    # The owner's connected services, as MCP tools. Calls no rule allows go to approvals.py,
    # which runs reads and puts changes in the owner's Decisions. "default" so that nothing
    # else (like auto mode's classifier) approves them instead.
    out = agent.run(text, budget_usd=PER_MESSAGE_CAP_USD, system=system_prompt(channel), permission_mode="default",
                    mcp="live", allow=ALLOWED_TOOLS, deny=DENIED_TOOLS, resume=st.get("session_id"),
                    live=live, timeout=900, extra_env={"STEERABLE_RUN": run} if run else None)
    if not out.ok:
        log_run("bridge", "error", stderr=out.stderr[-1000:])
        return "Something went wrong on my side. It's logged, and I'll check it in the next session."
    record("telegram-chat", out.cost, model=out.model, note=text[:60])
    st["session_id"] = out.session_id or st.get("session_id")
    telegram.save_state(st)
    log_run("bridge", "error" if out.is_error else "ok", cost_usd=out.cost,
            session=st["session_id"])
    return out.text or "(no reply)"


def set_approval(tid: str, approve: bool) -> str | None:
    """Approve or reject a task waiting on needs:approval (Telegram buttons, the CLI and the
    agent API all land here). Returns the task text, or None if it's no longer waiting."""
    found: list[str] = []

    def change(lines: list[str]) -> list[str]:
        for i, line in enumerate(lines):
            if line.startswith("- [ ]") and "needs:approval" in line and task_id(line) == tid:
                found.append(line[6:])
                if approve:
                    lines[i] = line.replace("needs:approval", "approved")
                else:
                    lines[i] = (line.replace("- [ ]", "- [x]", 1).replace("needs:approval", "")
                                .rstrip() + f"  rejected:{date.today()}")
                break
        return lines

    edit_tasks(change)
    if not found:
        return None
    if approve:
        finish_onboarding()  # a first routine approved: the last step of onboarding, whether or not the COO did it
    text = found[0]
    log_run("bridge", "approved" if approve else "rejected", task=text)
    workflow = m.group(1) if (m := re.search(r"@workflow:(\S+)", text)) else None
    if workflow:
        settle_approval(workflow, approve)
        if approve:
            builder.start_build(workflow, text.replace("needs:approval", "approved"))  # no-op if it exists
    record_event(f"You decided: {'Start it' if approve else 'Not now'}. ({task_title(text)})",
                 who="CEO", workflow=workflow)
    return re.sub(r"\s+", " ", text.replace("needs:approval", "")).strip()


def _attach(messages: list[dict]) -> tuple[list[dict], list[str]]:
    """Save the photos and files in these messages (one, or an album). Returns what was saved
    and, for what wasn't, why, in plain words."""
    saved, problems = [], []
    for m in messages:
        found = telegram.attachment(m)
        if not found:
            continue
        file_id, name, size = found
        if size > files.MAX_BYTES:
            problems.append(f"{name} is too big (over 20 MB).")
            continue
        try:
            saved.append(files.save(name, telegram.download(file_id)))
        except files.FileError as e:
            problems.append(f"{name}: {e}")
        except Exception as e:  # noqa: BLE001 - Telegram or the network
            log_run("bridge", "error", step="download", error=repr(e)[:300])
            problems.append(f"I couldn't get {name} from Telegram. Send it again?")
    return saved, problems


def handle_message(msg: dict, album: list[dict] | None = None) -> None:
    """One message from Telegram, or an album: photos sent together arrive as several messages
    sharing a media_group_id, handed over here as one, so they get one answer."""
    group = [msg, *(album or [])]
    chat = msg["chat"]
    text = next(((m.get("text") or m.get("caption") or "").strip() for m in group if m.get("text") or m.get("caption")), "")
    st = telegram.state()
    if not st.get("chat_id"):
        # Only the chat that opens the owner's one-time link (t.me/<bot>?start=<code>) is bound.
        if chat["type"] == "private" and text.startswith("/start"):
            if telegram.claim(text[len("/start"):].strip(), chat["id"]):
                log_run("bridge", "bound", chat_id=chat["id"])
                telegram.send(f"Hi, it's your {COMPANY} COO 👋\n"
                              "You'll get a short brief every morning, and anything that needs you. Just text me anytime.\n"
                              "/brief: today's brief · /status: health check · /new: fresh topic")
            else:
                telegram.send_to(chat["id"], "To connect, open the Telegram link on your Steerable dashboard "
                                             "(Connections). Links work once, for 30 minutes.")
        return
    if chat["id"] != st["chat_id"]:
        return
    if any(telegram.attachment(m) for m in group):
        telegram.typing()
        saved, problems = _attach(group)
        if problems:
            telegram.send("\n".join(problems))
        if saved or text:
            telegram.send(converse(text, attached=saved))
        return
    if not text:
        return
    if text == "/status":
        out = subprocess.run([".venv/bin/python", "scripts/status.py"], cwd=ROOT,
                             capture_output=True, text=True).stdout
        telegram.send(out or "No status output.")
    elif text == "/brief":
        body, buttons = build()
        telegram.send(body, buttons)
    elif text == "/new":
        try:
            new_conversation()
            telegram.send("Fresh start. What's on your mind?")
        except Busy:
            telegram.send("I'm still answering your last message. Try /new again in a moment.")
    else:
        telegram.typing()
        telegram.send(converse(text))


def handle_incident_button(cb: dict, data: str) -> None:
    kind, iid, *rest = data.split(":")
    inc = incident.load().get(iid)
    if not inc:
        telegram.answer_callback(cb["id"], "Unknown incident")
        return
    if kind == "ds":
        st = telegram.state()
        st["session_id"] = inc.get("session_id") or st.get("session_id")
        telegram.save_state(st)
        telegram.answer_callback(cb["id"])
        telegram.send("I'm in that incident's context now. Ask away. (/new to leave it)")
        return
    if inc["status"] == "resolved" and kind != "ac":
        telegram.answer_callback(cb["id"], "Already handled")
        return
    telegram.answer_callback(cb["id"], "On it…")
    if kind == "fx":
        result = incident.apply_fix(iid)
    elif kind == "fd":
        result = incident.discard_fix(iid)
    else:
        n = int(rest[0])
        if n in inc.get("done_actions", []):
            result = "already done"
        else:
            result = incident.run_action(iid, n)
        actions = (inc.get("verdict") or {}).get("actions", [])
        if len(set(incident.load()[iid].get("done_actions", []))) >= len(actions):
            incident.resolve(iid, "actions done")
    telegram.send(f"{inc['summary']}: {result}")


def handle_callback(cb: dict) -> None:
    if cb["message"]["chat"]["id"] != telegram.owner_chat():
        return
    data = cb.get("data", "")
    if data[:3] in ("ap:", "rj:"):
        approve = data.startswith("ap:")
        task = set_approval(data[3:], approve)
        note = (("✅ Approved: " if approve else "❌ Rejected: ") + task) if task else "Already handled"
        telegram.answer_callback(cb["id"], note[:190])
        telegram.send(note)
    elif data[:3] in ("fx:", "fd:", "ac:", "ds:"):
        handle_incident_button(cb, data)
    else:
        telegram.answer_callback(cb["id"])


def main() -> None:
    """Long-poll while there's a bot token (from the dashboard or TELEGRAM_BOT_TOKEN). Returns
    when it's removed; the container's supervisor starts it again when one is added."""
    if not telegram.token():
        print("No Telegram bot connected; connect one on the dashboard's Connections page.")
        time.sleep(30)
        return
    bot = telegram.token()
    while telegram.token() == bot:
        offset = telegram.state().get("offset", 0)
        try:
            updates = telegram.get_updates(offset, timeout=25)
            if any((u.get("message") or {}).get("media_group_id") for u in updates):
                time.sleep(1.5)  # the rest of an album is a moment behind its first photo
                updates += telegram.get_updates(updates[-1]["update_id"] + 1, timeout=0)
            albums: dict[str, list[dict]] = {}
            for upd in updates:
                if group := (upd.get("message") or {}).get("media_group_id"):
                    albums.setdefault(group, []).append(upd["message"])
            for upd in updates:
                offset = upd["update_id"] + 1
                st = telegram.state()
                st["offset"] = offset
                telegram.save_state(st)
                if "message" in upd:
                    group = upd["message"].get("media_group_id")
                    if group and albums.get(group, [None])[0] is not upd["message"]:
                        continue  # handled with the album's first message
                    handle_message(upd["message"], albums.get(group, [])[1:] if group else None)
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
        except Exception as e:
            log_run("bridge", "error", error=repr(e))
            time.sleep(10)


if __name__ == "__main__":
    main()
