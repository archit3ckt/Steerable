"""Last week's numbers from Stripe (sales, refunds, payments, new customers), compared with the week before.

Goal:    know how the business is doing without opening Stripe
Metric:  weeks reported
Task:    - [ ] Send me last week's numbers  @workflow:<name>  every:weekly

Weeks are counted in UTC. Amounts are per currency; the message leads with the currency that took
the most. Only reads from Stripe, so a read-only key is enough.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import library  # noqa: E402
from common import save_report, step, tell_owner  # noqa: E402
from integrations import call  # noqa: E402

SETTINGS = {
    "WEEK_STARTS": "monday",  # or "sunday"
    "SEND_TO_OWNER": True,
}

API = "https://api.stripe.com/v1"
MAX_PAGES = 50  # 5,000 of each a week
WEEKS = library.table(
    "Weekly numbers",
    columns="Week:date, Currency:text, Sales:number, Refunds:number, Payments:number, New customers:number",
    description="Each week's sales, refunds and new customers from Stripe (weeks start on the date shown)")


def every(path: str, start: datetime, end: datetime) -> list[dict]:
    found, after = [], None
    for _ in range(MAX_PAGES):
        params = {"limit": 100, "created[gte]": int(start.timestamp()), "created[lt]": int(end.timestamp())}
        if after:
            params["starting_after"] = after
        page = call("stripe", "GET", f"{API}/{path}", params=params)
        data = page.get("data") or []
        found += data
        if not page.get("has_more") or not data:
            break
        after = data[-1]["id"]
    return found


def week(start: datetime) -> dict:
    """{currency: {"sales", "refunds", "payments"}} and the new customers, for the week from `start`."""
    end = start + timedelta(days=7)
    money: dict[str, dict] = {}
    for c in every("charges", start, end):
        if c.get("status") != "succeeded" or not c.get("paid", True):
            continue
        m = money.setdefault((c.get("currency") or "").upper(), {"sales": 0.0, "refunds": 0.0, "payments": 0})
        m["sales"] += (c.get("amount") or 0) / 100
        m["payments"] += 1
    for r in every("refunds", start, end):
        if r.get("status") in ("failed", "canceled"):
            continue
        m = money.setdefault((r.get("currency") or "").upper(), {"sales": 0.0, "refunds": 0.0, "payments": 0})
        m["refunds"] += (r.get("amount") or 0) / 100
    return {"money": money, "customers": len(every("customers", start, end))}


def change(now: float, before: float) -> str:
    if not before:
        return "" if not now else " (none the week before)"
    pct = round((now - before) / before * 100)
    return " (same as the week before)" if pct == 0 else f" ({'up' if pct > 0 else 'down'} {abs(pct)}% on the week before)"


def main() -> None:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    back = (today.weekday() + (1 if SETTINGS["WEEK_STARTS"] == "sunday" else 0)) % 7
    this_week = today - timedelta(days=back)
    last_start, prev_start = this_week - timedelta(days=7), this_week - timedelta(days=14)

    step(1)
    last, prev = week(last_start), week(prev_start)

    step(2, items=sum(m["payments"] for m in last["money"].values()))
    currencies = sorted(last["money"], key=lambda c: -last["money"][c]["sales"]) or [""]
    lines = [f"**Last week** ({last_start:%d %b} to {this_week - timedelta(days=1):%d %b}):"]
    for cur in currencies:
        now = last["money"].get(cur) or {"sales": 0.0, "refunds": 0.0, "payments": 0}
        was = prev["money"].get(cur) or {"sales": 0.0, "refunds": 0.0, "payments": 0}
        unit = f" {cur}" if cur else ""
        lines.append(f"- Sales: {now['sales']:,.2f}{unit} from {now['payments']} payment{'s' if now['payments'] != 1 else ''}"
                     + change(now["sales"], was["sales"]))
        if now["refunds"] or was["refunds"]:
            lines.append(f"- Refunds: {now['refunds']:,.2f}{unit}" + change(now["refunds"], was["refunds"]))
    lines.append(f"- New customers: {last['customers']}" + change(last["customers"], prev["customers"]))

    step(3, items=len(currencies))
    for cur in currencies:
        now = last["money"].get(cur) or {"sales": 0.0, "refunds": 0.0, "payments": 0}
        WEEKS.add({"Week": last_start.date().isoformat(), "Currency": cur, "Sales": round(now["sales"], 2),
                   "Refunds": round(now["refunds"], 2), "Payments": now["payments"], "New customers": last["customers"]},
                  key=f"{last_start.date().isoformat()}:{cur}", overwrite=True)
    text = "\n".join(lines)
    save_report(f"# Weekly numbers\n\n{text}\n")

    step(4, items=1)
    if SETTINGS["SEND_TO_OWNER"]:
        tell_owner(text)
    top = last["money"].get(currencies[0]) or {"sales": 0.0, "payments": 0}
    was = (prev["money"].get(currencies[0]) or {"sales": 0.0})["sales"]
    unit = f" {currencies[0]}" if currencies[0] else ""
    print(f"Last week: {top['sales']:,.2f}{unit} from {top['payments']} payment{'s' if top['payments'] != 1 else ''}"
          + change(top["sales"], was))


if __name__ == "__main__":
    main()
