"""A short brief before each meeting with people from outside: who they are, when the owner last met them,
and the latest emails with them. From Google Calendar and Gmail; only reads, and no AI.

Goal:    walk into every call knowing where things stand
Metric:  meetings briefed
Task:    - [ ] Prepare a brief before each client meeting  @workflow:<name>  every:daily

A meeting needs a brief when it has a time (not all day) and someone from outside: not the owner, not
from the owner's own domain, not in SKIP. Each meeting is briefed once.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import library  # noqa: E402
from common import each, save_report, step, tell_owner  # noqa: E402
from integrations import call  # noqa: E402

SETTINGS = {
    "HOURS_AHEAD": 24,
    "EMAILS_PER_PERSON": 5,
    "SKIP": [],  # like ["family.com", "assistant@ourfirm.com"]
}

DRY_RUN = os.environ.get("STEERABLE_DRY_RUN") == "1"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
# Shared mail services: people there aren't one company, so the owner's domain check doesn't apply to them.
PERSONAL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "me.com", "proton.me"}
BRIEFS = library.table(
    "Meeting briefs",
    columns="Meeting:text, When:text, With:text, Last met:date, Brief:longtext",
    description="A brief for each meeting with people from outside: last time you met and your latest emails")


def rfc3339(t: datetime) -> str:
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


def outsiders(event: dict, me: str) -> list[dict]:
    mine = me.split("@")[-1]
    out = []
    for a in event.get("attendees") or []:
        email = (a.get("email") or "").lower()
        domain = email.split("@")[-1]
        if (not email or a.get("self") or a.get("resource") or email == me or (domain == mine and mine not in PERSONAL)
                or any(s.lower() in (email, domain) for s in SETTINGS["SKIP"])):
            continue
        out.append({"email": email, "name": a.get("displayName") or email.split("@")[0]})
    return out


def header(message: dict, name: str) -> str:
    return next((h["value"] for h in message.get("payload", {}).get("headers", []) if h["name"].lower() == name.lower()), "")


def recent_emails(email: str) -> list[str]:
    listed = call("google", "GET", f"{GMAIL}/messages",
                  params={"q": f"from:{email} OR to:{email}", "maxResults": SETTINGS["EMAILS_PER_PERSON"]})
    lines = []
    for m in listed.get("messages") or []:
        full = call("google", "GET", f"{GMAIL}/messages/{m['id']}",
                    params={"format": "metadata", "metadataHeaders": ["From", "Subject"]})
        when = datetime.fromtimestamp(int(full.get("internalDate") or 0) / 1000, timezone.utc).strftime("%d %b")
        who = "you" if "SENT" in (full.get("labelIds") or []) else (header(full, "From").split("<")[0].strip() or email)
        snippet = " ".join((full.get("snippet") or "").split())[:140]
        lines.append(f"- {when}, {who}: {header(full, 'Subject') or '(no subject)'}" + (f": {snippet}" if snippet else ""))
    return lines


def last_met(email: str, before: datetime) -> str:
    """When the owner last had a meeting with this person (the past year), as YYYY-MM-DD, or ""."""
    past = call("google", "GET", CALENDAR, params={
        "q": email, "timeMin": rfc3339(before - timedelta(days=365)), "timeMax": rfc3339(before),
        "singleEvents": "true", "orderBy": "startTime", "maxResults": 250})
    starts = [e["start"]["dateTime"] for e in past.get("items") or [] if e.get("start", {}).get("dateTime")]
    return starts[-1][:10] if starts else ""


def main() -> None:
    me = (call("google", "GET", f"{GMAIL}/profile").get("emailAddress") or "").lower()
    now = datetime.now(timezone.utc)
    step(1)
    events = call("google", "GET", CALENDAR, params={
        "timeMin": rfc3339(now), "timeMax": rfc3339(now + timedelta(hours=SETTINGS["HOURS_AHEAD"])),
        "singleEvents": "true", "orderBy": "startTime", "maxResults": 50}).get("items") or []
    meetings = [{**e, "people": outsiders(e, me)} for e in events
                if e.get("start", {}).get("dateTime") and e.get("status") != "cancelled"]
    meetings = [m for m in meetings if m["people"] and not BRIEFS.get(f"{m['id']}:{m['start']['dateTime']}")]

    step(2, items=meetings)
    briefs = []
    for m in each(meetings):
        start = datetime.fromisoformat(m["start"]["dateTime"].replace("Z", "+00:00"))
        when = start.strftime("%a %d %b, %H:%M")
        parts, met = [f"### {m.get('summary') or 'Meeting'} ({when})"], []
        for p in m["people"]:
            last = last_met(p["email"], start)
            met.append(last)
            parts.append(f"**{p['name']}** ({p['email']}): " + (f"last met {last}" if last else "first meeting"))
            emails = recent_emails(p["email"])
            parts += emails or ["- No emails together yet."]
        brief = "\n".join(parts)
        briefs.append({"meeting": m, "when": when, "brief": brief, "last": max(met) if any(met) else ""})

    step(3, items=briefs)
    for b in briefs:
        m = b["meeting"]
        BRIEFS.add({"Meeting": m.get("summary") or "Meeting", "When": b["when"],
                    "With": ", ".join(p["name"] for p in m["people"]), "Brief": b["brief"],
                    **({"Last met": b["last"]} if b["last"] else {})}, key=f"{m['id']}:{m['start']['dateTime']}")
    if briefs:
        save_report("# Meeting briefs\n\n" + "\n\n".join(b["brief"] for b in briefs) + "\n")

    step(4, items=len(briefs))
    if briefs:
        lines = [f"**Briefs for {len(briefs)} upcoming meeting{'s' if len(briefs) != 1 else ''}:**"]
        lines += [f"- {b['when']}: {b['meeting'].get('summary') or 'Meeting'} with "
                  f"{', '.join(p['name'] for p in b['meeting']['people'])}" for b in briefs]
        lines.append("Each brief is in your library, under Meeting briefs.")
        tell_owner("\n".join(lines))
    n = len(briefs)
    print(f"{'Would brief' if DRY_RUN else 'Briefed'} {n} upcoming meeting{'s' if n != 1 else ''}" if n
          else "No upcoming meetings need a brief")


if __name__ == "__main__":
    main()
