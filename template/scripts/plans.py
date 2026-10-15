#!/usr/bin/env python3
"""The business's plans: business plan, marketing plan, sales, hiring, a launch... One document per
subject, kept up to date instead of written again, with every version kept: who changed it (you or
the COO), why, what changed, and a way back to any earlier version.

They live in the library database (library.db, so they're in the export), shown in the Library.

    .venv/bin/python scripts/plans.py list
    .venv/bin/python scripts/plans.py show <plan id or title>                    # the current text
    .venv/bin/python scripts/plans.py save "Marketing plan" --from drafts/marketing-plan.md --note "Added the autumn campaign"
    .venv/bin/python scripts/plans.py history <plan>
    .venv/bin/python scripts/plans.py diff <plan> <version>                       # what that version changed
    .venv/bin/python scripts/plans.py restore <plan> <version> --note "why"

No duplicates: `save` updates the plan on the same subject when there is one (a plan of the same kind,
or a title that close), as a new version. Pass --different only for a truly separate plan on the same
subject (one per product, say). Write the whole plan each time, not just the part that changed: start
from `show`, edit a copy in drafts/, then save it. A save that drops more than half the plan is
refused unless --shorter says that's meant.
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import secrets
import sys
from pathlib import Path

import library
from common import ROOT, log_run, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS plan_versions (plan_id TEXT NOT NULL, n INTEGER NOT NULL, body TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '', who TEXT NOT NULL, at TEXT NOT NULL, restored_from INTEGER,
    PRIMARY KEY (plan_id, n));
"""

# The subjects a plan can be about, with words that give them away in a title.
KINDS = {
    "business": ("business plan", "business", "strategy", "company plan"),
    "marketing": ("marketing", "brand", "content", "social media", "advertising", "campaign", "seo", "promotion"),
    "sales": ("sales", "selling", "pipeline", "outreach", "leads"),
    "financial": ("financial", "finance", "budget", "cash flow", "cashflow", "pricing", "forecast", "money"),
    "operations": ("operations", "operating", "process", "supply", "inventory", "logistics"),
    "hiring": ("hiring", "recruiting", "team", "staffing", "people"),
    "product": ("product", "roadmap", "menu", "offering", "services"),
    "launch": ("launch", "go-to-market", "go to market", "opening"),
    "customer": ("customer", "retention", "support", "service plan", "loyalty"),
}
KIND_NAMES = {"business": "Business plan", "marketing": "Marketing plan", "sales": "Sales plan", "financial": "Financial plan",
              "operations": "Operations plan", "hiring": "Hiring plan", "product": "Product plan", "launch": "Launch plan",
              "customer": "Customer plan", "other": "Plan"}
WHO = ("coo", "you", "autopilot")
MAX_BODY = 200_000


class PlanError(Exception):
    """Something to tell the owner or the COO, in plain words."""


class _Conn:
    def __enter__(self):
        self.cm = library.connect()
        con = self.cm.__enter__()
        con.executescript(SCHEMA)
        if "run" not in {r[1] for r in con.execute("PRAGMA table_info(plan_versions)")}:
            con.execute("ALTER TABLE plan_versions ADD COLUMN run TEXT")  # the chat turn or routine run that saved it
        return con

    def __exit__(self, *exc):
        return self.cm.__exit__(*exc)


def connect() -> _Conn:
    return _Conn()


def kind_of(title: str) -> str:
    t = title.lower()
    for kind, words in KINDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words):
            return kind
    return "other"


def _norm(title: str) -> str:
    t = re.sub(r"\b(our|the|a|an|plan|20\d\d|q[1-4]|new|updated|draft|v\d+)\b", " ", title.lower())
    return " ".join(re.findall(r"[a-z0-9À-￿]+", t))


def _row(con, r) -> dict:
    last = con.execute("SELECT body, who, note, at FROM plan_versions WHERE plan_id = ? AND n = ?", (r["id"], r["version"])).fetchone()
    body = last["body"] if last else ""
    first = next((line.strip("# ").strip() for line in body.splitlines() if line.strip() and not line.startswith("#")), "")
    return {"id": r["id"], "title": r["title"], "kind": r["kind"], "version": r["version"], "createdAt": r["created"],
            "updatedAt": r["updated"], "updatedBy": last["who"] if last else "coo", "note": last["note"] if last else "",
            "summary": first[:200], "words": len(body.split())}


def plans() -> list[dict]:
    """Every plan, most recently changed first."""
    with connect() as con:
        rows = con.execute("SELECT * FROM plans WHERE archived = 0 ORDER BY updated DESC").fetchall()
        return [_row(con, r) for r in rows]


def find(ref: str) -> dict | None:
    """A plan by its id, or by title (exact, then the same subject)."""
    ref = (ref or "").strip()
    with connect() as con:
        r = con.execute("SELECT * FROM plans WHERE id = ? AND archived = 0", (ref,)).fetchone()
        if r is None:
            r = con.execute("SELECT * FROM plans WHERE lower(title) = lower(?) AND archived = 0", (ref,)).fetchone()
        return _row(con, r) if r else None


def match(title: str, kind: str | None = None) -> dict | None:
    """The plan this title is about, if there is one: the same kind of plan, or a title that close."""
    kind = kind or kind_of(title)
    want = _norm(title)
    best, score = None, 0.0
    for p in plans():
        same_kind = kind != "other" and p["kind"] == kind
        ratio = difflib.SequenceMatcher(None, want, _norm(p["title"])).ratio() if want else 0.0
        s = max(ratio, 0.9 if same_kind else 0.0)
        if s > score:
            best, score = p, s
    return best if score >= 0.75 else None


def body(plan_id: str, n: int | None = None) -> str:
    with connect() as con:
        if n is None:
            r = con.execute("SELECT version FROM plans WHERE id = ?", (plan_id,)).fetchone()
            if not r:
                raise PlanError("There's no such plan.")
            n = r["version"]
        v = con.execute("SELECT body FROM plan_versions WHERE plan_id = ? AND n = ?", (plan_id, n)).fetchone()
    if not v:
        raise PlanError(f"That plan has no version {n}.")
    return v["body"]


def _clean(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        raise PlanError("The plan is empty.")
    if len(text) > MAX_BODY:
        raise PlanError(f"That's too long for a plan ({len(text):,} characters; up to {MAX_BODY:,}).")
    return text + "\n"


def _add_version(con, plan_id: str, text: str, note: str, who: str, restored_from: int | None = None) -> int:
    n = con.execute("SELECT COALESCE(MAX(n), 0) + 1 FROM plan_versions WHERE plan_id = ?", (plan_id,)).fetchone()[0]
    at = now_iso()
    con.execute("INSERT INTO plan_versions (plan_id, n, body, note, who, at, restored_from, run) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (plan_id, n, text, note.strip()[:500], who, at, restored_from, os.environ.get("STEERABLE_RUN") or None))
    con.execute("UPDATE plans SET version = ?, updated = ? WHERE id = ?", (n, at, plan_id))
    return n


def save(title: str, text: str, note: str = "", who: str = "coo", plan_id: str | None = None, kind: str | None = None,
         different: bool = False, shorter: bool = False) -> dict:
    """Save a plan: a new version of the plan on this subject, or a new plan if there's none.
    Returns {"plan": ..., "created": bool, "changed": bool}."""
    if who not in WHO:
        raise PlanError("Unknown author.")
    text = _clean(text)
    title = re.sub(r"\s+", " ", (title or "").strip())[:120]
    if kind and kind not in KINDS and kind != "other":
        raise PlanError(f"Kind is one of: {', '.join([*KINDS, 'other'])}.")
    existing = None
    if plan_id:
        existing = find(plan_id)
        if not existing:
            raise PlanError("There's no such plan.")
    elif not different:
        existing = match(title, kind) if title else None
    if existing is None:
        if not title:
            raise PlanError("Give the plan a title, like \"Marketing plan\".")
        new_id = "pl" + secrets.token_hex(4)
        at = now_iso()
        with connect() as con:
            con.execute("INSERT INTO plans (id, title, kind, version, created, updated) VALUES (?, ?, ?, 0, ?, ?)",
                        (new_id, title, kind or kind_of(title), at, at))
            _add_version(con, new_id, text, note or "First version", who)
        log_run("plans", "created", plan=new_id, who=who)
        return {"plan": find(new_id), "created": True, "changed": True}
    current = body(existing["id"])
    if current == text:
        return {"plan": existing, "created": False, "changed": False}
    if len(text) < len(current) * 0.5 and not shorter:
        raise PlanError(f"This would cut “{existing['title']}” to less than half its length. Save the whole plan "
                        "(start from `plans.py show`), or pass --shorter if dropping that much is meant.")
    with connect() as con:
        _add_version(con, existing["id"], text, note, who)
    log_run("plans", "updated", plan=existing["id"], who=who)
    return {"plan": find(existing["id"]), "created": False, "changed": True}


def versions(plan_id: str) -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT n, note, who, at, restored_from, length(body) AS size FROM plan_versions WHERE plan_id = ? ORDER BY n DESC",
                           (plan_id,)).fetchall()
    return [{"n": r["n"], "note": r["note"], "who": r["who"], "at": r["at"], "restoredFrom": r["restored_from"]} for r in rows]


def changes(old: str, new: str, context: int = 2) -> list[dict]:
    """Line by line, what changed from old to new: {"op": "same"|"add"|"del", "text"}, with the unchanged
    stretches between changes folded into {"op": "skip", "count": lines hidden}."""
    out: list[dict] = []
    a, b = old.splitlines(), new.splitlines()
    shown_to = 0  # lines of the old text accounted for so far
    for group in difflib.SequenceMatcher(None, a, b, autojunk=False).get_grouped_opcodes(context):
        if group[0][1] > shown_to:
            out.append({"op": "skip", "count": group[0][1] - shown_to})
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out += [{"op": "same", "text": line} for line in a[i1:i2]]
            if tag in ("delete", "replace"):
                out += [{"op": "del", "text": line} for line in a[i1:i2]]
            if tag in ("insert", "replace"):
                out += [{"op": "add", "text": line} for line in b[j1:j2]]
        shown_to = group[-1][2]
    if out and shown_to < len(a):
        out.append({"op": "skip", "count": len(a) - shown_to})
    return out


def run_plans(run: str) -> list[dict]:
    """The plans a chat turn or routine run saved: [{"id", "title", "version", "note", "created"}], its last version of each."""
    if not run:
        return []
    with connect() as con:
        rows = con.execute("""SELECT p.id, p.title, MAX(v.n) AS n, MIN(v.n) AS first FROM plan_versions v JOIN plans p ON p.id = v.plan_id
                              WHERE v.run = ? AND p.archived = 0 GROUP BY p.id ORDER BY p.title""", (run,)).fetchall()
        out = []
        for r in rows:
            note = con.execute("SELECT note FROM plan_versions WHERE plan_id = ? AND n = ?", (r["id"], r["n"])).fetchone()["note"]
            out.append({"id": r["id"], "title": r["title"], "version": r["n"], "note": note, "created": r["first"] == 1})
    return out


def detail(plan_id: str) -> dict | None:
    p = find(plan_id)
    if not p:
        return None
    return {**p, "body": body(p["id"]), "versions": versions(p["id"])}


def version(plan_id: str, n: int) -> dict | None:
    """One version: its text, and what it changed from the one before."""
    vs = {v["n"]: v for v in versions(plan_id)}
    if n not in vs:
        return None
    text = body(plan_id, n)
    before = body(plan_id, n - 1) if n - 1 in vs else ""
    return {**vs[n], "body": text, "changes": changes(before, text)}


def restore(plan_id: str, n: int, who: str = "you", note: str = "") -> dict:
    """Make an earlier version the current one again, as a new version (nothing is lost)."""
    p = find(plan_id)
    if not p:
        raise PlanError("There's no such plan.")
    if n == p["version"]:
        raise PlanError("That's already the current version.")
    text = body(p["id"], n)
    with connect() as con:
        _add_version(con, p["id"], text, note or f"Back to version {n}", who, restored_from=n)
    log_run("plans", "restored", plan=p["id"], version=n, who=who)
    return find(p["id"])


def remove(plan_id: str) -> None:
    """Archive a plan: it leaves the Library, its versions stay in the database."""
    with connect() as con:
        if not con.execute("UPDATE plans SET archived = 1, updated = ? WHERE id = ? AND archived = 0", (now_iso(), plan_id)).rowcount:
            raise PlanError("There's no such plan.")
    log_run("plans", "archived", plan=plan_id)


def _read_from(path: str) -> str:
    p = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if ROOT.resolve() not in p.parents or not p.is_file():
        raise PlanError("--from must be a file in the company folder, like drafts/marketing-plan.md.")
    return p.read_text(encoding="utf-8")


def _when(iso: str) -> str:
    return iso[:16].replace("T", " ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("show").add_argument("plan")
    s = sub.add_parser("save")
    s.add_argument("title")
    s.add_argument("--from", dest="source", required=True, help="the whole plan, as a Markdown file (drafts/...)")
    s.add_argument("--note", required=True, help="what changed and why, in a sentence")
    s.add_argument("--id", help="update this plan (otherwise the plan on the same subject)")
    s.add_argument("--kind", choices=[*KINDS, "other"])
    s.add_argument("--different", action="store_true", help="a separate plan, even though one on the same subject exists")
    s.add_argument("--shorter", action="store_true", help="dropping more than half the plan is meant")
    sub.add_parser("history").add_argument("plan")
    d = sub.add_parser("diff")
    d.add_argument("plan")
    d.add_argument("version", type=int)
    r = sub.add_parser("restore")
    r.add_argument("plan")
    r.add_argument("version", type=int)
    r.add_argument("--note", default="")
    args = ap.parse_args()

    def need(ref: str) -> dict:
        p = find(ref) or match(ref)
        if not p:
            raise PlanError(f"There's no plan called “{ref}”. `plans.py list` shows them.")
        return p

    try:
        if args.cmd == "list":
            ps = plans()
            if not ps:
                print("No plans yet.")
            for p in ps:
                print(f"{p['id']}  {p['title']}  ({p['kind']}, version {p['version']}, {p['words']} words, "
                      f"changed {_when(p['updatedAt'])} by {p['updatedBy']})")
        elif args.cmd == "show":
            p = need(args.plan)
            print(f"# {p['title']}  ({p['id']}, version {p['version']})\n")
            print(body(p["id"]), end="")
        elif args.cmd == "save":
            out = save(args.title, _read_from(args.source), args.note, "coo", args.id, args.kind, args.different, args.shorter)
            p = out["plan"]
            if out["created"]:
                print(f"Saved a new plan: “{p['title']}” ({p['id']}).")
            elif out["changed"]:
                print(f"Updated “{p['title']}” ({p['id']}) to version {p['version']}.")
            else:
                print(f"“{p['title']}” already says exactly that; nothing to save.")
        elif args.cmd == "history":
            p = need(args.plan)
            for v in versions(p["id"]):
                print(f"version {v['n']}  {_when(v['at'])}  {v['who']}: {v['note']}")
        elif args.cmd == "diff":
            p = need(args.plan)
            v = version(p["id"], args.version)
            if not v:
                raise PlanError(f"That plan has no version {args.version}.")
            for line in v["changes"]:
                print({"same": "  ", "add": "+ ", "del": "- "}.get(line["op"], "  ...") + line.get("text", ""))
        elif args.cmd == "restore":
            p = restore(need(args.plan)["id"], args.version, "coo", args.note)
            print(f"“{p['title']}” is back to version {args.version} (saved as version {p['version']}).")
    except PlanError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
