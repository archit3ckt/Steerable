"""Run a routine now, once, as its schedule would (the owner asked, in the chat or with "Run now").
Only a routine that's switched on; it waits its turn if the heartbeat is busy, and doesn't move
the schedule.

    .venv/bin/python scripts/run.py job_scan
"""
import sys

import heartbeat

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        heartbeat.start_manual(sys.argv[1])
    except ValueError as e:
        sys.exit(str(e))
    print("Started. It runs once now; the timeline shows what it did, and the schedule stays as it was.")
