"""A chat turn cut off by a restart (an engine update, a crash) isn't left hanging: when the engine
starts, it clears the leftover "working" state and carries on answering the owner's last message in
the same conversation (bridge.resume_interrupted). Nothing to answer, or too long ago: it only clears.

    python3 -m unittest tests.test_chat_resume -v
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if "-p" not in args:  # `claude auth status` and the like: not a turn
    sys.exit(0)
prompt = args[args.index("-p") + 1] if args.index("-p") + 1 < len(args) else sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"prompt": prompt, "resume": args[args.index("--resume") + 1] if "--resume" in args else None}) + "\n")
print(json.dumps({"type": "result", "result": "Yes, those three goals are reasonable. I've set them up.",
                  "total_cost_usd": 0.01, "session_id": "s-chat"}))
"""

RESUME = r"""
import json
import bridge
print(json.dumps({"resumed": bridge.resume_interrupted(), "live": bridge.LIVE.exists(),
                  "log": [json.loads(l) for l in bridge.CHAT_LOG.read_text().splitlines()]}))
"""


def ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


class ChatResumeTest(unittest.TestCase):
    def setUp(self):
        self.co = Company(fake_claude=FAKE_CLAUDE)
        self.log = self.co.root / "logs/chat.jsonl"
        self.live = self.co.root / ".cache/chat_live.jsonl"

    def tearDown(self):
        self.co.close()

    def chat(self, *entries) -> None:
        self.log.write_text("".join(json.dumps(e) + "\n" for e in entries))

    def test_cut_off_turn_is_answered(self):
        self.chat({"ts": ago(9), "from": "coo", "text": "I suggest three goals."},
                  {"ts": ago(3), "from": "you", "text": "if you think thats reasonable"})
        self.live.write_text('{"type": "assistant"}\n')
        out = self.co.py(RESUME, timeout=120)
        self.assertTrue(out["resumed"])
        self.assertFalse(out["live"])
        [call] = self.co.calls()
        self.assertIn("if you think thats reasonable", call["prompt"])
        self.assertIn("cut off", call["prompt"])
        self.assertEqual([e["from"] for e in out["log"]], ["coo", "you", "coo"])  # not logged twice
        self.assertEqual(out["log"][-1]["text"], "Yes, those three goals are reasonable. I've set them up.")

    def test_nothing_waiting_only_clears(self):
        self.chat({"ts": ago(3), "from": "you", "text": "hi"}, {"ts": ago(2), "from": "coo", "text": "Hello."})
        self.live.write_text('{"type": "assistant"}\n')
        out = self.co.py(RESUME)
        self.assertFalse(out["resumed"])
        self.assertFalse(out["live"])
        self.assertEqual(self.co.calls(), [])

    def test_long_ago_only_clears(self):
        self.chat({"ts": ago(60 * 5), "from": "you", "text": "old question"})
        self.live.write_text('{"type": "assistant"}\n')
        out = self.co.py(RESUME)
        self.assertFalse(out["resumed"])
        self.assertFalse(out["live"])
        self.assertEqual(self.co.calls(), [])

    def test_no_leftover_does_nothing(self):
        self.chat({"ts": ago(3), "from": "you", "text": "a question being answered elsewhere"})
        out = self.co.py(RESUME)
        self.assertFalse(out["resumed"])
        self.assertEqual(self.co.calls(), [])


if __name__ == "__main__":
    unittest.main()
