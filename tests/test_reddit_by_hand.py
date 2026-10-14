"""Reddit without app keys (Reddit stopped giving them out): no keys are asked for, the COO reads
the rules with reddit.py, drafts the post on its own, and the owner posts it themselves ("I posted
it"). Old requests for Reddit keys no longer show in Decisions. reddit.rules is stubbed here; the
browser reading itself is checked by hand against reddit.com (it needs the network).

    python3 -m unittest tests.test_reddit_by_hand -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"

SCRIPT = r"""
import json, sys
sys.path.insert(0, "scripts")
import reddit
reddit.rules = lambda sub: {"subreddit": "smallbusiness", "about": "",
                            "rules": [{"name": "No promotion", "detail": ""}, {"name": "Say who you are", "detail": ""}]}
import agent_api, social, vault
out = {}
def attempt(name, fn, *a, **kw):
    try:
        out[name] = fn(*a, **kw)
    except social.SocialError as e:
        out[name] = {"error": str(e)}

vault.ask("REDDIT_CLIENT_ID", label="your Reddit app's ID", why="old")  # asked before Reddit closed its API
out["setup"] = social.setup("reddit")
out["missing"] = social.missing(["reddit"])
attempt("mixed", social.post, ["reddit", "bluesky"], "Hi", title="T", subreddit="smallbusiness")
attempt("waiting", social.post, ["reddit"], "How we cut delivery costs", title="What worked for us", subreddit="r/smallbusiness",
        why="You asked where to share it")
ids = [d["id"] for d in agent_api.decisions()]
out["value_shown"] = any(i.startswith("value:") for i in ids)
d = next(x for x in agent_api.decisions() if x["id"] == "social:" + out["waiting"]["waiting"])
out["decision"] = {"title": d["title"], "options": [o["label"] for o in d["options"]], "draft": d["draft"], "context": d["context"]}
agent_api.decide(d["id"], "post")
out["chat"] = agent_api.chat()[-1]["text"]
out["timeline"] = [e["title"] for e in agent_api.timeline()][:3]
print(json.dumps(out))
"""


class RedditByHandTest(unittest.TestCase):
    def test_draft_and_owner_posts(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\nCOO_NAME=Juno\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp)},
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)

            self.assertEqual((out["setup"], out["missing"]), ([], []))  # nothing to ask the owner for
            self.assertFalse(out["value_shown"])  # the old "Add Reddit" key form is gone
            self.assertIn("on its own", out["mixed"]["error"])
            self.assertEqual(out["decision"]["title"], "Post this on r/smallbusiness?")
            self.assertEqual(out["decision"]["options"], ["I posted it", "Don't post"])
            self.assertEqual(out["decision"]["draft"]["body"], "What worked for us\n\nHow we cut delivery costs")
            self.assertIn("No promotion; Say who you are", out["decision"]["context"])
            self.assertIn("Reddit doesn't let apps post", out["decision"]["context"])
            self.assertIn("you posted it", out["chat"])
            self.assertTrue(any("You posted to r/smallbusiness" in t for t in out["timeline"]), out["timeline"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
