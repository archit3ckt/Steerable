"""Small decisions, settled for the owner: when they've switched on "Decide small things for me",
a question the COO would put in their Decisions (scripts/ask.py) that's small and easy to undo is
settled with the COO's own pick instead, and the COO carries on. The owner sees what was settled in
Decisions and the morning brief, and can undo any of it: the question comes back to them, and the
check learns they want to decide things like it.

Never settled, whatever the check says (NEVER below): money, contacting or publishing to people,
deleting, logins and accounts, legal matters, and hiring.

    small_decisions.on() / set_on(True)
    small_decisions.consider(mission_id, question, context, options, pick, why)   # from ask.py
    small_decisions.recent()  /  small_decisions.undo(mission_id)
"""
import json
import re
from datetime import datetime, timedelta, timezone

from common import CACHE, log_run, now_iso

PREFS = CACHE / "preferences.json"
STORE = CACHE / "small_decisions.json"
KEEP = 100
MIN_CONFIDENCE = 0.75

# Only the owner decides these: matched in the question, its context and its options.
NEVER = re.compile(
    r"\b(pay|paid|payment|price|pricing|prices|charge|cost|costs|budget|spend|spending|buy|purchase|refund|invoice|"
    r"discount|salary|wage|fee|fees|money|cash|loan|tax|taxes|\$|€|£|₪|"
    r"email|e-mail|message|messages|call|contact|reply|respond|send|post|publish|announce|tweet|newsletter|outreach|"
    r"customer|customers|client|clients|supplier|suppliers|partner|investor|"
    r"delete|remove|cancel|close|shut|drop|archive|"
    r"password|login|log in|sign up|account|accounts|access|permission|"
    r"legal|lawyer|contract|terms|privacy|compliance|license|licence|lawsuit|"
    r"hire|hiring|fire|firing|employee|employees|staff|recruit)\b",
    re.IGNORECASE,
)


def on() -> bool:
    try:
        return bool(json.loads(PREFS.read_text()).get("decideSmall"))
    except (FileNotFoundError, ValueError):
        return False


def set_on(value: bool) -> None:
    try:
        prefs = json.loads(PREFS.read_text())
    except (FileNotFoundError, ValueError):
        prefs = {}
    prefs["decideSmall"] = bool(value)
    PREFS.write_text(json.dumps(prefs))
    log_run("small_decisions", "on" if value else "off")


def _load() -> list[dict]:
    try:
        return json.loads(STORE.read_text())
    except (FileNotFoundError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[-KEEP:], ensure_ascii=False, indent=1))
    tmp.replace(STORE)


def owners_only(text: str) -> bool:
    """Something only the owner decides (NEVER)."""
    return bool(NEVER.search(text or ""))


def _check(question: str, context: str, options: list[dict], pick: str) -> tuple[bool, str]:
    """Is it small and easy to undo, so the COO's pick can stand? (Jev, or Haiku.) Learns from what
    the owner took back."""
    from decide import decide

    undone = [i["question"] for i in _load() if i.get("undone")][-8:]
    listed = "\n".join(f"- {o['label']}{' (the COO picks this)' if o['id'] == pick else ''}" for o in options)
    context_text = (f"{question}\n{context}\nOptions:\n{listed}\n\n"
                    "Small means: easy to change later, nothing leaves the business, no money, no one outside is "
                    "contacted, and the owner wouldn't mind not being asked (a format, an order, a time, which of two "
                    "similar options, a working detail).")
    if undone:
        context_text += "\n\nThe owner took these back, wanting to decide them themselves:\n" + "\n".join(f"- {q}" for q in undone)
    d = decide("Can the COO settle this question itself, with its own pick, without asking the owner?",
               {"settle": "it's small and easy to undo: the COO's pick can stand",
                "owner": "the owner should decide it"},
               context=context_text, use_cache=False)
    ok = d.choice == "settle" and d.backend != "rules" and d.confidence >= MIN_CONFIDENCE
    return ok, f"{d.backend} {d.confidence:.2f}: {d.reason}"


def consider(mission_id: int, question: str, context: str, options: list[dict], pick: str, why: str) -> dict | None:
    """When the owner lets small decisions be settled for them and this is one, settle it with the
    COO's pick and return the chosen option. None when it's theirs to decide."""
    if not on():
        return None
    chosen = next((o for o in options if o["id"] == pick), None)
    if not chosen:
        return None
    text = " ".join([question, context, why, *(o["label"] + " " + o.get("outcome", "") for o in options)])
    if owners_only(text):
        log_run("small_decisions", "owners", question=question)
        return None
    try:
        ok, reason = _check(question, context, options, pick)
    except Exception as e:  # noqa: BLE001  (no answer: the owner decides)
        log_run("small_decisions", "error", question=question, error=str(e)[:200])
        return None
    log_run("small_decisions", "settled" if ok else "owners", question=question, reason=reason)
    if not ok:
        return None
    from ops_db import connect, record_event

    with connect() as con:
        con.execute("""UPDATE missions SET status = 'In progress', needs_ceo_approval = 0, options = NULL,
                       outcome = COALESCE(outcome, '') || ?, updated = CURRENT_TIMESTAMP WHERE id = ?""",
                    (f"\nSettled for the owner (a small decision): {chosen['label']}.", mission_id))
    items = [i for i in _load() if i["id"] != mission_id]
    items.append({"id": mission_id, "question": question, "context": context, "options": options, "pick": pick,
                  "why": why, "chosen": chosen["label"], "at": now_iso(), "undone": False})
    _save(items)
    record_event(f"Settled for you: {chosen['label']}. ({question})", who="COO", mission=question)
    return chosen


def recent(days: int = 7) -> list[dict]:
    """What was settled for the owner lately and is still standing, newest first."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return [i for i in reversed(_load())
            if not i.get("undone") and datetime.fromisoformat(i["at"]) >= since]


def undo(mission_id: int) -> dict | None:
    """The owner takes it back: the question returns to their Decisions, and what they want to
    decide themselves is remembered (for the check, and the learning review). None if it's gone."""
    items = _load()
    item = next((i for i in items if i["id"] == mission_id and not i.get("undone")), None)
    if not item:
        return None
    from ops_db import connect, record_event

    with connect() as con:
        con.execute("""UPDATE missions SET status = 'Waiting on CEO', options = ?, recommendation = ?,
                       recommendation_why = ?, outcome = ?, updated = CURRENT_TIMESTAMP WHERE id = ?""",
                    (json.dumps(item["options"]), item["pick"], item["why"],
                     item["context"] + "\n(You asked to decide this one yourself.)", mission_id))
    item["undone"] = True
    item["undoneAt"] = now_iso()
    _save(items)
    record_event(f"You took back a small decision: {item['question']}. It's in your Decisions.", who="CEO",
                 mission=item["question"])
    from common import lesson

    lesson(f"The owner wants to decide things like this themselves: {item['question']}")
    return item


def brief_line() -> str | None:
    """For the morning brief: what was settled for the owner since yesterday."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    done = [i for i in recent(1) if datetime.fromisoformat(i["at"]) >= since]
    if not done:
        return None
    listed = "; ".join(f"{i['question']}: {i['chosen']}" for i in done[:5])
    return f"🤝 Settled {len(done)} small thing{'s' if len(done) != 1 else ''} for you: {listed}. Undo any in Decisions."
