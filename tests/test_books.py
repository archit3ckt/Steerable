"""Books the owner teaches the COO (books.py): reading EPUB and text files into chapters, full-text
search, the study (its Claude session faked here), and the owner's answers: a skill written and
cited, a routine approved and sent to the builder, a goal set; pausing, resuming and removing.

    python3 -m unittest tests.test_books -v
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"


def epub() -> bytes:
    chapters = {
        "c1.xhtml": "<h1>Systems, not heroics</h1>" + "<p>Write down how every repeated task is done, so anyone can do it. </p>" * 20,
        "c2.xhtml": "<h1>The weekly scorecard</h1>" + "<p>Pick five to fifteen numbers and review them every week with an owner each. </p>" * 20,
        "cover.xhtml": "<p>Cover</p>",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   '<metadata><dc:title>Run It Like a System</dc:title><dc:creator>A. Author</dc:creator></metadata>'
                   '<manifest><item id="cover" href="cover.xhtml"/><item id="c1" href="c1.xhtml"/><item id="c2" href="c2.xhtml"/></manifest>'
                   '<spine><itemref idref="cover"/><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
        for name, body in chapters.items():
            z.writestr(f"OEBPS/{name}", f"<html><body>{body}</body></html>")
    return buf.getvalue()


SCRIPT = r"""
import json, os, subprocess, sys
sys.path.insert(0, "scripts")
import agent_api, books, bridge, builder, burst, files
out = {}
def err(fn):
    try:
        fn(); return None
    except (books.BookError, agent_api.ApiError) as e:
        return str(e) if isinstance(e, books.BookError) else e.message

saved = files.save("run-it.epub", open(sys.argv[1], "rb").read())
book = books.add(saved["id"], "It made my last shop run without me", start=False)
bid = book["id"]
out["added"] = [book["title"], book["author"], book["chapters"], book["status"], sorted(os.listdir(f"books/{bid}/chapters"))]
out["search"] = [(r["chapter"], r["chapterTitle"], "[" in r["passage"]) for r in books.search("weekly scorecard")]
out["search_none"] = books.search("zebra")

# The study, its Claude session faked: it writes the notes and the ideas.
def fake_run(cmd, **kw):
    prompt = cmd[cmd.index("-p") + 1]
    out["prompt_has"] = ["Run It Like a System" in prompt, "made my last shop" in prompt, "chapters/01.md" in prompt]
    out["tools"] = cmd[cmd.index("--allowedTools") + 1: cmd.index("--disallowedTools")]
    open(f"books/{bid}/notes.md", "w").write("## Systems, not heroics\n- Write processes down.\n")
    json.dump([
        {"kind": "skill", "name": "Write a process", "summary": "Turn any task done twice into a written process.", "source": "ch. 1",
         "body": "When a task repeats, write the steps, the tools and what done looks like."},
        {"kind": "routine", "name": "Weekly scorecard", "summary": "Every Monday, the week's key numbers.", "source": "ch. 2",
         "body": {"description": "Builds the weekly scorecard every Monday", "workflow": "weekly_scorecard", "every": "weekly", "saves": 1}},
        {"kind": "goal", "name": "Run without me", "summary": "Hand off daily work.", "source": "ch. 1",
         "body": {"goal": "The business runs a week without the owner", "metric": "days away", "target": "7"}},
        {"kind": "skill", "name": "", "summary": "no name", "body": "x"},
        {"kind": "poem", "name": "x", "summary": "x", "body": "x"},
    ], open(f"books/{bid}/proposals.json", "w"))
    return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": "ok", "total_cost_usd": 0.42}) + "\n", "")
burst.run = fake_run
built = []
builder.start_build = lambda wf, text: built.append(wf)
out["study"] = books.study(bid)
d = books.detail(bid)
out["after_study"] = [d["status"], d["cost"], [(p["kind"], p["name"]) for p in d["proposals"]], d["notes"].splitlines()[0], d["contents"]]
props = {p["name"]: p["id"] for p in d["proposals"]}

# The owner's answers
books.answer(bid, props["Write a process"], True)
skill = [p for p in os.listdir(".claude/skills") if p.startswith("book-")]
out["skill"] = [skill, open(f".claude/skills/{skill[0]}/SKILL.md").read() if skill else ""]
books.answer(bid, props["Weekly scorecard"], True)
out["routine"] = [built, [l for l in open("tasks.md").read().splitlines() if "weekly_scorecard" in l]]
api = agent_api.ROUTES
r = agent_api.book_detail(bid, {"q": ["scorecard"]})
out["passages"] = len(r["passages"])
books.answer(bid, props["Run without me"], False)
out["declined_goal_kept_out"] = True
out["again"] = err(lambda: books.answer(bid, props["Run without me"], True))
out["status"] = books.get(bid)["status"]
git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True).stdout
out["committed"] = git("log", "--format=%s", "-1", "--", ".claude/skills").strip()

books.set_paused(bid, True)
out["paused"] = [books.get(bid)["status"], [p for p in os.listdir(".claude/skills") if p.startswith("book-")]]
books.set_paused(bid, False)
out["resumed"] = [books.get(bid)["status"], [p for p in os.listdir(".claude/skills") if p.startswith("book-")]]
out["guard"] = __import__("guard").check_and_commit("test")  # the book's skill changes are already settled

out["bad_file"] = err(lambda: books.add(files.save("notes.xlsx", b"PK")["id"]))
txt = files.save("short.txt", ("# One\n" + "Pricing matters a lot. " * 50 + "\n# Two\n" + "Hire slowly. " * 60).encode())
t2 = books.add(txt["id"], start=False)
out["txt"] = [t2["title"], t2["chapters"]]
out["api_list"] = [b["title"] for b in agent_api.ROUTES and books.books()]
books.remove(bid)
out["removed"] = [books.get(bid), os.path.exists(f"books/{bid}"), [p for p in os.listdir(".claude/skills") if p.startswith("book-")],
                  books.search("scorecard"), "weekly_scorecard" in open("tasks.md").read()]
out["missing"] = err(lambda: agent_api.book_detail("b00000000", {}))
print(json.dumps(out, ensure_ascii=False, default=str))
"""


class BooksTest(unittest.TestCase):
    def test_teach_a_book(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\nMONTHLY_BUDGET_USD=20\n")
            (root / "tasks.md").write_text("# Tasks\n\n## Open\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"]):
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            (tmp / "book.epub").write_bytes(epub())
            proc = subprocess.run([sys.executable, "-c", SCRIPT, str(tmp / "book.epub")], cwd=root, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout.strip().splitlines()[-1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(out["added"], ["Run It Like a System", "A. Author", 2, "studying", ["01.md", "02.md"]])  # the cover isn't a chapter
        self.assertEqual(out["search"][0][:2], [2, "The weekly scorecard"])
        self.assertTrue(out["search"][0][2])  # the matching words are marked
        self.assertEqual(out["search_none"], [])
        self.assertEqual(out["prompt_has"], [True, True, True])
        self.assertIn("Read(./books/", out["tools"][0])
        self.assertIn(f"Edit(./books/{out['tools'][0].split('/')[2]}/notes.md)", out["tools"])  # writes are granted by Edit rules
        self.assertTrue(all(not t.startswith("Bash") for t in out["tools"]))
        self.assertEqual({t.split("/")[-1].rstrip(")") for t in out["tools"] if t.startswith(("Edit", "Write"))}, {"notes.md", "proposals.json"})
        status, cost, proposals, first_note, contents = out["after_study"]
        self.assertEqual((status, cost), ("ready", 0.42))
        self.assertEqual(proposals, [["skill", "Write a process"], ["routine", "Weekly scorecard"], ["goal", "Run without me"]])
        self.assertEqual(first_note, "## Systems, not heroics")
        self.assertEqual(contents, ["Systems, not heroics", "The weekly scorecard"])
        names, text = out["skill"]
        self.assertEqual(names, ["book-run-it-like-a-system-write-a-process"])
        self.assertIn("name: book-run-it-like-a-system-write-a-process", text)
        self.assertIn("description: \"Turn any task done twice into a written process. (from “Run It Like a System” by A. Author, ch. 1)\"", text)
        self.assertIn("Source: “Run It Like a System” by A. Author, ch. 1", text)
        self.assertEqual(out["routine"][0], ["weekly_scorecard"])
        self.assertIn("approved", out["routine"][1][0])
        self.assertNotIn("needs:approval", out["routine"][1][0])
        self.assertGreater(out["passages"], 0)
        self.assertIn("already been answered", out["again"])
        self.assertEqual(out["status"], "learned")
        self.assertEqual(out["committed"], "Learned “Write a process” from Run It Like a System")
        self.assertEqual(out["paused"], ["paused", []])
        self.assertEqual(out["resumed"], ["learned", ["book-run-it-like-a-system-write-a-process"]])
        self.assertEqual(out["guard"], [])
        self.assertIn("EPUB, PDF, Word", out["bad_file"])
        self.assertEqual(out["txt"], ["short", 2])
        removed = out["removed"]
        self.assertEqual(removed[:4], [None, False, [], []])
        self.assertTrue(removed[4])  # the routine it led to stays: it's the owner's now
        self.assertIn("no such book", out["missing"])


if __name__ == "__main__":
    unittest.main()
