"""Company mission board in SQLite (ops.db in the project root), modeled on Paperclip's
structure in lightweight form: Goals -> Missions (with sub-missions) -> Activity.

    python scripts/ops_db.py          # create or upgrade the tables (safe to rerun)
    python scripts/ops_db.py --seed   # also seed the starting goals and missions, if empty
    python scripts/ops_db.py --show   # print the board
    python scripts/ops_db.py mission "<mission, or m<id>>" --status Done --outcome "what came of it"
    python scripts/ops_db.py goal "<goal, or g<id>>" --current 3 [--status Achieved]
    python scripts/ops_db.py add-mission "<mission>" --goal "<goal>" --done-when "..." [--owner COO]

    from ops_db import log
    log("Find first customers", "COO", "Drafted 12 outreach emails")

Who uses it:
- Claude keeps it current: mission status, outcomes and cost, and one Activity row per meaningful step.
- The CEO sees it through the brief, `steerable board`, or a mirror the COO builds into
  their own tool (Sheets, Airtable...). The mirror is one-way: this file stays the source of truth.
- tasks.md stays the heartbeat's machine-readable schedule for automated workflows. Missions
  carry the matching workflow name in "workflow".
Only operational state lives here. The company's own data (customers, orders...) stays in its own tools.
"""
import json
import sqlite3
import sys

from common import ROOT, log_run

DB = ROOT / "ops.db"

STATUSES = ["Backlog", "Todo", "In progress", "Waiting on CEO", "Blocked", "Recurring", "Done", "Cancelled"]
OWNERS = ["CEO", "COO", "Workflow"]
_in = lambda values: "(" + ", ".join(f"'{v}'" for v in values) + ")"  # noqa: E731

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    goal TEXT NOT NULL UNIQUE,
    why TEXT,
    metric TEXT,
    target TEXT,
    current TEXT,
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Achieved', 'Dropped')),
    priority TEXT CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
    due TEXT,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS missions (
    id INTEGER PRIMARY KEY,
    mission TEXT NOT NULL UNIQUE,
    goal_id INTEGER REFERENCES goals(id),
    parent_id INTEGER REFERENCES missions(id),
    status TEXT NOT NULL DEFAULT 'Todo' CHECK (status IN {_in(STATUSES)}),
    owner TEXT CHECK (owner IN {_in(OWNERS)}),
    priority TEXT CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
    due TEXT,
    workflow TEXT,
    needs_ceo_approval INTEGER NOT NULL DEFAULT 0,
    budget REAL,
    spent REAL NOT NULL DEFAULT 0,
    definition_of_done TEXT,
    outcome TEXT,
    options TEXT,
    recommendation TEXT,
    recommendation_why TEXT,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    mission_id INTEGER REFERENCES missions(id),
    what TEXT NOT NULL,
    who TEXT CHECK (who IN {_in(OWNERS)}),
    cost REAL NOT NULL DEFAULT 0,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS missions_workflow ON missions(workflow);
CREATE INDEX IF NOT EXISTS activity_mission ON activity(mission_id);
"""


def connect() -> sqlite3.Connection:
    """WAL plus a busy timeout: the heartbeat, incident runs and the bridge may write at once."""
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    _upgrade(con)
    return con


def _upgrade(con: sqlite3.Connection) -> None:
    """Add columns that newer versions expect to boards created before them."""
    goal_cols = {r["name"] for r in con.execute("PRAGMA table_info(goals)")}
    if "current" not in goal_cols:  # where the metric stands now, e.g. "31" of target "40"
        con.execute("ALTER TABLE goals ADD COLUMN current TEXT")
    mission_cols = {r["name"] for r in con.execute("PRAGMA table_info(missions)")}
    for col in ("options", "recommendation", "recommendation_why"):
        # A question for the CEO (scripts/ask.py): JSON options, the COO's pick, and why.
        if col not in mission_cols:
            con.execute(f"ALTER TABLE missions ADD COLUMN {col} TEXT")
    if "ref" not in {r["name"] for r in con.execute("PRAGMA table_info(activity)")}:
        con.execute("ALTER TABLE activity ADD COLUMN ref TEXT")  # the run it's about (its library changes)


def find_mission(con: sqlite3.Connection, title: str | None = None, workflow: str | None = None):
    if title:
        row = con.execute("SELECT * FROM missions WHERE mission = ?", (title,)).fetchone()
        if row:
            return row
    if workflow:
        return con.execute("SELECT * FROM missions WHERE workflow = ? ORDER BY id LIMIT 1", (workflow,)).fetchone()
    return None


def log(mission: str, who: str, what: str, cost: float = 0.0) -> None:
    """Append one Activity row (the audit trail the CEO sees). `mission` is the mission title."""
    with connect() as con:
        m = find_mission(con, mission)
        con.execute("INSERT INTO activity (mission_id, what, who, cost) VALUES (?, ?, ?, ?)",
                    (m["id"] if m else None, what, who, cost))


def record_event(what: str, who: str = "Workflow", mission: str | None = None,
                 workflow: str | None = None, status: str | None = None,
                 cost: float = 0.0, outcome: str | None = None, ref: str | None = None) -> str | None:
    """Keep the board in sync from automated code: log Activity, and optionally set the mission's
    status, add to its spent, or set its outcome. It never raises: the board must not break ops.
    Returns the mission's previous status (useful for restoring it later)."""
    try:
        with connect() as con:
            m = find_mission(con, mission, workflow)
            prev = m["status"] if m else None
            if m and ((status and status != prev) or cost or outcome):
                con.execute("""UPDATE missions SET status = COALESCE(?, status), spent = ROUND(spent + ?, 4),
                               outcome = COALESCE(?, outcome), updated = CURRENT_TIMESTAMP WHERE id = ?""",
                            (status, round(cost, 4), outcome, m["id"]))
            con.execute("INSERT INTO activity (mission_id, what, who, cost, ref) VALUES (?, ?, ?, ?, ?)",
                        (m["id"] if m else None, what, who, cost, ref))
        return prev
    except Exception as e:
        log_run("ops_db", "error", error=repr(e)[:300])
        return None


def settle_approval(workflow: str, approved: bool) -> None:
    """The CEO answered a workflow's approval: its mission stops waiting on them.
    Approved work moves on; rejected work goes back to the backlog. Never raises."""
    try:
        with connect() as con:
            con.execute("""UPDATE missions SET needs_ceo_approval = 0, updated = CURRENT_TIMESTAMP,
                           status = CASE WHEN ? THEN (CASE WHEN status = 'Waiting on CEO' THEN 'In progress' ELSE status END)
                                         ELSE 'Backlog' END
                           WHERE workflow = ? AND status NOT IN ('Done', 'Cancelled')""", (approved, workflow))
    except Exception as e:
        log_run("ops_db", "error", error=repr(e)[:300])


def waiting_on_ceo() -> list[str]:
    """Missions that need the CEO: waiting on them, or approval pending and not finished."""
    try:
        with connect() as con:
            return [r["mission"] for r in con.execute(
                """SELECT mission FROM missions WHERE status NOT IN ('Done', 'Cancelled')
                   AND (status = 'Waiting on CEO' OR needs_ceo_approval) ORDER BY priority, id""")]
    except Exception as e:
        log_run("ops_db", "error", error=repr(e)[:300])
        return []


# memory/ops_seed.json uses the board's display names; map them to columns.
GOAL_FIELDS = {"Goal": "goal", "Why it matters": "why", "Metric": "metric", "Target": "target",
               "Current": "current", "Status": "status", "Priority": "priority", "Due": "due"}
MISSION_FIELDS = {"Mission": "mission", "Status": "status", "Owner": "owner", "Priority": "priority",
                  "Due": "due", "Workflow": "workflow", "Needs CEO approval": "needs_ceo_approval",
                  "Budget": "budget", "Definition of done": "definition_of_done", "Outcome / notes": "outcome"}


def _insert(con: sqlite3.Connection, table: str, fields: dict, mapping: dict, **extra) -> int:
    row = {mapping[k]: v for k, v in fields.items() if k in mapping} | extra
    cur = con.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                      tuple(row.values()))
    return cur.lastrowid


def seed(con: sqlite3.Connection) -> str:
    if con.execute("SELECT 1 FROM missions LIMIT 1").fetchone():
        return "board already has missions; seed skipped"
    data = json.loads((ROOT / "memory" / "ops_seed.json").read_text())
    goal_ids = {g["Goal"]: _insert(con, "goals", g, GOAL_FIELDS) for g in data.get("goals", [])}
    mission_ids = {}
    missions = data.get("missions", [])
    for m in sorted(missions, key=lambda m: "Parent mission" in m):  # parents before children
        mission_ids[m["Mission"]] = _insert(con, "missions", m, MISSION_FIELDS,
                                            goal_id=goal_ids.get(m.get("Goal")),
                                            parent_id=mission_ids.get(m.get("Parent mission")))
    return f"seeded {len(goal_ids)} goals, {len(mission_ids)} missions"


class BoardError(Exception):
    """Something to tell the COO, in plain words."""


def _resolve(con: sqlite3.Connection, table: str, column: str, ref: str, prefix: str):
    """A goal or mission by its id (g3 / m3 / 3), its exact name, or a unique part of its name."""
    ref = (ref or "").strip()
    if not ref:
        raise BoardError("Name it.")
    num = ref[len(prefix):] if ref.lower().startswith(prefix) else ref
    if num.isdigit():
        row = con.execute(f"SELECT * FROM {table} WHERE id = ?", (int(num),)).fetchone()
        if row:
            return row
    row = con.execute(f"SELECT * FROM {table} WHERE lower({column}) = lower(?)", (ref,)).fetchone()
    if row:
        return row
    words = [w for w in ref.lower().split() if len(w) > 2]
    found = [r for r in con.execute(f"SELECT * FROM {table}") if words and all(w in r[column].lower() for w in words)]
    if len(found) == 1:
        return found[0]
    kind = "mission" if table == "missions" else "goal"
    if not found:
        raise BoardError(f"There's no {kind} like \u201c{ref}\u201d. `ops_db.py --show` lists them.")
    raise BoardError(f"Which {kind}? " + "; ".join(f"{prefix}{r['id']} {r[column]}" for r in found[:8]))


def set_mission(ref: str, status: str | None = None, outcome: str | None = None, who: str = "COO") -> dict:
    """Move a mission along (Done, In progress, Blocked...), with what came of it; logged on the board and the timeline."""
    if status and status not in STATUSES:
        raise BoardError(f"Status is one of: {', '.join(STATUSES)}.")
    with connect() as con:
        m = _resolve(con, "missions", "mission", ref, "m")
    words = {"Done": "Done", "Cancelled": "Dropped", "Blocked": "Blocked", "In progress": "Started"}.get(status or "", "Updated")
    record_event(f"{words}: {m['mission']}" + (f". {outcome}" if outcome else ""), who=who, mission=m["mission"],
                 status=status, outcome=outcome)
    return {"id": f"m{m['id']}", "mission": m["mission"], "status": status or m["status"]}


def set_goal(ref: str, current: str | None = None, status: str | None = None) -> dict:
    if status and status not in ("Active", "Achieved", "Dropped"):
        raise BoardError("A goal's status is Active, Achieved or Dropped.")
    with connect() as con:
        g = _resolve(con, "goals", "goal", ref, "g")
        con.execute("UPDATE goals SET current = COALESCE(?, current), status = COALESCE(?, status) WHERE id = ?",
                    (current, status, g["id"]))
        con.execute("INSERT INTO activity (mission_id, what, who) VALUES (NULL, ?, 'COO')",
                    (f"Goal \u201c{g['goal']}\u201d: " + ", ".join(x for x in (f"now {current}" if current else "", status or "") if x),))
    return {"id": f"g{g['id']}", "goal": g["goal"], "current": current or g["current"], "status": status or g["status"]}


def add_mission(title: str, goal: str, done_when: str = "", owner: str = "COO", parent: str | None = None) -> dict:
    if owner not in OWNERS:
        raise BoardError(f"Owner is one of: {', '.join(OWNERS)}.")
    with connect() as con:
        g = _resolve(con, "goals", "goal", goal, "g")
        if con.execute("SELECT 1 FROM missions WHERE lower(mission) = lower(?)", (title.strip(),)).fetchone():
            raise BoardError(f"There's already a mission \u201c{title.strip()}\u201d. Update it instead.")
        pid = _resolve(con, "missions", "mission", parent, "m")["id"] if parent else None
        cur = con.execute("INSERT INTO missions (mission, goal_id, parent_id, owner, definition_of_done) VALUES (?, ?, ?, ?, ?)",
                          (title.strip(), g["id"], pid, owner, done_when or None))
        con.execute("INSERT INTO activity (mission_id, what, who) VALUES (?, ?, 'COO')", (cur.lastrowid, f"New mission: {title.strip()}"))
    return {"id": f"m{cur.lastrowid}", "mission": title.strip(), "goal": g["goal"]}


def open_missions(limit: int = 12) -> list[dict]:
    with connect() as con:
        rows = con.execute("""SELECT m.*, g.goal AS goal_title FROM missions m LEFT JOIN goals g ON g.id = m.goal_id
                              WHERE m.status NOT IN ('Done', 'Cancelled', 'Recurring')
                              ORDER BY m.updated DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def notice_done(said: str, reply: str) -> str | None:
    """After a chat turn: did it say one of the open missions is finished? One cheap decide() call
    (Jev, then Haiku) over all of them; only a confident model answer marks it Done, with the
    owner's words as its outcome. Returns the mission it marked, if any. Never raises."""
    try:
        missions = open_missions()
        if not missions or not (said or "").strip():
            return None
        from decide import decide

        options = {f"m{m['id']}": f"{m['mission']}" + (f" (done when: {m['definition_of_done']})" if m["definition_of_done"] else "")
                   for m in missions}
        options["none"] = "No project was finished in this exchange (the safe answer when it's unclear or only planned)"
        d = decide("In this chat between a business owner and their COO, which one of these projects is now actually "
                   "finished? Only pick one if the conversation clearly says it's done, not planned or in progress.",
                   options, context=f"Owner: {said.strip()[:1500]}\n\nCOO: {(reply or '').strip()[:1500]}", use_cache=False)
        if d.choice == "none" or d.backend.startswith("rules") or d.confidence < 0.85 or d.choice not in options:
            return None
        m = next(x for x in missions if f"m{x['id']}" == d.choice)
        quote = " ".join(said.split())[:200]
        record_event(f"Done: {m['mission']} (from your chat)", who="COO", mission=m["mission"], status="Done",
                     outcome=f"From the chat: \u201c{quote}\u201d")
        log_run("ops_db", "noticed_done", mission=m["id"], backend=d.backend, confidence=round(d.confidence, 2))
        return m["mission"]
    except Exception as e:  # noqa: BLE001 - the board must never break the chat
        log_run("ops_db", "error", error=repr(e)[:300])
        return None


def show(con: sqlite3.Connection) -> None:
    for g in con.execute("SELECT * FROM goals ORDER BY status != 'Active', priority, id"):
        print(f"[{g['priority'] or '--'}] {g['goal']}  ({g['status']}; {g['metric'] or 'no metric'}: "
              f"{g['current'] or '?'} -> {g['target'] or '?'})")
        for m in con.execute("SELECT * FROM missions WHERE goal_id = ? ORDER BY parent_id IS NOT NULL, id", (g["id"],)):
            indent = "      " if m["parent_id"] else "    "
            print(f"{indent}{m['status']:<14} {m['mission']}  [{m['owner'] or '-'}] ${m['spent']:.2f}")
    orphans = con.execute("SELECT * FROM missions WHERE goal_id IS NULL").fetchall()
    if orphans:
        print("[no goal]")
        for m in orphans:
            print(f"    {m['status']:<14} {m['mission']}  [{m['owner'] or '-'}] ${m['spent']:.2f}")


def _cli(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="ops_db.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mission", help="move a mission along")
    m.add_argument("ref")
    m.add_argument("--status", choices=STATUSES)
    m.add_argument("--outcome")
    g = sub.add_parser("goal", help="update a goal's number or status")
    g.add_argument("ref")
    g.add_argument("--current")
    g.add_argument("--status", choices=["Active", "Achieved", "Dropped"])
    a = sub.add_parser("add-mission", help="a new mission under a goal")
    a.add_argument("title")
    a.add_argument("--goal", required=True)
    a.add_argument("--done-when", default="")
    a.add_argument("--owner", choices=OWNERS, default="COO")
    a.add_argument("--parent")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "mission":
            if not args.status and not args.outcome:
                raise BoardError("Give a --status, an --outcome, or both.")
            out = set_mission(args.ref, args.status, args.outcome)
            print(f"{out['id']} \u201c{out['mission']}\u201d is now {out['status']}. It shows on the Goals page.")
        elif args.cmd == "goal":
            if not args.current and not args.status:
                raise BoardError("Give a --current value, a --status, or both.")
            out = set_goal(args.ref, args.current, args.status)
            print(f"{out['id']} \u201c{out['goal']}\u201d: now {out['current'] or '?'} ({out['status']}).")
        else:
            out = add_mission(args.title, args.goal, args.done_when, args.owner, args.parent)
            print(f"Added {out['id']} \u201c{out['mission']}\u201d under \u201c{out['goal']}\u201d.")
    except BoardError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        sys.exit(_cli(sys.argv[1:]))
    with connect() as con:
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("goals", "missions", "activity")}
        print(f"{DB.name}: " + ", ".join(f"{n} {t}" for t, n in counts.items()))
        if "--seed" in sys.argv:
            print(seed(con))
        if "--show" in sys.argv:
            show(con)
