"""TEMPLATE: copy this file to start every new workflow (see "Workflow standard" in CLAUDE.md).

    cp workflows/_template.py workflows/<name>.py

Goal:    <which goal in CLAUDE.md this serves>
Metric:  <the number that shows it's working, e.g. datasets live, signups per week>
Task:    - [ ] <description>  @workflow:<name>  every:daily

Dry run: with STEERABLE_DRY_RUN=1, do everything except contacting anyone, publishing, paying or
deleting, and print what you would have done. Builds and tests only ever run it that way.
The last line printed is shown to the owner as what the run did: make it a plain sentence.

Anything it can't undo (submit, send, post, pay, delete) only inside `if act("<what>", {...}):`,
after checking its records and the page; a practice run returns False there and notes it.

The heartbeat runs it with the task line as argv[1]. Exit codes:
    0  success
    2  ran, but a quality check failed (the heartbeat opens a "quality" incident)
    any other / crash  (the heartbeat opens a "crash" incident)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from budget import check  # noqa: E402
from common import act, each, lesson, log_run, step  # noqa: E402
from state import State  # noqa: E402
import library  # noqa: E402,F401  (records the owner looks up: library.table(...).add(..., key=...))
from decide import decide  # noqa: E402
from incident import open_incident  # noqa: E402

NAME = Path(__file__).stem


def run(task: str) -> list[dict]:
    """1. Do the work with plain code first. Call check() before any paid model call.
    Call step(n) as each step of workflows/<name>.flow.json starts (step(1) is the first after the trigger),
    with what reaches it: step(2, items=posts). Go through a list with `for post in each(posts):` so the
    owner sees how far it's got.
    Records for the owner: library.table(...).add(cells, key=...). Working state: State().seen(key, keep_days=60).
    A lasting lesson about how the owner wants this done: lesson("...")."""
    rows: list[dict] = []
    return rows


def quality_problems(rows: list[dict]) -> list[str]:
    """2. Quality checks: is the result actually right, not just produced?"""
    problems = []
    if len(rows) < 1:  # e.g. compare with the last run: within ±20%
        problems.append(f"only {len(rows)} rows")
    # required fields filled, values in sane ranges, a few samples spot-checked with decide()
    return problems


def watch(rows: list[dict]) -> None:
    """3. Watchers for this workflow's own failure modes, beyond crashes.

    Contain first (stop the automation for the affected scope), then open an incident.
    Examples: an angry customer reply (support), a metric not moving for N days (growth),
    a source that went stale (data).
    """
    # if stalled_metric():
    #     pause_scope(...)  # contain
    #     open_incident("signal", f"{NAME}:metric-stalled", "Signups flat for 7 days",
    #                   details="...", workflow=NAME)


def main() -> int:
    task = sys.argv[1] if len(sys.argv) > 1 else ""
    rows = run(task)
    problems = quality_problems(rows)
    watch(rows)
    log_run(NAME, "quality_failed" if problems else "ok", rows=len(rows), problems=problems)
    if problems:
        print("Quality check failed: " + "; ".join(problems))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
