"""Keeps the COO's own space in order. After every chat turn (bridge.converse) it looks at what
the chat changed in its memory, skills and instructions, puts back what would break them, and
commits the rest to the company's git history, so any change can be undone later.

Put back (from the last commit), with the reason logged and reported:
- a file deleted or emptied, or cut to under 40% of what it was (a gutted memory);
- a file over its size limit (memory that only grows stops being memory);
- anything that isn't text;
- a CLAUDE.md that lost the engine's own sections (the onboarding section may go: that's its job);
- too many memory files (one fact per line in a few files, not a file per fact).

The chat can only write these places to begin with (bridge.ALLOWED_TOOLS); this checks what it
did there. The learning review checks and commits skills itself (learn.py).

    python scripts/guard.py        # check and commit now
"""
import subprocess
import sys
from pathlib import Path

from common import ROOT, log_run

WATCHED = ("memory", ".claude/skills", "CLAUDE.md")
LIMITS = {"memory": 30_000, ".claude/skills": 30_000, "CLAUDE.md": 80_000}  # bytes per file
MAX_MEMORY_FILES = 40
KEEP_SECTIONS = ("## Role:", "## Security", "## Rules", "## Workflow standard")


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=check)


def _committed(rel: str) -> bytes | None:
    out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True)
    return out.stdout if out.returncode == 0 else None


def _limit(rel: str) -> int:
    return next(v for k, v in LIMITS.items() if rel == k or rel.startswith(k + "/"))


def problems(rel: str, now: bytes | None, before: bytes | None) -> str | None:
    """Why this change must be put back, or None."""
    if now is None or not now.strip():
        return "deleted or emptied" if before and before.strip() else None
    try:
        text = now.decode("utf-8")
    except UnicodeDecodeError:
        return "not text"
    if "\x00" in text:
        return "not text"
    if len(now) > _limit(rel):
        return f"over {_limit(rel) // 1000} KB"
    if before and len(before) > 400 and len(now) < 0.4 * len(before):
        return f"cut from {len(before)} to {len(now)} bytes"
    if rel == "CLAUDE.md":
        lost = [s for s in KEEP_SECTIONS if s in before.decode("utf-8", "replace") and s not in text] if before else []
        if lost:
            return "lost the engine's sections: " + ", ".join(s.strip("# :") for s in lost)
    return None


def changed() -> list[str]:
    out = _git("status", "--porcelain", "-uall", "--", *WATCHED).stdout
    return [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]


def check_and_commit(who: str = "chat") -> list[dict]:
    """Put back what would break the COO's own space; commit the rest. Returns what was put back."""
    if not (ROOT / ".git").exists():
        return []
    put_back = []
    files = changed()
    memory_files = [p for p in (ROOT / "memory").rglob("*") if p.is_file()] if (ROOT / "memory").exists() else []
    too_many = len(memory_files) > MAX_MEMORY_FILES
    for rel in files:
        path = ROOT / rel
        now = path.read_bytes() if path.is_file() else None
        before = _committed(rel)
        reason = problems(rel, now, before)
        if not reason and too_many and rel.startswith("memory/") and before is None:
            reason = f"more than {MAX_MEMORY_FILES} memory files"
        if not reason:
            continue
        if before is None:
            path.unlink(missing_ok=True)  # a new file that can't stay
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(before)
        put_back.append({"file": rel, "reason": reason})
    if put_back:
        log_run("guard", "put_back", by=who, changes=put_back)
        try:
            import burst

            burst.report_problem("guard", ", ".join(c["file"] for c in put_back), "; ".join(f"{c['file']}: {c['reason']}" for c in put_back))
        except Exception:  # noqa: BLE001 - reporting must never break the chat
            pass
    left = changed()
    if left:
        _git("add", "-A", "--", *WATCHED)
        _git("-c", "user.name=COO", "-c", "user.email=coo@steerable.local", "commit", "-q",
             "-m", f"COO updated its notes ({who})", "--", *WATCHED)
    return put_back


if __name__ == "__main__":
    fixed = check_and_commit("by hand")
    print("Put back: " + "; ".join(f"{c['file']} ({c['reason']})" for c in fixed) if fixed else "All in order.")
    sys.exit(0)
