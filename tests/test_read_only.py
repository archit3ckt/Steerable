"""A paused company's engine, woken only so the owner can download their data
(STEERABLE_READ_ONLY=1): reads and the export work, every change is refused, and the
supervisor starts no heartbeat.

    python3 -m unittest tests.test_read_only -v
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_agent_api import TOKEN, build_company  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class ReadOnlyTest(unittest.TestCase):
    def test_reads_and_export_work_changes_dont(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            build_company(root)
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            env = {**os.environ, "AGENT_API_PORT": str(port), "STEERABLE_READ_ONLY": "1", "HOME": str(tmp)}
            proc = subprocess.Popen([sys.executable, "scripts/agent_api.py"], cwd=root, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                        break
                    except OSError:
                        time.sleep(0.1)

                def call(method, path, body=None):
                    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                                 data=json.dumps(body).encode() if body is not None else None,
                                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
                    try:
                        with urllib.request.urlopen(req, timeout=10) as r:
                            return r.status, r.read()
                    except urllib.error.HTTPError as e:
                        return e.code, e.read()

                status, _ = call("GET", "/v1/overview")
                self.assertEqual(status, 200)
                status, data = call("GET", "/v1/export")
                self.assertEqual(status, 200)
                self.assertGreater(len(data), 100)
                status, body = call("POST", "/v1/chat", {"text": "hi"})
                self.assertEqual(status, 409)
                self.assertIn("paused", json.loads(body)["error"])
                status, _ = call("POST", "/v1/onboarding/start", {})
                self.assertEqual(status, 409)
            finally:
                proc.terminate()
                proc.wait(5)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_supervisor_starts_nothing_else(self):
        code = ("import os, sys; sys.path.insert(0, 'container'); os.environ['STEERABLE_READ_ONLY'] = '1'\n"
                "import importlib.util as u\n"
                "spec = u.spec_from_file_location('entrypoint', 'container/entrypoint.py'); m = u.module_from_spec(spec)\n"
                "spec.loader.exec_module(m)\n"
                "print(m.READ_ONLY, sorted(m.Supervisor.wanted()))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                             env={**os.environ, "TELEGRAM_BOT_TOKEN": "x"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "True ['agent API']")  # no bridge even with a bot token


if __name__ == "__main__":
    unittest.main()
