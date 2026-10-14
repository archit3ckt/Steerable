"""Ask for a change to a routine from the chat: a bug the COO found, or something the owner wants
done differently. Kept for older instructions; it's change.py now: the change waits for the
owner's OK in Decisions, then the builder makes it, tests it and checks it against the standards.
The routine keeps running meanwhile. (Crashes still go to the fixer, incident.py.)

    .venv/bin/python scripts/fix.py reply_tracker "Drafting is skipped when the AI is blocked. Retry them next run instead."
"""
import sys

import change

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    try:
        c = change.propose(sys.argv[1], " ".join(sys.argv[2:]), why="Asked for in the chat.")
    except change.ChangeError as e:
        sys.exit(str(e))
    print(f"It's in the owner's Decisions: update {c['title']}? It keeps running as it is until the new version is tested.")
