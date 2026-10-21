"""How many items pass between a routine's steps, n8n-style (common.step(n, items=...), common.each): shown
on the flow chart's arrows while it runs, with how far a loop has got, and kept from the last run after.

    python3 -m unittest tests.test_flow_counts -v
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402

ROUTINE = '''"""Sort new posts."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from common import STEPS, each, step

step(1)
posts = list(range(150))
step(2, items=posts)
for p in each(posts):
    if p == 36 and os.environ.get("PEEK"):  # what the routine page reads mid-loop
        Path(os.environ["PEEK"]).write_text((STEPS / "sort_posts.json").read_text())
fits = [p for p in posts if p % 10 == 0]
step(3, items=fits)
print(f"Kept {len(fits)} posts")
'''

FLOW = json.dumps({"steps": [{"kind": "trigger", "label": "Every morning"}, {"kind": "read", "label": "Read posts"},
                             {"kind": "think", "label": "Judge each"}, {"kind": "save", "label": "Keep the good ones"}]})

RUN = r"""
import json
import agent_api, heartbeat
line = next(l for l in open("tasks.md").read().splitlines() if "@workflow:sort_posts" in l)
ok = heartbeat.run_routine(line, line[6:], "sort_posts", "2026-10-21", manual=True)
detail = agent_api.routine_detail("sort_posts")
print(json.dumps({"ok": ok, "lastFlow": detail.get("lastFlow"), "runningNow": detail.get("runningNow")}))
"""


class FlowCountsTest(unittest.TestCase):
    def setUp(self):
        self.co = Company()
        (self.co.root / "workflows/sort_posts.py").write_text(ROUTINE)
        (self.co.root / "workflows/sort_posts.flow.json").write_text(FLOW)
        (self.co.root / "tasks.md").write_text("# Tasks\n\n## Open\n- [ ] Sort posts  @workflow:sort_posts  every:daily  approved\n")
        self.co.py("import json, ops_db; ops_db.connect(); print(json.dumps(1))")

    def tearDown(self):
        self.co.close()

    def test_counts_on_the_arrows_and_loop_progress(self):
        peek = self.co.tmp / "peek.json"
        out = self.co.py(RUN, timeout=120, PEEK=str(peek))
        self.assertTrue(out["ok"])
        self.assertIsNone(out["runningNow"])  # finished
        self.assertEqual(out["lastFlow"]["counts"], {"2": 150, "3": 15})
        mid = json.loads(peek.read_text())  # what the page saw while it worked through the posts
        self.assertEqual(mid["step"], 2)
        self.assertEqual(mid["counts"], {"2": 150})
        self.assertEqual(mid["progress"]["total"], 150)
        self.assertLessEqual(mid["progress"]["done"], 36)

    def test_running_now_carries_this_runs_counts(self):
        code = r"""
import json
from datetime import datetime, timedelta, timezone
import agent_api, common, heartbeat
since = datetime.now(timezone.utc) - timedelta(minutes=2)
heartbeat.NOW.write_text(json.dumps({"routine": "sort_posts", "since": since.isoformat(timespec="seconds")}))
(common.STEPS).mkdir(exist_ok=True)
(common.STEPS / "sort_posts.json").write_text(json.dumps({"step": 2, "at": (since + timedelta(seconds=5)).isoformat(timespec="seconds"),
    "counts": {"2": 150}, "progress": {"step": 2, "done": 37, "total": 150}}))
print(json.dumps(agent_api.routine_detail("sort_posts").get("runningNow")))
"""
        now = self.co.py(code)
        self.assertEqual(now["step"], 2)
        self.assertEqual(now["counts"], {"2": 150})
        self.assertEqual(now["progress"], {"step": 2, "done": 37, "total": 150})


if __name__ == "__main__":
    unittest.main()
