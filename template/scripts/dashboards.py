#!/usr/bin/env python3
"""Dashboards over the library: a page of numbers and charts about the records the business keeps
(how many leads this month, jobs by status, orders per week...). The COO makes them when the owner
asks, and the owner can add, change and arrange charts in the Library too.

A dashboard is a list of widgets, each a plain description, never code or SQL. The engine counts it
in SQL with the same filters as the library's views, so it's always up to date and stays quick:

    {"type": "number",   "title": "Applied this month", "table": "Job openings", "where": {"Status": "Applied"},
                         "date": "Applied on", "period": "month"}                 # vs last month
    {"type": "bars",     "table": "Leads", "by": "Status"}                         # rows per status
    {"type": "bars",     "table": "Leads", "by": "Status", "measure": "sum", "column": "Value"}
    {"type": "trend",    "table": "Job openings", "date": "added", "every": "week", "last": 8}
    {"type": "list",     "table": "Leads", "sort": "Value", "dir": "desc", "limit": 5, "show": ["Name", "Value"]}
    {"type": "progress", "table": "Cafes", "where": {"Status": "Active"}, "goal": 12}

Every widget has a table and may have: title, where ({column: value}, like a view's filters; "" means
empty), measure (count, sum, average, min, max; all but count need a number column in "column"),
date (a date column, or "added": when the row was added) with period (week, month, quarter, year:
number and progress count only this period, and number compares with the one before) or, for trend,
every (day, week, month) and last (how many), and wide (true: the whole width). bars: by (a column:
status, text, person, checkbox, tags or a link to another table) and limit. list: sort, dir, limit (up
to 10) and show (up to 4 columns).

They live in the library database (library.db, so they're in the export), shown in the Library.

    .venv/bin/python scripts/dashboards.py sources                     # tables, their columns and types
    .venv/bin/python scripts/dashboards.py list
    .venv/bin/python scripts/dashboards.py show <dashboard id or name> # its widgets as JSON, and what they show now
    .venv/bin/python scripts/dashboards.py save "Job search" --from drafts/job-search-dashboard.json
    .venv/bin/python scripts/dashboards.py remove <dashboard>

The file for `save` is {"description": "...", "widgets": [...]}, the whole dashboard. Saving a name
that exists updates that dashboard (no duplicates); to change one, start from `show`.

A chart can also sit in a chat reply or a plan: one widget description (not list) in a ```chart block.
The app counts it each time it's shown, so it never goes stale, and the owner can pin it to a dashboard.
Check one first; it prints what it shows now, or what's wrong:

    .venv/bin/python scripts/dashboards.py chart '{"type": "bars", "table": "Leads", "by": "Status"}'

A routine telling the owner about figures it already has (not in a table) gives them instead of a
table: {"type": "bars", "title": "Sales by product", "unit": "$", "items": [{"label": "Mugs", "value": 420}]},
"points": [{"start": "2026-10-05", "value": 3}] with "every" for a trend, "value" (and "previous" with
"period") for a number, "value" and "goal" for progress.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

import library
from common import ROOT, log_run, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS dashboards (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    widgets TEXT NOT NULL DEFAULT '[]', who TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS dashboard_asks (id TEXT PRIMARY KEY, dashboard_id TEXT, text TEXT NOT NULL,
    status TEXT NOT NULL, reply TEXT, made TEXT, at TEXT NOT NULL);
"""
KINDS = ("number", "bars", "trend", "list", "progress")
MEASURES = ("count", "sum", "average", "min", "max")
PERIODS = ("week", "month", "quarter", "year")
EVERY = {"day": 14, "week": 8, "month": 6}  # how many, unless `last` says
ADDED = "added"  # any table's rows: the day each was added
GROUPABLE = ("status", "text", "person", "checkbox", "tags", "relation")
MAX_WIDGETS = 24
MAX_DASHBOARDS = 50
WHO = ("coo", "you", "autopilot")


class DashboardError(Exception):
    """Something to tell the owner or the COO, in plain words."""


class _Conn:
    def __enter__(self):
        self.cm = library.connect()
        con = self.cm.__enter__()
        con.executescript(SCHEMA)
        return con

    def __exit__(self, *exc):
        return self.cm.__exit__(*exc)


def connect() -> _Conn:
    return _Conn()


def _id(prefix: str) -> str:
    return prefix + secrets.token_hex(4)


# ---------- widgets: checked, then counted ----------

def _table(con, ref) -> library.Table:
    row = library._table_row(con, str(ref or "").strip()) if ref else None
    if not row:
        raise DashboardError(f"There's no table called {ref}." if ref else "Say which table the widget counts.")
    return library.Table(dict(row), library._columns(con, row["id"]))


def _column(t: library.Table, name, types: tuple[str, ...] | None = None, what: str = "column") -> dict:
    try:
        col = t._col(str(name))
    except library.LibraryError:
        raise DashboardError(f"{t.name} has no column {name}. Its columns: {', '.join(c['name'] for c in t.columns)}.") from None
    if types and col["type"] not in types:
        raise DashboardError(f"{col['name']} can't be the {what}: it's a {col['type']} column.")
    return col


def _title(w: dict, t: library.Table) -> str:
    """A widget's name when none was given, in plain words."""
    if w["type"] == "list":
        return f"Top {t.name}" if w.get("sort") else f"Latest {t.name}"
    what = "Rows" if w["measure"] == "count" else f"{w['measure'].capitalize()} of {w['column']}"
    if w["type"] == "bars":
        return f"{t.name} by {w['by']}" if w["measure"] == "count" else f"{what} by {w['by']}"
    if w["type"] == "trend":
        added = w["date"] == ADDED
        return f"{t.name} added per {w['every']}" if added and w["measure"] == "count" else f"{what} per {w['every']}"
    period = f" this {w['period']}" if w.get("period") else ""
    return (f"{t.name}{period}" if w["measure"] == "count" else f"{what}{period}")


def clean_widget(con, spec: dict, keep_id: str | None = None) -> dict:
    """A widget as stored: checked against its table, only the fields its type uses."""
    if not isinstance(spec, dict):
        raise DashboardError("A widget is a description like {\"type\": \"number\", \"table\": \"Leads\"}.")
    kind = spec.get("type")
    if kind not in KINDS:
        raise DashboardError(f"A widget's type is one of {', '.join(KINDS)}.")
    t = _table(con, spec.get("table"))
    w: dict = {"id": keep_id or (spec.get("id") if re.fullmatch(r"w[0-9a-f]{8}", str(spec.get("id") or "")) else _id("w")),
               "type": kind, "table": t.id}
    where = spec.get("where") or {}
    if not isinstance(where, dict):
        raise DashboardError("A widget's filters are {column: value}.")
    w["where"] = {_column(t, k)["name"]: ("" if v is None else str(v)[:200]) for k, v in list(where.items())[:10]}

    if kind != "list":
        measure = spec.get("measure") or "count"
        if measure not in MEASURES:
            raise DashboardError(f"A widget counts with one of {', '.join(MEASURES)}.")
        w["measure"] = measure
        if measure != "count":
            if not spec.get("column"):
                raise DashboardError(f"Say which number column to {measure}.")
            w["column"] = _column(t, spec["column"], ("number",), f"one to {measure}")["name"]

    if kind in ("number", "progress", "trend"):
        when = spec.get("date")
        if kind == "trend" or spec.get("period"):
            when = when or ADDED
        if when:
            w["date"] = ADDED if str(when).lower() in (ADDED, "added on", "when added") else _column(t, when, ("date",), "date")["name"]
    if kind in ("number", "progress") and spec.get("period"):
        if spec["period"] not in PERIODS:
            raise DashboardError(f"A period is one of {', '.join(PERIODS)}.")
        w["period"] = spec["period"]
    if kind == "trend":
        every = spec.get("every") or "week"
        if every not in EVERY:
            raise DashboardError(f"A trend goes by {', '.join(EVERY)}.")
        w["every"] = every
        w["last"] = max(2, min(int(spec.get("last") or EVERY[every]), 36))
    if kind == "bars":
        if not spec.get("by"):
            raise DashboardError("Say which column the bars are by.")
        w["by"] = _column(t, spec["by"], GROUPABLE, "one the bars are by")["name"]
        w["limit"] = max(2, min(int(spec.get("limit") or 8), 20))
    if kind == "list":
        if spec.get("sort") and str(spec["sort"]).lower() != ADDED:
            w["sort"] = _column(t, spec["sort"])["name"]
            w["dir"] = "asc" if spec.get("dir") == "asc" else "desc"
        w["limit"] = max(1, min(int(spec.get("limit") or 5), 10))
        show = spec.get("show") or [c["name"] for c in t.columns if c["type"] not in ("longtext", "files")][:3]
        if not isinstance(show, list):
            raise DashboardError("show is a list of columns.")
        w["show"] = [_column(t, c)["name"] for c in show[:4]]
    if kind == "progress":
        try:
            goal = float(spec.get("goal"))
        except (TypeError, ValueError):
            goal = 0
        if goal <= 0:
            raise DashboardError("A progress widget needs a goal above zero.")
        w["goal"] = int(goal) if goal.is_integer() else goal
    if spec.get("wide") is True or (spec.get("wide") is None and kind in ("trend", "list")):
        w["wide"] = True
    title = str(spec.get("title") or "").strip()[:80]
    w["title"] = title or _title(w, t)
    return w


def _bounds(period: str, today: date, back: int = 0) -> tuple[str, str]:
    """The first and last day of this period (back=1: the one before)."""
    if period == "week":
        start = today - timedelta(days=today.weekday() + 7 * back)
        return start.isoformat(), (start + timedelta(days=6)).isoformat()
    if period == "year":
        return f"{today.year - back}-01-01", f"{today.year - back}-12-31"
    months = 3 if period == "quarter" else 1
    first = (today.month - 1) // months * months  # months since January, to the period's start
    index = today.year * 12 + first - back * months
    start = date(index // 12, index % 12 + 1, 1)
    end_index = index + months
    end = date(end_index // 12, end_index % 12 + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _bucket(every: str, day: date) -> date:
    if every == "week":
        return day - timedelta(days=day.weekday())
    if every == "month":
        return day.replace(day=1)
    return day


def _step(every: str, day: date, n: int) -> date:
    if every == "day":
        return day + timedelta(days=n)
    if every == "week":
        return day + timedelta(weeks=n)
    index = day.year * 12 + day.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def compute(con, w: dict, today: date | None = None) -> dict:
    """What a widget shows now. Raises DashboardError when its table or columns are gone."""
    today = today or date.today()
    t = _table(con, w["table"])
    cell = t._cell
    try:
        filt, args = t._filter(where=w.get("where") or {})
    except library.LibraryError as e:
        raise DashboardError(str(e)) from None
    measure = w.get("measure", "count")
    if measure == "count":
        agg = "COUNT(*)"
    else:
        agg = {"sum": "SUM", "average": "AVG", "min": "MIN", "max": "MAX"}[measure] + f"(CAST({cell(_column(t, w['column']))} AS REAL))"
    day = None
    if w.get("date"):
        day = "substr(created, 1, 10)" if w["date"] == ADDED else cell(_column(t, w["date"], ("date",), "date"))
    unit = None
    if measure != "count":
        unit = _column(t, w["column"])["options"].get("unit")
    out: dict = {"unit": unit} if unit else {}

    def one(extra: str = "", extra_args: list | None = None):
        v = con.execute(f"SELECT {agg} FROM rows WHERE {filt}{extra}", [*args, *(extra_args or [])]).fetchone()[0]
        return 0 if v is None and measure in ("count", "sum") else v

    kind = w["type"]
    if kind in ("number", "progress"):
        if w.get("period"):
            now_from, now_to = _bounds(w["period"], today)
            out["value"] = one(f" AND {day} BETWEEN ? AND ?", [now_from, now_to])
            if kind == "number":
                was_from, was_to = _bounds(w["period"], today, 1)
                out["previous"] = one(f" AND {day} BETWEEN ? AND ?", [was_from, was_to])
        else:
            out["value"] = one()
        if kind == "progress":
            out["goal"] = w["goal"]
        return out

    if kind == "trend":
        every, last = w["every"], w["last"]
        end = _bucket(every, today)
        start = _step(every, end, -(last - 1))
        key = {"day": day, "week": f"date({day}, '-6 days', 'weekday 1')", "month": f"substr({day}, 1, 7) || '-01'"}[every]
        upto = _step(every, end, 1) - timedelta(days=1)
        got = {r[0]: r[1] for r in con.execute(
            f"SELECT {key} AS k, {agg} FROM rows WHERE {filt} AND {day} BETWEEN ? AND ? GROUP BY k",
            [*args, start.isoformat(), upto.isoformat()])}
        points = []
        for i in range(last):
            b = _step(every, start, i).isoformat()
            v = got.get(b)
            points.append({"start": b, "value": (0 if v is None and measure in ("count", "sum") else v)})
        out["points"] = points
        return out

    if kind == "bars":
        col = _column(t, w["by"])
        if col["type"] == "tags":
            q = (f"SELECT j.value AS v, {agg} FROM rows, json_each(rows.cells, '$.\"{col['id']}\"') AS j "
                 f"WHERE {filt} GROUP BY j.value")
        elif col["type"] == "checkbox":
            q = f"SELECT COALESCE({cell(col)}, 0) AS v, {agg} FROM rows WHERE {filt} GROUP BY v"
        else:
            q = f"SELECT {cell(col)} AS v, {agg} FROM rows WHERE {filt} GROUP BY v"
        found = [(r[0], 0 if r[1] is None and measure in ("count", "sum") else r[1]) for r in con.execute(q, args)]
        labels = col["options"].get("labels") or []
        if col["type"] == "status" and labels:
            order = {label: i for i, label in enumerate(labels)}
            found.sort(key=lambda x: (x[0] is None, order.get(x[0], len(labels)), str(x[0])))
        elif col["type"] == "checkbox":
            found.sort(key=lambda x: not x[0])
        else:
            found.sort(key=lambda x: (x[0] is None, -(x[1] or 0)))
        names: dict = {}
        items = []
        for value, n in found[: w["limit"]]:
            if col["type"] == "checkbox":
                label, filt_value = ("Yes", "true") if value else ("No", "false")
            elif value is None:
                label, filt_value = f"No {col['name'].lower()}", ""
            elif col["type"] == "relation":
                label, filt_value = library._row_label(con, value, names) or "(a removed row)", value
            else:
                label, filt_value = library._say(value), str(value)
            items.append({"label": label, "value": n, "filter": filt_value})
        out["items"] = items
        out["by"] = col["name"]
        if len(found) > w["limit"]:
            out["more"] = len(found) - w["limit"]
        return out

    # list
    try:
        page = t.query(where=w.get("where") or {}, sort=w.get("sort", ""), desc=w.get("dir") == "desc", limit=w["limit"])
    except library.LibraryError as e:
        raise DashboardError(str(e)) from None
    show = [_column(t, c) for c in w["show"]]
    out["columns"] = [{"name": c["name"], "type": c["type"], **({"unit": c["options"]["unit"]} if c["options"].get("unit") else {})}
                      for c in show]
    out["rows"] = [{"id": r["id"], "cells": {c["name"]: r["cells"].get(c["name"]) for c in show}} for r in page["rows"]]
    out["total"] = page["total"]
    out["related"] = page["related"]
    return out


# ---------- charts in messages ----------

CHART_BLOCK = re.compile(r"```chart[ \t]*\n(.*?)\n?```", re.S)
MAX_ITEMS = 20


def _figure(v, what: str):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise DashboardError(f"{what} is a number.")
    return v


def _given(spec: dict) -> dict:
    """A chart with its own figures (a routine's report): checked, kept as given."""
    kind = spec.get("type")
    if kind not in ("number", "bars", "trend", "progress"):
        raise DashboardError("A chart with its own figures is a number, bars, trend or progress.")
    title = str(spec.get("title") or "").strip()[:80]
    if not title:
        raise DashboardError("A chart with its own figures needs a title saying what they are.")
    w: dict = {"type": kind, "title": title}
    data: dict = {"unit": str(spec["unit"])[:8]} if spec.get("unit") else {}
    if kind in ("number", "progress"):
        data["value"] = _figure(spec.get("value"), "value")
        if kind == "number" and spec.get("period"):
            if spec["period"] not in PERIODS:
                raise DashboardError(f"A period is one of {', '.join(PERIODS)}.")
            w["period"] = spec["period"]
            data["previous"] = _figure(spec.get("previous"), "previous")
        if kind == "progress":
            data["goal"] = _figure(spec.get("goal"), "goal")
            if not data["goal"] or data["goal"] <= 0:
                raise DashboardError("A progress chart needs a goal above zero.")
    elif kind == "bars":
        items = spec.get("items")
        if not isinstance(items, list) or not items:
            raise DashboardError("Bars with their own figures need items: [{\"label\": ..., \"value\": ...}].")
        data["items"] = [{"label": str(i.get("label") or "")[:60], "value": _figure(i.get("value"), "Each bar's value")}
                         for i in items[:MAX_ITEMS] if isinstance(i, dict)]
        if len(items) > MAX_ITEMS:
            data["more"] = len(items) - MAX_ITEMS
    else:
        every = spec.get("every") or "week"
        if every not in EVERY:
            raise DashboardError(f"A trend goes by {', '.join(EVERY)}.")
        w["every"] = every
        points = spec.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise DashboardError("A trend with its own figures needs points: [{\"start\": \"2026-10-05\", \"value\": ...}].")
        clean = []
        for p in points[-36:]:
            start = str(p.get("start") if isinstance(p, dict) else "")
            try:
                date.fromisoformat(start)
            except ValueError:
                raise DashboardError("Each point's start is a date, like 2026-10-05.") from None
            clean.append({"start": start, "value": _figure(p.get("value"), "Each point's value")})
        data["points"] = clean
    return {**w, "data": data}


def chart(spec, today: date | None = None) -> dict:
    """One chart for a message (a ```chart block in the chat or a plan), counted now and kept nowhere:
    the widget as a dashboard would store it, with its table's name and what it shows. One with its
    own figures comes back checked. Anything wrong comes back as {"error": plain words}."""
    if not isinstance(spec, dict):
        return {"error": "A chart is a description like {\"type\": \"bars\", \"table\": \"Leads\", \"by\": \"Status\"}."}
    try:
        if "table" not in spec:
            return _given(spec)
        if spec.get("type") == "list":
            raise DashboardError("A chart in a message is a number, bars, trend or progress; rows belong in a table.")
        with connect() as con:
            w = clean_widget(con, spec)
            w.pop("id", None)
            w.pop("wide", None)
            name = con.execute("SELECT name FROM tables WHERE id = ?", (w["table"],)).fetchone()
            return {**w, "tableName": name[0] if name else None, "data": compute(con, w, today)}
    except (DashboardError, library.LibraryError) as e:
        return {"error": str(e)}


def charts_as_words(text: str) -> str:
    """A message for somewhere that can't draw charts (Telegram): each ```chart block becomes a line of
    what it shows."""
    def line(m: re.Match) -> str:
        try:
            got = chart(json.loads(m.group(1)))
        except ValueError:
            return ""
        if got.get("error"):
            return ""
        return f"{got['title']}: {_says(got)}"
    return CHART_BLOCK.sub(line, text or "")


# ---------- dashboards ----------

def _summary(r) -> dict:
    widgets = json.loads(r["widgets"])
    return {"id": r["id"], "name": r["name"], "description": r["description"], "widgets": len(widgets),
            "titles": [w.get("title", "") for w in widgets][:6], "createdAt": r["created"], "updatedAt": r["updated"],
            "updatedBy": r["who"]}


def dashboards() -> list[dict]:
    """Every dashboard, most recently changed first."""
    with connect() as con:
        return [_summary(r) for r in con.execute("SELECT * FROM dashboards WHERE archived = 0 ORDER BY updated DESC")]


def _row(con, ref: str):
    ref = str(ref or "").strip()
    return con.execute("SELECT * FROM dashboards WHERE archived = 0 AND (id = ? OR name = ? COLLATE NOCASE) "
                       "ORDER BY id = ? DESC LIMIT 1", (ref, ref, ref)).fetchone()


def find(ref: str) -> dict | None:
    with connect() as con:
        r = _row(con, ref)
        return _summary(r) if r else None


def sources() -> list[dict]:
    """The tables a widget can count, with their columns (for the editor and the COO)."""
    with connect() as con:
        out = []
        for t in con.execute("SELECT id, name FROM tables WHERE archived = 0 ORDER BY name COLLATE NOCASE"):
            out.append({"id": t["id"], "name": t["name"],
                        "columns": [{"name": c["name"], "type": c["type"],
                                     **({"labels": c["options"]["labels"]} if c["options"].get("labels") else {}),
                                     **({"unit": c["options"]["unit"]} if c["options"].get("unit") else {})}
                                    for c in library._columns(con, t["id"])]})
        return out


def detail(ref: str, today: date | None = None) -> dict | None:
    """A dashboard with what each widget shows now; a widget whose table or column is gone says so."""
    with connect() as con:
        r = _row(con, ref)
        if not r:
            return None
        widgets = []
        for w in json.loads(r["widgets"]):
            item = dict(w)
            name = con.execute("SELECT name FROM tables WHERE id = ? AND archived = 0", (w.get("table"),)).fetchone()
            item["tableName"] = name[0] if name else None
            try:
                item["data"] = compute(con, w, today)
            except (DashboardError, library.LibraryError) as e:
                item["error"] = str(e)
            except Exception as e:  # noqa: BLE001 - one broken widget mustn't take the dashboard down
                log_run("dashboards", "error", dashboard=r["id"], widget=w.get("id"), error=repr(e)[:300])
                item["error"] = "This chart couldn't be counted. Change it or remove it."
            widgets.append(item)
        return {**_summary(r), "widgets": widgets}


def _save(con, r, widgets: list[dict] | None = None, name: str | None = None, description: str | None = None, who: str = "coo"):
    sets, args = ["updated = ?", "who = ?"], [now_iso(), who if who in WHO else "coo"]
    if widgets is not None:
        sets.append("widgets = ?")
        args.append(json.dumps(widgets))
    if name is not None:
        sets.append("name = ?")
        args.append(name)
    if description is not None:
        sets.append("description = ?")
        args.append(description)
    con.execute(f"UPDATE dashboards SET {', '.join(sets)} WHERE id = ?", [*args, r["id"]])


def _name(name: str) -> str:
    name = " ".join(str(name or "").split())
    if not name or len(name) > 80:
        raise DashboardError("Give the dashboard a name, up to 80 characters.")
    return name


def save(name: str, widgets: list, description: str = "", who: str = "coo", dashboard_id: str | None = None) -> dict:
    """The whole dashboard: updates the one with this id, or this name, or makes a new one."""
    name = _name(name)
    if not isinstance(widgets, list) or len(widgets) > MAX_WIDGETS:
        raise DashboardError(f"A dashboard has a list of up to {MAX_WIDGETS} widgets.")
    with connect() as con:
        r = _row(con, dashboard_id) if dashboard_id else _row(con, name)
        if dashboard_id and not r:
            raise DashboardError("There's no such dashboard.")
        clean = []
        for i, spec in enumerate(widgets):
            try:
                clean.append(clean_widget(con, spec))
            except DashboardError as e:
                raise DashboardError(f"Widget {i + 1}: {e}") from None
        description = str(description or "").strip()[:300]
        if r:
            _save(con, r, clean, name, description, who)
            did, created = r["id"], False
        else:
            if con.execute("SELECT COUNT(*) FROM dashboards WHERE archived = 0").fetchone()[0] >= MAX_DASHBOARDS:
                raise DashboardError(f"The library can have up to {MAX_DASHBOARDS} dashboards. Remove one first.")
            did, now = _id("db"), now_iso()
            con.execute("INSERT INTO dashboards (id, name, description, widgets, who, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (did, name, description, json.dumps(clean), who if who in WHO else "coo", now, now))
            created = True
        out = _summary(_row(con, did))
    log_run("dashboards", "saved", dashboard=did, widgets=len(clean), who=who)
    return {"dashboard": out, "created": created}


def create(name: str, description: str = "", who: str = "you") -> dict:
    """An empty dashboard, made in the Library. A name that's taken is refused (save() would update it)."""
    name = _name(name)
    with connect() as con:
        if _row(con, name):
            raise DashboardError(f"There's already a dashboard called {name}.")
    return save(name, [], description, who)["dashboard"]


def rename(dashboard_id: str, name: str | None = None, description: str | None = None, who: str = "you") -> dict:
    with connect() as con:
        r = _row(con, dashboard_id)
        if not r or r["id"] != dashboard_id:
            raise DashboardError("There's no such dashboard.")
        if name is not None:
            name = _name(name)
            other = _row(con, name)
            if other and other["id"] != dashboard_id:
                raise DashboardError(f"There's already a dashboard called {name}.")
        _save(con, r, None, name, None if description is None else str(description).strip()[:300], who)
        return _summary(_row(con, dashboard_id))


def save_widget(dashboard_id: str, widget_id: str | None, spec: dict, who: str = "you") -> dict:
    """Add a widget (widget_id None, at the end) or change one, keeping its place."""
    with connect() as con:
        r = _row(con, dashboard_id)
        if not r or r["id"] != dashboard_id:
            raise DashboardError("There's no such dashboard.")
        widgets = json.loads(r["widgets"])
        if widget_id:
            at = next((i for i, w in enumerate(widgets) if w.get("id") == widget_id), None)
            if at is None:
                raise DashboardError("That chart isn't on this dashboard any more.")
            widgets[at] = clean_widget(con, spec, keep_id=widget_id)
            made = widgets[at]
        else:
            if len(widgets) >= MAX_WIDGETS:
                raise DashboardError(f"A dashboard can have up to {MAX_WIDGETS} charts.")
            made = clean_widget(con, {**spec, "id": None})
            widgets.append(made)
        _save(con, r, widgets, who=who)
    return made


def change_widget(dashboard_id: str, widget_id: str, action: str, who: str = "you") -> None:
    """remove, up or down (one place earlier or later)."""
    if action not in ("remove", "up", "down"):
        raise DashboardError("A chart can be removed, or moved up or down.")
    with connect() as con:
        r = _row(con, dashboard_id)
        if not r or r["id"] != dashboard_id:
            raise DashboardError("There's no such dashboard.")
        widgets = json.loads(r["widgets"])
        at = next((i for i, w in enumerate(widgets) if w.get("id") == widget_id), None)
        if at is None:
            raise DashboardError("That chart isn't on this dashboard any more.")
        if action == "remove":
            widgets.pop(at)
        else:
            to = at - 1 if action == "up" else at + 1
            if 0 <= to < len(widgets):
                widgets[at], widgets[to] = widgets[to], widgets[at]
        _save(con, r, widgets, who=who)


def remove(dashboard_id: str) -> None:
    """Archive it: it leaves the Library (the records it counted are untouched)."""
    with connect() as con:
        if not con.execute("UPDATE dashboards SET archived = 1, updated = ? WHERE id = ? AND archived = 0",
                           (now_iso(), dashboard_id)).rowcount:
            raise DashboardError("There's no such dashboard.")
    log_run("dashboards", "archived", dashboard=dashboard_id)


# ---------- asking the COO ----------

def ask(text: str, dashboard_id: str | None = None) -> dict:
    """The owner asks the COO for a dashboard (or a change to one); the agent API works on it in the background."""
    text = " ".join(str(text or "").split())
    if not text or len(text) > 2000:
        raise DashboardError("Say what you'd like to see, up to 2,000 characters.")
    with connect() as con:
        if dashboard_id:
            r = _row(con, dashboard_id)
            if not r or r["id"] != dashboard_id:
                raise DashboardError("There's no such dashboard.")
        waiting = con.execute("SELECT COUNT(*) FROM dashboard_asks WHERE status = 'asked' AND at > ?",
                              (_ago(minutes=15),)).fetchone()[0]
        if waiting >= 3:
            raise DashboardError("A few requests are still being worked on. Try again when they're done.")
        aid, now = _id("da"), now_iso()
        con.execute("INSERT INTO dashboard_asks (id, dashboard_id, text, status, at) VALUES (?, ?, ?, 'asked', ?)",
                    (aid, dashboard_id, text, now))
    return {"id": aid, "dashboardId": dashboard_id, "text": text, "status": "asked", "reply": None, "made": None, "at": now}


def answered(ask_id: str, reply: str, status: str = "answered") -> None:
    """The COO's reply; `made` is the dashboard it saved since the ask, if any."""
    with connect() as con:
        a = con.execute("SELECT * FROM dashboard_asks WHERE id = ?", (ask_id,)).fetchone()
        if not a:
            return
        made = con.execute("SELECT id FROM dashboards WHERE archived = 0 AND updated >= ? ORDER BY updated DESC, rowid DESC LIMIT 1",
                           (a["at"],)).fetchone()
        con.execute("UPDATE dashboard_asks SET status = ?, reply = ?, made = ? WHERE id = ?",
                    (status, (reply or "")[:4000], made[0] if made else None, ask_id))


def asks(dashboard_id: str | None = None, hours: int = 24) -> list[dict]:
    """Recent requests (newest first): still being worked on, or answered in the last `hours`.
    Without dashboard_id, the requests for new dashboards."""
    with connect() as con:
        # A request still "asked" after 15 minutes was lost (the engine restarted): say so.
        con.execute("UPDATE dashboard_asks SET status = 'failed', reply = ? WHERE status = 'asked' AND at < ?",
                    ("This request was interrupted. Ask again.", _ago(minutes=15)))
        cond = "dashboard_id = ?" if dashboard_id else "dashboard_id IS NULL"
        rows = con.execute(f"SELECT * FROM dashboard_asks WHERE {cond} AND (status = 'asked' OR at > ?) ORDER BY at DESC LIMIT 5",
                           [*([dashboard_id] if dashboard_id else []), _ago(hours=hours)]).fetchall()
        return [{"id": a["id"], "dashboardId": a["dashboard_id"], "text": a["text"], "status": a["status"],
                 "reply": a["reply"], "made": a["made"], "at": a["at"]} for a in rows]


def _ago(**delta) -> str:
    from datetime import datetime, timezone
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat(timespec="seconds")


def ask_prompt(a: dict, cli: str = ".venv/bin/python scripts/dashboards.py") -> str:
    """What the COO is told for a request from the Library."""
    about = ""
    if a.get("dashboardId"):
        d = find(a["dashboardId"])
        if d:
            about = (f" It's about the dashboard “{d['name']}” ({d['id']}): run `{cli} show {d['id']}` first, change "
                     "that, and save it under the same name.")
    return (f"From the Library, the owner asked for a dashboard: “{a['text']}”.{about}\n\n"
            f"Make it with scripts/dashboards.py: `{cli} sources` lists the tables and their columns. Write the whole "
            f"dashboard as JSON in drafts/ ({{\"description\": ..., \"widgets\": [...]}}, the widget kinds are in "
            f"`{cli} --help`), then `{cli} save \"<name>\" --from drafts/<file>.json` and check that the values it "
            "prints make sense. If the library doesn't have the records for it, say what's missing instead of making "
            "something empty. Reply in a sentence or two about this request only: what the dashboard shows (your reply "
            "is shown in the Library, and here).")


# ---------- the COO's command line ----------

def _read_json(path: str):
    p = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if ROOT.resolve() not in p.parents or not p.is_file():
        raise DashboardError("--from must be a file in the company folder, like drafts/sales-dashboard.json.")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DashboardError(f"That file isn't valid JSON: {e}.") from None


def _read_from(path: str) -> dict:
    data = _read_json(path)
    if isinstance(data, list):
        data = {"widgets": data}
    if not isinstance(data, dict) or not isinstance(data.get("widgets"), list):
        raise DashboardError("The file is {\"description\": \"...\", \"widgets\": [...]}.")
    return data


def _num(v) -> str:
    if v is None:
        return "nothing yet"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return f"{v:,}"


def _says(w: dict) -> str:
    """One line of what a widget shows, for the COO to check."""
    if w.get("error"):
        return f"PROBLEM: {w['error']}"
    d = w["data"]
    if w["type"] == "number":
        was = f" (the {w['period']} before: {_num(d['previous'])})" if "previous" in d else ""
        return f"{_num(d['value'])}{was}"
    if w["type"] == "progress":
        return f"{_num(d['value'])} of {_num(d['goal'])}"
    if w["type"] == "bars":
        more = f", and {d['more']} more" if d.get("more") else ""
        return ", ".join(f"{i['label']}: {_num(i['value'])}" for i in d["items"]) + more or "no rows"
    if w["type"] == "trend":
        return ", ".join(f"{p['start']}: {_num(p['value'])}" for p in d["points"][-6:])
    return f"{len(d['rows'])} of {d['total']} rows"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sources")
    sub.add_parser("list")
    sub.add_parser("show").add_argument("dashboard")
    s = sub.add_parser("save")
    s.add_argument("name")
    s.add_argument("--from", dest="source", required=True, help="the whole dashboard, as JSON (drafts/...)")
    sub.add_parser("remove").add_argument("dashboard")
    c = sub.add_parser("chart", help="check a chart for a message: what it shows now")
    c.add_argument("spec", nargs="?", help="the chart, as JSON")
    c.add_argument("--from", dest="source", help="or a file holding it (drafts/...)")
    args = ap.parse_args()
    try:
        if args.cmd == "sources":
            found = sources()
            if not found:
                print("The library has no tables yet.")
            for t in found:
                cols = ", ".join(f"{c['name']} ({c['type']}{': ' + '|'.join(c['labels']) if c.get('labels') else ''})"
                                 for c in t["columns"])
                print(f"{t['name']}: {cols}")
        elif args.cmd == "list":
            found = dashboards()
            if not found:
                print("No dashboards yet.")
            for d in found:
                print(f"{d['id']}  {d['name']}  ({d['widgets']} widgets, changed {d['updatedAt'][:16].replace('T', ' ')} by {d['updatedBy']})")
        elif args.cmd == "show":
            d = detail(args.dashboard)
            if not d:
                raise DashboardError(f"There's no dashboard called “{args.dashboard}”. `dashboards.py list` shows them.")
            spec = [{k: v for k, v in w.items() if k not in ("data", "error", "tableName", "id")} | {"table": w["tableName"] or w["table"]}
                    for w in d["widgets"]]
            print(f"# {d['name']}  ({d['id']})\n")
            print(json.dumps({"description": d["description"], "widgets": spec}, indent=2, ensure_ascii=False))
            print("\nWhat it shows now:")
            for w in d["widgets"]:
                print(f"- {w['title']}: {_says(w)}")
        elif args.cmd == "save":
            data = _read_from(args.source)
            out = save(args.name, data["widgets"], data.get("description", ""), "coo")
            d = detail(out["dashboard"]["id"])
            print(f"{'Made' if out['created'] else 'Updated'} the dashboard “{d['name']}” ({d['id']}): /library/dashboards/{d['id']}")
            for w in d["widgets"]:
                print(f"- {w['title']}: {_says(w)}")
        elif args.cmd == "chart":
            if args.source:
                spec = _read_json(args.source)
            else:
                try:
                    spec = json.loads(args.spec or "")
                except json.JSONDecodeError as e:
                    raise DashboardError(f"That isn't valid JSON: {e}.") from None
            got = chart(spec)
            if got.get("error"):
                raise DashboardError(got["error"])
            print(f"{got['title']}: {_says(got)}")
            print("\nIn a message:\n```chart\n" + json.dumps(spec, ensure_ascii=False) + "\n```")
        elif args.cmd == "remove":
            d = find(args.dashboard)
            if not d:
                raise DashboardError(f"There's no dashboard called “{args.dashboard}”.")
            remove(d["id"])
            print(f"Removed the dashboard “{d['name']}”.")
    except DashboardError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
