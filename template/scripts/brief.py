"""Daily brief to the owner on Telegram. Built from logs and tasks.md, with no model.

Format: what moved, what's at risk, what needs you (with Approve/Reject buttons).
Cron runs it at 09:00. Run it by hand with: python scripts/brief.py
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import telegram
from alert import BRIEF_QUEUE
from budget import limit, month_spend
from common import COMPANY, CORE_WORKFLOWS, ROOT, RUN_LOG, TASKS, log_run
from ops_db import waiting_on_ceo

EXTRAS = ROOT / ".cache" / "brief_extras"


def add_extra(name: str, text: str, buttons: list | None = None) -> None:
    """Let any workflow attach a message (with optional buttons) to the next morning brief."""
    EXTRAS.mkdir(parents=True, exist_ok=True)
    (EXTRAS / f"{name}.json").write_text(json.dumps({"text": text, "buttons": buttons or []}))


def task_id(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:8]


def pending_approvals() -> list[tuple[str, str]]:
    """(id, task text) for open tasks tagged needs:approval. The COO's own upkeep never waits
    on the owner, so it's left out even if an older tasks.md still tags it."""
    out = []
    for line in TASKS.read_text().splitlines():
        if any(f"@workflow:{w} " in line + " " for w in CORE_WORKFLOWS):
            continue
        if line.startswith("- [ ]") and "needs:approval" in line:
            out.append((task_id(line), line[6:]))
    return out


def last_day_runs() -> list[dict]:
    if not RUN_LOG.exists():
        return []
    since = datetime.now(timezone.utc) - timedelta(days=1)
    return [e for e in map(json.loads, RUN_LOG.read_text().splitlines())
            if datetime.fromisoformat(e["ts"]) >= since]


def build() -> tuple[str, list]:
    # The owner's routines only: the engine's own jobs (learning, upkeep) aren't news.
    runs = [r for r in last_day_runs() if r.get("workflow") and not r.get("system") and r["workflow"] not in CORE_WORKFLOWS]
    ok = sorted({r["workflow"] for r in runs if r["status"] == "ok"})
    failed = sorted({r["workflow"] for r in runs if r["status"] == "error"} - set(ok))
    queued = json.loads(BRIEF_QUEUE.read_text()) if BRIEF_QUEUE.exists() else []
    approvals = pending_approvals()
    spent, cap = month_spend(), limit()  # cap None: a Claude subscription, no limit

    lines = [f"☀️ {COMPANY} brief, {datetime.now():%a %d %b}", ""]
    lines.append("✅ Moved: " + (", ".join(ok) if ok else "nothing ran yesterday"))
    risks = [f"{w} is failing" for w in failed] + queued
    if cap is not None and spent >= cap * 0.8:
        risks.append(f"budget at {spent / cap:.0%} of ${cap:.0f}")
    lines.append("⚠️ At risk: " + ("; ".join(risks) if risks else "nothing"))
    if cap is not None:  # on a Claude subscription there's nothing to count against
        lines.append(f"💰 ${spent:.2f} of ${cap:.0f} spent this month")
    buttons = []
    if approvals:
        lines += ["", "❓ Needs you:"]
        for n, (tid, text) in enumerate(approvals, 1):
            lines.append(f"{n}. {text.replace('needs:approval', '').strip()}")
            buttons.append([(f"✅ Approve {n}", f"ap:{tid}"), (f"❌ Reject {n}", f"rj:{tid}")])
    import small_decisions

    settled = small_decisions.brief_line()
    if settled:
        lines += ["", settled]
    board = waiting_on_ceo()
    if board:
        lines += ["", "📋 On the mission board, waiting on you:"]
        lines += [f"• {m}" for m in board[:5]]
    if not approvals and not board:
        lines += ["", "Nothing needs you today."]
    return "\n".join(lines), buttons


def main() -> None:
    import incident  # imported here: incident imports alert, which brief also imports

    text, buttons = build()
    waiting = incident.awaiting()
    if waiting:
        text = text.replace("Nothing needs you today.", "")
        text += f"\n🛠 {len(waiting)} issue(s) need you, below."
    telegram.send(text, buttons)
    for inc in waiting:
        telegram.send(incident.message(inc), incident.buttons(inc))
    for f in sorted(EXTRAS.glob("*.json")) if EXTRAS.exists() else []:
        extra = json.loads(f.read_text())
        telegram.send(extra["text"], [[tuple(b) for b in row] for row in extra["buttons"]] or None)
        f.unlink()
    BRIEF_QUEUE.unlink(missing_ok=True)
    log_run("brief", "ok", approvals=len(buttons))


if __name__ == "__main__":
    main()
