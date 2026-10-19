"""A routine's steps, for the owner's flow chart (the routine's page in the dashboard).

Routines are code, so the steps are written down beside them: workflows/<name>.flow.json, in the
owner's words. The builder writes it with the routine. For one that has none (older routines),
describe() asks a small model to read the code once and write it; the agent API starts that in the
background the first time the page is opened, and the chart appears when it's done.

    {"steps": [
      {"kind": "trigger", "label": "Every Monday at 9:00"},
      {"kind": "read",    "label": "Read last week's orders", "service": "Shopify"},
      {"kind": "think",   "label": "Find cafes that haven't reordered"},
      {"kind": "write",   "label": "Draft a friendly reminder to each"},
      {"kind": "ask",     "label": "Wait for your OK"},
      {"kind": "send",    "label": "Send the emails", "service": "Gmail"}
    ]}

    python scripts/flow.py <workflow>      # describe one now
    python scripts/flow.py map <workflow>  # work out which lines of its code do each step (the code view)
"""
import json
import sys
import time

import agent
from budget import BudgetExceeded, check
from common import CACHE, ROOT, log_run

KINDS = ["trigger", "read", "think", "write", "ask", "send", "save"]
PENDING = CACHE / "flows"
RETRY_SECONDS = 24 * 3600
CAP_USD = "0.10"

SCHEMA = {
    "type": "object",
    "properties": {"steps": {"type": "array", "minItems": 2, "maxItems": 10, "items": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": KINDS},
            "label": {"type": "string", "description": "what happens, 2-7 plain words, no code or file names"},
            "service": {"type": "string", "description": "the app or site it uses, like Gmail or Shopify; else empty"},
            "detail": {"type": "string", "description": "one short sentence more, or empty"},
        },
        "required": ["kind", "label"],
    }}},
    "required": ["steps"],
}

GUIDE = (f"Steps run top to bottom. kind is one of {', '.join(KINDS)}: trigger (when it runs; always first), read "
         "(gets information), think (works something out), write (drafts or makes something), ask (waits for the "
         "owner's OK), send (sends or changes something outside), save (keeps a record). Labels are 2-7 plain words "
         "a shop owner understands, no code, file or tool names; service names the app or site when there is one.")


def path(workflow: str):
    return ROOT / "workflows" / f"{workflow}.flow.json"


def valid(data) -> list[dict] | None:
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list) or not 2 <= len(steps) <= 12:
        return None
    out = []
    for s in steps:
        if not isinstance(s, dict) or s.get("kind") not in KINDS or not str(s.get("label") or "").strip():
            return None
        step = {"kind": s["kind"], "label": str(s["label"]).strip()[:80]}
        for key in ("service", "detail"):
            if str(s.get(key) or "").strip():
                step[key] = str(s[key]).strip()[:160 if key == "detail" else 40]
        out.append(step)
    return out


def load(workflow: str) -> list[dict] | None:
    try:
        return valid(json.loads(path(workflow).read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def pending(workflow: str) -> bool:
    """A description is being written now (or failed less than a day ago, so don't retry yet)."""
    marker = PENDING / workflow
    return marker.exists() and time.time() - marker.stat().st_mtime < RETRY_SECONDS


def describe(workflow: str, schedule: str = "") -> list[dict] | None:
    """Read the routine's code once and write its steps. None if it couldn't."""
    code_file = ROOT / "workflows" / f"{workflow}.py"
    if not code_file.exists():
        return None
    PENDING.mkdir(parents=True, exist_ok=True)
    (PENDING / workflow).touch()
    try:
        check()
    except BudgetExceeded:
        return None
    prompt = (f"Describe this routine's steps for the business owner's flow chart. It runs: {schedule or 'on a schedule'}.\n"
              f"{GUIDE}\nReturn only the JSON.\n\n--- workflows/{workflow}.py ---\n{code_file.read_text()[:16000]}")
    try:
        data = agent.complete(prompt, source="flow", tier="fast", schema=SCHEMA, max_tokens=2000, budget_usd=CAP_USD)
    except Exception as e:  # noqa: BLE001
        log_run("flow", "error", workflow=workflow, stderr=str(e)[-500:])
        return None
    steps = valid(data)
    if steps:
        path(workflow).write_text(json.dumps({"steps": steps}, indent=1) + "\n")
        (PENDING / workflow).unlink(missing_ok=True)
        log_run("flow", "ok", workflow=workflow, steps=len(steps))
    return steps


# ---------- which lines do each step (the code view on the routine's page) ----------

MAX_LINES = 3000
MAP_SCHEMA = {
    "type": "object",
    "properties": {"steps": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "step": {"type": "integer", "description": "the step's number, from 1"},
            "ranges": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
                       "description": "[first line, last line] of each part of the code that does this step"},
        },
        "required": ["step", "ranges"],
    }}},
    "required": ["steps"],
}


def code_of(workflow: str) -> str | None:
    file = ROOT / "workflows" / f"{workflow}.py"
    return file.read_text(errors="replace") if file.exists() else None


def _hash(code: str) -> str:
    import hashlib

    return hashlib.sha256(code.encode()).hexdigest()[:16]


def code_map(workflow: str) -> list[list[list[int]]] | None:
    """For each step, the [first, last] line ranges of the code that does it, if they've been
    worked out for the code as it is now. None otherwise."""
    code = code_of(workflow)
    try:
        saved = json.loads(path(workflow).read_text()).get("code") or {}
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return saved.get("ranges") if code is not None and saved.get("hash") == _hash(code) else None


def map_pending(workflow: str) -> bool:
    marker = PENDING / f"{workflow}.map"
    return marker.exists() and time.time() - marker.stat().st_mtime < RETRY_SECONDS


def map_code(workflow: str) -> list[list[list[int]]] | None:
    """Ask the fast model which lines of the routine do each of its steps, and keep the answer
    beside the steps (redone when the code changes). None if it couldn't."""
    steps, code = load(workflow), code_of(workflow)
    if not steps or code is None:
        return None
    PENDING.mkdir(parents=True, exist_ok=True)
    (PENDING / f"{workflow}.map").touch()
    lines = code.splitlines()[:MAX_LINES]
    numbered = "\n".join(f"{n:>4} {line}" for n, line in enumerate(lines, 1))
    listed = "\n".join(f"{n}. [{s['kind']}] {s['label']}" for n, s in enumerate(steps, 1))
    prompt = ("A routine's steps, as its owner sees them in a flow chart, and its Python code with line numbers. For each "
              "step, give the line ranges of the code that does that step: the functions and the part of the main flow "
              "that carry it out. A step may have several ranges. Leave out imports, settings and helpers that serve "
              "every step. Ranges must not overlap between steps. Return only the JSON.\n\n"
              f"Steps:\n{listed}\n\nCode:\n{numbered}")
    try:
        data = agent.complete(prompt, source="flow", tier="fast", schema=MAP_SCHEMA, max_tokens=3000, budget_usd=CAP_USD)
    except Exception as e:  # noqa: BLE001
        log_run("flow", "map_error", workflow=workflow, stderr=str(e)[-300:])
        return None
    ranges: list[list[list[int]]] = [[] for _ in steps]
    taken: set[int] = set()
    for item in (data or {}).get("steps", []):
        n = item.get("step")
        if not isinstance(n, int) or not 1 <= n <= len(steps):
            continue
        for r in item.get("ranges", []):
            if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r)):
                continue
            a, b = max(1, min(r)), min(len(lines), max(r))
            if a <= b and not taken & set(range(a, b + 1)):
                ranges[n - 1].append([a, b])
                taken |= set(range(a, b + 1))
    if not any(ranges):
        return None
    saved = json.loads(path(workflow).read_text())
    saved["code"] = {"hash": _hash(code), "ranges": [sorted(r) for r in ranges]}
    path(workflow).write_text(json.dumps(saved, indent=1) + "\n")
    (PENDING / f"{workflow}.map").unlink(missing_ok=True)
    log_run("flow", "mapped", workflow=workflow)
    return saved["code"]["ranges"]


if __name__ == "__main__":
    if sys.argv[1:2] == ["map"]:
        print(json.dumps(map_code(sys.argv[2])))
    else:
        print(json.dumps(describe(sys.argv[1]), indent=1))
