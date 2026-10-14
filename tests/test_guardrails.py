"""What keeps the AI inside its space: the chat's tool permissions (bridge), the guard on its own
notes (guard.py), the standards check on routine code (routine_check.py), and the watchdog in the
daily upkeep.

    python3 -m unittest tests.test_guardrails -v
"""
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"
sys.path.insert(0, str(TEMPLATE / "scripts"))
from routine_check import check_source  # noqa: E402

GOOD = '''"""Reminds cafes to reorder. Notes live in memory/ and CLAUDE.md says how (docstrings are words)."""
import json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import library
from common import lesson, log_run, save_report, step
from state import State

def main():
    step(1)
    data = json.loads(open("prices.json").read())
    if not State().seen("cafe:1", keep_days=60):
        library.table("Leads").add({"Name": "Cafe"}, key="cafe:1")
    step(2)
    save_report("# Done")
    lesson("They prefer calls")
'''


class RoutineCheckTest(unittest.TestCase):
    def test_good_code_passes(self):
        self.assertEqual(check_source(GOOD, flow_steps=3), [])

    def test_what_it_catches(self):
        cases = {
            "Path('x.json').write_text('{}')": "write_text",
            "open('seen.json', 'w').write('x')": "opens a file for writing",
            "open(name, mode)": "opens a file for writing",
            "import subprocess": "imports subprocess",
            "import shutil\nshutil.rmtree('memory')": "imports shutil",
            "import os\nos.remove('ops.db')": "os.remove",
            "import os\nos.system('rm -rf /')": "os.system",
            "import sqlite3\nsqlite3.connect('library.db')": "imports sqlite3",
            "eval('1+1')": "eval()",
            "open('.env').read()": "refers to .env",
            "p = '/company/.cache/vault.json'": "refers to .cache",
            "x = 'memory/company.md'": "refers to memory/",
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                found = check_source(code)
                self.assertTrue(any(expected in p for p in found), found)
        self.assertIn("never calls step(n)", " ".join(check_source("print('hi')", flow_steps=3)))
        self.assertEqual(check_source("print('hi')", flow_steps=1), [])  # just the trigger: nothing to report


class ChatPermissionsTest(unittest.TestCase):
    def test_the_chat_writes_only_its_own_space(self):
        import bridge

        allowed, denied = bridge.ALLOWED_TOOLS, bridge.DENIED_TOOLS
        self.assertNotIn("Edit(./**)", allowed)
        self.assertNotIn("Write(./**)", allowed)
        self.assertNotIn("Bash(.venv/bin/python scripts/*)", allowed)
        for own in ("./memory/**", "./.claude/skills/**", "./drafts/**", "./CLAUDE.md"):
            self.assertIn(f"Write({own})", allowed)
        for system in ("./*.db", "./logs/**", "./files/**", "./.claude/settings*.json", "./.home/**", "./.venv/**",
                       "./.git/**", "./scripts/**", "./workflows/**", "./tasks.md"):
            self.assertIn(f"Write({system})", denied)
            self.assertIn(f"Edit({system})", denied)
        self.assertIn("Read(./.home/**)", denied)  # Claude's own sign-in
        for script in ("heartbeat.py", "builder.py", "ai_access.py", "tools.py", "upkeep.py", "telegram.py"):
            self.assertFalse(any(script in a for a in allowed), script)
        self.assertIn("Bash(.venv/bin/python scripts/propose.py *)", allowed)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root)
        (self.root / ".env").write_text("COMPANY_NAME=Co\n")
        (self.root / "memory/company.md").write_text("# Company\n" + "- A fact about the business.\n" * 40)
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"]):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def guard(self):
        code = "import json, sys\nsys.path.insert(0, 'scripts')\nimport guard\nprint(json.dumps(guard.check_and_commit('test')))"
        out = subprocess.run([sys.executable, "-c", code], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_bad_changes_are_put_back_and_good_ones_committed(self):
        memory, claude = self.root / "memory/company.md", self.root / "CLAUDE.md"
        original = memory.read_text()
        memory.write_text("# Company\n")  # gutted
        (self.root / "memory/decisions.md").write_text("x" * 40_000)  # bloated
        claude.write_text(claude.read_text().replace("## Rules", "## Whatever I like"))
        (self.root / "memory/blob.md").write_bytes(b"\x00\x01binary")
        (self.root / "memory/people.md").write_text("# People\n- Dana runs the cafe on Herzl.\n")  # a good, new note
        put_back = {c["file"]: c["reason"] for c in self.guard()}
        self.assertIn("cut from", put_back["memory/company.md"])
        self.assertIn("over 30 KB", put_back["memory/decisions.md"])
        self.assertIn("Rules", put_back["CLAUDE.md"])
        self.assertEqual(put_back["memory/blob.md"], "not text")
        self.assertEqual(memory.read_text(), original)
        self.assertIn("## Rules", claude.read_text())
        self.assertFalse((self.root / "memory/blob.md").exists())
        log = subprocess.run(["git", "log", "--format=%an %s", "-1", "--", "memory/people.md"], cwd=self.root,
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(log, "COO COO updated its notes (test)")
        self.assertEqual(subprocess.run(["git", "status", "--porcelain", "--", "memory", "CLAUDE.md"], cwd=self.root,
                                        capture_output=True, text=True).stdout.strip(), "")

    def test_onboarding_section_may_go(self):
        claude = self.root / "CLAUDE.md"
        text = claude.read_text()
        start = text.index("## First session: onboarding")
        end = text.index("\n## ", start + 5)
        claude.write_text(text[:start] + text[end + 1:])
        self.assertEqual(self.guard(), [])
        self.assertNotIn("First session", claude.read_text())

    def test_watchdog(self):
        (self.root / "workflows/messy.py").write_text("from pathlib import Path\nPath('seen.json').write_text('{}')\n")
        (self.root / "tasks.md").write_text("# Tasks\n\n## Open\n- [ ] Messy scan  @workflow:messy  every:daily  saves:1h\n")
        (self.root / ".cache").mkdir(exist_ok=True)
        (self.root / ".cache/huge.json").write_bytes(b"0" * (6 * 1024 * 1024))
        (self.root / "library.db").write_bytes(b"this is not a database at all" * 100)
        out = subprocess.run([sys.executable, "scripts/upkeep.py"], cwd=self.root, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        run = [json.loads(l) for l in (self.root / "logs/runs.jsonl").read_text().splitlines() if '"upkeep"' in l][-1]
        self.assertTrue(any(r.startswith("messy:") and "write_text" in r for r in run["watch_routines"]))
        self.assertIn(".cache/huge.json: 6 MB", run["watch_growth"])
        self.assertTrue(any(r.startswith("library.db") for r in run["watch_databases"]))
        status = subprocess.run([sys.executable, "scripts/status.py"], cwd=self.root, capture_output=True, text=True)
        self.assertIn("WATCH routines: messy", status.stdout)
        # It proposes bringing the routine up to standard, once.
        changes = json.loads((self.root / ".cache/changes.json").read_text())
        self.assertEqual([(c["workflow"], c["auto"], c["status"]) for c in changes.values()], [("messy", "standards", "waiting")])
        subprocess.run([sys.executable, "scripts/upkeep.py"], cwd=self.root, capture_output=True, text=True, timeout=120)
        self.assertEqual(len(json.loads((self.root / ".cache/changes.json").read_text())), 1)

    def test_tell_owner(self):
        code = ("import json, os, sys\nsys.path.insert(0, 'scripts')\nos.environ['STEERABLE_WORKFLOW'] = 'job_scan'\n"
                "from common import tell_owner\n"
                "os.environ['STEERABLE_DRY_RUN'] = '1'\nprint(tell_owner('dry'))\ndel os.environ['STEERABLE_DRY_RUN']\n"
                "print(json.dumps([tell_owner(f'**{n} new jobs**') for n in range(1, 5)]))")
        out = subprocess.run([sys.executable, "-c", code], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.strip().splitlines()
        self.assertEqual(lines[0], "Would tell the owner: dry")
        self.assertEqual(json.loads(lines[-1]), [True, True, True, False])  # three a day per routine
        chat = [json.loads(l) for l in (self.root / "logs/chat.jsonl").read_text().splitlines()]
        self.assertEqual([(m["from"], m["text"], m["routine"]) for m in chat][0], ("coo", "**1 new jobs**", "job_scan"))
        self.assertEqual(len(chat), 3)


if __name__ == "__main__":
    unittest.main()
