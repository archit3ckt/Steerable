"""Remind clients about Stripe invoices past their due date, with Stripe's own reminder email.

Goal:    get paid on time
Metric:  overdue invoices reminded, and how many were paid after a reminder
Task:    - [ ] Remind clients about overdue invoices  @workflow:<name>  every:weekly

Stripe sends the reminder (the invoice with its payment link) to the client's billing email. That
needs a Stripe key that may send invoices (Invoices: Write); with a read-only key it lists who is
overdue and tells the owner what to change instead of sending.
"""
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import library  # noqa: E402
from common import act, each, step, tell_owner  # noqa: E402
from integrations import IntegrationError, call  # noqa: E402

SETTINGS = {
    "DAYS_OVERDUE": 3,       # days past the due date before the first reminder
    "REMIND_EVERY_DAYS": 7,  # days between reminders for the same invoice
    "MAX_REMINDERS": 3,      # reminders per invoice, then it's left to the owner
    "MIN_AMOUNT": 0,         # skip invoices under this much still due (whole units of their currency)
}

DRY_RUN = os.environ.get("STEERABLE_DRY_RUN") == "1"
API = "https://api.stripe.com/v1"
MAX_PAGES = 10  # 1,000 open invoices
REMINDERS = library.table(
    "Invoice reminders",
    columns="Invoice:text, Client:text, Email:text, Amount due:number, Currency:text, Due:date, Reminders:number, "
            "Last reminded:date, Status:status(Reminded|Paid|Not sent|Check this)",
    description="Overdue Stripe invoices the COO reminded clients about")


def overdue(cutoff: int) -> list[dict]:
    """Open invoices due before `cutoff` (a Unix time), oldest first."""
    found, after = [], None
    for _ in range(MAX_PAGES):
        params = {"status": "open", "limit": 100, "due_date[lt]": cutoff}
        if after:
            params["starting_after"] = after
        page = call("stripe", "GET", f"{API}/invoices", params=params)
        data = page.get("data") or []
        found += [i for i in data if i.get("due_date") and i["due_date"] < cutoff]
        if not page.get("has_more") or not data:
            break
        after = data[-1]["id"]
    return sorted(found, key=lambda i: i["due_date"])


def due_again(row: dict | None, today: date) -> bool:
    if not row:
        return True
    cells = row["cells"]
    if cells.get("Status") == "Paid" or int(cells.get("Reminders") or 0) >= SETTINGS["MAX_REMINDERS"]:
        return False
    last = cells.get("Last reminded")
    return not last or (today - date.fromisoformat(last)).days >= SETTINGS["REMIND_EVERY_DAYS"]


def main() -> None:
    today = datetime.now(timezone.utc).date()
    step(1)
    invoices = overdue(int(time.time()) - SETTINGS["DAYS_OVERDUE"] * 86400)

    step(2, items=invoices)
    reminded, would, not_sent, checks = [], [], [], []
    for inv in each(invoices):
        amount = (inv.get("amount_remaining") or inv.get("amount_due") or 0) / 100
        if amount < SETTINGS["MIN_AMOUNT"] or not inv.get("customer_email"):
            continue
        row = REMINDERS.get(inv["id"])
        if not due_again(row, today):
            continue
        client = inv.get("customer_name") or inv["customer_email"]
        currency = (inv.get("currency") or "").upper()
        days = (today - datetime.fromtimestamp(inv["due_date"], timezone.utc).date()).days
        cells = {"Invoice": inv.get("number") or inv["id"], "Client": client, "Email": inv["customer_email"],
                 "Amount due": amount, "Currency": currency,
                 "Due": datetime.fromtimestamp(inv["due_date"], timezone.utc).date().isoformat()}
        said = f"{client}: invoice {cells['Invoice']}, {amount:,.2f} {currency}, {days} days overdue"
        if not act(f"Send {client} a reminder about invoice {cells['Invoice']} ({amount:,.2f} {currency}, "
                   f"{days} days overdue)", {"invoice": inv["id"], "email": inv["customer_email"]}, kind="send"):
            would.append(said)
            continue
        count = int((row or {"cells": {}})["cells"].get("Reminders") or 0)
        try:
            call("stripe", "POST", f"{API}/invoices/{inv['id']}/send")
        except IntegrationError as e:
            if e.status in (401, 403):  # the key may read invoices but not send them
                not_sent.append(said)
                REMINDERS.add({**cells, "Status": "Not sent"}, key=inv["id"], overwrite=True)
                continue
            checks.append(said)  # it may or may not have gone out: never send it twice blindly
            REMINDERS.add({**cells, "Status": "Check this"}, key=inv["id"], overwrite=True)
            continue
        reminded.append(said)
        REMINDERS.add({**cells, "Reminders": count + 1, "Last reminded": today.isoformat(), "Status": "Reminded"},
                      key=inv["id"], overwrite=True)

    open_ids = {i["id"] for i in invoices}
    waiting = REMINDERS.rows(where={"Status": "Reminded"}, limit=50)
    step(3, items=waiting)
    paid = []
    for row in each(waiting):
        if row["key"] in open_ids:
            continue
        inv = call("stripe", "GET", f"{API}/invoices/{row['key']}")
        if inv.get("status") == "paid":
            paid.append(row["cells"].get("Client") or row["key"])
            REMINDERS.update(row["id"], {"Status": "Paid"})

    step(4, items=len(reminded) + len(not_sent) + len(checks) + len(paid))
    lines = []
    if reminded:
        lines.append(f"**Reminded {len(reminded)} client{'s' if len(reminded) != 1 else ''} about overdue invoices:**")
        lines += [f"- {r}" for r in reminded]
    if not_sent:
        lines.append(f"**{len(not_sent)} client{'s are' if len(not_sent) != 1 else ' is'} late paying, but Stripe hasn't let "
                     "me send reminders yet.** Connect Stripe again on the Connections page, and allow it to send "
                     "invoices when it asks. I'll send them the next time I check.")
        lines += [f"- {r}" for r in not_sent]
    if checks:
        lines.append("**Please check these in Stripe:** I tried to send a reminder but couldn't tell if it went out.")
        lines += [f"- {r}" for r in checks]
    if paid:
        lines.append(f"Paid since a reminder: {', '.join(paid)}.")
    if lines:
        tell_owner("\n".join(lines))

    if DRY_RUN:
        print(f"Would remind {len(would)} client{'s' if len(would) != 1 else ''} about overdue invoices")
    elif not_sent and not reminded:
        print(f"Found {len(not_sent)} overdue invoices, but Stripe didn't let me send reminders")
    else:
        print(f"Reminded {len(reminded)} client{'s' if len(reminded) != 1 else ''} about overdue invoices"
              + (f"; {len(paid)} paid since a reminder" if paid else ""))


if __name__ == "__main__":
    main()
