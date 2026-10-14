"""Engine updates for existing companies (container/entrypoint.py: update_engine).

Builds a company from a copy of the template the way the container does, lets the "company"
change things the way a COO would, then ships new template versions and checks what an update
keeps, adds, and refuses.

    python3 -m unittest discover -s tests
"""
import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GIT_ENV = {"GIT_AUTHOR_NAME": "COO", "GIT_AUTHOR_EMAIL": "coo@test", "GIT_COMMITTER_NAME": "COO", "GIT_COMMITTER_EMAIL": "coo@test"}


def load_entrypoint(template: Path, company: Path, version_file: Path):
    os.environ.update({"STEERABLE_TEMPLATE": str(template), "COMPANY_DIR": str(company), "STEERABLE_PY": sys.executable,
                       "STEERABLE_VERSION_FILE": str(version_file), "COMPANY_NAME": "Bloom & Root", **GIT_ENV})
    spec = importlib.util.spec_from_file_location("entrypoint", REPO / "container/entrypoint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EngineUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.template = self.tmp / "template"
        shutil.copytree(REPO / "template", self.template, ignore=shutil.ignore_patterns("__pycache__"))
        self.company = self.tmp / "company"
        self.company.mkdir()
        self.version = self.tmp / "VERSION"
        self.version.write_text("v1")
        self.ep = load_entrypoint(self.template, self.company, self.version)
        self.ep.init_company()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ship(self, version: str, change):
        change(self.template)
        self.version.write_text(version)

    def edit(self, path: Path, old: str, new: str):
        text = path.read_text()
        assert old in text, old
        path.write_text(text.replace(old, new, 1))

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.company, capture_output=True, text=True, check=True).stdout

    def test_up_to_date_does_nothing(self):
        self.assertEqual(self.ep.update_engine(), "current")

    def test_engine_files_that_moved_are_taken_out(self):
        """The engine's own jobs used to be in workflows/. An update removes those copies, even
        ones changed here, and the company's own routines stay."""
        # As an older engine shipped them: the same files, in workflows/ (so git sees a move).
        for name in ("learn", "curate_skills"):
            (self.company / f"scripts/{name}.py").rename(self.company / f"workflows/{name}.py")
        self.git("add", "-A")
        self.git("commit", "-qm", "as shipped before")
        self.git("branch", "-f", "engine", "HEAD")
        with (self.company / "workflows/learn.py").open("a") as f:
            f.write("# patched here\n")  # and changed here, uncommitted
        (self.company / "workflows/reorder_reminders.py").write_text("print('ok')\n")
        self.ship("v2", lambda t: None)
        self.assertEqual(self.ep.update_engine(), "updated")
        self.assertFalse((self.company / "workflows/learn.py").exists())
        self.assertFalse((self.company / "workflows/curate_skills.py").exists())
        self.assertTrue((self.company / "scripts/learn.py").exists())
        self.assertTrue((self.company / "workflows/reorder_reminders.py").exists())
        self.assertTrue((self.company / "workflows/_template.py").exists())

    def test_a_company_left_halfway_by_an_earlier_try_catches_up(self):
        """An earlier update took the old copies out but couldn't finish. The next one does."""
        for name in ("learn", "curate_skills"):
            (self.company / f"scripts/{name}.py").rename(self.company / f"workflows/{name}.py")
        self.git("add", "-A")
        self.git("commit", "-qm", "as shipped before")
        self.git("branch", "-f", "engine", "HEAD")
        self.git("rm", "-q", "workflows/learn.py", "workflows/curate_skills.py")
        self.git("commit", "-qm", "Remove engine files that moved")
        self.ship("v2", lambda t: None)
        self.assertEqual(self.ep.update_engine(), "updated")
        self.assertTrue((self.company / "scripts/learn.py").exists())
        self.assertTrue((self.company / "scripts/curate_skills.py").exists())
        self.assertFalse((self.company / "workflows/learn.py").exists())
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_update_keeps_the_companys_changes(self):
        # What a COO does: fixes a script (an incident fix), finishes onboarding, writes memory.
        self.edit(self.company / "scripts/status.py", "One-screen status", "One-screen status (fixed by the COO)")
        claude = self.company / "CLAUDE.md"
        text = claude.read_text()
        claude.write_text(text[: text.index("## First session: onboarding")] + text[text.index("## Layout"):])
        (self.company / "memory/company.md").write_text("We sell plants to cafes.\n")
        (self.company / "workflows/reorder_reminders.py").write_text("print('ok')\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "COO work")

        # The new engine: a changed script, a new script, a changed CLAUDE.md section.
        def change(t: Path):
            self.edit(t / "scripts/budget.py", "Spend tracking and the monthly budget cap.", "Spend tracking and the monthly budget cap (v2).")
            (t / "scripts/new_feature.py").write_text("print('new')\n")
            self.edit(t / "CLAUDE.md", "## Rules", "## Rules\n(v2: rules are numbered below.)")
        self.ship("v2", change)
        self.assertEqual(self.ep.update_engine(), "updated")

        self.assertIn("(v2)", (self.company / "scripts/budget.py").read_text())
        self.assertTrue((self.company / "scripts/new_feature.py").exists())
        self.assertIn("(fixed by the COO)", (self.company / "scripts/status.py").read_text())
        claude_now = claude.read_text()
        self.assertIn("(v2: rules are numbered below.)", claude_now)
        self.assertNotIn("## First session: onboarding", claude_now)  # stays done
        self.assertIn("# Bloom & Root operations", claude_now)  # placeholders filled, not reset
        self.assertEqual((self.company / "memory/company.md").read_text(), "We sell plants to cafes.\n")
        self.assertTrue((self.company / "workflows/reorder_reminders.py").exists())
        self.assertIn("Update the engine to v2", self.git("log", "--format=%s", "-3"))
        con = sqlite3.connect(self.company / "ops.db")
        self.assertIn("Got the latest Steerable improvements (version v2).", [r[0] for r in con.execute("SELECT what FROM activity")])
        self.assertEqual(self.ep.update_engine(), "current")

    def test_a_clash_changes_nothing(self):
        self.edit(self.company / "scripts/budget.py", "Spend tracking and the monthly budget cap.", "Spend tracking, the COO's way.")
        self.git("commit", "-qam", "COO fix")
        before = self.git("rev-parse", "HEAD")
        self.ship("v2", lambda t: self.edit(t / "scripts/budget.py", "Spend tracking and the monthly budget cap.", "Spend tracking, the engine's way."))
        self.assertEqual(self.ep.update_engine(), "conflict")
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertIn("the COO's way", (self.company / "scripts/budget.py").read_text())
        self.assertEqual(self.git("status", "--porcelain").strip(), "")
        con = sqlite3.connect(self.company / "ops.db")
        self.assertTrue(any("Couldn't apply the latest engine improvements" in r[0] for r in con.execute("SELECT what FROM activity")))
        self.assertNotEqual(self.ep.update_engine(), "current")  # tried again next start

    def test_a_clash_in_the_manual_keeps_the_companys_wording_and_updates_the_rest(self):
        self.edit(self.company / "CLAUDE.md", "## First session: onboarding", "## How we work here\nWe close on Sundays.\n\n## First session: onboarding")
        self.git("commit", "-qam", "COO notes")

        def change(t):
            self.edit(t / "CLAUDE.md", "## First session: onboarding", "## Something new from the engine\n\n## First session: onboarding")
            (t / "scripts/new_feature.py").write_text("print('new')\n")
        self.ship("v2", change)
        self.assertEqual(self.ep.update_engine(), "updated")
        manual = (self.company / "CLAUDE.md").read_text()
        self.assertIn("We close on Sundays.", manual)
        self.assertNotIn("<<<<<<<", manual)
        self.assertTrue((self.company / "scripts/new_feature.py").exists())
        self.assertEqual(self.git("status", "--porcelain").strip(), "")

    def test_a_company_from_before_updates(self):
        # No engine branch or version record: its first commit is the template as shipped.
        self.git("branch", "-D", "engine")
        (self.company / ".git/steerable-engine.json").unlink()
        self.edit(self.company / "scripts/status.py", "One-screen status", "One-screen status (fixed)")
        self.git("commit", "-qam", "COO fix")
        self.ship("v2", lambda t: (t / "scripts/new_feature.py").write_text("print('new')\n"))
        self.assertEqual(self.ep.update_engine(), "updated")
        self.assertTrue((self.company / "scripts/new_feature.py").exists())
        self.assertIn("(fixed)", (self.company / "scripts/status.py").read_text())



class NewCompanyTest(unittest.TestCase):
    """Setting up a new company on a fresh volume (container/entrypoint.py: init_company)."""

    def test_a_volume_root_it_doesnt_own_and_a_failed_first_start(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        company = tmp / "company"
        company.mkdir()
        (company / "lost+found").mkdir()
        version = tmp / "VERSION"
        version.write_text("v1")
        ep = load_entrypoint(REPO / "template", company, version)
        # A volume's root belongs to root: changing its mode or times is refused.
        real_copystat = shutil.copystat

        def copystat(src, dst, **kwargs):
            if Path(dst) == company:
                raise PermissionError(1, "Operation not permitted")
            return real_copystat(src, dst, **kwargs)
        ep.shutil.copystat = copystat
        self.addCleanup(setattr, ep.shutil, "copystat", real_copystat)
        # A first start that died after copying some files.
        (company / "tasks.md").write_text("half copied")

        ep.init_company()
        git = lambda *a: subprocess.run(["git", *a], cwd=company, capture_output=True, text=True, check=True).stdout  # noqa: E731
        self.assertEqual(git("log", "--format=%s").strip(), "Start Bloom & Root")
        self.assertNotIn("{{COMPANY}}", (company / "CLAUDE.md").read_text())
        self.assertNotIn("half copied", (company / "tasks.md").read_text())
        self.assertTrue((company / ".git/steerable-engine.json").exists())
        self.assertTrue((company / "ops.db").exists())
        ep.init_company()  # set up: nothing happens
        self.assertEqual(git("rev-list", "--count", "HEAD").strip(), "1")



def company_archive(files: dict[str, bytes], extra=None) -> bytes:
    """A company archive like /v1/export makes, plus anything `extra` adds to the tar."""
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if extra:
            extra(tar)
    return buf.getvalue()


class ImportTest(unittest.TestCase):
    """Bringing in a company someone already had (container/entrypoint.py: bring_in_import)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.template = self.tmp / "template"
        shutil.copytree(REPO / "template", self.template, ignore=shutil.ignore_patterns("__pycache__"))
        self.company = self.tmp / "company"
        self.company.mkdir()
        self.shared = self.tmp / "shared"
        self.shared.mkdir()
        self.version = self.tmp / "VERSION"
        self.version.write_text("v1")
        os.environ["STEERABLE_SHARED_DIR"] = str(self.shared)
        self.addCleanup(os.environ.pop, "STEERABLE_SHARED_DIR", None)
        self.ep = load_entrypoint(self.template, self.company, self.version)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.company, capture_output=True, text=True, check=True).stdout

    def board_with_goal(self) -> bytes:
        db = self.tmp / "board.db"
        sys.path.insert(0, str(REPO / "template/scripts"))
        try:
            from ops_db import SCHEMA
        finally:
            sys.path.pop(0)
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.execute("INSERT INTO goals (goal, created) VALUES ('40 cafe accounts', '2026-01-01')")
        con.commit()
        con.close()
        return db.read_bytes()

    def test_brings_in_the_company_and_keeps_it_through_updates(self):
        claude = (self.template / "CLAUDE.md").read_text().replace("{{COMPANY}}", "Bloom & Root")
        files = {
            "company/CLAUDE.md": (claude + "\nWe close on Sundays.\n").encode(),
            "company/memory/company.md": b"# Bloom & Root\nPlants for cafes.\n",
            "company/workflows/reorder.py": b"print('reminded 6 cafes')\n",
            "company/ops.db": self.board_with_goal(),
            # Not company files: never brought in.
            "company/scripts/budget.py": b"BROKEN = True\n",
            "company/.env": b"ANTHROPIC_API_KEY=someone-elses\n",
            "company/../escape.txt": b"outside\n",
            "elsewhere/x.txt": b"no\n",
        }

        def link(tar):
            import tarfile
            info = tarfile.TarInfo("company/memory/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        (self.shared / "import.tar.gz").write_bytes(company_archive(files, link))

        self.ep.init_company()
        self.assertIn("We close on Sundays.", (self.company / "CLAUDE.md").read_text())
        self.assertEqual((self.company / "workflows/reorder.py").read_text(), "print('reminded 6 cafes')\n")
        self.assertNotIn("BROKEN", (self.company / "scripts/budget.py").read_text())
        self.assertFalse((self.company / ".env").exists())
        self.assertFalse((self.tmp / "escape.txt").exists())
        self.assertFalse((self.company / "memory/link").exists())
        con = sqlite3.connect(self.company / "ops.db")
        self.assertEqual(con.execute("SELECT goal FROM goals").fetchone()[0], "40 cafe accounts")
        con.close()
        self.assertEqual(self.git("log", "--format=%s").split("\n")[:2], ["Bring in Bloom & Root's company", "Start Bloom & Root"])
        self.assertEqual(self.git("rev-parse", "engine"), self.git("rev-parse", "HEAD~1"))  # the base: the engine as shipped
        self.assertTrue((self.shared / "import.tar.gz.done").exists())

        # An engine update keeps what they brought.
        (self.template / "scripts/new_feature.py").write_text("print('new')\n")
        self.version.write_text("v2")
        self.assertEqual(self.ep.update_engine(), "updated")
        self.assertTrue((self.company / "scripts/new_feature.py").exists())
        self.assertIn("We close on Sundays.", (self.company / "CLAUDE.md").read_text())

    def test_a_broken_archive_starts_fresh_and_says_so(self):
        (self.shared / "import.tar.gz").write_bytes(b"not a tarball")
        self.ep.init_company()
        self.assertEqual(self.git("log", "--format=%s").strip(), "Start Bloom & Root")
        self.assertEqual(self.git("status", "--porcelain").strip(), "")
        con = sqlite3.connect(self.company / "ops.db")
        notes = [r[0] for r in con.execute("SELECT what FROM activity")]
        con.close()
        self.assertTrue(any("fresh start" in n for n in notes), notes)


if __name__ == "__main__":
    unittest.main()
