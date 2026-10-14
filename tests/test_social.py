"""Posting to the owner's social accounts (scripts/social.py): from the chat a post waits in
Decisions and goes out when they tap Post; approved routines post (Reddit still asks); dry runs
post nothing. One fake server stands in for Meta, LinkedIn, Bluesky and Reddit.

    python3 -m unittest tests.test_social -v
"""
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"


class Fake(http.server.BaseHTTPRequestHandler):
    calls: list = []
    fail: set = set()

    def _reply(self, body, status=200, headers=None):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path = urllib.parse.urlparse(self.path).path
        kind = self.headers.get("Content-Type", "")
        body = (json.loads(raw) if "json" in kind and raw else
                dict(urllib.parse.parse_qsl(raw.decode())) if "urlencoded" in kind else
                {"bytes": len(raw), "type": kind})
        Fake.calls.append({"method": self.command, "path": path, "body": body,
                           "auth": self.headers.get("Authorization", ""), "agent": self.headers.get("User-Agent", "")})
        net = path.split("/")[1]
        if net in Fake.fail:
            return self._reply({"error": {"message": f"{net} is down for maintenance"}}, 500)
        if path == "/meta/PAGE1/photos":
            return self._reply({"id": "photo9", "post_id": "PAGE1_post9"})
        if path == "/meta/PAGE1/feed":
            return self._reply({"id": "PAGE1_post7"})
        if path == "/meta/photo9":
            return self._reply({"images": [{"source": "https://cdn.example/photo9.jpg"}]})
        if path == "/meta/IG1/media":
            return self._reply({"id": "box1"})
        if path == "/meta/box1":
            return self._reply({"status_code": "FINISHED"})
        if path == "/meta/IG1/media_publish":
            return self._reply({"id": "igpost1"})
        if path == "/meta/igpost1":
            return self._reply({"permalink": "https://www.instagram.com/p/abc/"})
        if path == "/li/v2/userinfo":
            return self._reply({"sub": "u42"})
        if path == "/li/rest/images":
            return self._reply({"value": {"uploadUrl": f"http://127.0.0.1:{self.server.server_address[1]}/li/upload", "image": "urn:li:image:9"}})
        if path == "/li/upload":
            return self._reply({})
        if path == "/li/rest/posts":
            return self._reply({}, 201, {"x-restli-id": "urn:li:share:77"})
        if path == "/bsky/xrpc/com.atproto.server.createSession":
            return self._reply({"accessJwt": "jwt1", "did": "did:plc:me"})
        if path == "/bsky/xrpc/com.atproto.repo.uploadBlob":
            return self._reply({"blob": {"$type": "blob", "ref": {"$link": "b1"}, "mimeType": "image/png", "size": 10}})
        if path == "/bsky/xrpc/com.atproto.repo.createRecord":
            return self._reply({"uri": "at://did:plc:me/app.bsky.feed.post/3k2", "cid": "c"})
        if path == "/rauth/api/v1/access_token":
            return self._reply({"access_token": "rt1"})
        if path == "/rapi/api/v1/smallbusiness/post_requirements":
            return self._reply({"is_flair_required": True})
        if path == "/rapi/r/smallbusiness/about/rules":
            return self._reply({"rules": [{"short_name": "No spam"}, {"short_name": "Say who you are"}]})
        if path == "/rapi/r/smallbusiness/api/link_flair_v2":
            return self._reply([{"id": "fl-1", "text": "Advice"}, {"id": "fl-2", "text": "Story"}])
        if path == "/rapi/api/submit":
            return self._reply({"json": {"errors": [], "data": {"name": "t3_x", "url": "https://www.reddit.com/r/smallbusiness/comments/x/"}}})
        return self._reply({"error": f"unknown {path}"}, 404)

    do_GET = do_POST = do_PUT = _handle

    def log_message(self, *args):
        pass


SCRIPT = r"""
import json, os, sys
sys.path.insert(0, "scripts")
import agent_api, social, vault
out = {}
def attempt(name, fn, *a, **kw):
    try:
        out[name] = fn(*a, **kw)
    except social.SocialError as e:
        out[name] = {"error": str(e)}

# No keys yet: the owner is asked for them.
attempt("no_keys", social.post, ["facebook", "instagram"], "Spring is here", image="files/2026-10/abcdef0123-photo.png")
out["asked"] = sorted(vault.requests())
os.environ.update(json.loads(os.environ["KEYS"]))

# From the chat: it waits in Decisions; Post publishes it.
attempt("checks_ig", social.post, ["instagram"], "No picture")
attempt("checks_bsky", social.post, ["bluesky"], "x" * 301)
attempt("checks_outside", social.post, ["facebook"], "hi", image="/etc/hostname")
attempt("waiting", social.post, ["facebook", "instagram"], "Spring is here", image="files/2026-10/abcdef0123-photo.png", why="New season")
d = next(x for x in agent_api.decisions() if x["id"] == "social:" + out["waiting"]["waiting"])
out["decision"] = {"title": d["title"], "draft": d["draft"]["body"], "facts": d["facts"], "context": d["context"]}
agent_api.decide(d["id"], "post")
out["after_post"] = [x["id"] for x in agent_api.decisions() if x["id"].startswith("social:")]
out["chat"] = agent_api.chat()[-1]["text"]

attempt("li_bsky", social.post, ["linkedin", "bluesky"], "We opened a second shop: https://example.com/shop", image="files/2026-10/abcdef0123-photo.png")
agent_api.decide("social:" + out["li_bsky"]["waiting"], "post")

# Reddit: rules first; a missing flair is caught before asking the owner.
attempt("reddit_noflair", social.post, ["reddit"], "How we cut our delivery costs", title="What worked for us", subreddit="r/smallbusiness")
attempt("reddit", social.post, ["reddit"], "How we cut our delivery costs", title="What worked for us", subreddit="smallbusiness", flair="fl-2")
rd = next(x for x in agent_api.decisions() if x["id"] == "social:" + out["reddit"]["waiting"])
out["reddit_context"] = rd["context"]
agent_api.decide(rd["id"], "post")

# A declined post goes nowhere.
attempt("declined", social.post, ["facebook"], "Not this one")
agent_api.decide("social:" + out["declined"]["waiting"], "skip")

# An approved routine posts on its own, except to Reddit; a dry run posts nothing.
os.environ["STEERABLE_CONTEXT"] = "routine"
attempt("routine_fb", social.post, ["facebook"], "Weekly special: soup")
attempt("routine_reddit", social.post, ["reddit"], "Weekly special", title="Soup", subreddit="smallbusiness", flair="fl-1")
os.environ["STEERABLE_DRY_RUN"] = "1"
attempt("dry", social.post, ["facebook"], "Just a test")
del os.environ["STEERABLE_DRY_RUN"]

# One network failing doesn't stop the others.
os.environ["FAIL"] = "1"
print(json.dumps(out))
"""

PART2 = r"""
import json, os, sys
sys.path.insert(0, "scripts")
import social
os.environ.update(json.loads(os.environ["KEYS"]))
os.environ["STEERABLE_CONTEXT"] = "routine"
res = social.post(["facebook", "linkedin"], "Partly")
print(json.dumps({"results": res["posted"], "summary": social.summary(res["posted"])}))
"""


class SocialTest(unittest.TestCase):
    def test_posting(self):
        fake = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{fake.server_address[1]}"
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\nCOO_NAME=Juno\n")
            subprocess.run([sys.executable, "scripts/ops_db.py"], cwd=root, check=True, capture_output=True)
            (root / "files/2026-10").mkdir(parents=True)
            (root / "files/2026-10/abcdef0123-photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
            keys = {"FACEBOOK_PAGE_ID": "PAGE1", "FACEBOOK_PAGE_TOKEN": "pagetok", "INSTAGRAM_ACCOUNT_ID": "IG1",
                    "LINKEDIN_TOKEN": "litok", "BLUESKY_HANDLE": "shop.bsky.social", "BLUESKY_APP_PASSWORD": "app-pw",
                    "REDDIT_CLIENT_ID": "cid", "REDDIT_CLIENT_SECRET": "csec", "REDDIT_USERNAME": "shopowner", "REDDIT_PASSWORD": "rpw"}
            env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp), "KEYS": json.dumps(keys),
                   "SOCIAL_META_BASE": f"{base}/meta", "SOCIAL_LINKEDIN_BASE": f"{base}/li", "SOCIAL_BLUESKY_BASE": f"{base}/bsky",
                   "SOCIAL_REDDIT_AUTH": f"{base}/rauth", "SOCIAL_REDDIT_API": f"{base}/rapi"}
            proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            calls = Fake.calls

            # Keys: asked for, in plain words, and never posted without them.
            self.assertIn("First I need", out["no_keys"]["error"])
            self.assertEqual(out["asked"], ["FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN", "INSTAGRAM_ACCOUNT_ID"])
            self.assertIn("need a picture", out["checks_ig"]["error"])
            self.assertIn("Too long for Bluesky", out["checks_bsky"]["error"])
            self.assertIn("company folder", out["checks_outside"]["error"])

            # The decision shows exactly what goes out; posting it reaches both networks, then it's gone.
            self.assertEqual(out["decision"]["title"], "Post this to Facebook and Instagram?")
            self.assertEqual(out["decision"]["draft"], "Spring is here")
            self.assertIn({"label": "Picture", "value": "photo.png"}, out["decision"]["facts"])
            self.assertEqual(out["decision"]["context"], "New season")
            self.assertEqual(out["after_post"], [])
            self.assertIn("https://www.facebook.com/PAGE1_post9", out["chat"])
            self.assertIn("https://www.instagram.com/p/abc/", out["chat"])
            ig = [c for c in calls if c["path"] == "/meta/IG1/media"][0]
            self.assertEqual(ig["body"]["image_url"], "https://cdn.example/photo9.jpg")  # via an unpublished Page photo
            self.assertEqual(ig["body"]["caption"], "Spring is here")

            post = [c for c in calls if c["path"] == "/li/rest/posts"][0]
            self.assertEqual(post["body"]["author"], "urn:li:person:u42")
            self.assertEqual(post["body"]["content"]["media"]["id"], "urn:li:image:9")
            self.assertEqual(post["auth"], "Bearer litok")
            rec = [c for c in calls if c["path"].endswith("createRecord")][0]["body"]["record"]
            facet = rec["facets"][0]
            text = rec["text"].encode()
            self.assertEqual(text[facet["index"]["byteStart"]:facet["index"]["byteEnd"]], b"https://example.com/shop")
            self.assertEqual(rec["embed"]["images"][0]["image"]["ref"]["$link"], "b1")

            self.assertIn("needs a flair", out["reddit_noflair"]["error"])
            self.assertIn("Story (--flair fl-2)", out["reddit_noflair"]["error"])
            self.assertIn("No spam; Say who you are", out["reddit_context"])
            submit = [c for c in calls if c["path"] == "/rapi/api/submit"]
            self.assertEqual(submit[0]["body"]["sr"], "smallbusiness")
            self.assertEqual((submit[0]["body"]["kind"], submit[0]["body"]["flair_id"]), ("self", "fl-2"))
            self.assertIn("u/shopowner", submit[0]["agent"])

            feeds = [c for c in calls if c["path"] == "/meta/PAGE1/feed"]
            self.assertEqual([c["body"]["message"] for c in feeds], ["Weekly special: soup"])  # declined and dry run: never sent
            self.assertTrue(all(r["ok"] for r in out["routine_fb"]["posted"]))
            self.assertIn("waiting", out["routine_reddit"])  # Reddit asks even from a routine
            self.assertEqual(len(submit), 1)
            self.assertIn("dry_run", out["dry"])

            Fake.fail = {"li"}
            proc = subprocess.run([sys.executable, "-c", PART2], cwd=root, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            part = json.loads(proc.stdout)
            self.assertEqual([(r["network"], r["ok"]) for r in part["results"]], [("facebook", True), ("linkedin", False)])
            self.assertIn("LinkedIn said no: li is down for maintenance", part["summary"])
            self.assertTrue(part["summary"].startswith("Some of it didn't go out."))
        finally:
            fake.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
