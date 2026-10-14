"""decide.py's second opinion when Jev is unsure: Haiku through the API key, or, for an engine
signed in with a Claude account and no key, through Claude Code (a fake `claude` here).

    python3 -m unittest tests.test_decide -v
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

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
Path(os.environ["SEEN"]).write_text(json.dumps({"args": args, "cwd": os.getcwd()}))
print(json.dumps({"result": "", "structured_output": {"choice": "fit", "confidence": 0.9, "reason": "DevOps, remote"},
                  "total_cost_usd": 0.0004}))
"""


class UnsureJev(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.dumps({"answers": {"decision": {"choice": "not_fit", "confidence": 0.08}}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


class SecondOpinionTest(unittest.TestCase):
    def test_haiku_through_the_claude_account(self):
        jev = http.server.ThreadingHTTPServer(("127.0.0.1", 0), UnsureJev)
        threading.Thread(target=jev.serve_forever, daemon=True).start()
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\n")
            (tmp / "bin").mkdir()
            (tmp / "bin/claude").write_text(FAKE_CLAUDE)
            (tmp / "bin/claude").chmod(0o755)
            env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "STEERABLE_GATEWAY_URL", "DECIDE_BACKEND")}
            env.update(PATH=f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}", HOME=str(tmp), SEEN=str(tmp / "seen.json"),
                       JEV_API_KEY="k", JEV_ENDPOINT=f"http://127.0.0.1:{jev.server_address[1]}/v1/systemone",
                       ANTHROPIC_API_KEY="")  # as docker-compose passes it: signed in with an account instead
            code = ("import json, sys\nsys.path.insert(0, 'scripts')\nfrom decide import decide\n"
                    "d = decide('Is this job a good fit?', ['fit', 'not_fit'], context='Junior DevOps, remote', use_cache=False)\n"
                    "print(json.dumps(d.__dict__))")
            proc = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            d = json.loads(proc.stdout)
            self.assertEqual((d["choice"], d["backend"]), ("fit", "haiku"))  # Jev was unsure; Haiku answered
            seen = json.loads((tmp / "seen.json").read_text())
            self.assertEqual(seen["args"][seen["args"].index("--model") + 1], "haiku")
            self.assertNotEqual(Path(seen["cwd"]).resolve(), root.resolve())  # not in the company folder
            spend = [json.loads(l) for l in (root / "logs/spend.jsonl").read_text().splitlines()]
            self.assertIn("haiku", {s.get("model") for s in spend})
        finally:
            jev.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
