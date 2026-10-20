"""Spreadsheets in and out of the library: export a table (what a view shows) as CSV or Excel, and
import a CSV or Excel file as a new table (column types guessed from the values) or into an existing
one (columns matched by name; new ones added as text; values that don't fit are left empty and
counted). Used by the agent API for the app's Import and Export buttons.

    .venv/bin/python scripts/library_io.py export "Leads" leads.xlsx
    .venv/bin/python scripts/library_io.py import customers.csv [--into "Customers"]
"""
import argparse
import csv
import io
import re
import sys
from datetime import date, datetime
from pathlib import Path

import library
from library import LibraryError

MAX_ROWS = 50_000
MAX_COLUMNS = 200
MAX_BYTES = 20 * 1024 * 1024
FORMATS = {"csv": "text/csv; charset=utf-8", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


# ---------- export ----------

def _plain(col: dict, value, related: dict, names: dict):
    """A cell as a spreadsheet keeps it."""
    if value is None:
        return ""
    if col["type"] == "relation":
        return related.get(value, "")
    if col["type"] == "checkbox":
        return "yes" if value else "no"
    if col["type"] == "tags":
        return ", ".join(value)
    if col["type"] == "files":
        return ", ".join(names.get(f, {}).get("name", f) for f in value)
    return value


def export(table_ref: str, fmt: str = "csv", **query) -> tuple[bytes, str, str]:
    """Every row a view shows (search, filters, sort; archived with archived=True), as (bytes, file
    name, content type). Read a page at a time, so a big table doesn't load at once."""
    if fmt not in FORMATS:
        raise LibraryError("Export as csv or xlsx.")
    t = library.table(table_ref)
    header = [c["name"] for c in t.columns]
    rows, offset = [], 0
    while len(rows) < MAX_ROWS:
        page = t.query(**query, limit=500, offset=offset)
        for r in page["rows"]:
            rows.append([_plain(c, r["cells"].get(c["name"]), page["related"], page["files"]) for c in t.columns])
        offset += 500
        if offset >= page["total"]:
            break
    stem = re.sub(r"[^\w\- ]+", "", t.name).strip() or "table"
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)
        writer.writerows(rows)
        return "﻿".encode() + buf.getvalue().encode("utf-8"), f"{stem}.csv", FORMATS["csv"]  # BOM: Excel reads it as UTF-8
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(t.name[:31] or "Table")
    ws.append(header)
    for r in rows:
        ws.append([v if not isinstance(v, str) or not v.startswith(("=", "+", "-", "@")) else "'" + v for v in r])  # no formulas
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), f"{stem}.xlsx", FORMATS["xlsx"]


# ---------- import ----------

def read_sheet(name: str, data: bytes) -> tuple[list[str], list[list]]:
    """The header and rows of a CSV or Excel file (its first sheet)."""
    if len(data) > MAX_BYTES:
        raise LibraryError("That file is too big. Import spreadsheets up to 20 MB.")
    lower = name.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise LibraryError("That Excel file couldn't be read. Save it again as .xlsx or .csv and try again.") from None
        values = [list(r) for _, r in zip(range(MAX_ROWS + 1), wb.worksheets[0].iter_rows(values_only=True))]
    elif lower.endswith((".csv", ".tsv", ".txt")):
        text = None
        for encoding in ("utf-8-sig", "cp1255", "latin-1"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        values = [r for _, r in zip(range(MAX_ROWS + 1), csv.reader(io.StringIO(text), dialect))]
    else:
        raise LibraryError("Import a .csv or .xlsx file.")
    values = [r for r in values if any(v not in (None, "") for v in r)]
    if not values:
        raise LibraryError("That file is empty.")
    width = min(MAX_COLUMNS, max(len(r) for r in values))
    header, seen = [], set()
    for i in range(width):
        raw = values[0][i] if i < len(values[0]) else None
        base = re.sub(r"[:,()]", " ", str(raw or "").strip())[:60].strip() or f"Column {i + 1}"
        name, n = base, 2
        while name.lower() in seen:
            name, n = f"{base} {n}", n + 1
        seen.add(name.lower())
        header.append(name)
    rows = [[(r[i] if i < len(r) else None) for i in range(width)] for r in values[1:]]
    return header, rows


DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def guess(name: str, values: list) -> str:
    """A column definition (Name:type) from its values."""
    filled = [v for v in values if _text(v) != ""]
    texts = [_text(v) for v in filled]
    if not filled:
        return f"{name}:text"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) or re.fullmatch(r"-?[\d,]*\.?\d+", t.replace("$", ""))
           for v, t in zip(filled, texts)):
        return f"{name}:number"
    if all(isinstance(v, (date, datetime)) or DATE.match(t) for v, t in zip(filled, texts)):
        return f"{name}:date"
    if all(re.match(r"^https?://\S+$", t) for t in texts):
        return f"{name}:link"
    if all(t.lower() in ("yes", "no", "true", "false", "y", "n", "x", "1", "0") for t in texts) and len(set(t.lower() for t in texts)) <= 2:
        return f"{name}:checkbox"
    labels = list(dict.fromkeys(texts))
    if len(filled) >= 8 and len(labels) <= 8 and all(len(t) <= 30 and "|" not in t and ")" not in t for t in labels):
        return f"{name}:status({'|'.join(labels)})"
    if max(len(t) for t in texts) > 300:
        return f"{name}:longtext"
    return f"{name}:text"


def import_sheet(name: str, data: bytes, into: str | None = None, title: str | None = None) -> dict:
    """A spreadsheet as a new table (named `title`, else after the file) or added to the table `into`.
    Returns {table: {id, name}, added, skipped (values left empty because they didn't fit), columns}."""
    header, rows = read_sheet(name, data)
    if len(rows) > MAX_ROWS:
        raise LibraryError(f"That's more than {MAX_ROWS:,} rows. Split it into smaller files.")
    if into:
        t = library.table(into)
        have = {c["name"].lower() for c in t.columns}
        extra = [guess(h, [r[i] for r in rows]) for i, h in enumerate(header) if h.lower() not in have]
        if extra:
            t = library.table(t.name, ", ".join(extra))
    else:
        existing = {x["name"].lower() for x in library.tables() + library.tables(archived=True)}
        base = (title or Path(name).stem or "Imported").strip()[:70] or "Imported"
        table_name, n = base, 2
        while table_name.lower() in existing:
            table_name, n = f"{base} ({n})", n + 1
        spec = ", ".join(guess(h, [r[i] for r in rows]) for i, h in enumerate(header))
        t = library.table(table_name, spec, f"Imported from {Path(name).name}")
    cols = {c["name"].lower(): c for c in t.columns}
    added = skipped = 0
    for r in rows:
        cells = {}
        for h, v in zip(header, r):
            col = cols[h.lower()]
            value = v if isinstance(v, (int, float, bool)) and col["type"] in ("number", "checkbox") else _text(v)
            if value == "" or value is None:
                continue
            if col["type"] == "date" and isinstance(value, str):
                value = value[:10]
            cells[col["name"]] = value
        try:
            t.add(cells)
        except LibraryError:
            # one value doesn't fit: keep the row, leaving the values that don't fit empty
            kept = {}
            for k, v in cells.items():
                col = cols[k.lower()]
                try:
                    if col["type"] == "relation":  # names, not rows: can't be matched safely
                        raise LibraryError("relation")
                    library._check(col, v, None)
                    kept[k] = v
                except LibraryError:
                    skipped += 1
            t.add(kept)
        added += 1
    return {"table": {"id": t.id, "name": t.name}, "added": added, "skipped": skipped, "columns": [c["name"] for c in t.columns]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("table")
    e.add_argument("file", help="name.csv or name.xlsx")
    i = sub.add_parser("import")
    i.add_argument("file")
    i.add_argument("--into")
    i.add_argument("--title")
    args = parser.parse_args()
    try:
        if args.cmd == "export":
            data, _, _ = export(args.table, Path(args.file).suffix.lstrip(".").lower() or "csv")
            Path(args.file).write_bytes(data)
            print(f"Saved {args.file}.")
        else:
            got = import_sheet(Path(args.file).name, Path(args.file).read_bytes(), args.into, args.title)
            print(f"Added {got['added']} rows to {got['table']['name']}." + (f" {got['skipped']} value(s) didn't fit and were left empty." if got["skipped"] else ""))
    except LibraryError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
