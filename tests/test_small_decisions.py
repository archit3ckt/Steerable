"""Small decisions settled for the owner (small_decisions.py): off by default; when on, a small
question asked with ask.py is settled with the COO's pick, never one about money, people outside,
deleting, logins, legal matters or hiring; the owner can undo it, and it comes back to them.
A fake Jev answers the "is it small?" check.

    python3 -m unittest tests.test_small_decisions -v
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"


class Jev(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.dumps({"answers": {"decision": {"choice": "settle", "confidence": 0.93}}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


class SmallDecisionsTest(unittest.TestCase):
    def setUp(self):
        self.jev = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Jev)
        threading.Thread(target=self.jev.serve_forever, daemon=True).start()
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root, ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / ".env").write_text("COMPANY_NAME=Co\n")
        self.env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "STEERABLE_GATEWAY_URL", "DECIDE_BACKEND")}
        self.env.update(HOME=str(self.tmp), JEV_API_KEY="k", JEV_ENDPOINT=f"http://127.0.0.1:{self.jev.server_address[1]}/v1/systemone")
        subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=self.root, check=True, capture_output=True, env=self.env)

    def tearDown(self):
        self.jev.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ask(self, question, context, *options, pick):
        args = [sys.executable, "scripts/ask.py", question, "--context", context, "--recommend", pick, "--why", "It reads best."]
        for o in options:
            args += ["--option", o]
        return subprocess.run(args, cwd=self.root, capture_output=True, text=True, env=self.env, timeout=60)

    def py(self, code):
        out = subprocess.run([sys.executable, "-c", "import json, sys; sys.path.insert(0, 'scripts'); import small_decisions as s\n" + code],
                             cwd=self.root, capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def waiting(self):
        con = __import__("sqlite3").connect(self.root / "ops.db")
        return [r[0] for r in con.execute("SELECT mission FROM missions WHERE status = 'Waiting on CEO'")]

    def test_off_by_default_then_settled_and_undone(self):
        small = ("Order of the weekly report", "The weekly report can list routines by name or by when they ran.",
                 "name=By name", "time=By time")
        out = self.ask(*small, pick="time")
        self.assertIn("waiting for the owner", out.stdout)  # off: it's theirs, as always
        self.assertEqual(self.waiting(), ["Order of the weekly report"])

        self.py("s.set_on(True); print('true')")
        out = self.ask("Layout of the weekly report", "One page, or one section per routine.", "one=One page", "per=One section each", pick="per")
        self.assertIn('go with "One section each"', out.stdout)
        self.assertNotIn("Layout of the weekly report", self.waiting())
        settled = self.py("print(json.dumps(s.recent()))")
        self.assertEqual([(i["question"], i["chosen"]) for i in settled], [("Layout of the weekly report", "One section each")])
        self.assertIn("Settled 1 small thing for you", self.py("print(json.dumps(s.brief_line()))"))

        # Never settled for them: money, and people outside the business.
        out = self.ask("Raise the delivery fee", "Couriers cost more.", "yes=Raise it to $6", "no=Keep it", pick="yes")
        self.assertIn("waiting for the owner", out.stdout)
        out = self.ask("Which supplier to write to", "Two can deliver Friday.", "a=GreenLeaf", "b=Fresh Co", pick="a")
        self.assertIn("waiting for the owner", out.stdout)

        # Undo: it comes back to them, and is remembered.
        mission = settled[0]["id"]
        self.assertTrue(self.py(f"print(json.dumps(bool(s.undo({mission}))))"))
        self.assertIn("Layout of the weekly report", self.waiting())
        self.assertEqual(self.py("print(json.dumps(s.recent()))"), [])
        self.assertIsNone(self.py(f"print(json.dumps(s.undo({mission})))"))  # once


if __name__ == "__main__":
    unittest.main()
