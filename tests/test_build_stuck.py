"""A routine is never "being set up" for hours. A build stops itself at its time limit by the clock on the
wall (its watchdog stops the AI session and everything under it), and that's a failure the engine tries
again, unseen. The heartbeat's recovery stops a build still running past its time instead of only
relabelling it, and tells a build's own process from another one that got the same pid after a restart.

    python3 -m unittest tests.test_build_stuck -v
"""
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402

# Never answers: starts a child that would outlive it, notes both pids, and waits.
FAKE_CLAUDE = r"""#!/usr/bin/env python3
import os, subprocess, sys, time
if "-p" not in sys.argv:
    sys.exit(0)
child = subprocess.Popen(["sleep", "300"])
open(os.environ["FAKE_LOG"] + ".pids", "w").write(f"{os.getpid()} {child.pid}")
time.sleep(300)
"""

BUILD = r"""
import json, subprocess, time
import builder
real_popen = subprocess.Popen
builder.subprocess.Popen = lambda cmd, *a, **k: None if str(cmd[1]).endswith("builder.py") else real_popen(cmd, *a, **k)
bid = builder.start_build("count_new", "Count new things  @workflow:count_new  every:daily")
started = time.time()
builder.build(bid)
print(json.dumps({"seconds": time.time() - started, "build": builder.load()[bid]}))
"""

RECOVER = r"""
import json, subprocess
import builder
real_popen = subprocess.Popen
builder.subprocess.Popen = lambda cmd, *a, **k: None if str(cmd[1]).endswith("builder.py") else real_popen(cmd, *a, **k)
print(json.dumps({"done": builder.recover_stale(), "builds": builder.load()}))
"""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except OSError:
        return False


def ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


class BuildStuckTest(unittest.TestCase):
    def setUp(self):
        self.co = Company(fake_claude=FAKE_CLAUDE)
        (self.co.root / "tasks.md").write_text(
            "# Tasks\n\n## Open\n- [ ] Count new things  @workflow:count_new  every:daily  approved\n")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        self.co.close()

    def tree(self) -> subprocess.Popen:
        """A stand-in for a build's process: it has a child of its own, like an AI session."""
        p = subprocess.Popen([sys.executable, "-c", "import subprocess, time; subprocess.Popen(['sleep', '300']); time.sleep(300)"])
        self.procs.append(p)
        time.sleep(0.5)
        return p

    def children(self, pid: int) -> list[int]:
        return [int(c) for c in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()]

    def test_a_build_past_its_limit_stops_itself(self):
        out = self.co.py(BUILD, timeout=120, STEERABLE_BUILD_LIMIT_SECONDS="3")
        self.assertLess(out["seconds"], 40)
        b = out["build"]
        self.assertEqual(b["status"], "failed")
        self.assertEqual(b["triage"], "retry")  # the engine's to try again, never the owner's
        self.assertIn("time limit", b["failure"])
        claude, child = (int(x) for x in Path(str(self.co.log) + ".pids").read_text().split())
        time.sleep(0.5)
        self.assertFalse(alive(claude))
        self.assertFalse(alive(child))  # what it started is stopped too

    def test_recovery_stops_a_build_still_running_past_its_time(self):
        p = self.tree()
        [child] = self.children(p.pid)
        token = self.co.py(f"import common, json; print(json.dumps(common.proc_token({p.pid})))")
        self.co.builds({"bstuck": {"id": "bstuck", "workflow": "count_new", "task": "Count new things  @workflow:count_new  every:daily",
                                   "title": "Count new things", "status": "building", "opened": ago(120), "pid": p.pid, "proc": token}})
        out = self.co.py(RECOVER)
        p.wait(timeout=10)
        time.sleep(0.5)
        self.assertFalse(alive(child))
        self.assertEqual(out["builds"]["bstuck"]["status"], "retried")
        self.assertEqual(len(out["builds"]), 2)  # started again, by the engine itself

    def test_another_process_with_its_pid_isnt_the_build(self):
        p = self.tree()  # alive, but not the build: it started after the build's process did
        self.co.builds({"bgone": {"id": "bgone", "workflow": "count_new", "task": "Count new things  @workflow:count_new  every:daily",
                                  "title": "Count new things", "status": "building", "opened": ago(5), "pid": p.pid,
                                  "proc": "another-boot:12345"}})
        out = self.co.py(RECOVER)
        self.assertEqual(out["builds"]["bgone"]["status"], "retried")  # known dead at once, not after an hour
        self.assertIsNone(p.poll())  # and the unrelated process is left alone


if __name__ == "__main__":
    unittest.main()
