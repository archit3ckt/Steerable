"""New emails from people the owner hasn't written to before: the ones asking to work with the business become
leads in the library, each with a reply drafted for the owner (or sent, if they said so).

Goal:    every new inquiry gets a quick, warm answer
Metric:  leads found, and how fast they're answered
Task:    - [ ] Pick out new leads from my email and draft a reply  @workflow:<name>  every:3h

Whether an email is a lead is a small decision (decide.py: Jev first, cheap), asked once per email. People
the owner has emailed before are clients or contacts, not new leads, so they're left out.
"""
import base64
import os
import re
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import library  # noqa: E402
from common import act, each, save_draft, step, tell_owner  # noqa: E402
from decide import decide  # noqa: E402
from integrations import call  # noqa: E402
from state import State  # noqa: E402

SETTINGS = {
    "LOOK_BACK_HOURS": 48,
    "SKIP": [],  # like ["supplier.com", "newsletter@site.com"]
    "REPLY": "Hi {name},\n\nThanks for getting in touch about \"{subject}\". I'd be glad to help. Could we find "
             "20 minutes this week to talk it through? Let me know a few times that suit you.\n\nThanks",
    "SEND": False,
}

DRY_RUN = os.environ.get("STEERABLE_DRY_RUN") == "1"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
NO_REPLY = re.compile(r"no-?reply|do-?not-?reply|notifications?@|mailer-daemon|newsletter|news@|info@mail", re.I)
QUESTION = "Is this email from someone asking to hire the business or buy from it?"
OPTIONS = {
    "lead": "a person or company asking about working together: a project, help they need, prices, availability, a proposal",
    "not": "anything else: newsletters, sales pitches to the business, receipts, notifications, personal mail",
}
RULES = {w: "lead" for w in ("quote", "pricing", "your rates", "proposal", "work with you", "hire you", "availability",
                             "help with our", "project")}
LEADS = library.table(
    "Leads",
    columns="Name:text, Email:text, Subject:text, Received:date, Status:status(New|Replied|Not a fit)",
    description="People who wrote asking to work with the business, picked out of new email")
CHECKED = State()


def header(message: dict, name: str) -> str:
    return next((h["value"] for h in message.get("payload", {}).get("headers", []) if h["name"].lower() == name.lower()), "")


def new_emails(me: str) -> list[dict]:
    days = max(1, round(SETTINGS["LOOK_BACK_HOURS"] / 24))
    listed = call("google", "GET", f"{GMAIL}/messages", params={
        "q": f"in:inbox newer_than:{days}d -from:me -category:promotions -category:social -category:updates",
        "maxResults": 100})
    out = []
    for m in listed.get("messages") or []:
        if CHECKED.seen(f"m:{m['id']}", keep_days=30):
            continue
        full = call("google", "GET", f"{GMAIL}/messages/{m['id']}",
                    params={"format": "metadata", "metadataHeaders": ["From", "Reply-To", "Subject", "Message-ID"]})
        name, address = parseaddr(header(full, "Reply-To") or header(full, "From"))
        address = address.lower()
        domain = address.split("@")[-1]
        if (not address or address == me or NO_REPLY.search(address)
                or any(s.lower() in (address, domain) for s in SETTINGS["SKIP"])):
            continue
        out.append({"id": m["id"], "thread": full.get("threadId"), "name": name or address.split("@")[0],
                    "address": address, "subject": header(full, "Subject") or "(no subject)",
                    "message_id": header(full, "Message-ID"), "snippet": " ".join((full.get("snippet") or "").split()),
                    "received": datetime.fromtimestamp(int(full.get("internalDate") or 0) / 1000, timezone.utc).date().isoformat()})
    return out


def known(address: str) -> bool:
    """Has the owner written to them before? Then they're a client or a contact, not a new lead."""
    sent = call("google", "GET", f"{GMAIL}/messages", params={"q": f"in:sent to:{address}", "maxResults": 1})
    return bool(sent.get("messages")) or int(sent.get("resultSizeEstimate") or 0) > 0


def send(lead: dict, text: str, me: str) -> None:
    mail = EmailMessage()
    mail["To"], mail["From"], mail["Subject"] = lead["address"], me, f"Re: {lead['subject']}"
    if lead["message_id"]:
        mail["In-Reply-To"] = mail["References"] = lead["message_id"]
    mail.set_content(text)
    call("google", "POST", f"{GMAIL}/messages/send",
         json={"raw": base64.urlsafe_b64encode(mail.as_bytes()).decode(), "threadId": lead["thread"]})


def main() -> None:
    me = (call("google", "GET", f"{GMAIL}/profile").get("emailAddress") or "").lower()
    step(1)
    emails = [e for e in new_emails(me) if not known(e["address"])]

    step(2, items=emails)
    leads = []
    for e in each(emails):
        d = decide(QUESTION, OPTIONS, context=f"From: {e['name']} <{e['address']}>\nSubject: {e['subject']}\n{e['snippet'][:1500]}",
                   rules=RULES)
        if d.choice == "lead":
            leads.append(e)

    step(3, items=leads)
    for lead in leads:
        LEADS.add({"Name": lead["name"], "Email": lead["address"], "Subject": lead["subject"],
                   "Received": lead["received"]}, key=lead["id"])

    step(4, items=leads)
    replied, drafted = [], []
    for lead in leads:
        text = SETTINGS["REPLY"].format(name=lead["name"].split()[0], subject=lead["subject"])
        said = f"{lead['name']} ({lead['address']}): “{lead['subject']}”"
        if SETTINGS["SEND"] and act(f"Reply to {lead['address']} about “{lead['subject']}”",
                                    {"to": lead["address"], "text": text}, kind="send"):
            send(lead, text, me)
            LEADS.update(lead["id"], {"Status": "Replied"})
            replied.append(said)
        else:
            save_draft(f"lead-{lead['id']}", f"To: {lead['address']}\nSubject: Re: {lead['subject']}\n\n{text}\n")
            drafted.append(said)

    step(5, items=len(leads))
    if leads:
        lines = [f"**{len(leads)} new lead{'s' if len(leads) != 1 else ''}:**"] + [f"- {s}" for s in replied + drafted]
        if replied:
            lines.append("I replied to them, asking for a call.")
        if drafted:
            lines.append("I wrote a reply to each, asking for a call: send them as they are or change them first.")
        tell_owner("\n".join(lines))
    n = len(leads)
    print(f"{'Would keep' if DRY_RUN else 'Found'} {n} new lead{'s' if n != 1 else ''}" if n else "No new leads")


if __name__ == "__main__":
    main()
