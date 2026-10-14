"""Long conversations: the chat is read in pages from the end of its log (agent_api.chat_page),
with ids that don't change as the history grows.

    python3 -m unittest tests.test_chat_pages -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"
COUNT = 5000

SCRIPT = """
import json, sys, time
sys.path.insert(0, "scripts")
import agent_api
out = {}
start = time.time()
latest = agent_api.chat_page(limit=50)
out["latest_ms"] = (time.time() - start) * 1000
out["latest"] = latest
out["before"] = agent_api.chat_page(before=latest["messages"][0]["id"], limit=50)
# Walk all the way back, a page at a time.
pages, first, seen = 1, latest["messages"][0]["id"], len(latest["messages"])
while True:
    page = agent_api.chat_page(before=first, limit=200)
    if not page["messages"]:
        break
    pages += 1; seen += len(page["messages"]); first = page["messages"][0]["id"]
    if not page["hasEarlier"]:
        break
out["walked"] = seen
out["oldest"] = first
target = agent_api.search_chat("needle-2500")[0]["id"]
start = time.time()
out["around"] = agent_api.chat_page(around=target, limit=40)
out["around_ms"] = (time.time() - start) * 1000
out["target"] = target
out["after_none"] = agent_api.chat_page(after=latest["messages"][-1]["id"])
# Two new messages arrive: ids already shown stay the same, and "after" returns just the new ones.
with open("logs/chat.jsonl", "a") as f:
    for i, who in enumerate(("you", "coo")):
        f.write(json.dumps({"ts": "2030-01-01T00:00:0%dZ" % i, "from": who, "text": "new " + who}) + "\\n")
out["after_new"] = agent_api.chat_page(after=latest["messages"][-1]["id"])
out["latest_again"] = agent_api.chat_page(limit=50)
out["unknown"] = agent_api.chat_page(before="000000000000")
out["list"] = len(agent_api.chat())
print(json.dumps(out))
"""


class ChatPagesTest(unittest.TestCase):
    def test_pages_of_a_long_history(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\n")
            (root / "logs").mkdir(exist_ok=True)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            with (root / "logs/chat.jsonl").open("w") as f:
                for i in range(COUNT):
                    text = f"message {i}" + (" needle-2500" if i == 2500 else "") + (" long " * 3000 if i % 97 == 0 else "")
                    f.write(json.dumps({"ts": (start + timedelta(minutes=i)).isoformat(), "from": "you" if i % 2 else "coo",
                                        "text": text}) + "\n")
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            text = lambda m: m["text"].split(" long ")[0].replace(" needle-2500", "")

            latest = out["latest"]["messages"]
            self.assertEqual([text(m) for m in latest], [f"message {i}" for i in range(COUNT - 50, COUNT)])
            self.assertTrue(out["latest"]["hasEarlier"])
            self.assertEqual([text(m) for m in out["before"]["messages"]], [f"message {i}" for i in range(COUNT - 100, COUNT - 50)])
            self.assertEqual(out["walked"], COUNT)  # every message reachable by scrolling up, none twice
            self.assertLess(out["latest_ms"], 200)

            around = out["around"]["messages"]
            at = [m["id"] for m in around].index(out["target"])
            self.assertEqual(text(around[at]), "message 2500")
            self.assertEqual((at, len(around)), (20, 41))  # 20 before, the message, 20 after
            self.assertTrue(out["around"]["hasEarlier"] and out["around"]["hasLater"])

            self.assertEqual(out["after_none"]["messages"], [])
            self.assertEqual([m["text"] for m in out["after_new"]["messages"]], ["new you", "new coo"])
            again = {m["id"] for m in out["latest_again"]["messages"]}
            self.assertTrue({m["id"] for m in latest[2:]} <= again)  # stable ids as the history grows
            self.assertTrue(out["unknown"]["reset"])
            self.assertEqual(out["list"], 200)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
