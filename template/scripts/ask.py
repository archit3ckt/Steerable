"""Ask the owner a direction-level question, with options and your pick.

For choices only the owner should make (pricing, which supplier, whether to drop a product).
It goes on the mission board as "Waiting on CEO", and the owner sees it in the app's Decisions
(and the Telegram brief) with your recommendation first. Their answer lands in the mission's
outcome and the activity log.

    .venv/bin/python scripts/ask.py "Handle the supplier price rise" \\
        --context "The supplier raised prices 8% from May 1. Margins drop to 31% if we do nothing." \\
        --option raise="Raise our prices 5%" --option switch="Switch to GreenLeaf Wholesale" \\
        --option absorb="Keep prices, take the hit" \\
        --recommend raise --why "Customers have accepted small rises before, and it keeps margins at 36%." \\
        --goal "$8k monthly revenue"

For a choice of direction, give each option its case, and the owner sees them side by side as cards:
        --pro raise="Customers took small rises before" --con raise="A few price-sensitive buyers may leave" \\
        --tag raise="Starts May 1"
Two or three short points each, in plain words.
"""
import argparse
import json
import re
import sys

from common import log_run
from ops_db import connect, record_event


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="the decision, in a few words")
    parser.add_argument("--context", required=True, help="why it's on their desk, two or three sentences")
    parser.add_argument("--option", action="append", required=True, metavar="ID=LABEL",
                        help="an option (at least two); add ID=LABEL|what happens to say what it leads to")
    parser.add_argument("--recommend", required=True, help="the id of the option you'd pick")
    parser.add_argument("--why", required=True, help="why you'd pick it, one sentence")
    parser.add_argument("--goal", help="the goal it's about")
    for flag, what in (("--pro", "a point for it"), ("--con", "a point against it"), ("--tag", "a short fact: cost, time, what it needs")):
        parser.add_argument(flag, action="append", default=[], metavar="ID=TEXT", help=f"{what} (an option's id), repeatable")
    args = parser.parse_args()

    options = []
    for raw in args.option:
        oid, _, rest = raw.partition("=")
        label, _, outcome = rest.partition("|")
        if not re.fullmatch(r"[a-z0-9_-]{1,30}", oid) or not label.strip():
            print(f"Write options as id=Label, like raise=\"Raise our prices 5%\" (got {raw!r}).", file=sys.stderr)
            return 1
        options.append({"id": oid, "label": label.strip()[:80], **({"outcome": outcome.strip()[:120]} if outcome.strip() else {})})
    if len(options) < 2:
        print("Give at least two options.", file=sys.stderr)
        return 1
    if args.recommend not in {o["id"] for o in options}:
        print("--recommend must be one of the option ids.", file=sys.stderr)
        return 1
    by_id = {o["id"]: o for o in options}
    for flag, key, cap in (("pro", "pros", 3), ("con", "cons", 3), ("tag", "tags", 3)):
        for raw in getattr(args, flag):
            oid, _, text = raw.partition("=")
            if oid not in by_id or not text.strip():
                print(f"Write --{flag} as option_id=text, for one of the options (got {raw!r}).", file=sys.stderr)
                return 1
            points = by_id[oid].setdefault(key, [])
            if len(points) < cap:
                points.append(text.strip()[:120])

    with connect() as con:
        goal = con.execute("SELECT id FROM goals WHERE goal = ?", (args.goal,)).fetchone() if args.goal else None
        con.execute("""INSERT INTO missions (mission, goal_id, status, owner, outcome, options, recommendation, recommendation_why)
                       VALUES (?, ?, 'Waiting on CEO', 'COO', ?, ?, ?, ?)
                       ON CONFLICT(mission) DO UPDATE SET status = 'Waiting on CEO', outcome = excluded.outcome,
                         options = excluded.options, recommendation = excluded.recommendation,
                         recommendation_why = excluded.recommendation_why, updated = CURRENT_TIMESTAMP""",
                    (args.question, goal["id"] if goal else None, args.context, json.dumps(options), args.recommend, args.why))
        mission_id = con.execute("SELECT id FROM missions WHERE mission = ?", (args.question,)).fetchone()["id"]
    # The owner may let small decisions be settled for them (small_decisions.py): then this one
    # may be, with your pick, and you carry on.
    import small_decisions

    settled = small_decisions.consider(mission_id, args.question, args.context, options, args.recommend, args.why)
    if settled:
        log_run("ask", "settled", question=args.question, option=settled["id"])
        print(f"Settled: the owner lets you decide small things like this, so go with \"{settled['label']}\" and carry on. "
              "They'll see it in Decisions and the brief, and can undo it.")
        return 0
    record_event(f"Asked you to decide: {args.question}", who="COO", mission=args.question)
    log_run("ask", "ok", question=args.question)
    print(f"Asked. It's waiting for the owner in Decisions: {args.question}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
