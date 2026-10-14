"""Values only the owner has (scripts/vault.py): the COO asks, the owner adds it in the app, and
routines read it like any setting, without anyone touching a file.

    python3 -m unittest discover -s tests -p test_vault.py
"""
import json
import subprocess
import sys
import unittest

from test_site_login import Api


class VaultTest(Api, unittest.TestCase):
    def test_ask_add_and_read(self):
        out = subprocess.run([sys.executable, "scripts/vault.py", "ask", "REDDIT_INBOX_RSS", "--label", "your Reddit inbox link",
                              "--why", "So the reply tracker sees replies to your answers.", "--url", "https://old.reddit.com/prefs/feeds"],
                             cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        # The engine's own settings can't be asked for.
        bad = subprocess.run([sys.executable, "scripts/vault.py", "ask", "ANTHROPIC_API_KEY", "--label", "x", "--why", "y"],
                             cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)

        d = next(d for d in self.call("GET", "/v1/decisions")[1] if d["id"] == "value:REDDIT_INBOX_RSS")
        self.assertEqual(d["connect"], {"provider": "value:REDDIT_INBOX_RSS", "label": "Add your Reddit inbox link"})
        self.assertNotIn(".env", json.dumps(d))
        self.assertEqual(self.call("GET", "/v1/values/REDDIT_INBOX_RSS")[1],
                         {"name": "REDDIT_INBOX_RSS", "label": "your Reddit inbox link", "why": "So the reply tracker sees replies to your answers.",
                          "url": "https://old.reddit.com/prefs/feeds", "hint": None, "saved": False})

        self.assertEqual(self.call("POST", "/v1/values/REDDIT_INBOX_RSS", {"value": "  "})[0], 400)
        self.assertEqual(self.call("POST", "/v1/values/TELEGRAM_BOT_TOKEN", {"value": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/v1/values/REDDIT_INBOX_RSS", {"value": "https://www.reddit.com/message/inbox/.rss?feed=abc&user=me"}),
                         (200, {"name": "REDDIT_INBOX_RSS", "saved": True}))
        self.assertNotIn("value:REDDIT_INBOX_RSS", [d["id"] for d in self.call("GET", "/v1/decisions")[1]])
        self.assertTrue(self.call("GET", "/v1/values/REDDIT_INBOX_RSS")[1]["saved"])
        self.assertNotIn("feed=abc", json.dumps(self.call("GET", "/v1/values/REDDIT_INBOX_RSS")[1]))

        # A routine reads it like any setting.
        read = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); from common import env; print(env('REDDIT_INBOX_RSS'))"],
                              cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(read.stdout.strip(), "https://www.reddit.com/message/inbox/.rss?feed=abc&user=me")
        self.assertEqual(oct((self.root / ".cache/vault.json").stat().st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()


class FixRequestTest(Api, unittest.TestCase):
    def test_a_fix_request_becomes_a_change_proposal(self):
        """fix.py, from older instructions, now goes through the change flow: the owner's OK first."""
        out = subprocess.run([sys.executable, "scripts/fix.py", "reorder_reminders",
                              "Drafting is skipped when the AI is blocked; retry those next run instead."],
                             cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("It's in the owner's Decisions", out.stdout)
        d = next(x for x in self.call("GET", "/v1/decisions")[1] if x["id"].startswith("change:"))
        self.assertEqual(d["draft"]["body"], "Drafting is skipped when the AI is blocked; retry those next run instead.")
        self.assertNotEqual(subprocess.run([sys.executable, "scripts/fix.py", "nope", "x" * 30], cwd=self.root, env=self.env,
                                           capture_output=True, text=True).returncode, 0)
        incidents = json.loads((self.root / ".cache/incidents.json").read_text())
        self.assertFalse([i for i in incidents.values() if i.get("kind") == "request"])  # not the fixer's job any more
        # Nothing was paused.
        line = next(l for l in (self.root / "tasks.md").read_text().splitlines() if "@workflow:reorder_reminders" in l)
        self.assertNotIn("paused:", line)
