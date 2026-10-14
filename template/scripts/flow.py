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
"""
import json
import subprocess
import sys
import time

from budget import BudgetExceeded, check, record
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
    proc = subprocess.run(["claude", "-p", prompt, "--output-format", "json", "--model", "haiku",
                           "--max-budget-usd", CAP_USD, "--json-schema", json.dumps(SCHEMA),
                           "--permission-mode", "dontAsk", "--max-turns", "3"],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    try:
        out = json.loads(proc.stdout)
        data = out.get("structured_output") or json.loads(out.get("result") or "{}")
    except (json.JSONDecodeError, TypeError):
        log_run("flow", "error", workflow=workflow, stderr=proc.stderr[-500:])
        return None
    record("flow", float(out.get("total_cost_usd") or 0), model="haiku", note=workflow)
    steps = valid(data)
    if steps:
        path(workflow).write_text(json.dumps({"steps": steps}, indent=1) + "\n")
        (PENDING / workflow).unlink(missing_ok=True)
        log_run("flow", "ok", workflow=workflow, steps=len(steps))
    return steps


if __name__ == "__main__":
    print(json.dumps(describe(sys.argv[1]), indent=1))
