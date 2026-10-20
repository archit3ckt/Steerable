"""Routines we wrote and tested for work most small businesses need (scripts/catalog/<id>/), so a
build can start from one instead of from nothing: an approved task that clearly asks for one is
adapted from it (builder.py), which takes a few turns instead of dozens.

Each entry is a folder: routine.py (with its SETTINGS dict at the top, the part an adaptation sets
for the company), routine.flow.json (its flow chart) and about.json ({"title", "description" (one
sentence a task line is matched against), "services" (provider ids it uses), "settings" (each
SETTINGS key: what it is, in plain words)}). The bar an entry meets is in catalog/README.md.

    python scripts/catalog.py list
    python scripts/catalog.py match "<task line>"
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import decide

CATALOG = Path(__file__).resolve().parent / "catalog"
MATCH_MIN = 0.8  # below this, a full build: a near miss would cost more to bend than to write
QUESTION = "Which ready-made routine does this task ask for?"
NONE = "none of these: something different, or only similar"


def entries() -> list[dict]:
    if not CATALOG.is_dir():
        return []
    out = []
    for d in sorted(CATALOG.iterdir()):
        if d.is_dir() and not d.name.startswith("_") and (d / "about.json").exists():
            out.append({**json.loads((d / "about.json").read_text()), "id": d.name})
    return out


def get(entry_id: str) -> dict | None:
    return next((e for e in entries() if e["id"] == entry_id), None)


def match(task: str) -> dict | None:
    """The entry this task asks for, or None when none fits well enough (or deciding fails)."""
    found = entries()
    if not found:
        return None
    options = {e["id"]: e["description"] for e in found}
    options["none"] = NONE  # listed last: the default when nothing can tell
    try:
        d = decide.decide(QUESTION, options, context=task)
    except Exception:  # noqa: BLE001  a full build is always possible
        return None
    if d.choice == "none" or d.confidence < MATCH_MIN:
        return None
    return get(d.choice)


def install(entry: dict, wt: Path, name: str) -> None:
    """Put the entry in a build's worktree as workflows/<name>.py and its flow chart, and commit it, so
    what the build changes shows against our tested version."""
    src = CATALOG / entry["id"]
    shutil.copyfile(src / "routine.py", wt / "workflows" / f"{name}.py")
    shutil.copyfile(src / "routine.flow.json", wt / "workflows" / f"{name}.flow.json")
    subprocess.run(["git", "-C", str(wt), "add", "workflows/"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", f"Start {name} from {entry['id']}"], check=True,
                   capture_output=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["list"]:
        for e in entries():
            print(f"{e['id']}: {e['title']} ({', '.join(e['services']) or 'no services'})")
    elif sys.argv[1:2] == ["match"] and len(sys.argv) > 2:
        e = match(sys.argv[2])
        print(e["id"] if e else "none")
    else:
        print(__doc__)
        sys.exit(2)
