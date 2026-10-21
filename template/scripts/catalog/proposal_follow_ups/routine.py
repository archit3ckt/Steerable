"""Proposals and quotes the owner sent by Gmail that got no answer: a nudge after a few days, and a second one
later, kept as drafts for the owner (or sent, if they said so).

Goal:    no proposal goes quiet for want of a follow-up
Metric:  proposals nudged, and answers after a nudge
Task:    - [ ] Follow up on proposals that got no answer  @workflow:<name>  every:weekdays

A sent email is a proposal when its subject or text has one of WORDS, or it carries a PDF. Once anyone
answers in the thread it's left alone, and marked answered.
"""
import base64
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import library  # noqa: E402
from common import act, each, save_draft, step, tell_owner  # noqa: E402
from integrations import call  # noqa: E402

SETTINGS = {
    "WORDS": ["proposal", "quote", "estimate", "scope of work", "pricing", "engagement letter"],
    "NUDGE_AFTER_DAYS": [3, 10],
    "LOOK_BACK_DAYS": 45,
    "SKIP": [],  # like ["partner.com", "anna@ourfirm.com"]
    "MESSAGES": [
        "Hi {name},\n\nI wanted to check you got the proposal for \"{subject}\". Happy to walk you through it or "
        "adjust anything.\n\nThanks",
        "Hi {name},\n\nFollowing up once more on \"{subject}\". If the timing isn't right, just say so and I'll "
        "check back later.\n\nThanks",
    ],
    "SEND": False,
}

DRY_RUN = os.environ.get("STEERABLE_DRY_RUN") == "1"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_THREADS = 200
NO_REPLY = re.compile(r"no-?reply|do-?not-?reply|notifications?@|mailer-daemon", re.I)
PROPOSALS = library.table(
    "Proposals",
    columns="To:text, Subject:text, Sent:date, Nudges:number, Last nudge:date, "
            "Status:status(Waiting|Nudged|Answered|Check this)",
    description="Proposals and quotes sent by email, and the nudges the business manager wrote for them")


def header(message: dict, name: str) -> str:
    return next((h["value"] for h in message.get("payload", {}).get("headers", []) if h["name"].lower() == name.lower()), "")


def days_since(message: dict) -> float:
    return (time.time() * 1000 - int(message.get("internalDate") or 0)) / 86_400_000


def thread(tid: str) -> list[dict]:
    t = call("google", "GET", f"{GMAIL}/threads/{tid}",
             params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Message-ID"]})
    return sorted(t.get("messages") or [], key=lambda m: int(m.get("internalDate") or 0))


def sent(message: dict) -> bool:
    return "SENT" in (message.get("labelIds") or [])


def skipped(address: str, me: str) -> bool:
    a = address.lower()
    return a == me or bool(NO_REPLY.search(a)) or any(s.lower() in (a, a.split("@")[-1]) for s in SETTINGS["SKIP"])


def proposals(me: str) -> list[dict]:
    """Threads that start from a proposal of the owner's, with what's happened since."""
    words = " OR ".join(f'"{w}"' for w in SETTINGS["WORDS"])
    query = f"in:sent newer_than:{SETTINGS['LOOK_BACK_DAYS']}d ({words} OR filename:pdf)"
    found, token = [], None
    while len(found) < MAX_THREADS:
        page = call("google", "GET", f"{GMAIL}/threads",
                    params={"q": query, "maxResults": 100, **({"pageToken": token} if token else {})})
        for t in page.get("threads") or []:
            messages = thread(t["id"])
            first = next((m for m in messages if sent(m)), None)
            if not first:
                continue
            to = [a for _, a in getaddresses([header(first, "To")]) if a]
            if not to or skipped(to[0], me):
                continue
            after = messages[messages.index(first) + 1:]
            found.append({"thread": t["id"], "first": first, "last": messages[-1], "to": header(first, "To"),
                          "address": to[0], "answered": any(not sent(m) for m in after),
                          "subject": re.sub(r"^(re|fwd?):\s*", "", header(first, "Subject"), flags=re.I) or "(no subject)"})
        token = page.get("nextPageToken")
        if not token:
            break
    return found


def first_name(to: str) -> str:
    name, addr = parseaddr(to.split(",")[0])
    return (name.split()[0] if name else addr.split("@")[0]).strip("\"'") or "there"


def send(item: dict, text: str, me: str) -> None:
    mail = EmailMessage()
    mail["To"], mail["From"], mail["Subject"] = item["to"], me, f"Re: {item['subject']}"
    if message_id := header(item["last"], "Message-ID"):
        mail["In-Reply-To"] = mail["References"] = message_id
    mail.set_content(text)
    raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
    call("google", "POST", f"{GMAIL}/messages/send", json={"raw": raw, "threadId": item["thread"]})


def main() -> None:
    me = (call("google", "GET", f"{GMAIL}/profile").get("emailAddress") or "").lower()
    today = datetime.now(timezone.utc).date().isoformat()
    step(1)
    found = proposals(me)

    step(2, items=found)
    due, answered = [], []
    for p in each(found):
        row = PROPOSALS.get(p["thread"])
        if p["answered"]:
            if row and row["cells"].get("Status") in ("Waiting", "Nudged"):
                PROPOSALS.update(row["id"], {"Status": "Answered"})
                answered.append(p["to"])
            continue
        nudges = int((row or {"cells": {}})["cells"].get("Nudges") or 0)
        if nudges >= len(SETTINGS["NUDGE_AFTER_DAYS"]):
            continue
        # Due when the proposal is old enough for this nudge, the owner hasn't just written themselves, and the
        # last nudge (sent or only drafted: a draft never shows in Gmail) was long enough ago.
        after = SETTINGS["NUDGE_AFTER_DAYS"]
        gap = max(2, after[nudges] - after[nudges - 1]) if nudges else 0
        last_nudge = (row or {"cells": {}})["cells"].get("Last nudge")
        rested = not last_nudge or (datetime.now(timezone.utc).date() - datetime.fromisoformat(last_nudge).date()).days >= gap
        if days_since(p["first"]) >= after[nudges] and days_since(p["last"]) >= 2 and rested:
            due.append({**p, "nudges": nudges})

    step(3, items=due)
    drafted, sent_now = [], []
    for p in each(due):
        text = SETTINGS["MESSAGES"][min(p["nudges"], len(SETTINGS["MESSAGES"]) - 1)].format(
            name=first_name(p["to"]), subject=p["subject"])
        cells = {"To": p["to"], "Subject": p["subject"],
                 "Sent": datetime.fromtimestamp(int(p["first"]["internalDate"]) / 1000, timezone.utc).date().isoformat(),
                 "Nudges": p["nudges"] + 1, "Last nudge": today, "Status": "Nudged"}
        said = f"{p['to']}: “{p['subject']}” (nudge {p['nudges'] + 1})"
        if SETTINGS["SEND"] and act(f"Send {p['address']} a nudge about the proposal “{p['subject']}”",
                                    {"to": p["address"], "thread": p["thread"], "text": text}, kind="send"):
            send(p, text, me)
            sent_now.append(said)
        else:
            save_draft(f"proposal-{p['thread']}", f"To: {p['to']}\nSubject: Re: {p['subject']}\n\n{text}\n")
            drafted.append(said)
        PROPOSALS.add(cells, key=p["thread"], overwrite=True)

    step(4, items=len(sent_now) + len(drafted) + len(answered))
    lines = []
    if sent_now:
        lines.append(f"**Nudged {len(sent_now)} proposal{'s' if len(sent_now) != 1 else ''} with no answer:**")
        lines += [f"- {s}" for s in sent_now]
    if drafted:
        lines.append(f"**{len(drafted)} proposal{'s' if len(drafted) != 1 else ''} with no answer yet.** I wrote a "
                     "nudge for each; send them as they are or change them first:")
        lines += [f"- {d}" for d in drafted]
    if answered:
        lines.append(f"Answered since: {', '.join(answered)}.")
    if lines:
        tell_owner("\n".join(lines))
    n = len(sent_now) + len(drafted)
    if not n:
        print("No proposals waiting on a nudge")
    else:
        verb = "Would nudge" if DRY_RUN else ("Nudged" if sent_now and not drafted else "Wrote nudges for")
        print(f"{verb} {n} proposal{'s' if n != 1 else ''} with no answer")


if __name__ == "__main__":
    main()
