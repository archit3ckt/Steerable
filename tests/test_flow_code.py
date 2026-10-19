"""The code view on a routine's page: which lines of its code do each step (flow.map_code), kept
beside the steps and worked out again when the code changes. A fake Messages API answers.

    python3 -m unittest tests.test_flow_code -v
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

CODE = "\n".join([
    '"""Remind cafes to reorder."""',      # 1
    "import sys",                          # 2
    "",                                    # 3
    "def orders():",                       # 4
    "    return []",                       # 5
    "",                                    # 6
    "def remind(cafes):",                  # 7
    "    print('sent', len(cafes))",       # 8
    "",                                    # 9
    "remind(orders())",                    # 10
])


class FakeModel(http.server.BaseHTTPRequestHandler):
    asked: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeModel.asked.append(body)
        # Step 2 reads (lines 4-5), step 3 sends (7-8 and 10); a range past the end and an overlap are dropped.
        answer = {"steps": [{"step": 2, "ranges": [[4, 5]]}, {"step": 3, "ranges": [[7, 8], [10, 10], [5, 7], [40, 50]]}, {"step": 9, "ranges": [[1, 1]]}]}
        data = json.dumps({"id": "m", "type": "message", "role": "assistant", "model": body["model"],
                           "content": [{"type": "text", "text": json.dumps(answer)}], "usage": {"input_tokens": 10, "output_tokens": 5}}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


class CodeMapTest(unittest.TestCase):
    def test_lines_for_each_step(self):
        api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
        threading.Thread(target=api.serve_forever, daemon=True).start()
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root, ignore=shutil.ignore_patterns("__pycache__"))
            (root / ".env").write_text("COMPANY_NAME=Co\n")
            (root / "workflows/reorder.py").write_text(CODE)
            (root / "workflows/reorder.flow.json").write_text(json.dumps({"steps": [
                {"kind": "trigger", "label": "Every Monday"}, {"kind": "read", "label": "Read orders"}, {"kind": "send", "label": "Send reminders"}]}))
            env = {**os.environ, "HOME": str(tmp), "ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{api.server_address[1]}"}
            py = lambda code: subprocess.run([sys.executable, "-c", "import json, sys; sys.path.insert(0, 'scripts'); import flow\n" + code],  # noqa: E731
                                             cwd=root, env=env, capture_output=True, text=True, timeout=60)
            out = py("print(json.dumps([flow.code_map('reorder'), flow.map_code('reorder'), flow.code_map('reorder')]))")
            self.assertEqual(out.returncode, 0, out.stderr)
            before, made, after = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertIsNone(before)  # not worked out yet
            self.assertEqual(made, [[], [[4, 5]], [[7, 8], [10, 10]]])
            self.assertEqual(after, made)  # kept beside the steps
            prompt = FakeModel.asked[-1]["messages"][0]["content"][-1]["text"]
            self.assertIn("   4 def orders():", prompt)  # numbered lines
            self.assertIn("2. [read] Read orders", prompt)
            # The steps stay as they were; a change to the code makes the map stale.
            saved = json.loads((root / "workflows/reorder.flow.json").read_text())
            self.assertEqual(len(saved["steps"]), 3)
            (root / "workflows/reorder.py").write_text(CODE + "\nprint('done')\n")
            self.assertEqual(json.loads(py("print(json.dumps(flow.code_map('reorder')))").stdout.strip()), None)
        finally:
            api.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
