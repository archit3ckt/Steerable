"""Weekly skill curation: archive COO-created skills nobody has used in a month. No model, $0.

Goal:    a lean skill library, so the right skill is found and stale advice doesn't linger.
Metric:  active skills vs. archived; no skill unused for 30+ days.
Task:    - [ ] Curate skills  @workflow:curate_skills  every:weekly

Rules (Hermes Agent's curator lifecycle):
- Only skills the COO created (registry created_by: coo). Skills a person wrote are never touched.
- Pinned skills are never touched: python scripts/skills.py pin <name>
- Activity = last use (hook), last change (git), or creation. 14+ days quiet = stale (reported),
  30+ days = archived to .claude/skills-archive/ in git, so `git mv` brings one back.
- A skill younger than 14 days is never stale: unused isn't stale, it's new.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import skills  # noqa: E402
from brief import add_extra  # noqa: E402
from common import log_run  # noqa: E402

NAME = Path(__file__).stem
STALE_DAYS, ARCHIVE_DAYS = 14, 30


def main() -> int:
    now = datetime.now(timezone.utc)
    reg = skills.registry()
    stale, archived = [], []
    for name in skills.names():
        meta = reg.get(name, {})
        if meta.get("created_by") != "coo" or meta.get("pinned"):
            continue
        last = skills.last_activity(name)
        if last is None or last > now - timedelta(days=STALE_DAYS):
            continue
        if last <= now - timedelta(days=ARCHIVE_DAYS):
            skills.archive(name)
            archived.append(name)
        else:
            stale.append(name)

    problems = [f"{n} still in .claude/skills after archiving" for n in archived if (skills.SKILLS / n).exists()]
    if archived:
        skills.commit("COO archived unused skills: " + ", ".join(archived))
        add_extra("curated", "🗂 Archived skills unused for 30+ days: " + ", ".join(archived)
                  + ". They're in .claude/skills-archive/ if you want one back.")
    log_run(NAME, "quality_failed" if problems else "ok", active=len(skills.names()), stale=stale,
            archived=archived, problems=problems)
    if problems:
        print("Quality check failed: " + "; ".join(problems))
        return 2
    print(f"{len(skills.names())} active, {len(stale)} stale, {len(archived)} archived")
    return 0


if __name__ == "__main__":
    sys.exit(main())
