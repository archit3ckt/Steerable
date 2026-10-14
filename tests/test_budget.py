"""The monthly limit (scripts/budget.py): Steerable Cloud's gateway decides when there is one.

    python3 -m unittest tests.test_budget
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

REPO = Path(__file__).resolve().parent.parent


class Gateway(http.server.BaseHTTPRequestHandler):
    budget: dict = {}
    keys: list = []

    def do_GET(self):
        Gateway.keys.append(self.headers.get("x-api-key"))
        data = json.dumps(Gateway.budget).encode()
        self.send_response(200 if self.path == "/budget" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class BudgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "template/scripts", cls.root / "scripts")
        (cls.root / "logs").mkdir()
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def check(self, gateway: bool = True) -> str:
        script = ("import sys; sys.path.insert(0, 'scripts')\nfrom budget import BudgetExceeded, check\n"
                  "try:\n    check()\n    print('ok')\nexcept BudgetExceeded as e:\n    print(e)")
        env = {k: v for k, v in os.environ.items() if k not in ("STEERABLE_GATEWAY_URL", "ANTHROPIC_API_KEY")}
        env["MONTHLY_BUDGET_USD"] = "20"
        if gateway:
            env.update(STEERABLE_GATEWAY_URL=f"http://127.0.0.1:{self.server.server_address[1]}", ANTHROPIC_API_KEY="sk-steerable-c1-1-sig")
        out = subprocess.run([sys.executable, "-c", script], cwd=self.root, capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_the_gateway_decides(self):
        Gateway.budget = {"spentUsd": 10, "capUsd": 62, "paused": False}  # over the local $20, under plan + top-up
        self.assertEqual(self.check(), "ok")
        self.assertEqual(Gateway.keys[-1], "sk-steerable-c1-1-sig")
        Gateway.budget = {"spentUsd": 62, "capUsd": 62, "paused": False}
        self.assertIn("included AI work is used up", self.check())
        Gateway.budget = {"spentUsd": 0, "capUsd": 62, "paused": True}
        self.assertIn("paused", self.check())

    def test_without_a_gateway_the_local_cap(self):
        (self.root / "logs/spend.jsonl").write_text("")
        self.assertEqual(self.check(gateway=False), "ok")
