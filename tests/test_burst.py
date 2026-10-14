"""Burst Jobs, the engine's side (scripts/burst.py).

A fake platform stands in for Steerable Cloud's jobs endpoint: on POST it runs
`scripts/burst.py exec <id>` as a separate process in the same folder, which is what a Job does
on the same volume.

    python3 -m unittest tests.test_burst
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


class Platform(http.server.BaseHTTPRequestHandler):
    root: Path
    requests: list = []
    mode = "run"      # run | oom | refuse
    states: dict = {}
    jobs: list = []

    def _json(self, status: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Platform.requests.append({"auth": self.headers.get("Authorization"), **body})
        if Platform.mode == "refuse":
            return self._json(503, {"error": "Couldn't start the job."})
        if Platform.mode == "oom":
            Platform.states[body["id"]] = {"state": "failed", "reason": "it ran out of memory"}
        else:
            Platform.states[body["id"]] = {"state": "running"}
            job_env = {k: v for k, v in os.environ.items() if k != "STEERABLE_JOBS_URL"}
            job_env["JOB_MARKER"] = "in-the-job"
            Platform.jobs.append(subprocess.Popen([sys.executable, "scripts/burst.py", "exec", body["id"]],
                                                  cwd=Platform.root, env=job_env))
        self._json(201, {"id": body["id"]})

    def do_GET(self):
        self._json(200, Platform.states.get(self.path.rsplit("/", 1)[-1], {"state": "gone"}))

    def log_message(self, *args):
        pass


class BurstTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "template/scripts", cls.root / "scripts")
        Platform.root = cls.root
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Platform)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        for job in Platform.jobs:
            job.wait()
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def run_burst(self, call: str, jobs: bool = True) -> dict:
        """Run burst.run(<call>) in a fresh engine process and return what it got back."""
        script = f"""
import json, subprocess, sys
sys.path.insert(0, "scripts")
import burst
burst.CHECK_EVERY = 0.2
try:
    p = {call}
    print(json.dumps({{"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}}))
except subprocess.TimeoutExpired as e:
    print(json.dumps({{"timeout": True}}))
"""
        env = {k: v for k, v in os.environ.items() if k not in ("STEERABLE_JOBS_URL", "STEERABLE_IN_BURST")}
        env["ANTHROPIC_API_KEY"] = "sk-steerable-c1-1-sig"
        if jobs:
            env["STEERABLE_JOBS_URL"] = self.url
        Platform.requests.clear()
        out = subprocess.run([sys.executable, "-c", script], cwd=self.root, capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    PRINT_ENV = ('burst.run([sys.executable, "-c", "import os; print(os.environ.get(\'JOB_MARKER\'), '
                 'os.environ.get(\'STEERABLE_CONTEXT\'), os.environ.get(\'STEERABLE_IN_BURST\'))"], '
                 'kind="browser", timeout=30, env={**__import__("os").environ, "STEERABLE_CONTEXT": "routine"})')

    def test_runs_here_without_a_platform(self):
        got = self.run_burst(self.PRINT_ENV, jobs=False)
        self.assertEqual(got["stdout"].split(), ["None", "routine", "None"])
        self.assertEqual(Platform.requests, [])

    def test_runs_in_a_job_with_the_same_folder(self):
        Platform.mode = "run"
        got = self.run_burst(self.PRINT_ENV)
        # Ran in the "Job" process, with the caller's extra environment, marked as inside a Job.
        self.assertEqual(got["stdout"].split(), ["in-the-job", "routine", "1"])
        self.assertEqual(Platform.requests[0]["kind"], "browser")
        self.assertEqual(Platform.requests[0]["timeoutSeconds"], 30)
        self.assertEqual(Platform.requests[0]["auth"], "Bearer sk-steerable-c1-1-sig")
        self.assertEqual(list((self.root / ".cache/jobs").iterdir()), [])  # nothing left behind

        # Output, exit codes and files written in the Job all come back.
        got = self.run_burst('burst.run([sys.executable, "-c", "open(\'memory-note.md\', \'w\').write(\'kept\'); '
                             'import sys; print(\'out\'); sys.exit(3)"], kind="claude", timeout=30)')
        self.assertEqual((got["returncode"], got["stdout"].strip()), (3, "out"))
        self.assertEqual((self.root / "memory-note.md").read_text(), "kept")

    def test_output_streams_to_a_file(self):
        """With stream=, stdout also lands in a file in the shared folder, here and in a Job."""
        Platform.mode = "run"
        call = 'burst.run([sys.executable, "-c", "print(\'one\'); print(\'two\')"], kind="claude", timeout=30, stream="live.txt")'
        for jobs in (False, True):
            got = self.run_burst(call, jobs=jobs)
            self.assertEqual(got["stdout"].split(), ["one", "two"])
            self.assertEqual((self.root / "live.txt").read_text().split(), ["one", "two"])
            (self.root / "live.txt").unlink()

    def test_a_job_that_runs_too_long(self):
        Platform.mode = "run"
        got = self.run_burst('burst.run([sys.executable, "-c", "import time; time.sleep(5)"], kind="claude", timeout=1)')
        self.assertEqual(got, {"timeout": True})

    def test_a_job_that_fails(self):
        Platform.mode = "oom"
        got = self.run_burst('burst.run(["true"], kind="claude", timeout=30)')
        self.assertEqual(got["returncode"], 137)
        self.assertEqual(got["stderr"], "The job stopped: it ran out of memory.")

    def test_platform_refuses(self):
        Platform.mode = "refuse"
        got = self.run_burst('burst.run(["true"], kind="claude", timeout=30)')
        self.assertEqual(got["returncode"], 1)
        self.assertIn("Couldn't start a job", got["stderr"])
        Platform.mode = "run"


if __name__ == "__main__":
    unittest.main()
