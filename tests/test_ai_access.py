"""Signing the COO in to a Claude account, and turning on Jev, from the dashboard
(scripts/ai_access.py). A fake `claude` plays Claude Code's sign-in: it prints a link, waits for
the code, and accepts only the right one. A fake TypeSafe answers Jev with one key only."""
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
state = Path(os.environ["HOME"]) / "signed-in"
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    yes = state.exists()
    print(json.dumps({"loggedIn": yes, "authMethod": "claude.ai" if yes else "none",
                      "email": "owner@example.com" if yes else None}))
elif args[:2] == ["auth", "login"]:
    url = "https://claude.com/cai/oauth/authorize?code=true&state=abc"
    print("Opening browser to sign in…")
    print(f"If the browser didn't open, visit: \x1b]8;;{url}\x07{url}\x1b]8;;\x07", flush=True)
    sys.stdout.write("Paste code here if prompted > "); sys.stdout.flush()
    code = sys.stdin.readline().strip()
    if code == "good-code#abc":
        state.write_text("yes"); print("Login successful.")
    else:
        print("OAuth error: invalid code"); sys.exit(1)
elif args[:2] == ["auth", "logout"]:
    state.unlink(missing_ok=True)
"""


class FakeJev(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.headers.get("Authorization") != "Bearer good-jev":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":"bad key"}')
            return
        body = json.dumps({"answers": {"decision": {"choice": "yes", "confidence": 0.9}}, "model": "jev"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


SCRIPT = """
import json, sys
sys.path.insert(0, "scripts")
import ai_access, decide
out = {}
def step(name, fn, *args):
    try:
        out[name] = fn(*args)
    except ai_access.AiError as e:
        out[name] = {"error": str(e)}
step("before", ai_access.status)
out["ai_before"] = ai_access.has_ai()
step("start", ai_access.start_login)
step("waiting", ai_access.status)
step("bad_code", ai_access.finish_login, "wrong#abc")
step("start_again", ai_access.start_login)
step("good_code", ai_access.finish_login, "good-code#abc")
out["ai_after"] = ai_access.has_ai()
step("signed_out", ai_access.sign_out)
step("bad_jev", ai_access.save_jev, "bad-jev")
step("good_jev", ai_access.save_jev, "good-jev")
out["backend"] = decide.decide("Is this a test?", ["yes", "no"], use_cache=False).backend
step("jev_off", ai_access.remove_jev)
print(json.dumps(out))
"""


class AiAccessTest(unittest.TestCase):
    def test_claude_sign_in_and_jev(self):
        jev = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeJev)
        threading.Thread(target=jev.serve_forever, daemon=True).start()
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            (bin_dir / "claude").write_text(FAKE_CLAUDE)
            (bin_dir / "claude").chmod(0o755)
            (tmp / "home").mkdir()
            env = {k: v for k, v in os.environ.items()
                   if k not in ("ANTHROPIC_API_KEY", "STEERABLE_GATEWAY_URL", "JEV_API_KEY", "DECIDE_BACKEND")}
            env.update(HOME=str(tmp / "home"), PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                       JEV_ENDPOINT=f"http://127.0.0.1:{jev.server_address[1]}/v1/systemone",
                       DECIDE_BACKEND="")  # as docker-compose passes it when unset
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env=env, capture_output=True,
                                  text=True, timeout=180)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)

            self.assertEqual(out["before"]["claude"]["method"], "none")
            self.assertFalse(out["ai_before"])  # the health line says so
            self.assertTrue(out["ai_after"])
            self.assertFalse(out["before"]["jev"]["on"])
            self.assertEqual(out["start"]["url"], "https://claude.com/cai/oauth/authorize?code=true&state=abc")
            self.assertTrue(out["waiting"]["claude"]["signingIn"])
            self.assertIn("didn't work", out["bad_code"]["error"])
            self.assertEqual(out["good_code"]["claude"]["method"], "account")
            self.assertEqual(out["good_code"]["claude"]["email"], "owner@example.com")
            self.assertFalse(out["good_code"]["claude"]["signingIn"])
            self.assertEqual(out["signed_out"]["claude"]["method"], "none")

            self.assertIn("didn't work", out["bad_jev"]["error"])
            self.assertTrue(out["good_jev"]["jev"]["on"])
            self.assertEqual(out["backend"], "jev")  # with a key and nothing chosen, decisions use Jev
            self.assertFalse(out["jev_off"]["jev"]["on"])
            # The key is kept in the vault, never in a file the agents can read.
            self.assertNotIn("good-jev", (root / ".env").read_text())
        finally:
            jev.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
