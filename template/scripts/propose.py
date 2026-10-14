"""Propose a new routine to the owner. It waits for their approval: Approve/Reject buttons in
the Telegram brief, or a decision card in the Steerable app. Nothing runs until they say yes.

The COO uses this instead of editing tasks.md, which the chat agent can't write, so it can
never approve its own work.

    .venv/bin/python scripts/propose.py "Remind cafes to reorder" --workflow reorder_reminders \\
        --every weekly --goal "40 cafe accounts" --metric "reorders per week" --saves 2

How often (common.EVERY): --every daily | weekly | 3h (every N hours, 1 to 12), or
--every daily --at 08:00,13:00,18:00 (those times each day, the company's time zone).
--replace swaps a proposal the owner hasn't approved yet (a different schedule, say) for this one.
"""
import argparse
import re
import sys

from common import check_schedule, edit_tasks, log_run, task_title
from ops_db import record_event


def task_line(args: argparse.Namespace) -> str:
    title = task_title(args.description)
    if not title or len(title) > 200:
        raise ValueError("Give the routine a short description (up to 200 characters).")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", args.workflow):
        raise ValueError("--workflow must be a snake_case name, like reorder_reminders.")
    note = ""
    if args.goal:
        note = f" (goal: {args.goal}" + (f"; metric: {args.metric}" if args.metric else "") + ")"
    every = args.every or ("daily" if args.at else None)
    if problem := check_schedule(every, args.at):
        raise ValueError(problem)
    parts = [f"- [ ] {title}{note}", f"@workflow:{args.workflow}"]
    if every:
        parts.append(f"every:{every}")
    if args.at:
        parts.append(f"at:{','.join(sorted(set(args.at.split(','))))}")
    if args.due:
        parts.append(f"due:{args.due}")
    if args.saves is not None:  # 0 is a real answer: "saves nothing"
        parts.append(f"saves:{args.saves:g}h")
    parts.append("needs:approval")
    return "  ".join(parts)


def propose(line: str, workflow: str, replace: bool = False) -> bool:
    added: list[bool] = []

    def change(lines: list[str]) -> list[str]:
        mine = [i for i, existing in enumerate(lines) if f"@workflow:{workflow}" in existing and existing.startswith("- [ ]")]
        if mine and replace and all("needs:approval" in lines[i] for i in mine):
            # Still waiting for the owner: swap it for this one, in its place.
            lines[mine[0]] = line
            for i in reversed(mine[1:]):
                del lines[i]
            added.append(True)
            return lines
        if mine:
            return lines  # already proposed or running
        at = next((i + 1 for i, existing in enumerate(lines) if existing.strip() == "## Open"), None)
        if at is None:
            lines += ["", "## Open"]
            at = len(lines)
        while at < len(lines) and lines[at].startswith("- "):
            at += 1  # after the last open task
        lines.insert(at, line)
        added.append(True)
        return lines

    edit_tasks(change)
    return bool(added)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("description", help="what it does, in the owner's words")
    parser.add_argument("--workflow", required=True, help="the workflows/<name>.py it will run")
    parser.add_argument("--every", help="daily, weekly, or every N hours like 3h (1 to 12)")
    parser.add_argument("--at", help="times each day, HH:MM 24-hour, comma-separated (like 08:00,13:00,18:00); implies daily")
    parser.add_argument("--replace", action="store_true", help="swap a proposal for this routine that's still waiting for approval")
    parser.add_argument("--due", help="YYYY-MM-DD, for a one-off")
    parser.add_argument("--goal", help="the goal it serves")
    parser.add_argument("--metric", help="the number that shows it's working")
    parser.add_argument("--saves", type=float, required=True,
                        help="your honest estimate of hours a week it saves the owner (0 if none)")
    args = parser.parse_args()
    try:
        line = task_line(args)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    if not propose(line, args.workflow, args.replace):
        print(f"A routine named {args.workflow} is already "
              + ("running. Its schedule can't be changed this way once approved." if args.replace else
                 "proposed or running. Use --replace to change a proposal that's still waiting."))
        return 0
    record_event(f"{'Changed the proposal' if args.replace else 'Proposed a new routine'}: {task_title(line)}",
                 who="COO", workflow=args.workflow)
    log_run("propose", "ok", workflow=args.workflow)
    print(f"Proposed. It's waiting for the owner's approval:\n{line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
