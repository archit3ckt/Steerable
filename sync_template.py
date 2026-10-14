#!/usr/bin/env python3
"""Refresh template/ from a live company project, so improvements flow back into the kit.

    python3 sync_template.py "../My Company"

Copies the generic parts (scripts, .gitignore, requirements, memory/README.md) and
rebuilds template/CLAUDE.md from the project's CLAUDE.md, with the company-specific
sections blanked and the onboarding section put back. Company data (memory files,
tasks, logs, .env, workflows) is never copied.
"""
import re
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
TEMPLATE = KIT / "template"

ONBOARDING = """## Company overview
(Pending onboarding. Details go in [memory/company.md](memory/company.md).)

## Goals
(Pending onboarding.)

## First session: onboarding (delete this section when done)
Run it bite-size: one question at a time, short messages.
1. **Interview the owner** about what the company does (check its website if there is one), who the customers are, how money comes in, what the owner does daily and weekly, which tasks repeat, which tools and accounts they use, what takes the most time, and their limits (time, monthly budget, which channels they're comfortable with).
2. **Save** the answers to memory/company.md and memory/processes.md. Fill in the Company overview and Goals above, and the Goals in tasks.md.
3. **Rank** processes by money impact and ease of automation. Check the legal and terms-of-service limits of each channel in the owner's country before proposing it.
4. **Set up the COO channel.** Help the owner create a Telegram bot (@BotFather), put the token in .env, and send /start. Then explain in three lines how they'll hear from you: the daily brief, urgent pings only, and one-tap buttons for decisions.
5. **Create the mission board.** Write the goals from the interview and the first missions into memory/ops_seed.json (goals with Goal/Priority/Status/Metric/Target; missions with Mission/Goal/Owner/Status/Priority/Definition of done, optionally Parent mission and Workflow). Then run `.venv/bin/python scripts/ops_db.py --seed --show`. From then on, keep the board current.
6. **Propose ONE first workflow**, the one closest to revenue, built to the Workflow standard (goal and metric, quality checks, watchers, logging). Include its plan and expected monthly cost. Wait for approval before building it.

"""


def build_claude_md(src: str) -> str:
    s = re.sub(r"^# .*", "# {{COMPANY}} operations", src, count=1)
    s = re.sub(r"## Company overview.*?(?=## Layout)", ONBOARDING, s, flags=re.S)
    s = re.sub(r"09:00 [A-Za-z ]*?time", "09:00 local time", s)
    s = re.sub(r"`[a-z0-9-]+-bridge`", "`{{SLUG}}-bridge`", s)
    s = re.sub(r"`<slug>-bridge`", "`{{SLUG}}-bridge`", s)
    s = re.sub(r"^- Template for new companies:.*\n", "", s, flags=re.M)
    s = re.sub(r" \(the owner allowed this, [0-9-]+\)", "", s)
    # Company-specific sections become generic placeholders
    s = re.sub(r"## CURRENT FOCUS.*?(?=\n## )", """## CURRENT FOCUS
(None yet. After onboarding, set ONE test with a dated pass bar in memory/decisions.md and write it here. The COO holds the CEO to it: **no new tools or side projects** unless they serve the test or something is broken. Park new ideas in memory/ideas.md. At the end, evidence decides.)
""", s, flags=re.S)
    s = re.sub(r"`[a-z0-9-]+\.code-workspace` \([^)]*\)", "`{{SLUG}}.code-workspace`", s)
    s = re.sub(r"Product code \(`[^`]*`\)", "Product code", s)
    s = s.replace("Workflows can attach brief messages", "Workflows can attach brief messages")
    # Describe only the workflows the kit ships; a company's own workflows stay with the company.
    kit_workflows = {f.stem for f in (TEMPLATE / "workflows").glob("*.py")}
    s = re.sub(r"^- `workflows/(\w+)\.py`.*?(?=^- |^#|\Z)",
               lambda m: m.group(0) if m.group(1) in kit_workflows else "", s, flags=re.M | re.S)
    s = s.replace(" Validation tables: `scripts/validation_db.py`.", "")
    s = re.sub(r"^- Teable \(database and UI\).*\n", "", s, flags=re.M)
    s = re.sub(r"^- Backups: `workflows/backup_teable\.py`.*\n", "", s, flags=re.M)
    s = re.sub(r"^- \*\*Mission board\*\* \(Teable.*$", lambda m: MISSION_BOARD, s, flags=re.M)
    return s


# Never copied into the kit: scripts specific to one company, and the Teable-era board that the
# kit replaced with SQLite (the live project still runs Teable until it migrates).
COMPANY_SCRIPTS = {"validation_db.py", "teable.py", "ops_db.py"}

MISSION_BOARD = "- **Mission board** (`ops.db`, SQLite: Goals → Missions with sub-missions → Activity), modeled on Paperclip. Claude keeps it current: update mission status and outcome when work moves, and add one Activity row per meaningful step (`ops_db.log(mission, who, what, cost)`). New work starts as a mission linked to a goal. Automated workflows also keep their task line in tasks.md (the heartbeat's schedule). It holds operations only; the company's own data (customers, orders) stays in its own tools. The CEO sees it in the brief and with `steerable board`. If they want it in Sheets, Airtable or Monday, build a one-way mirror workflow; ops.db stays the source of truth. Code: `scripts/ops_db.py`. Starting data: `memory/ops_seed.json`."



def strip_bridge(src: str) -> str:
    """Remove company-specific imports and Telegram button handlers from bridge.py."""
    for line in ("import teable\n", "import validation_db\n", "from ops_db import record_event\n"):
        src = src.replace(line, "", 1)
    return re.sub(r'    elif data\[:3\] in \("qp:", "qs:"\):.*?(?=    else:\n)', "", src, flags=re.S)


def main(project: Path) -> None:
    for f in (project / "scripts").glob("*.py"):
        if f.name not in COMPANY_SCRIPTS:
            shutil.copy2(f, TEMPLATE / "scripts" / f.name)
    bridge = TEMPLATE / "scripts" / "bridge.py"
    bridge.write_text(strip_bridge(bridge.read_text()))
    for name in (".gitignore", "requirements.txt"):
        shutil.copy2(project / name, TEMPLATE / name)
    shutil.copy2(project / "memory/README.md", TEMPLATE / "memory/README.md")
    ideas = (project / "memory/ideas.md").read_text()
    (TEMPLATE / "memory/ideas.md").write_text(ideas.split("|---|")[0] + "|---|---|---|---|\n")
    for wf in ("_template.py",):  # infrastructure workflows every company gets
        shutil.copy2(project / "workflows" / wf, TEMPLATE / "workflows" / wf)
    env = (project / ".env.example").read_text()
    (TEMPLATE / ".env.example").write_text(
        re.sub(r"^COMPANY_NAME=.*$", "COMPANY_NAME={{COMPANY}}", env, flags=re.M))
    (TEMPLATE / "CLAUDE.md").write_text(build_claude_md((project / "CLAUDE.md").read_text()))
    print(f"template/ refreshed from {project}. Review with: git diff")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
