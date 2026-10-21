"""Emails the owner sent from Gmail that got no reply: a short follow-up for each, kept as a draft for
the owner (or sent, if they said so).

Goal:    no lead, quote or request goes quiet because nobody followed up
Metric:  follow-ups written, and replies after one
Task:    - [ ] Follow up on emails that got no reply  @workflow:<name>  every:weekdays

A thread needs a follow-up when its last message is one the owner sent, at least WAIT_DAYS ago, to
someone not in SKIP and not a no-reply address. It's followed up once per message of the owner's
(a later email of theirs in the thread starts the wait again).
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
    "WAIT_DAYS": 3,
    "LOOK_BACK_DAYS": 21,
    "SKIP": [],  # like ["supplier.com", "anna@ourshop.com"]
    "MESSAGE": "Hi {name},\n\nJust following up on my email about \"{subject}\". Is this still of interest? "
               "Happy to answer any questions.\n\nThanks",
    "SEND": False,
}

DRY_RUN = os.environ.get("STEERABLE_DRY_RUN") == "1"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_THREADS = 200
NO_REPLY = re.compile(r"no-?reply|do-?not-?reply|notifications?@|mailer-daemon", re.I)
FOLLOW_UPS = library.table(
    "Follow-ups",
    columns="To:text, Subject:text, Sent:date, Status:status(Drafted|Sent|Replied|Check this), Thread:text",
    description="Emails that got no reply, and the follow-ups the COO wrote for them")


def header(message: dict, name: str) -> str:
    return next((h["value"] for h in message.get("payload", {}).get("headers", []) if h["name"].lower() == name.lower()), "")


def thread(tid: str) -> list[dict]:
    t = call("google", "GET", f"{GMAIL}/threads/{tid}",
             params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Message-ID"]})
    return sorted(t.get("messages") or [], key=lambda m: int(m.get("internalDate") or 0))


def skipped(addresses: list[str], me: str) -> bool:
    for addr in addresses:
        a = addr.lower()
        if a == me or NO_REPLY.search(a) or any(s.lower() in (a, a.split("@")[-1]) for s in SETTINGS["SKIP"]):
            return True
    return False


def waiting(me: str) -> list[dict]:
    """Threads whose last message is the owner's, old enough, to people worth following up."""
    found, token = [], None
    query = f"in:sent newer_than:{SETTINGS['LOOK_BACK_DAYS']}d older_than:{SETTINGS['WAIT_DAYS']}d"
    cutoff = (time.time() - SETTINGS["WAIT_DAYS"] * 86400) * 1000
    while len(found) < MAX_THREADS:
        params = {"q": query, "maxResults": 100, **({"pageToken": token} if token else {})}
        page = call("google", "GET", f"{GMAIL}/threads", params=params)
        for t in page.get("threads") or []:
            messages = thread(t["id"])
            if not messages:
                continue
            last = messages[-1]
            if "SENT" not in (last.get("labelIds") or []) or int(last.get("internalDate") or 0) > cutoff:
                continue
            to = [a for _, a in getaddresses([header(last, "To")]) if a]
            if not to or skipped(to, me):
                continue
            found.append({"thread": t["id"], "message": last["id"], "to": header(last, "To"), "address": to[0],
                          "subject": re.sub(r"^(re|fwd?):\s*", "", header(last, "Subject"), flags=re.I) or "(no subject)",
                          "message_id": header(last, "Message-ID"),
                          "sent": datetime.fromtimestamp(int(last["internalDate"]) / 1000, timezone.utc).date().isoformat()})
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
    if item["message_id"]:
        mail["In-Reply-To"] = mail["References"] = item["message_id"]
    mail.set_content(text)
    raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
    call("google", "POST", f"{GMAIL}/messages/send", json={"raw": raw, "threadId": item["thread"]})


def main() -> None:
    me = (call("google", "GET", f"{GMAIL}/profile").get("emailAddress") or "").lower()
    step(1)
    items = [i for i in waiting(me) if not FOLLOW_UPS.get(i["message"])]

    step(2, items=items)
    for item in items:
        item["text"] = SETTINGS["MESSAGE"].format(name=first_name(item["to"]), subject=item["subject"])

    step(3, items=items)
    drafted, sent = [], []
    for item in each(items):
        cells = {"To": item["to"], "Subject": item["subject"], "Sent": item["sent"], "Thread": item["thread"]}
        said = f"{item['to']}: “{item['subject']}” (sent {item['sent']})"
        if SETTINGS["SEND"] and act(f"Send {item['address']} a follow-up about “{item['subject']}”",
                                    {"to": item["address"], "thread": item["thread"], "text": item["text"]}, kind="send"):
            send(item, item["text"], me)
            sent.append(said)
            FOLLOW_UPS.add({**cells, "Status": "Sent"}, key=item["message"])
            continue
        save_draft(item["thread"], f"To: {item['to']}\nSubject: Re: {item['subject']}\n\n{item['text']}\n")
        drafted.append(said)
        FOLLOW_UPS.add({**cells, "Status": "Drafted"}, key=item["message"])

    open_rows = [r for r in FOLLOW_UPS.rows(limit=60) if r["cells"].get("Status") in ("Drafted", "Sent")]
    step(4, items=open_rows)
    replied = []
    for row in each(open_rows):
        if row["cells"].get("Status") not in ("Drafted", "Sent") or not row["cells"].get("Thread"):
            continue
        messages = thread(row["cells"]["Thread"])
        ids = [m["id"] for m in messages]
        later = messages[ids.index(row["key"]) + 1:] if row["key"] in ids else []
        if any("SENT" not in (m.get("labelIds") or []) for m in later):  # someone wrote back after it
            replied.append(row["cells"].get("To") or "")
            FOLLOW_UPS.update(row["id"], {"Status": "Replied"})

    step(5, items=len(sent) + len(drafted) + len(replied))
    lines = []
    if sent:
        lines.append(f"**Followed up on {len(sent)} email{'s' if len(sent) != 1 else ''} with no reply:**")
        lines += [f"- {s}" for s in sent]
    if drafted:
        lines.append(f"**{len(drafted)} email{'s' if len(drafted) != 1 else ''} with no reply yet.** I wrote a follow-up "
                     "for each; send them as they are or change them first:")
        lines += [f"- {d}" for d in drafted]
    if replied:
        lines.append(f"Replied since: {', '.join(replied)}.")
    if lines:
        tell_owner("\n".join(lines))
    n = len(sent) + len(drafted)
    verb = "Would follow up" if DRY_RUN else ("Followed up" if sent and not drafted else "Wrote follow-ups")
    print(f"{verb} on {n} email{'s' if n != 1 else ''} with no reply" if n else "No emails waiting on a reply")


if __name__ == "__main__":
    main()
