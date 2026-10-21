"""Last month per client: meetings and hours (Google Calendar), emails exchanged (Gmail) and what was invoiced
(Stripe, if it's connected). Only reads, and no AI.

Goal:    see where the time and the money went, client by client
Metric:  months reported
Task:    - [ ] Send me last month by client  @workflow:<name>  every:monthly

A client is a company (an email domain) or, on a shared mail service like Gmail, a person. Someone counts
as a client when they had MIN_MEETINGS meetings in the month or were invoiced in it.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import library  # noqa: E402
from common import each, save_report, step, tell_owner  # noqa: E402
from integrations import IntegrationError, call  # noqa: E402

SETTINGS = {
    "CLIENTS": {},  # like {"acme.com": "Acme", "jo@gmail.com": "Jo Smith"}
    "SKIP": [],  # like ["ourfirm.com", "printer.com"]
    "MIN_MEETINGS": 1,
}

DRY_RUN = os.environ.get("STEERABLE_DRY_RUN") == "1"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
PERSONAL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "me.com", "proton.me"}
MONTHS = library.table(
    "Client months",
    columns="Month:date, Client:text, Meetings:number, Hours:number, Emails:number, Invoiced:number",
    description="Each client's month: meetings and hours, emails exchanged and what was invoiced (the month starts on the date shown)")


def last_month(now: datetime) -> tuple[datetime, datetime]:
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = first.replace(year=first.year - 1, month=12) if first.month == 1 else first.replace(month=first.month - 1)
    return start, first


def rfc3339(t: datetime) -> str:
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


def client_of(email: str, me: str) -> str | None:
    """The client an address belongs to (its domain, or the address on a shared mail service); None if not one."""
    email = (email or "").lower()
    domain = email.split("@")[-1]
    mine = me.split("@")[-1]
    if not email or email == me or (domain == mine and mine not in PERSONAL):
        return None
    if any(s.lower() in (email, domain) for s in SETTINGS["SKIP"]):
        return None
    return email if domain in PERSONAL else domain


def name_of(key: str) -> str:
    return SETTINGS["CLIENTS"].get(key) or key


def meetings(start: datetime, end: datetime, me: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    token = None
    while True:
        page = call("google", "GET", CALENDAR, params={
            "timeMin": rfc3339(start), "timeMax": rfc3339(end), "singleEvents": "true", "orderBy": "startTime",
            "maxResults": 2500, **({"pageToken": token} if token else {})})
        for e in page.get("items") or []:
            s, f = e.get("start", {}).get("dateTime"), e.get("end", {}).get("dateTime")
            if not s or not f or e.get("status") == "cancelled":
                continue
            hours = (datetime.fromisoformat(f.replace("Z", "+00:00")) - datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds() / 3600
            for key in {client_of(a.get("email", ""), me) for a in e.get("attendees") or [] if not a.get("self")} - {None}:
                c = out.setdefault(key, {"meetings": 0, "hours": 0.0, "emails": 0, "invoiced": 0.0})
                c["meetings"] += 1
                c["hours"] += hours
        token = page.get("nextPageToken")
        if not token:
            return out


def invoiced(start: datetime, end: datetime, me: str) -> dict[str, float]:
    """Paid in the month, per client (Stripe); nothing if Stripe isn't connected."""
    out: dict[str, float] = {}
    after = None
    try:
        for _ in range(20):
            page = call("stripe", "GET", "https://api.stripe.com/v1/invoices", params={
                "status": "paid", "limit": 100, "created[gte]": int(start.timestamp()) - 90 * 86400,
                **({"starting_after": after} if after else {})})
            for inv in page.get("data") or []:
                paid = (inv.get("status_transitions") or {}).get("paid_at") or 0
                key = client_of(inv.get("customer_email") or "", me)
                if key and start.timestamp() <= paid < end.timestamp():
                    out[key] = out.get(key, 0.0) + (inv.get("amount_paid") or 0) / 100
            if not page.get("has_more") or not page.get("data"):
                break
            after = page["data"][-1]["id"]
    except IntegrationError:
        return {}
    return out


def emails(key: str, start: datetime, end: datetime) -> int:
    q = f"(from:{key} OR to:{key}) after:{start:%Y/%m/%d} before:{end:%Y/%m/%d}"
    return int(call("google", "GET", f"{GMAIL}/messages", params={"q": q, "maxResults": 1}).get("resultSizeEstimate") or 0)


def main() -> None:
    me = (call("google", "GET", f"{GMAIL}/profile").get("emailAddress") or "").lower()
    start, end = last_month(datetime.now(timezone.utc))
    step(1)
    clients = meetings(start, end, me)

    paid = invoiced(start, end, me)
    for key, amount in paid.items():
        clients.setdefault(key, {"meetings": 0, "hours": 0.0, "emails": 0, "invoiced": 0.0})["invoiced"] = amount
    clients = {k: c for k, c in clients.items() if c["meetings"] >= SETTINGS["MIN_MEETINGS"] or c["invoiced"]}
    step(2, items=clients)
    for key in each(list(clients)):
        clients[key]["emails"] = emails(key, start, end)

    month = start.date().isoformat()
    ranked = sorted(clients.items(), key=lambda kv: (-kv[1]["invoiced"], -kv[1]["hours"]))
    step(3, items=ranked)
    for key, c in ranked:
        MONTHS.add({"Month": month, "Client": name_of(key), "Meetings": c["meetings"], "Hours": round(c["hours"], 1),
                    "Emails": c["emails"], "Invoiced": round(c["invoiced"], 2)}, key=f"{month}:{key}", overwrite=True)

    step(4, items=len(ranked))
    label = start.strftime("%B %Y")
    if ranked:
        lines = [f"**{label}, by client:**"]
        for key, c in ranked:
            bits = [f"{c['meetings']} meeting{'s' if c['meetings'] != 1 else ''} ({c['hours']:.1f} h)", f"{c['emails']} emails"]
            if c["invoiced"]:
                bits.append(f"{c['invoiced']:,.2f} invoiced")
            lines.append(f"- {name_of(key)}: {', '.join(bits)}")
        text = "\n".join(lines)
        save_report(f"# {label} by client\n\n{text}\n")
        tell_owner(text)
    print(f"{label}: {len(ranked)} client{'s' if len(ranked) != 1 else ''}" + (" (practice run)" if DRY_RUN else ""))


if __name__ == "__main__":
    main()
