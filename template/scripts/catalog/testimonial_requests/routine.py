"""A week after a client pays for a piece of work (a Stripe invoice), a short request for a testimonial, kept as
a draft for the owner (or sent from their Gmail, if they said so). Each client is asked at most once in a while.

Goal:    more testimonials to win the next clients with
Metric:  requests made, and testimonials received
Task:    - [ ] Ask happy clients for a testimonial  @workflow:<name>  every:weekly

A paid invoice of at least MIN_AMOUNT, paid AFTER_DAYS to 60 days ago, leads to a request; the client's last
one counts. The owner marks what came of it in the library (Got one, Declined).
"""
import base64
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import library  # noqa: E402
from common import act, each, save_draft, step, tell_owner  # noqa: E402
from integrations import call  # noqa: E402

SETTINGS = {
    "MIN_AMOUNT": 500,
    "AFTER_DAYS": 7,
    "ASK_EVERY_DAYS": 180,
    "SKIP": [],  # like ["bigcorp.com"]
    "MESSAGE": "Hi {name},\n\nIt was a pleasure working with you. If you were happy with the work, would you write "
               "two or three sentences about it that I could share with future clients? A reply to this email is "
               "perfect.\n\nThanks",
    "SEND": False,
}

DRY_RUN = os.environ.get("STEERABLE_DRY_RUN") == "1"
STRIPE = "https://api.stripe.com/v1"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
WINDOW_DAYS = 60
NO_REPLY = re.compile(r"no-?reply|do-?not-?reply", re.I)
REQUESTS = library.table(
    "Testimonial requests",
    columns="Client:text, Email:text, Invoice:text, Asked:date, Status:status(Asked|Got one|Declined)",
    description="Clients asked for a testimonial after paying for a piece of work; mark what came of it")


def paid_lately() -> list[dict]:
    """The latest qualifying paid invoice per client email."""
    now = time.time()
    newest, oldest = now - SETTINGS["AFTER_DAYS"] * 86400, now - WINDOW_DAYS * 86400
    latest: dict[str, dict] = {}
    after = None
    for _ in range(20):
        page = call("stripe", "GET", f"{STRIPE}/invoices", params={
            "status": "paid", "limit": 100, "created[gte]": int(oldest) - 90 * 86400,
            **({"starting_after": after} if after else {})})
        for inv in page.get("data") or []:
            paid = (inv.get("status_transitions") or {}).get("paid_at") or 0
            email = (inv.get("customer_email") or "").lower()
            if not email or NO_REPLY.search(email) or not oldest <= paid <= newest:
                continue
            if (inv.get("amount_paid") or 0) / 100 < SETTINGS["MIN_AMOUNT"]:
                continue
            if any(s.lower() in (email, email.split("@")[-1]) for s in SETTINGS["SKIP"]):
                continue
            if email not in latest or paid > latest[email]["paid"]:
                latest[email] = {"email": email, "name": inv.get("customer_name") or email.split("@")[0],
                                 "invoice": inv.get("number") or inv["id"], "paid": paid}
        if not page.get("has_more") or not page.get("data"):
            break
        after = page["data"][-1]["id"]
    return sorted(latest.values(), key=lambda c: c["paid"])


def asked_lately(email: str, today) -> bool:
    row = REQUESTS.get(email)
    asked = (row or {"cells": {}})["cells"].get("Asked")
    return bool(asked) and (today - datetime.fromisoformat(asked).date()).days < SETTINGS["ASK_EVERY_DAYS"]


def send(to: str, text: str) -> None:
    mail = EmailMessage()
    mail["To"], mail["Subject"] = to, "A quick favour"
    mail.set_content(text)
    call("google", "POST", f"{GMAIL}/messages/send", json={"raw": base64.urlsafe_b64encode(mail.as_bytes()).decode()})


def main() -> None:
    today = datetime.now(timezone.utc).date()
    step(1)
    clients = paid_lately()

    step(2, items=clients)
    due = [c for c in each(clients) if not asked_lately(c["email"], today)]

    step(3, items=due)
    sent, drafted = [], []
    for c in each(due):
        text = SETTINGS["MESSAGE"].format(name=c["name"].split()[0])
        if SETTINGS["SEND"] and act(f"Ask {c['email']} for a testimonial", {"to": c["email"], "text": text}, kind="send"):
            send(c["email"], text)
            sent.append(c["name"])
        else:
            save_draft(f"testimonial-{c['email']}", f"To: {c['email']}\nSubject: A quick favour\n\n{text}\n")
            drafted.append(c["name"])
        REQUESTS.add({"Client": c["name"], "Email": c["email"], "Invoice": c["invoice"], "Asked": today.isoformat(),
                      "Status": "Asked"}, key=c["email"], overwrite=True)

    step(4, items=len(due))
    lines = []
    if sent:
        lines.append(f"**Asked {', '.join(sent)} for a testimonial.** When they answer, mark it in your library "
                     "(Testimonial requests).")
    if drafted:
        lines.append(f"**{', '.join(drafted)} paid recently: a good moment to ask for a testimonial.** I wrote the "
                     "request; send it as it is or change it first.")
    if lines:
        tell_owner("\n".join(lines))
    n = len(due)
    print(f"{'Would ask' if DRY_RUN else 'Asked'} {n} client{'s' if n != 1 else ''} for a testimonial" if n
          else "No clients to ask for a testimonial")


if __name__ == "__main__":
    main()
