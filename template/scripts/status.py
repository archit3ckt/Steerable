"""One-screen status: heartbeat health, runs, failures, spend, open tasks. No model.

    python scripts/status.py          # last 7 days
    python scripts/status.py --days 1
"""
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from budget import limit, month_spend
from common import ROOT, RUN_LOG


def main(days: int) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    runs = []
    if RUN_LOG.exists():
        for line in RUN_LOG.read_text().splitlines():
            e = json.loads(line)
            if datetime.fromisoformat(e["ts"]) >= since:
                runs.append(e)

    beats = [r for r in runs if r["script"] == "heartbeat"]
    if beats:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(beats[-1]["ts"])
        mins = int(age.total_seconds() // 60)
        health = "OK" if mins <= 30 else "STALE: is cron running?"
        print(f"Heartbeat:  last {mins} min ago ({health})")
    else:
        print(f"Heartbeat:  no runs in the last {days} days. Is cron running?")

    work = [r for r in runs if r.get("workflow")]
    by_status = Counter(r["status"] for r in work)
    print(f"Workflows:  {sum(by_status.values())} runs in {days}d "
          f"({by_status['ok']} ok, {by_status['error']} failed)")
    for r in [r for r in work if r["status"] == "error"][-5:]:
        err = (r.get("stderr") or "").strip().splitlines()
        print(f"  FAIL {r['ts'][:16]} {r['workflow']}: {err[-1] if err else '?'}")

    # The engine's own jobs (learning, tidying skills): a failure here is a fault in the engine,
    # for whoever runs it, never for the owner.
    for r in [r for r in runs if r["status"] == "system_error"][-3:]:
        err = (r.get("stderr") or r.get("stdout") or "").strip().splitlines()
        print(f"  ENGINE {r['ts'][:16]} {r.get('system')}: {err[-1] if err else '?'} (retried next time; needs an engine update if it persists)")
    for r in [r for r in runs if r["status"] in ("engine_fault", "engine_code")][-3:]:
        print(f"  ENGINE {r['ts'][:16]} a fix or build wanted to change engine code: {', '.join(r.get('files') or [])}")

    # What the daily upkeep's watchdog found last time (upkeep.watch): databases, routines, growth.
    upkeep = [r for r in runs if r["script"] == "upkeep"]
    for kind in ("databases", "routines", "growth"):
        for item in (upkeep[-1].get(f"watch_{kind}") or [])[:5] if upkeep else []:
            print(f"  WATCH {kind}: {item}")

    stops = [r for r in runs if r["status"] == "budget_stop"]
    spent = month_spend()
    cap = limit()
    print((f"Spend:      ${spent:.2f} estimated this month (Claude subscription: no cap)" if cap is None else
           f"Spend:      ${spent:.2f} of ${cap:.2f} this month") + ("  (BUDGET STOP hit)" if stops else ""))

    tasks = (ROOT / "tasks.md").read_text().splitlines()
    open_tasks = [t for t in tasks if t.startswith("- [ ]")]
    gated = [t for t in open_tasks if "needs:approval" in t]
    print(f"Tasks:      {len(open_tasks)} open, {len(gated)} waiting for your approval")
    for t in gated:
        print(f"  APPROVE? {t[6:]}")


if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
    main(days)
