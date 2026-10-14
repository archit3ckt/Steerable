"""Books the owner teaches the COO. The owner gives a book they like (EPUB, PDF, Word or text) and
says why; the engine keeps its text, split into chapters and searchable, in books/<id>/ (not in the
COO's memory, so memory doesn't fill up). The COO studies it in the background: it reads every
chapter, writes short notes in its own words with chapter references, and proposes what it would
change about how it runs this business: skills (how-tos it uses when they fit), routines and goals.
Nothing changes until the owner approves each one. An approved skill is written to
.claude/skills/book-<book>-<name>/SKILL.md, citing the book; pausing a book takes its skills away
(they come back on resume); removing it deletes them. The owner's copy is only ever used for their
own company.

    .venv/bin/python scripts/books.py list
    .venv/bin/python scripts/books.py search "pricing" [--book <id>]
    .venv/bin/python scripts/books.py study <id>          (the background study; started by add())
"""
import argparse
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import burst
import files
import library
from common import CACHE, ROOT, alive, log_run, now_iso
from ops_db import record_event

BOOKS = ROOT / "books"
SKILLS = ROOT / ".claude" / "skills"
LIVE = CACHE / "book-live"
STUDY_CAP_USD = "4"  # one book's study, at most
MAX_CHARS = 4_000_000  # about 600,000 words
KINDS = ("skill", "routine", "goal")

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL DEFAULT '',
    why TEXT NOT NULL DEFAULT '', file TEXT, chapters INTEGER NOT NULL DEFAULT 0, words INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL, error TEXT, pid INTEGER, cost REAL NOT NULL DEFAULT 0, added TEXT NOT NULL, studied TEXT);
CREATE TABLE IF NOT EXISTS book_proposals (id TEXT PRIMARY KEY, book_id TEXT NOT NULL, kind TEXT NOT NULL,
    name TEXT NOT NULL, summary TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting', note TEXT, position INTEGER NOT NULL DEFAULT 0, answered TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS book_text USING fts5(book_id UNINDEXED, chapter UNINDEXED, title UNINDEXED, text);
"""


class BookError(Exception):
    """Something to tell the owner, in plain words."""


def _db():
    con_cm = library.connect()
    con = con_cm.__enter__()
    con.executescript(SCHEMA)
    return con_cm, con


class _Conn:
    def __enter__(self):
        self.cm, con = _db()
        return con

    def __exit__(self, *exc):
        return self.cm.__exit__(*exc)


def connect() -> _Conn:
    """The library database, with the books' tables."""
    return _Conn()


def slug(text: str, n: int = 30) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n].strip("-") or "book"


# ---------- reading a book's text ----------

HEAD_START, HEAD_END = "\x01", "\x02"
SPLIT_AT = 12_000  # characters: a section bigger than this is split at its headings
BOILERPLATE = re.compile(r"project gutenberg.*licen[cs]e|^the project gutenberg e-?book of|^the full project gutenberg|^table of contents$|^contents$", re.I)


def _sections(text: str, title: str) -> list[tuple[str, str]]:
    """A section as chapters: split at its headings when it's big (a whole book in one file)."""
    heads = list(re.finditer(f"{HEAD_START}(.*?){HEAD_END}", text, re.S))
    clean = lambda t: re.sub(r"\n{3,}", "\n\n", t.replace(HEAD_START, "").replace(HEAD_END, "")).strip()  # noqa: E731
    if len(text) <= SPLIT_AT or len(heads) < 2:
        return [(title, clean(text))]
    out = []
    lead = clean(text[: heads[0].start()])
    if len(lead) >= 300:
        out.append((title, lead))
    for i, m in enumerate(heads):
        body = clean(text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)])
        name = re.sub(r"\s+", " ", clean(m.group(1)))[:120] or f"Part {i + 1}"
        if out and len(body) < 300:  # a heading with little under it (a subtitle): keep it with what came before
            out[-1] = (out[-1][0], f"{out[-1][1]}\n\n{name}\n\n{body}".strip())
            continue
        out.append((name, body))
    return out


class _Text(HTMLParser):
    """An XHTML chapter as text, keeping paragraph breaks and the first heading."""

    BLOCK = {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr", "section", "blockquote"}

    def __init__(self):
        super().__init__()
        self.parts, self.heading, self._in_heading, self._skip = [], "", False, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3"):
            self.parts.append(HEAD_START)  # where a heading starts: big sections are split there
            if not self.heading and tag != "h3":
                self._in_heading = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if tag in ("h1", "h2", "h3"):
            self._in_heading = False
            self.parts.append(HEAD_END)
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._in_heading:
            self.heading += data

    def text(self) -> str:
        """The text, with headings still marked (HEAD_START ... HEAD_END) for _sections."""
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", "".join(self.parts))).strip()


def _epub(path: Path) -> tuple[str, str, list[tuple[str, str]]]:
    try:
        z = zipfile.ZipFile(path)
        container = ElementTree.fromstring(z.read("META-INF/container.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        raise BookError("That EPUB couldn't be opened. Try another copy, or a PDF.") from None
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "o": "http://www.idpf.org/2007/opf",
          "dc": "http://purl.org/dc/elements/1.1/"}
    opf_path = container.find(".//c:rootfile", ns).get("full-path")
    opf = ElementTree.fromstring(z.read(opf_path))
    base = str(Path(opf_path).parent) if "/" in opf_path else ""
    title = (opf.findtext(".//dc:title", "", ns) or "").strip()
    author = (opf.findtext(".//dc:creator", "", ns) or "").strip()
    manifest = {i.get("id"): i.get("href") for i in opf.findall(".//o:manifest/o:item", ns)}
    chapters = []
    for ref in opf.findall(".//o:spine/o:itemref", ns):
        href = manifest.get(ref.get("idref"))
        if not href:
            continue
        name = f"{base}/{href}" if base else href
        try:
            raw = z.read(name.split("#")[0]).decode("utf-8", "ignore")
        except KeyError:
            continue
        parser = _Text()
        parser.feed(raw)
        title_here = re.sub(r"\s+", " ", html.unescape(parser.heading.strip()))[:120] or f"Part {len(chapters) + 1}"
        for name, text in _sections(parser.text(), title_here):
            if len(text) < 300 or BOILERPLATE.search(name):  # covers, title pages, licences: not chapters
                continue
            chapters.append((name, text))
    return title, author, chapters


def _pdf(path: Path) -> tuple[str, str, list[tuple[str, str]]]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception:
        raise BookError("That PDF couldn't be read. If it's a scan (pictures of pages), it has no text to learn from.") from None
    meta = reader.metadata or {}
    title, author = str(meta.get("/Title") or "").strip(), str(meta.get("/Author") or "").strip()
    starts = []
    try:
        for item in reader.outline:  # the book's own table of contents, top level
            if not isinstance(item, list):
                starts.append((reader.get_destination_page_number(item), str(item.title).strip()[:120]))
    except Exception:
        starts = []
    starts = sorted({p: t for p, t in starts}.items())
    if len(starts) < 2:
        starts = [(i, f"Pages {i + 1}–{min(i + 20, len(pages))}") for i in range(0, len(pages), 20)]
    chapters = []
    for n, (page, name) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(pages)
        text = "\n\n".join(pages[page:end]).strip()
        if len(text) >= 300:
            chapters.append((name, text))
    return title, author, chapters


def _docx(path: Path) -> tuple[str, str, list[tuple[str, str]]]:
    from docx import Document

    doc = Document(str(path))
    chapters, name, lines = [], "", []
    for p in doc.paragraphs:
        if p.style is not None and p.style.name.lower().startswith("heading 1") and p.text.strip():
            if lines:
                chapters.append((name or f"Part {len(chapters) + 1}", "\n\n".join(lines)))
            name, lines = p.text.strip()[:120], []
        elif p.text.strip():
            lines.append(p.text.strip())
    if lines:
        chapters.append((name or f"Part {len(chapters) + 1}", "\n\n".join(lines)))
    props = doc.core_properties
    return (props.title or "").strip(), (props.author or "").strip(), chapters


def _plain(path: Path) -> tuple[str, str, list[tuple[str, str]]]:
    text = path.read_bytes().decode("utf-8", "ignore")
    heads = list(re.finditer(r"(?im)^(#{1,2} .+|chapter\s+[\w\d]+.*)$", text))
    if len(heads) >= 2:
        chapters = [(m.group(1).lstrip("# ").strip()[:120], text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip())
                    for i, m in enumerate(heads)]
    else:
        words = text.split()
        chapters = [(f"Part {i // 8000 + 1}", " ".join(words[i:i + 8000])) for i in range(0, len(words), 8000)]
    return "", "", [(n, t) for n, t in chapters if len(t) >= 300]


def extract(path: Path) -> tuple[str, str, list[tuple[str, str]]]:
    """(title, author, [(chapter title, text)]) from an EPUB, PDF, Word or text file."""
    ext = path.suffix.lower()
    reader = {".epub": _epub, ".pdf": _pdf, ".docx": _docx, ".txt": _plain, ".md": _plain}.get(ext)
    if not reader:
        raise BookError("Teach a book as an EPUB, PDF, Word (.docx) or text file.")
    title, author, chapters = reader(path)
    if not chapters:
        raise BookError("There's no text in that file to learn from.")
    total, kept = 0, []
    for name, text in chapters[:300]:
        total += len(text)
        if total > MAX_CHARS:
            break
        kept.append((name, text))
    return title, author, kept


# ---------- adding and studying ----------

def add(file_id: str, why: str = "", title: str = "", author: str = "", start: bool = True) -> dict:
    """A book from a file the owner attached (files.py), kept and indexed, and its study started."""
    try:
        path = files.find(file_id)
    except files.FileError as e:
        raise BookError(str(e)) from None
    found_title, found_author, chapters = extract(path)
    name = files.describe(path)["name"]
    title = (title or found_title or Path(name).stem.replace("_", " ")).strip()[:200]
    author = (author or found_author).strip()[:200]
    bid = "b" + secrets.token_hex(4)
    folder = BOOKS / bid / "chapters"
    folder.mkdir(parents=True)
    words = 0
    with connect() as con:
        for n, (chapter, text) in enumerate(chapters, 1):
            (folder / f"{n:02d}.md").write_text(f"# {chapter}\n\n{text}\n")
            words += len(text.split())
            for chunk in _chunks(text):
                con.execute("INSERT INTO book_text (book_id, chapter, title, text) VALUES (?, ?, ?, ?)", (bid, n, chapter, chunk))
        con.execute("""INSERT INTO books (id, title, author, why, file, chapters, words, status, added)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (bid, title, author, (why or "").strip()[:2000], file_id, len(chapters), words, "studying", now_iso()))
    (BOOKS / bid / "contents.md").write_text(f"# {title}\n{('by ' + author) if author else ''}\n\n" +
                                            "\n".join(f"{n:02d}. {c}" for n, (c, _) in enumerate(chapters, 1)) + "\n")
    log_run("books", "added", book=bid, chapters=len(chapters), words=words)
    record_event(f"Started studying “{title}”{' by ' + author if author else ''} ({len(chapters)} chapters).", who="COO")
    if start:
        _start(bid)
    return get(bid)


def _chunks(text: str, size: int = 1500) -> list[str]:
    out, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if len(cur) + len(para) > size and cur:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        out.append(cur)
    return [c[:4000] for c in out]


def _start(bid: str) -> None:
    proc = subprocess.Popen([sys.executable, str(Path(__file__)), "study", bid], cwd=ROOT, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with connect() as con:
        con.execute("UPDATE books SET pid = ?, status = 'studying', error = NULL WHERE id = ?", (proc.pid, bid))


def _prompt(b, company_notes: str) -> str:
    folder = f"books/{b['id']}"
    return f"""You are the COO of this business, studying a book the owner wants you to learn from, so you get better at running the business.

The book: “{b['title']}”{' by ' + b['author'] if b['author'] else ''}. Its {b['chapters']} chapters are {folder}/chapters/01.md to {b['chapters']:02d}.md (contents: {folder}/contents.md).
Why the owner likes it: {b['why'] or "(they didn't say)"}

What you know about the business (from your notes):
{company_notes[:6000] or '(no notes yet)'}

Do this:
1. Read every chapter, in order. Skim stories; keep the ideas, methods and rules of thumb.
2. Write {folder}/notes.md: for each chapter, a heading and 3 to 6 key ideas in your own words (no long quotes), each with how it applies to THIS business.
3. Write {folder}/proposals.json: a JSON list of 3 to 12 changes that would make you better at running this business the book's way. Each is
   {{"kind": "skill" | "routine" | "goal", "name": a short title in plain words (like "Weekly follow-ups"), "summary": one plain sentence for the owner, "source": "ch. 3" (or "ch. 3, 7"), "body": ...}}
   - skill: body is the skill's instructions in markdown: when to use it, the steps, how it applies here, and the chapter it comes from. In your own words, under 1,500 words. Make each skill one practice you'd actually use (a process, a checklist, a way to decide).
   - routine: body is {{"description": what it does in the owner's words, "workflow": snake_case name, "every": "daily" | "weekly" | "Nh", "at": "HH:MM" or "", "saves": hours a week it saves}}. Only for something that should run on its own on a schedule.
   - goal: body is {{"goal": the goal, "metric": the number that shows progress, "target": the target, "why": one sentence}}.
   Prefer a few strong proposals over many weak ones. Skip anything that doesn't fit this business.
Write only those two files. Don't change anything else."""


def study(bid: str) -> int:
    """The background study: one Claude session reads the book and writes notes and proposals."""
    from budget import BudgetExceeded, check, record

    b = get(bid)
    if not b:
        return 1
    folder = BOOKS / bid
    try:
        check()
    except BudgetExceeded as e:
        return _fail(bid, f"Not now: {e}")
    notes = ""
    for name in ("company.md", "people.md"):
        p = ROOT / "memory" / name
        if p.exists():
            notes += p.read_text()[:4000] + "\n"
    LIVE.mkdir(parents=True, exist_ok=True)
    live = LIVE / f"{bid}.jsonl"
    live.unlink(missing_ok=True)
    cmd = ["claude", "-p", _prompt(b, notes), "--output-format", "stream-json", "--verbose", "--model", "sonnet",
           "--max-budget-usd", STUDY_CAP_USD, "--permission-mode", "default",
           "--allowedTools", f"Read(./books/{bid}/**)", "Read(./memory/**)", "Glob",
           # Claude Code grants file writes through Edit rules (Write alone isn't enough), so both.
           *(f"{tool}(./books/{bid}/{name})" for tool in ("Edit", "Write") for name in ("notes.md", "proposals.json")),
           # Edit rules cover every file-writing tool (Write too), so writes are limited by the allow list above.
           "--disallowedTools", "Bash", "WebFetch", "WebSearch", "Read(./.env)", "Read(./.cache/**)", "Read(./.home/**)"]
    try:
        proc = burst.run(cmd, kind="claude", timeout=3600, stream=live)
    except Exception as e:  # noqa: BLE001
        return _fail(bid, f"The study couldn't start ({type(e).__name__}).")
    cost = 0.0
    for line in (proc.stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "total_cost_usd" in event:
            cost = float(event.get("total_cost_usd") or 0)
    if cost:
        record("book-study", cost, model="sonnet", note=b["title"][:60])
    with connect() as con:
        con.execute("UPDATE books SET cost = cost + ? WHERE id = ?", (cost, bid))
    try:
        proposals = json.loads((folder / "proposals.json").read_text())
    except (OSError, ValueError):
        return _fail(bid, "The study ended before the ideas were written down. Try again.")
    kept = save_proposals(bid, proposals)
    with connect() as con:
        con.execute("UPDATE books SET status = 'ready', studied = ?, pid = NULL WHERE id = ?", (now_iso(), bid))
    log_run("books", "studied", book=bid, proposals=kept, cost_usd=cost)
    record_event(f"Finished studying “{b['title']}”: {kept} idea{'s' if kept != 1 else ''} waiting for you in the Library.", who="COO")
    return 0


def _fail(bid: str, why: str) -> int:
    with connect() as con:
        con.execute("UPDATE books SET status = 'failed', error = ?, pid = NULL WHERE id = ?", (why, bid))
    log_run("books", "error", book=bid, error=why)
    return 1


def plain_name(name: str) -> str:
    """A title in plain words: "runway-check" becomes "Runway check"."""
    name = name.strip()[:80]
    if re.fullmatch(r"[a-z0-9]+([-_][a-z0-9]+)+", name):
        name = re.sub(r"[-_]+", " ", name).capitalize()
    return name


def save_proposals(bid: str, proposals) -> int:
    """The study's proposals, checked; the ones that don't make sense are left out."""
    if not isinstance(proposals, list):
        return 0
    kept = 0
    with connect() as con:
        for n, p in enumerate(proposals[:20]):
            if not isinstance(p, dict) or p.get("kind") not in KINDS:
                continue
            name, summary = plain_name(str(p.get("name") or "")), str(p.get("summary") or "").strip()[:400]
            body = p.get("body")
            if not name or not summary or not body:
                continue
            if p["kind"] == "skill":
                if not isinstance(body, str) or len(body) > 20_000:
                    continue
            elif p["kind"] == "routine":
                if not isinstance(body, dict) or not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", str(body.get("workflow") or "")):
                    continue
            elif not isinstance(body, dict) or not str(body.get("goal") or "").strip():
                continue
            con.execute("""INSERT INTO book_proposals (id, book_id, kind, name, summary, source, body, position)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        ("p" + secrets.token_hex(4), bid, p["kind"], name, summary, str(p.get("source") or "")[:60],
                         body if isinstance(body, str) else json.dumps(body), n))
            kept += 1
    return kept


def progress(bid: str, chapters: int) -> str:
    """What the study is doing, in plain words, from its live events."""
    path = LIVE / f"{bid}.jsonl"
    if not path.exists():
        return "Getting started"
    read, writing = set(), ""
    for line in path.read_text(errors="ignore").splitlines()[-4000:]:
        for m in re.finditer(r"chapters/(\d+)\.md", line):
            read.add(int(m.group(1)))
        if "notes.md" in line and '"Write"' in line:
            writing = "Writing down what it learned"
        if "proposals.json" in line and '"Write"' in line:
            writing = "Drafting skills and ideas for you"
    return writing or (f"Reading chapter {max(read)} of {chapters}" if read else "Getting started")


# ---------- the owner's answers ----------

def _skill_dir(b: dict, p) -> Path:
    return SKILLS / f"book-{slug(b['title'], 24)}-{slug(p['name'], 30)}"


def _write_skill(b: dict, p) -> None:
    folder = _skill_dir(b, p)
    folder.mkdir(parents=True, exist_ok=True)
    source = f"“{b['title']}”{' by ' + b['author'] if b['author'] else ''}{', ' + p['source'] if p['source'] else ''}"
    description = f"{p['summary']} (from {source})".replace("\n", " ")
    body = p["body"].strip()
    heading = "" if body.startswith("# ") else f"# {p['name']}\n\n"  # unless the skill brings its own
    (folder / "SKILL.md").write_text(f"---\nname: {folder.name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n"
                                     f"{heading}{body}\n\nSource: {source}. The owner asked me to learn this book.\n")


def _commit(message: str) -> None:
    """Skills the engine wrote or removed for a book, committed so guard.py treats them as settled."""
    if not (ROOT / ".git").exists():
        return
    subprocess.run(["git", "add", "-A", "--", ".claude/skills"], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "-c", "user.name=COO", "-c", "user.email=coo@steerable.local", "commit", "-q", "-m", message,
                    "--", ".claude/skills"], cwd=ROOT, capture_output=True)


def answer(bid: str, pid: str, approve: bool) -> dict:
    """The owner adds a proposal (a skill is written, a routine is approved and built, a goal is set) or skips it."""
    b = get(bid)
    if not b:
        raise BookError("There's no such book.")
    with connect() as con:
        p = con.execute("SELECT * FROM book_proposals WHERE id = ? AND book_id = ?", (pid, bid)).fetchone()
    if not p:
        raise BookError("That idea isn't here any more.")
    if p["status"] != "waiting":
        raise BookError("That one's already been answered.")
    note, status = None, "declined"
    if approve:
        status = "approved"
        if p["kind"] == "skill":
            if b["status"] != "paused":
                _write_skill(b, p)
                _commit(f"Learned “{p['name']}” from {b['title']}")
            note = "Juno uses it from now on." if b["status"] != "paused" else "Added; the book is paused, so it waits."
        elif p["kind"] == "routine":
            note = _routine(b, p)
        else:
            note = _goal(b, p)
    with connect() as con:
        con.execute("UPDATE book_proposals SET status = ?, note = ?, answered = ? WHERE id = ?", (status, note, now_iso(), pid))
        waiting = con.execute("SELECT COUNT(*) FROM book_proposals WHERE book_id = ? AND status = 'waiting'", (bid,)).fetchone()[0]
        if not waiting and b["status"] == "ready":
            con.execute("UPDATE books SET status = 'learned' WHERE id = ?", (bid,))
    if approve:
        record_event(f"Learned from “{b['title']}”: {p['name']}", who="CEO")
    return get(bid)


def _routine(b: dict, p) -> str:
    import bridge
    from brief import task_id
    from propose import propose, task_line

    body = json.loads(p["body"])
    workflow = body["workflow"]
    if (ROOT / "workflows" / f"{workflow}.py").exists():
        workflow = f"{workflow}_{secrets.token_hex(2)}"
    args = argparse.Namespace(description=str(body.get("description") or p["summary"])[:190], workflow=workflow,
                              every=body.get("every") or None, at=body.get("at") or None, due=None,
                              goal=None, metric=None, saves=float(body.get("saves") or 0))
    try:
        line = task_line(args)
    except ValueError as e:
        raise BookError(f"That routine doesn't quite work: {e}") from None
    propose(line, workflow)
    bridge.set_approval(task_id(line), True)  # the owner just approved it: build it
    return "Approved: Juno is setting it up (see Work)."


def _goal(b: dict, p) -> str:
    from ops_db import connect as ops

    body = json.loads(p["body"])
    with ops() as con:
        con.execute("INSERT OR IGNORE INTO goals (goal, why, metric, target, status) VALUES (?, ?, ?, ?, 'Active')",
                    (str(body["goal"])[:200], (str(body.get("why") or "") + f" (from “{b['title']}”)")[:500],
                     str(body.get("metric") or "")[:200] or None, str(body.get("target") or "")[:100] or None))
        con.commit()
    return "Added to your goals."


def set_paused(bid: str, paused: bool) -> dict:
    """Pause a book: its skills are taken away (kept here); resume brings them back."""
    b = get(bid)
    if not b:
        raise BookError("There's no such book.")
    with connect() as con:
        skills = con.execute("SELECT * FROM book_proposals WHERE book_id = ? AND kind = 'skill' AND status = 'approved'", (bid,)).fetchall()
        waiting = con.execute("SELECT COUNT(*) FROM book_proposals WHERE book_id = ? AND status = 'waiting'", (bid,)).fetchone()[0]
        con.execute("UPDATE books SET status = ? WHERE id = ?", ("paused" if paused else ("ready" if waiting else "learned"), bid))
    for p in skills:
        if paused:
            shutil.rmtree(_skill_dir(b, p), ignore_errors=True)
        else:
            _write_skill(b, p)
    _commit(f"{'Paused' if paused else 'Resumed'} what was learned from {b['title']}")
    return get(bid)


def remove(bid: str) -> None:
    """Forget a book: its skills, text, notes and ideas. Routines and goals it led to stay (they're the owner's now)."""
    b = get(bid)
    if not b:
        raise BookError("There's no such book.")
    if b.get("pid") and alive(b["pid"]):
        try:
            os.killpg(b["pid"], 15)
        except OSError:
            pass
    with connect() as con:
        for p in con.execute("SELECT * FROM book_proposals WHERE book_id = ? AND kind = 'skill'", (bid,)).fetchall():
            shutil.rmtree(_skill_dir(b, p), ignore_errors=True)
        con.execute("DELETE FROM book_proposals WHERE book_id = ?", (bid,))
        con.execute("DELETE FROM book_text WHERE book_id = ?", (bid,))
        con.execute("DELETE FROM books WHERE id = ?", (bid,))
    shutil.rmtree(BOOKS / bid, ignore_errors=True)
    (LIVE / f"{bid}.jsonl").unlink(missing_ok=True)
    _commit(f"Forgot {b['title']}")
    record_event(f"Forgot the book “{b['title']}”.", who="CEO")


def retry(bid: str) -> dict:
    b = get(bid)
    if not b:
        raise BookError("There's no such book.")
    if b["status"] == "studying" and b.get("pid") and alive(b["pid"]):
        raise BookError("It's studying it right now.")
    with connect() as con:
        con.execute("DELETE FROM book_proposals WHERE book_id = ? AND status = 'waiting'", (bid,))
    _start(bid)
    return get(bid)


# ---------- reading ----------

def _row(r) -> dict:
    return {k: r[k] for k in r.keys()}


def get(bid: str) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT * FROM books WHERE id = ?", (bid,)).fetchone()
        if not r:
            return None
        b = _row(r)
        counts = dict(con.execute("SELECT status, COUNT(*) FROM book_proposals WHERE book_id = ? GROUP BY status", (bid,)).fetchall())
    if b["status"] == "studying" and b.get("pid") and not alive(b["pid"]):
        _fail(bid, "The study stopped (the engine restarted). Try again.")
        b["status"], b["error"] = "failed", "The study stopped (the engine restarted). Try again."
    b["waiting"], b["approved"] = counts.get("waiting", 0), counts.get("approved", 0)
    b["progress"] = progress(bid, b["chapters"]) if b["status"] == "studying" else None
    return b


def books() -> list[dict]:
    if not library.DB.exists():
        return []
    with connect() as con:
        ids = [r[0] for r in con.execute("SELECT id FROM books ORDER BY added DESC")]
    return [b for b in (get(i) for i in ids) if b]


def detail(bid: str) -> dict | None:
    b = get(bid)
    if not b:
        return None
    with connect() as con:
        props = [_row(p) for p in con.execute("SELECT * FROM book_proposals WHERE book_id = ? ORDER BY position, rowid", (bid,))]
    for p in props:
        if p["kind"] != "skill":
            try:
                p["body"] = json.loads(p["body"])
            except ValueError:
                pass
    notes = BOOKS / bid / "notes.md"
    contents = BOOKS / bid / "contents.md"
    return {**b, "proposals": props, "notes": notes.read_text()[:200_000] if notes.exists() else "",
            "contents": [line[4:] for line in contents.read_text().splitlines()[3:] if line[:2].isdigit()] if contents.exists() else []}


def search(query: str, bid: str | None = None, limit: int = 8) -> list[dict]:
    """Passages of the books (or one book) matching every word, best first."""
    words = [w for w in re.findall(r"\w+", query or "", flags=re.UNICODE)][:10]
    if not words:
        return []
    match = " ".join('"' + w.replace('"', "") + '"' for w in words)
    sql = """SELECT t.book_id, t.chapter, t.title, snippet(book_text, 3, '[', ']', ' … ', 40) AS passage, b.title AS book
             FROM book_text t JOIN books b ON b.id = t.book_id WHERE book_text MATCH ?"""
    args: list = [match]
    if bid:
        sql += " AND t.book_id = ?"
        args.append(bid)
    sql += " ORDER BY rank LIMIT ?"
    args.append(max(1, min(limit, 50)))
    with connect() as con:
        return [{"book": r["book"], "bookId": r["book_id"], "chapter": r["chapter"], "chapterTitle": r["title"],
                 "passage": r["passage"]} for r in con.execute(sql, args)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--book")
    st = sub.add_parser("study")
    st.add_argument("book")
    args = parser.parse_args()
    if args.cmd == "study":
        return study(args.book)
    if args.cmd == "list":
        for b in books():
            print(f"{b['id']}  “{b['title']}”{' by ' + b['author'] if b['author'] else ''}  ({b['status']}, {b['chapters']} chapters)")
        return 0
    found = search(args.query, args.book)
    if not found:
        print("Nothing in the books matches that.")
    for r in found:
        print(f"“{r['book']}”, ch. {r['chapter']} ({r['chapterTitle']}): {r['passage']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
