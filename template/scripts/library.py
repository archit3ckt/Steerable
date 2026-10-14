"""The company library: tables of records the owner looks up and changes (job openings, leads,
suppliers, orders), kept by the COO and its routines. Records, not working state (state.py) and
not knowledge (memory/ and skills). Stored in library.db in the company folder, so it's exported
and moved with the company. Nothing is ever deleted: rows are archived.

Columns are typed and values checked: text, longtext, number, date (YYYY-MM-DD), status (one of
its labels), person, link (http/https), checkbox, relation (a row of another table), tags (several
labels, any or from a list: Tags:tags or Tags:tags(Remote|Urgent)) and files (files kept by
files.py, by id). Each table has views (grid, kanban by a status, calendar by a date: their
filters, sort, grouping and hidden columns), and rows have comments (the owner can ask the COO). Rows can
carry a key (a job's ID, a lead's email) so a routine adds-or-updates without duplicates. Every
change is kept in history with who made it: you (the owner, through the app), coo (the chat),
or autopilot (an approved routine). The owner's changes are signals the learning review reads.

Each change also keeps the values it replaced and the run that made it (STEERABLE_RUN, set by the
heartbeat for a routine's run and by the bridge for a chat turn), so the app shows what one run
changed as a table: rows added, cells changed from → to, rows archived (run_counts, run_changes).
Those values are kept for DETAIL_DAYS; the history lines stay.

Python, for routines:
    import library
    jobs = library.table("Job openings", columns="Title:text, Company:text, Link:link, "
                         "Status:status(New|Interesting|Applied|Interview|Offer|Rejected), Found:date")
    jobs.add({"Title": "DevOps Engineer", "Link": url, "Status": "New"}, key="board:38500710")
    jobs.update("board:38500710", {"Status": "Applied"})
    jobs.rows(where={"Status": "New"})

CLI, for the COO in the chat:
    .venv/bin/python scripts/library.py tables
    .venv/bin/python scripts/library.py create "Leads" --columns "Name:text, Status:status(New|Contacted|Won|Lost), Value:number"
    .venv/bin/python scripts/library.py add "Leads" --set Name="Café Luna" Status=New
    .venv/bin/python scripts/library.py update "Leads" <row id or key> --set Status=Contacted
    .venv/bin/python scripts/library.py find "Leads" --where Status=New
    .venv/bin/python scripts/library.py columns "Leads" --add "Next step:date"
    .venv/bin/python scripts/library.py view "Leads" "Pipeline" --type kanban --by Status
    .venv/bin/python scripts/library.py view "Leads" "Follow-ups" --type calendar --by "Next step"
"""
import argparse
import contextvars
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from common import ROOT, now_iso

DB = ROOT / "library.db"
TYPES = ("text", "longtext", "number", "date", "status", "person", "link", "checkbox", "relation", "tags", "files")
VIEW_TYPES = ("grid", "kanban", "calendar")
MAX_VIEWS = 30
LIMITS = {"text": 1000, "longtext": 20000, "person": 200, "link": 2000}
DETAIL_DAYS = 90  # how long a change's old and new values are kept (what a run's change table shows)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tables (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '', options TEXT NOT NULL DEFAULT '{}',
    created TEXT NOT NULL, updated TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS columns (id TEXT PRIMARY KEY, table_id TEXT NOT NULL, name TEXT NOT NULL COLLATE NOCASE,
    type TEXT NOT NULL, options TEXT NOT NULL DEFAULT '{}', position INTEGER NOT NULL, UNIQUE (table_id, name));
CREATE TABLE IF NOT EXISTS rows (id TEXT PRIMARY KEY, table_id TEXT NOT NULL, key TEXT, cells TEXT NOT NULL DEFAULT '{}',
    created TEXT NOT NULL, updated TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, UNIQUE (table_id, key));
CREATE INDEX IF NOT EXISTS rows_table ON rows (table_id, archived, updated);
CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, table_id TEXT NOT NULL, row_id TEXT,
    who TEXT NOT NULL, what TEXT NOT NULL, at TEXT NOT NULL,
    run TEXT, kind TEXT, before TEXT, after TEXT);
CREATE INDEX IF NOT EXISTS history_at ON history (at);
CREATE TABLE IF NOT EXISTS views (id TEXT PRIMARY KEY, table_id TEXT NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}', position INTEGER NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS views_table ON views (table_id, position);
CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, table_id TEXT NOT NULL, row_id TEXT NOT NULL, who TEXT NOT NULL,
    text TEXT NOT NULL, at TEXT NOT NULL, ask INTEGER NOT NULL DEFAULT 0, status TEXT);
CREATE INDEX IF NOT EXISTS comments_row ON comments (row_id, at);
"""
# Libraries made before changes were kept per run get the columns, then the index that uses them.
UPGRADE = [("run", "TEXT"), ("kind", "TEXT"), ("before", "TEXT"), ("after", "TEXT")]


class LibraryError(Exception):
    """Something to tell the owner or the COO, in plain words."""


_local = threading.local()


def _open() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    # SQLite's LOWER() only knows English letters; FOLD lowercases every alphabet (Greek, Cyrillic, accents).
    con.create_function("FOLD", 1, lambda v: v.casefold() if isinstance(v, str) else v, deterministic=True)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, and each save is quick
    con.executescript(SCHEMA)
    have = {r["name"] for r in con.execute("PRAGMA table_info(history)")}
    for name, kind in UPGRADE:
        if name not in have:
            con.execute(f"ALTER TABLE history ADD COLUMN {name} {kind}")
    con.execute("CREATE INDEX IF NOT EXISTS history_run ON history (run, table_id, row_id)")
    con.commit()
    return con


@contextmanager
def connect():
    """The library, saved after each use. One connection per thread, kept open, so a routine adding
    thousands of rows doesn't reopen the database for each (opened again if the file was replaced)."""
    try:
        ident = DB.stat().st_ino
    except OSError:
        ident = None
    cached = getattr(_local, "con", None)
    if cached is None or _local.ident != ident or _local.path != DB:
        if cached is not None:
            cached.close()
        _local.con, _local.path = _open(), DB
        _local.ident = DB.stat().st_ino
    con = _local.con
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise


_acting = contextvars.ContextVar("library_acting", default=None)


@contextmanager
def acting(name: str):
    """Changes made inside are by `name` (the agent API: "you", for the owner's own edits)."""
    token = _acting.set(name)
    try:
        yield
    finally:
        _acting.reset(token)


def who() -> str:
    """Who's making a change: as set by acting(), else from how this code was started."""
    if _acting.get():
        return _acting.get()
    return "autopilot" if os.environ.get("STEERABLE_CONTEXT") == "routine" else "coo"


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def _dry() -> bool:
    return os.environ.get("STEERABLE_DRY_RUN") == "1"


# ---------- columns ----------

COLUMN = re.compile(r"^\s*(?P<name>[^:]{1,60}?)\s*:\s*(?P<type>[a-z]+)\s*(?:\((?P<opts>[^)]*)\))?\s*$")


def _practice(table: str, change: str, cells: dict, key: str | None) -> None:
    """A practice run's library write, for its trace: what it would add or change, briefly."""
    import runtrace

    shown = {str(k)[:40]: (v if not isinstance(v, str) or len(v) <= 120 else v[:119] + "\u2026")
             for k, v in list((cells or {}).items())[:8]}
    runtrace.event("record", table=table, change=change, cells=shown, key=(key or "")[:120] or None)


def parse_columns(spec: str) -> list[dict]:
    """ "Name:text, Status:status(New|Won), Customer:relation(Customers)" -> column definitions."""
    out = []
    for part in [p for p in re.split(r",(?![^(]*\))", spec or "") if p.strip()]:
        m = COLUMN.match(part)
        if not m or m["type"] not in TYPES:
            raise LibraryError(f"Columns are Name:type, with type one of {', '.join(TYPES)}. This one isn't: {part.strip()}")
        col = {"name": m["name"].strip(), "type": m["type"], "options": {}}
        if m["type"] == "status":
            labels = [x.strip() for x in (m["opts"] or "").split("|") if x.strip()]
            if not labels:
                raise LibraryError(f"A status column needs its labels, like Status:status(New|Done). ({col['name']})")
            col["options"] = {"labels": labels}
        elif m["type"] == "number" and m["opts"]:
            col["options"] = {"unit": m["opts"].strip()[:4]}
        elif m["type"] == "tags" and m["opts"]:
            col["options"] = {"labels": [x.strip() for x in m["opts"].split("|") if x.strip()]}
        elif m["type"] == "relation":
            if not m["opts"]:
                raise LibraryError(f"A relation names its table, like Customer:relation(Customers). ({col['name']})")
            col["options"] = {"table": m["opts"].strip()}
        out.append(col)
    return out


def _check(col: dict, value, con) -> object:
    """A value as the column keeps it, or a LibraryError saying why it doesn't fit."""
    if value is None or value == "":
        return None
    kind, name = col["type"], col["name"]
    if kind in ("text", "longtext", "person"):
        value = str(value).strip()
        if len(value) > LIMITS[kind]:
            raise LibraryError(f"{name} is too long ({len(value)} characters; up to {LIMITS[kind]}).")
        return value
    if kind == "number":
        try:
            return float(str(value).replace(",", "").replace("$", "").strip())
        except ValueError:
            raise LibraryError(f"{name} takes a number, not “{value}”.") from None
    if kind == "date":
        text = str(value).strip()
        try:
            return (datetime.fromisoformat(text).date() if "T" in text else date.fromisoformat(text)).isoformat()
        except ValueError:
            raise LibraryError(f"{name} takes a date as YYYY-MM-DD, not “{value}”.") from None
    if kind == "status":
        labels = col["options"].get("labels", [])
        match = next((x for x in labels if x.lower() == str(value).strip().lower()), None)
        if not match:
            raise LibraryError(f"{name} is one of {', '.join(labels)}, not “{value}”.")
        return match
    if kind == "link":
        text = str(value).strip()
        if not re.match(r"^https?://\S+$", text) or len(text) > LIMITS["link"]:
            raise LibraryError(f"{name} takes a web address starting with https://, not “{value}”.")
        return text
    if kind == "checkbox":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes", "1", "x", "on"):
            return True
        if text in ("false", "no", "0", "", "off"):
            return False
        raise LibraryError(f"{name} is yes or no, not “{value}”.")
    if kind == "tags":
        items = value if isinstance(value, list) else str(value).split(",")
        out, labels = [], col["options"].get("labels")
        for item in items:
            text = str(item).strip()[:100]
            if not text:
                continue
            if labels:
                match = next((x for x in labels if x.lower() == text.lower()), None)
                if not match:
                    raise LibraryError(f"{name} takes {', '.join(labels)}, not “{text}”.")
                text = match
            if text not in out:
                out.append(text)
        return out[:30] or None
    if kind == "files":
        import files

        ids = value if isinstance(value, list) else str(value).split(",")
        out = []
        for fid in [str(x).strip() for x in ids if str(x).strip()][:20]:
            try:
                files.find(fid)
            except files.FileError:
                raise LibraryError(f"{name}: there's no file {fid}. Attach it first.") from None
            if fid not in out:
                out.append(fid)
        return out or None
    if kind == "relation":
        target = _table_row(con, col["options"].get("table", ""))
        row = _find_row(con, target["id"], str(value)) if target else None
        if not row:
            raise LibraryError(f"{name} links to a row of {col['options'].get('table')}; “{value}” isn't one.")
        return row["id"]
    return value


# ---------- tables and rows ----------

def _table_row(con, ref: str):
    return con.execute("SELECT * FROM tables WHERE (id = ? OR name = ?) AND archived = 0", (ref, ref)).fetchone()


def _columns(con, table_id: str) -> list[dict]:
    return [{"id": r["id"], "name": r["name"], "type": r["type"], "options": json.loads(r["options"])}
            for r in con.execute("SELECT * FROM columns WHERE table_id = ? ORDER BY position", (table_id,))]


def _say(value) -> str:
    """A value in a history line: 999, not 999.0; yes/no for a checkbox."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _find_row(con, table_id: str, ref: str):
    return con.execute("SELECT * FROM rows WHERE table_id = ? AND (id = ? OR key = ?)", (table_id, ref, ref)).fetchone()


def _history(con, table_id: str, row_id: str | None, what: str, kind: str | None = None,
             before: dict | None = None, after: dict | None = None) -> None:
    """One line of history. Row changes also keep their kind (add, change, archive, restore), the
    cells they replaced and set (by column id), and the run that made them."""
    con.execute("INSERT INTO history (table_id, row_id, who, what, at, run, kind, before, after) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (table_id, row_id, who(), what, now_iso(), os.environ.get("STEERABLE_RUN") or None, kind,
                 json.dumps(before) if before else None, json.dumps(after) if after else None))


def tables() -> list[dict]:
    with connect() as con:
        rows = con.execute("""SELECT t.*, (SELECT COUNT(*) FROM rows r WHERE r.table_id = t.id AND r.archived = 0) AS n
                              FROM tables t WHERE t.archived = 0 ORDER BY t.updated DESC""").fetchall()
        return [{"id": t["id"], "name": t["name"], "description": t["description"], "rows": t["n"], "updated": t["updated"],
                 "columns": [c["name"] for c in _columns(con, t["id"])]} for t in rows]


def table(name: str, columns: str = "", description: str = "") -> "Table":
    """The table with this name, created if it doesn't exist; any columns it lacks are added."""
    if not name.strip() or len(name) > 80:
        raise LibraryError("Give the table a name, up to 80 characters.")
    wanted = parse_columns(columns)
    with connect() as con:
        t = _table_row(con, name.strip())
        if not t:
            if not wanted:
                raise LibraryError(f"There's no table called {name}. Create it with its columns.")
            if _dry():  # a practice run: a table in memory only, so its checks still run
                return Table({"id": "dry", "name": name.strip()}, [{**c, "id": f"dry_{i}"} for i, c in enumerate(wanted)])
            tid, now = _id("t"), now_iso()
            con.execute("INSERT INTO tables (id, name, description, created, updated) VALUES (?, ?, ?, ?, ?)",
                        (tid, name.strip(), description.strip()[:500], now, now))
            _history(con, tid, None, f"Created the table {name.strip()}")
            t = _table_row(con, tid)
        have = {c["name"].lower() for c in _columns(con, t["id"])}
        extra = []
        for i, col in enumerate(wanted):
            if col["name"].lower() not in have:
                if _dry():
                    extra.append({**col, "id": f"dry_{i}"})  # added for real on the first real run
                else:
                    _add_column(con, t["id"], col)
        return Table(dict(t), _columns(con, t["id"]) + extra)


def _add_column(con, table_id: str, col: dict) -> None:
    if col["type"] == "relation" and not _table_row(con, col["options"]["table"]):
        raise LibraryError(f"There's no table called {col['options']['table']} to link to.")
    position = con.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM columns WHERE table_id = ?", (table_id,)).fetchone()[0]
    con.execute("INSERT INTO columns (id, table_id, name, type, options, position) VALUES (?, ?, ?, ?, ?, ?)",
                (_id("c"), table_id, col["name"], col["type"], json.dumps(col["options"]), position))
    _history(con, table_id, None, f"Added the column {col['name']}")


class Table:
    def __init__(self, row: dict, columns: list[dict]):
        self.id, self.name, self.columns = row["id"], row["name"], columns

    def _by_name(self, cells: dict, con) -> dict:
        by_name = {c["name"].lower(): c for c in self.columns}
        out = {}
        for name, value in cells.items():
            col = by_name.get(str(name).lower())
            if not col:
                raise LibraryError(f"{self.name} has no column {name}. Its columns: {', '.join(c['name'] for c in self.columns)}.")
            out[col["id"]] = _check(col, value, con)
        return out

    def _out(self, r) -> dict:
        names = {c["id"]: c["name"] for c in self.columns}
        cells = json.loads(r["cells"])
        return {"id": r["id"], "key": r["key"], "created": r["created"], "updated": r["updated"],
                "archived": bool(r["archived"]), "cells": {names[k]: v for k, v in cells.items() if k in names}}

    def add(self, cells: dict, key: str | None = None, overwrite: bool = False) -> str:
        """Add a row. With a key that's already there, the row gets the cells it doesn't have yet,
        so what the owner changed stays (overwrite=True replaces them, for values that really change,
        like a price); an archived row stays archived. Returns the row's id."""
        if _dry():
            with connect() as con:
                self._by_name(cells, con)  # still checked
                there = bool(key) and self.id != "dry" and _find_row(con, self.id, key) is not None
            _practice(self.name, "update" if there else "add", cells, key)
            return "dry"
        with connect() as con:
            values = self._by_name(cells, con)
            if key and (existing := _find_row(con, self.id, key)):
                if existing["archived"]:
                    return existing["id"]
                if not overwrite:
                    have = json.loads(existing["cells"])
                    values = {k: v for k, v in values.items() if have.get(k) in (None, "")}
                return self._update(con, existing, values)
            for col in self.columns:  # a status starts at its first label
                if col["type"] == "status" and values.get(col["id"]) is None:
                    values[col["id"]] = col["options"]["labels"][0]
            rid, now = _id("r"), now_iso()
            cells = {k: v for k, v in values.items() if v is not None}
            con.execute("INSERT INTO rows (id, table_id, key, cells, created, updated) VALUES (?, ?, ?, ?, ?, ?)",
                        (rid, self.id, key, json.dumps(cells), now, now))
            con.execute("UPDATE tables SET updated = ? WHERE id = ?", (now, self.id))
            _history(con, self.id, rid, "Added it", "add", after=cells)
            return rid

    def update(self, ref: str, cells: dict) -> str:
        if _dry():
            _practice(self.name, "update", cells, ref)
            return ref
        with connect() as con:
            row = _find_row(con, self.id, ref)
            if not row:
                raise LibraryError(f"{self.name} has no row {ref}.")
            return self._update(con, row, self._by_name(cells, con))

    def _update(self, con, row, values: dict) -> str:
        names = {c["id"]: c["name"] for c in self.columns}
        cells = json.loads(row["cells"])
        changes, before, after = [], {}, {}
        for cid, value in values.items():
            if cells.get(cid) != value:
                changes.append(f"Set {names[cid]} to {_say(value)}" if value is not None else f"Cleared {names[cid]}")
                before[cid], after[cid] = cells.get(cid), value
                if value is None:
                    cells.pop(cid, None)
                else:
                    cells[cid] = value
        if changes:
            now = now_iso()
            con.execute("UPDATE rows SET cells = ?, updated = ? WHERE id = ?", (json.dumps(cells), now, row["id"]))
            con.execute("UPDATE tables SET updated = ? WHERE id = ?", (now, self.id))
            _history(con, self.id, row["id"], "; ".join(changes), "change", before=before, after=after)
        return row["id"]

    def archive(self, ref: str) -> None:
        if _dry():
            _practice(self.name, "archive", {}, ref)
            return
        with connect() as con:
            row = _find_row(con, self.id, ref)
            if not row:
                raise LibraryError(f"{self.name} has no row {ref}.")
            con.execute("UPDATE rows SET archived = 1, updated = ? WHERE id = ?", (now_iso(), row["id"]))
            _history(con, self.id, row["id"], "Archived it", "archive")

    def restore(self, ref: str) -> None:
        if _dry():
            return
        with connect() as con:
            row = _find_row(con, self.id, ref)
            if not row:
                raise LibraryError(f"{self.name} has no row {ref}.")
            con.execute("UPDATE rows SET archived = 0, updated = ? WHERE id = ?", (now_iso(), row["id"]))
            _history(con, self.id, row["id"], "Brought it back", "restore")

    def get(self, ref: str) -> dict | None:
        with connect() as con:
            r = _find_row(con, self.id, ref)
            return self._out(r) if r else None

    def rows(self, where: dict | None = None, limit: int = 500, offset: int = 0, archived: bool = False) -> list[dict]:
        """Rows, newest change first, whose cells equal `where` (by column name, any case for text)."""
        with connect() as con:
            found = [self._out(r) for r in con.execute(
                "SELECT * FROM rows WHERE table_id = ? AND archived = ? ORDER BY updated DESC", (self.id, int(archived)))]
        names = {c["name"].lower(): c["name"] for c in self.columns}
        for name, value in (where or {}).items():
            if str(name).lower() not in names:
                raise LibraryError(f"{self.name} has no column {name}.")
            col = names[str(name).lower()]
            found = [r for r in found if str(r["cells"].get(col, "")).lower() == str(value).lower()]
        return found[offset: offset + max(1, min(limit, 5000))]

    def _cell(self, col: dict) -> str:
        return f"json_extract(cells, '$.\"{col['id']}\"')"  # ids are c_<hex>

    def _col(self, name: str) -> dict:
        col = next((c for c in self.columns if c["name"].lower() == str(name).lower()), None)
        if not col:
            raise LibraryError(f"{self.name} has no column {name}.")
        return col

    def _key(self, col: dict) -> tuple[str, list]:
        """How a column sorts in SQL: a status by its labels' order, text without case."""
        key, args = self._cell(col), []
        if col["type"] == "status" and col["options"].get("labels"):
            labels = col["options"]["labels"]
            key = "CASE " + " ".join(f"WHEN {self._cell(col)} = ? THEN {i}" for i in range(len(labels))) + " END"
            args = list(labels)
        elif col["type"] in ("text", "longtext", "person", "link", "tags"):
            key = f"FOLD({key})"
        return key, args

    def query(self, search: str = "", where: dict | None = None, sort: str = "", desc: bool = False,
              limit: int = 100, offset: int = 0, archived: bool = False, group: str = "",
              between: tuple[str, str, str] | None = None) -> dict:
        """A page of rows for the app's views, all in SQL so a big table stays quick: rows whose text
        cells contain every word of `search`, whose cells equal `where` (by column name; a tags column
        contains it), whose date column `between` = (column, from, to) falls in that range, grouped by a
        column (rows ordered by it first, with a count per value in `groups`), sorted by a column (a
        status by its labels' order, empty cells last) or newest first. Also the total, sums of number
        columns over all matching rows, related rows' labels and attached files' names."""
        conds, args = ["table_id = ?", "archived = ?"], [self.id, int(archived)]
        cell = self._cell
        texts = [c for c in self.columns if c["type"] in ("text", "longtext", "person", "link", "status", "tags")]
        for word in (search or "").split()[:8]:
            if texts:
                conds.append("(" + " OR ".join(f"INSTR(FOLD({cell(c)}), ?) > 0" for c in texts) + ")")
                args += [word.casefold()] * len(texts)
        for name, value in (where or {}).items():
            col = self._col(name)
            if value in (None, ""):
                conds.append(f"{cell(col)} IS NULL")
            elif col["type"] == "checkbox":
                conds.append(f"COALESCE({cell(col)}, 0) = ?")
                args.append(1 if str(value).lower() in ("1", "true", "yes") else 0)
            elif col["type"] in ("tags", "files"):
                conds.append(f"EXISTS (SELECT 1 FROM json_each(cells, '$.\"{col['id']}\"') WHERE FOLD(value) = FOLD(?))")
                args.append(str(value))
            else:
                conds.append(f"FOLD(CAST({cell(col)} AS TEXT)) = FOLD(?)")
                args.append(str(value))
        if between:
            col = self._col(between[0])
            if col["type"] != "date":
                raise LibraryError(f"{col['name']} isn't a date column.")
            conds.append(f"{cell(col)} >= ? AND {cell(col)} <= ?")
            args += [between[1], between[2]]
        filt = " AND ".join(conds)
        order, order_args = ["created DESC", "rowid DESC"], []
        if sort:
            key, key_args = self._key(self._col(sort))
            order = [f"({key}) IS NULL", f"({key}) {'DESC' if desc else 'ASC'}", "created DESC"]
            order_args = key_args * 2  # the key appears twice: IS NULL, then the value
        group_col = None
        if group:
            group_col = self._col(group)
            if group_col["type"] in ("longtext", "tags", "files"):
                raise LibraryError(f"Rows can't be grouped by {group_col['name']}.")
            key, key_args = self._key(group_col)
            order = [f"({key}) IS NULL", f"({key})", *order]
            order_args = key_args * 2 + order_args
        limit = max(1, min(int(limit), 500))
        with connect() as con:
            total = con.execute(f"SELECT COUNT(*) FROM rows WHERE {filt}", args).fetchone()[0]
            found = con.execute(f"SELECT * FROM rows WHERE {filt} ORDER BY {', '.join(order)} LIMIT ? OFFSET ?",
                                [*args, *order_args, limit, max(0, int(offset))]).fetchall()
            numbers = [c for c in self.columns if c["type"] == "number"]
            sums = {}
            if numbers and total:
                got = con.execute(f"SELECT {', '.join(f'SUM({cell(c)})' for c in numbers)} FROM rows WHERE {filt}", args).fetchone()
                sums = {c["name"]: got[i] for i, c in enumerate(numbers) if got[i] is not None}
            groups = []
            if group_col:
                key, key_args = self._key(group_col)
                q = con.execute(f"""SELECT {cell(group_col)} AS value, COUNT(*) AS n FROM rows WHERE {filt}
                                    GROUP BY {cell(group_col)} ORDER BY ({key}) IS NULL, ({key})""", [*args, *key_args * 2])
                groups = [{"value": r["value"], "count": r["n"]} for r in q]
                if group_col["type"] == "checkbox":
                    merged: dict = {}
                    for g in groups:
                        merged[bool(g["value"])] = merged.get(bool(g["value"]), 0) + g["count"]
                    groups = [{"value": v, "count": n} for v, n in merged.items()]
            rows = [self._out(r) for r in found]
            related: dict[str, str] = {}
            for c in self.columns:
                if c["type"] == "relation":
                    for r in rows:
                        if r["cells"].get(c["name"]):
                            _row_label(con, r["cells"][c["name"]], related)
                    for g in groups if group_col and group_col["id"] == c["id"] else []:
                        if g["value"]:
                            _row_label(con, g["value"], related)
        return {"total": total, "rows": rows, "sums": sums, "related": related, "groups": groups,
                "files": _file_names(c for r in rows for k, v in r["cells"].items() if isinstance(v, list)
                                     for c in v if any(col["name"] == k and col["type"] == "files" for col in self.columns))}

    # ---------- views ----------

    def _view_config(self, kind: str, config: dict) -> dict:
        """A view's settings, checked: q, sort, dir, where, hidden, group, by (kanban: a status column;
        calendar: a date column)."""
        if kind not in VIEW_TYPES:
            raise LibraryError(f"A view is one of {', '.join(VIEW_TYPES)}.")
        config = config if isinstance(config, dict) else {}
        out: dict = {}
        if config.get("sort"):
            out["sort"] = self._col(config["sort"])["name"]
            out["dir"] = "desc" if config.get("dir") == "desc" else "asc"
        where = config.get("where") or {}
        if not isinstance(where, dict):
            raise LibraryError("A view's filters are column: value.")
        out["where"] = {self._col(k)["name"]: str(v)[:200] for k, v in list(where.items())[:20]}
        hidden = config.get("hidden") or []
        out["hidden"] = [self._col(h)["name"] for h in hidden if isinstance(h, str)][:100]
        if config.get("group"):
            col = self._col(config["group"])
            if col["type"] in ("longtext", "tags", "files"):
                raise LibraryError(f"Rows can't be grouped by {col['name']}.")
            out["group"] = col["name"]
        if kind in ("kanban", "calendar"):
            want = "status" if kind == "kanban" else "date"
            by = config.get("by") or next((c["name"] for c in self.columns if c["type"] == want), None)
            if not by:
                raise LibraryError(f"A {'board' if kind == 'kanban' else 'calendar'} needs a {want} column, and {self.name} has none.")
            col = self._col(by)
            if col["type"] != want:
                raise LibraryError(f"A {'board' if kind == 'kanban' else 'calendar'} is arranged by a {want} column; {col['name']} isn't one.")
            out["by"] = col["name"]
        return out

    def views(self) -> list[dict]:
        """The table's views, in order. A table always has one: a grid of every row."""
        with connect() as con:
            found = con.execute("SELECT * FROM views WHERE table_id = ? ORDER BY position, created", (self.id,)).fetchall()
            if not found and not _dry():
                now = now_iso()
                con.execute("INSERT INTO views (id, table_id, name, type, config, position, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (_id("v"), self.id, "All rows", "grid", "{}", 0, now, now))
                found = con.execute("SELECT * FROM views WHERE table_id = ? ORDER BY position", (self.id,)).fetchall()
        return [{"id": v["id"], "name": v["name"], "type": v["type"], "config": json.loads(v["config"])} for v in found]

    def save_view(self, view_id: str | None, name: str | None = None, kind: str | None = None, config: dict | None = None) -> dict:
        """Add a view (view_id None) or change one's name or settings."""
        if _dry():
            return {"id": "dry", "name": name or "", "type": kind or "grid", "config": config or {}}
        with connect() as con:
            if view_id:
                v = con.execute("SELECT * FROM views WHERE id = ? AND table_id = ?", (view_id, self.id)).fetchone()
                if not v:
                    raise LibraryError(f"{self.name} has no view {view_id}.")
                kind = v["type"]
                name = (name if name is not None else v["name"]).strip()
                config = self._view_config(kind, config if config is not None else json.loads(v["config"]))
            else:
                if con.execute("SELECT COUNT(*) FROM views WHERE table_id = ?", (self.id,)).fetchone()[0] >= MAX_VIEWS:
                    raise LibraryError(f"A table can have up to {MAX_VIEWS} views.")
                kind = kind or "grid"
                name = (name or {"grid": "Grid", "kanban": "Board", "calendar": "Calendar"}.get(kind, "View")).strip()
                config = self._view_config(kind, config or {})
            if not name or len(name) > 60:
                raise LibraryError("Give the view a name, up to 60 characters.")
            now = now_iso()
            if view_id:
                con.execute("UPDATE views SET name = ?, config = ?, updated = ? WHERE id = ?", (name, json.dumps(config), now, view_id))
            else:
                view_id = _id("v")
                position = con.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM views WHERE table_id = ?", (self.id,)).fetchone()[0]
                con.execute("INSERT INTO views (id, table_id, name, type, config, position, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (view_id, self.id, name, kind, json.dumps(config), position, now, now))
        return {"id": view_id, "name": name, "type": kind, "config": config}

    def delete_view(self, view_id: str) -> None:
        """Remove a view (the rows stay; it's only a way of looking at them). The last one can't go."""
        if _dry():
            return
        with connect() as con:
            if con.execute("SELECT COUNT(*) FROM views WHERE table_id = ?", (self.id,)).fetchone()[0] <= 1:
                raise LibraryError("A table keeps at least one view.")
            if not con.execute("DELETE FROM views WHERE id = ? AND table_id = ?", (view_id, self.id)).rowcount:
                raise LibraryError(f"{self.name} has no view {view_id}.")

    # ---------- comments ----------

    def comments(self, ref: str) -> list[dict]:
        with connect() as con:
            row = _find_row(con, self.id, ref)
            if not row:
                return []
            return [{"id": c["id"], "who": c["who"], "text": c["text"], "at": c["at"], "ask": bool(c["ask"]), "status": c["status"]}
                    for c in con.execute("SELECT * FROM comments WHERE row_id = ? ORDER BY at, rowid", (row["id"],))]

    def comment(self, ref: str, text: str, ask: bool = False) -> dict:
        """A comment on a row, by who() is acting. ask: the owner asks the COO to act on it (status "asked")."""
        text = (text or "").strip()
        if not text or len(text) > 5000:
            raise LibraryError("Write a comment, up to 5,000 characters.")
        with connect() as con:
            row = _find_row(con, self.id, ref)
            if not row:
                raise LibraryError(f"{self.name} has no row {ref}.")
            cid, now = _id("m"), now_iso()
            con.execute("INSERT INTO comments (id, table_id, row_id, who, text, at, ask, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (cid, self.id, row["id"], who(), text, now, int(ask), "asked" if ask else None))
        return {"id": cid, "who": who(), "text": text, "at": now, "ask": ask, "status": "asked" if ask else None}

    def answered(self, comment_id: str, status: str = "answered") -> None:
        with connect() as con:
            con.execute("UPDATE comments SET status = ? WHERE id = ? AND table_id = ?", (status, comment_id, self.id))

    def count(self) -> int:
        with connect() as con:
            return con.execute("SELECT COUNT(*) FROM rows WHERE table_id = ? AND archived = 0", (self.id,)).fetchone()[0]

    def history(self, ref: str | None = None, limit: int = 100) -> list[dict]:
        with connect() as con:
            if ref:
                row = _find_row(con, self.id, ref)
                if not row:
                    return []
                q = con.execute("SELECT * FROM history WHERE row_id = ? ORDER BY id DESC LIMIT ?", (row["id"], limit))
            else:
                q = con.execute("SELECT * FROM history WHERE table_id = ? ORDER BY id DESC LIMIT ?", (self.id, limit))
            return [{"who": h["who"], "what": h["what"], "at": h["at"]} for h in q]


def owner_changes(since: str) -> list[dict]:
    """What the owner changed since then (a time, ISO): signals for the learning review."""
    if not DB.exists():
        return []
    with connect() as con:
        q = con.execute("""SELECT h.what, h.at, t.name AS table_name, r.cells, r.table_id FROM history h
                           JOIN tables t ON t.id = h.table_id LEFT JOIN rows r ON r.id = h.row_id
                           WHERE h.who = 'you' AND h.at >= ? ORDER BY h.id""", (since,))
        out = []
        for h in q:
            label = ""
            if h["cells"]:
                cols = {c["id"]: c for c in _columns(con, h["table_id"])}
                first = next((v for k, v in json.loads(h["cells"]).items() if cols.get(k, {}).get("type") in ("text", "person")), "")
                label = f" “{str(first)[:80]}”" if first else ""
            out.append({"table": h["table_name"], "row": label.strip(), "what": h["what"], "at": h["at"]})
        return out


# ---------- what one run changed ----------

# A row's change in a run, from all its history lines in that run: added wins, then archived.
_NET = """CASE WHEN MAX(kind = 'add') THEN 'added' WHEN MAX(kind = 'archive') AND NOT MAX(kind = 'restore') THEN 'archived'
               WHEN MAX(kind = 'restore') AND NOT MAX(kind = 'archive') THEN 'restored' ELSE 'changed' END"""


def run_counts(run: str) -> list[dict]:
    """How many rows a run added, changed and archived, per table: [{table, tableId, added, changed, ...}]."""
    if not run or not DB.exists():
        return []
    with connect() as con:
        q = con.execute(f"""SELECT n.table_id, t.name, n.net, COUNT(*) AS rows FROM
                              (SELECT table_id, {_NET} AS net FROM history
                               WHERE run = ? AND row_id IS NOT NULL AND kind IS NOT NULL GROUP BY table_id, row_id) n
                            JOIN tables t ON t.id = n.table_id GROUP BY n.table_id, n.net ORDER BY t.name""", (run,))
        out: dict[str, dict] = {}
        for r in q:
            out.setdefault(r["table_id"], {"table": r["name"], "tableId": r["table_id"]})[r["net"]] = r["rows"]
        return list(out.values())


def _file_names(ids) -> dict:
    """Attached files' names and kinds, by id (files.py keeps them)."""
    out = {}
    ids = list(dict.fromkeys(ids))
    if not ids:
        return out
    import files

    for fid in ids[:500]:
        try:
            d = files.describe(files.find(fid))
            out[fid] = {"name": d["name"], "kind": d["kind"]}
        except files.FileError:
            out[fid] = {"name": "(a file that's gone)", "kind": "other"}
    return out


def _label_column(columns: list[dict]) -> dict | None:
    return next((c for c in columns if c["type"] in ("text", "person")), columns[0] if columns else None)


def _row_label(con, row_id: str, cache: dict) -> str:
    """A related row as words: its first text cell."""
    if row_id not in cache:
        r = con.execute("SELECT table_id, cells FROM rows WHERE id = ?", (row_id,)).fetchone()
        label = ""
        if r:
            col = _label_column(_columns(con, r["table_id"]))
            label = str(json.loads(r["cells"]).get(col["id"], "")) if col else ""
        cache[row_id] = label[:80] or "(unnamed)"
    return cache[row_id]


def run_changes(run: str, table_id: str | None = None, after: int = 0, limit: int = 50) -> dict:
    """One table's changes in a run, a page of rows at a time (in the order the run touched them):
    {tables: run_counts, table: {id, name, columns: [{name, type}], rows: [{id, change, cells:
    {column: {value, before?}}}], next: cursor or None, details: whether old values are still kept}}.
    `before` is in a cell only when that cell changed (and wasn't new in this run)."""
    counts = run_counts(run)
    if not counts:
        return {"tables": [], "table": None}
    table_id = table_id if any(c["tableId"] == table_id for c in counts) else counts[0]["tableId"]
    limit = max(1, min(limit, 200))
    with connect() as con:
        name = con.execute("SELECT name FROM tables WHERE id = ?", (table_id,)).fetchone()["name"]
        cols = _columns(con, table_id)
        page = con.execute("""SELECT row_id, MIN(id) AS first FROM history
                              WHERE run = ? AND table_id = ? AND row_id IS NOT NULL AND kind IS NOT NULL
                              GROUP BY row_id HAVING MIN(id) > ? ORDER BY first LIMIT ?""",
                           (run, table_id, after, limit + 1)).fetchall()
        more = len(page) > limit
        page = page[:limit]
        ids = [r["row_id"] for r in page]
        marks = ",".join("?" * len(ids))
        lines: dict[str, list] = {}
        for h in con.execute(f"SELECT * FROM history WHERE run = ? AND row_id IN ({marks}) ORDER BY id", (run, *ids)):
            lines.setdefault(h["row_id"], []).append(h)
        current = {r["id"]: r for r in con.execute(f"SELECT id, cells, archived FROM rows WHERE id IN ({marks})", ids)}
        details = True
        rows, shown = [], set()
        for rid in ids:
            hist = lines.get(rid, [])
            kinds = [h["kind"] for h in hist]
            change = ("added" if "add" in kinds else "archived" if "archive" in kinds and "restore" not in kinds
                      else "restored" if "restore" in kinds and "archive" not in kinds else "changed")
            now_cells = json.loads(current[rid]["cells"]) if rid in current else {}
            old, new = {}, {}
            for h in hist:
                if h["kind"] in ("add", "change") and h["after"] is None and h["before"] is None:
                    details = False  # older than DETAIL_DAYS: only the history line is left
                set_now = json.loads(h["after"]) if h["after"] else {}
                was = json.loads(h["before"]) if h["before"] else {}
                for cid, value in set_now.items():
                    if h["kind"] == "change" and cid not in new and change != "added":
                        old[cid] = was.get(cid)
                    new[cid] = value
                if h["kind"] == "change":
                    for cid in was:  # cleared cells are in before only
                        if cid not in set_now:
                            if cid not in new and change != "added":
                                old[cid] = was[cid]
                            new[cid] = None
            shown.update(new if change in ("added", "changed") else ())
            cells = {**now_cells, **new} if change == "added" else {**now_cells}
            rows.append({"id": rid, "change": change, "values": cells, "old": old})
        label = _label_column(cols)
        if label:
            shown.add(label["id"])
        if not shown:  # only archived or restored rows: show what identifies them
            shown = {c["id"] for c in cols[:4]}
        order = [c for c in cols if c["id"] in shown]
        related: dict[str, str] = {}

        def show(col, value):
            return _row_label(con, value, related) if col["type"] == "relation" and value else value

        out_rows = []
        for r in rows:
            cells = {}
            for col in order:
                cell = {"value": show(col, r["values"].get(col["id"]))}
                if col["id"] in r["old"]:
                    cell["before"] = show(col, r["old"][col["id"]])
                cells[col["name"]] = cell
            out_rows.append({"id": r["id"], "change": r["change"], "cells": cells})
    return {"tables": counts, "table": {
        "id": table_id, "name": name, "columns": [{"name": c["name"], "type": c["type"]} for c in order],
        "rows": out_rows, "next": page[-1]["first"] if more else None, "details": details}}


def forget_details(days: int = DETAIL_DAYS) -> int:
    """The daily upkeep: drop the old and new values of changes older than `days` (their history
    lines stay). Returns how many changes it cleared."""
    if not DB.exists():
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with connect() as con:
        return con.execute("UPDATE history SET before = NULL, after = NULL WHERE at < ? AND (before IS NOT NULL OR after IS NOT NULL)",
                           (cutoff,)).rowcount


# ---------- CLI ----------

def _pairs(items: list[str]) -> dict:
    out = {}
    for item in items or []:
        if "=" not in item:
            raise LibraryError(f"Write each value as Column=value, not “{item}”.")
        k, v = item.split("=", 1)
        out[k.strip()] = v
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tables")
    c = sub.add_parser("create")
    c.add_argument("name")
    c.add_argument("--columns", required=True)
    c.add_argument("--description", default="")
    a = sub.add_parser("add")
    a.add_argument("table")
    a.add_argument("--set", nargs="+", required=True)
    a.add_argument("--key")
    a.add_argument("--overwrite", action="store_true", help="with a key that exists: replace its values instead of only filling empty ones")
    u = sub.add_parser("update")
    u.add_argument("table")
    u.add_argument("row")
    u.add_argument("--set", nargs="+", required=True)
    f = sub.add_parser("find")
    f.add_argument("table")
    f.add_argument("--where", nargs="*")
    f.add_argument("--limit", type=int, default=50)
    col = sub.add_parser("columns")
    col.add_argument("table")
    col.add_argument("--add")
    ar = sub.add_parser("archive")
    ar.add_argument("table")
    ar.add_argument("row")
    v = sub.add_parser("view", help="add a view: a grid, a board (kanban) by a status column, or a calendar by a date column")
    v.add_argument("table")
    v.add_argument("name")
    v.add_argument("--type", choices=VIEW_TYPES, default="grid")
    v.add_argument("--by", help="kanban: the status column; calendar: the date column")
    v.add_argument("--sort")
    v.add_argument("--desc", action="store_true")
    v.add_argument("--where", nargs="*", help="Column=value filters")
    v.add_argument("--group", help="grid: the column to group rows by")
    h = sub.add_parser("history")
    h.add_argument("table")
    h.add_argument("row", nargs="?")
    args = parser.parse_args()
    try:
        if args.cmd == "tables":
            print(json.dumps(tables(), indent=1, ensure_ascii=False))
        elif args.cmd == "create":
            t = table(args.name, args.columns, args.description)
            print(f"The table {t.name} is ready, with columns: {', '.join(x['name'] for x in t.columns)}. Tell the owner in a sentence.")
        elif args.cmd == "columns":
            t = table(args.table, args.add or "")
            print(json.dumps(t.columns, indent=1, ensure_ascii=False))
        elif args.cmd == "add":
            print(table(args.table).add(_pairs(args.set), key=args.key, overwrite=args.overwrite))
        elif args.cmd == "update":
            print(table(args.table).update(args.row, _pairs(args.set)))
        elif args.cmd == "find":
            print(json.dumps(table(args.table).rows(where=_pairs(args.where), limit=args.limit), indent=1, ensure_ascii=False))
        elif args.cmd == "archive":
            table(args.table).archive(args.row)
            print("Archived. It can be brought back.")
        elif args.cmd == "view":
            config = {"by": args.by, "sort": args.sort, "dir": "desc" if args.desc else "asc",
                      "where": _pairs(args.where), "group": args.group}
            made = table(args.table).save_view(None, args.name, args.type, {k: v for k, v in config.items() if v})
            print(f"The view {made['name']} is ready in {args.table}. Tell the owner in a sentence where to find it (the table's tabs).")
        elif args.cmd == "history":
            print(json.dumps(table(args.table).history(args.row), indent=1, ensure_ascii=False))
    except LibraryError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
