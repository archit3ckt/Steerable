"""After a client call: the owner's notes from it become a short recap email for the client and action items.

Goal:    every call ends with a clear written recap, sent the same day
Metric:  calls recapped
Task:    - [ ] Write a recap after each client call  @workflow:<name>  every:3h

The notes come from the library table "Call notes": the owner adds a row after a call (client, their email,
the date, the notes), or asks the business manager to. A row whose Recap is "To do" gets a recap; the email
is kept as a draft unless the owner said to send it, and the action items go to the table "Action items".
"""
import base64
import os
import re
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import agent  # noqa: E402
import library  # noqa: E402
from budget import BudgetExceeded, check  # noqa: E402
from common import act, each, save_draft, step, tell_owner  # noqa: E402
from integrations import call  # noqa: E402

SETTINGS = {
    "TONE": "warm, clear and brief",
    "SIGN_OFF": "Thanks",
    "SEND": False,
    "MAX_PER_RUN": 10,
}

DRY_RUN = os.environ.get("STEERABLE_DRY_RUN") == "1"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
NOTES = library.table(
    "Call notes",
    columns="Client:text, Email:text, Date:date, Notes:longtext, Recap:status(To do|Drafted|Sent|Skipped)",
    description="Notes from client calls; each one waiting is turned into a recap email and action items")
ACTIONS = library.table(
    "Action items",
    columns="What:text, Client:text, Who:status(You|Client), Due:date, Status:status(Open|Done)",
    description="What was agreed on calls, and who does it")

SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "the email's subject, short"},
        "email": {"type": "string", "description": "the recap email's text, from greeting to sign-off"},
        "actions": {"type": "array", "items": {
            "type": "object",
            "properties": {"what": {"type": "string", "description": "one thing to do, starting with a verb"},
                           "who": {"type": "string", "enum": ["You", "Client"]},
                           "due": {"type": "string", "description": "YYYY-MM-DD if a date was agreed, else empty"}},
            "required": ["what", "who", "due"], "additionalProperties": False}},
    },
    "required": ["subject", "email", "actions"],
    "additionalProperties": False,
}

PROMPT = """You write the recap email a consultant sends a client after a call, from the consultant's own notes.

Client: {client}
Date of the call: {date}
The consultant's notes:
<notes>
{notes}
</notes>

Write it {tone}. Thank them briefly, sum up what was discussed and decided in a few short lines, then list
the next steps with who does each and by when (only dates the notes give). Nothing the notes don't say: no
promises, prices or dates of your own. Sign off with "{sign_off}" and no name. Also list the action items:
"You" for the consultant's, "Client" for the client's."""


def recap(row: dict) -> dict | None:
    c = row["cells"]
    try:
        check()
    except BudgetExceeded:
        return None
    out = agent.complete(PROMPT.format(client=c.get("Client") or "the client", date=c.get("Date") or "recently",
                                       notes=(c.get("Notes") or "")[:8000], tone=SETTINGS["TONE"],
                                       sign_off=SETTINGS["SIGN_OFF"]),
                         source="call_recaps", tier="smart", schema=SCHEMA, max_tokens=1500, budget_usd="0.10")
    return out if isinstance(out, dict) and out.get("email") else None


def send(to: str, subject: str, text: str) -> None:
    mail = EmailMessage()
    mail["To"], mail["Subject"] = to, subject
    mail.set_content(text)
    call("google", "POST", f"{GMAIL}/messages/send",
         json={"raw": base64.urlsafe_b64encode(mail.as_bytes()).decode()})


def main() -> None:
    step(1)
    waiting = [r for r in NOTES.rows(where={"Recap": "To do"}, limit=200) if (r["cells"].get("Notes") or "").strip()]
    waiting = waiting[:SETTINGS["MAX_PER_RUN"]]

    step(2, items=waiting)
    done = []
    for row in each(waiting):
        r = recap(row)
        if r:
            done.append((row, r))

    step(3, items=sum(len(r["actions"]) for _, r in done))
    for row, r in done:
        for n, a in enumerate(r["actions"]):
            due = a.get("due") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.get("due") or "") else None
            ACTIONS.add({"What": a["what"][:1000], "Client": row["cells"].get("Client") or "", "Who": a["who"],
                         **({"Due": due} if due else {})}, key=f"{row['id']}:{n}")

    step(4, items=done)
    drafted, sent = [], []
    for row, r in done:
        c = row["cells"]
        who = c.get("Client") or c.get("Email") or "the client"
        if SETTINGS["SEND"] and c.get("Email") and act(
                f"Send {c['Email']} the recap of your call on {c.get('Date') or 'recently'}",
                {"to": c["Email"], "subject": r["subject"], "text": r["email"]}, kind="send"):
            send(c["Email"], r["subject"], r["email"])
            NOTES.update(row["id"], {"Recap": "Sent"})
            sent.append(who)
        else:
            save_draft(f"recap-{row['id']}", f"To: {c.get('Email') or ''}\nSubject: {r['subject']}\n\n{r['email']}\n")
            NOTES.update(row["id"], {"Recap": "Drafted"})
            drafted.append(who)

    step(5, items=len(done))
    lines = []
    if sent:
        lines.append(f"**Sent the recap of your call to {', '.join(sent)}.**")
    if drafted:
        lines.append(f"**Recaps ready for your calls with {', '.join(drafted)}.** Send them as they are or change "
                     "them first.")
    if done:
        n = sum(len(r["actions"]) for _, r in done)
        lines.append(f"{n} action item{'s' if n != 1 else ''} added to your library.")
        tell_owner("\n".join(lines))
    print(f"{'Would recap' if DRY_RUN else 'Recapped'} {len(done)} call{'s' if len(done) != 1 else ''}" if done
          else "No calls waiting for a recap")


if __name__ == "__main__":
    main()
