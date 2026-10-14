"""The COO's skill library (.claude/skills/): registry, usage tracking, archiving.

Skills are procedural memory: how to do a class of task for this CEO. Claude Code loads one
only when its description matches the task. scripts/learn.py writes them; scripts/
curate_skills.py archives the stale ones (both run by the heartbeat's built-in schedule). Modeled on Hermes Agent's skill lifecycle.

    .claude/skills/<name>/SKILL.md     a skill (frontmatter: name, description)
    .claude/skills/.registry.json      who created each skill, when, and whether it's pinned (in git)
    .claude/skills-archive/<name>/     archived skills (in git, so recoverable)
    .cache/skills_usage.json           when each skill was last used (runtime only)

Only skills the COO created are ever archived; skills a person wrote are never touched,
and neither are pinned ones.

    python scripts/skills.py           # list skills with usage
    python scripts/skills.py used      # Claude Code PostToolUse hook: reads the hook JSON on stdin
    python scripts/skills.py pin NAME  # protect a COO-created skill from archiving
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

from common import CACHE, ROOT, now_iso

SKILLS = ROOT / ".claude" / "skills"
ARCHIVE = ROOT / ".claude" / "skills-archive"
REGISTRY = SKILLS / ".registry.json"
USAGE = CACHE / "skills_usage.json"
COO_GIT = ["-c", "user.name=COO", "-c", "user.email=coo@steerable.local"]


def _read(path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def registry() -> dict:
    return _read(REGISTRY)


def save_registry(reg: dict) -> None:
    SKILLS.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n")


def names() -> list[str]:
    return sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md")) if SKILLS.exists() else []


def frontmatter(name: str) -> dict:
    """name and description from SKILL.md's frontmatter ({} if missing or malformed)."""
    try:
        text = (SKILLS / name / "SKILL.md").read_text()
    except OSError:
        return {}
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    return {k.strip(): v.strip().strip('"') for k, v in
            (line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)}


def record_use(name: str) -> None:
    usage = _read(USAGE)
    row = usage.setdefault(name, {"uses": 0})
    row["uses"] += 1
    row["last_used"] = now_iso()
    USAGE.write_text(json.dumps(usage, indent=2, sort_keys=True))


def last_activity(name: str) -> datetime | None:
    """Latest of: last use, last git change to the skill, registry creation date."""
    stamps = [_read(USAGE).get(name, {}).get("last_used"), registry().get(name, {}).get("created")]
    git = subprocess.run(["git", "log", "-1", "--format=%cI", "--", f".claude/skills/{name}"],
                         cwd=ROOT, capture_output=True, text=True).stdout.strip()
    stamps.append(git)
    parsed = [datetime.fromisoformat(s) for s in stamps if s]
    return max((d if d.tzinfo else d.replace(tzinfo=timezone.utc)) for d in parsed) if parsed else None


def archive(name: str) -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "mv", f".claude/skills/{name}", f".claude/skills-archive/{name}"], cwd=ROOT, check=True)
    reg = registry()
    reg.get(name, {})["archived"] = now_iso()
    save_registry(reg)


def commit(message: str) -> bool:
    """Commit skill changes as the COO. False if there was nothing to commit."""
    paths = [str(d.relative_to(ROOT)) for d in (SKILLS, ARCHIVE) if d.exists()]
    subprocess.run(["git", "add", "-A", *paths], cwd=ROOT, capture_output=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return False
    subprocess.run(["git", *COO_GIT, "commit", "-q", "-m", message], cwd=ROOT, check=True)
    return True


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "used":  # never fail: a broken hook must not disturb the session
        try:
            tool_input = json.loads(sys.stdin.read() or "{}").get("tool_input") or {}
            if name := (tool_input.get("skill") or tool_input.get("name") or "").split(":")[-1]:
                record_use(name)
        except Exception:
            pass
    elif cmd == "pin":
        reg = registry()
        reg.setdefault(sys.argv[2], {})["pinned"] = True
        save_registry(reg)
        print(f"pinned {sys.argv[2]}")
    else:
        usage, reg = _read(USAGE), registry()
        for n in names():
            who = reg.get(n, {}).get("created_by", "person")
            pin = " pinned" if reg.get(n, {}).get("pinned") else ""
            print(f"{n:32} {usage.get(n, {}).get('uses', 0):>4} uses  by {who}{pin}  {frontmatter(n).get('description', '')[:60]}")
