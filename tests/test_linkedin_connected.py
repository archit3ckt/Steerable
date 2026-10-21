"""LinkedIn connected with one click on the Connections page (Steerable Cloud): posts go through the gateway
with the owner's own sign-in, pictures too, and an owner who hasn't connected it is asked for that one click,
never for a token to paste. A fake gateway stands in for Steerable and LinkedIn.

    python3 -m unittest tests.test_linkedin_connected -v
"""
import json
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402
from test_catalog_routines import FakeGateway  # noqa: E402


def png() -> bytes:
    raw = b"\x00" + b"\x2d\x6a\x4f" * 4
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class LinkedInConnectedTest(unittest.TestCase):
    def setUp(self):
        self.co = Company()
        self.connected = True
        self.posted = []
        li = "/x/linkedin/api.linkedin.com"

        def listing(q, b):
            return {"connected": [{"provider": "linkedin", "name": "LinkedIn", "account": "Sam Rivera", "status": "ACTIVE"}] if self.connected else [],
                    "available": [{"id": "linkedin", "name": "LinkedIn"}]}

        def post(q, b):
            self.posted.append(json.loads(b))
            return (201, {})

        self.gw = FakeGateway({
            ("GET", "/x"): listing,
            ("GET", f"{li}/v2/userinfo"): {"sub": "abc123", "name": "Sam Rivera"},
            ("POST", f"{li}/rest/images"): {"value": {"uploadUrl": "https://www.linkedin.com/dms-uploads/xyz?ca=1", "image": "urn:li:image:9"}},
            ("PUT", "/x/linkedin/www.linkedin.com/dms-uploads/xyz"): {},
            ("POST", f"{li}/rest/posts"): post,
        })
        (self.co.root / "files").mkdir(exist_ok=True)
        (self.co.root / "files/photo.png").write_bytes(png())

    def tearDown(self):
        self.gw.close()
        self.co.close()

    def run_py(self, code: str):
        return self.co.py(code, STEERABLE_GATEWAY_URL=self.gw.url, ANTHROPIC_API_KEY="tok")

    def test_posts_through_the_connection_with_a_picture(self):
        out = self.run_py("""
import json, social
print(json.dumps({"configured": social.configured()["linkedin"],
                  "out": social.post_linkedin("Shipped a new case study", social._image("files/photo.png"), "https://example.com/case")}))
""")
        self.assertTrue(out["configured"])
        self.assertEqual(len(self.posted), 1)
        body = self.posted[0]
        self.assertEqual(body["author"], "urn:li:person:abc123")
        self.assertEqual(body["content"], {"media": {"id": "urn:li:image:9"}})
        self.assertIn("https://example.com/case", body["commentary"])
        puts = [s for s in self.gw.seen if s["method"] == "PUT"]
        self.assertEqual(len(puts), 1)  # the picture went up through the gateway, to LinkedIn's upload address
        posts = [s for s in self.gw.seen if s["path"].endswith("/rest/posts")]
        self.assertEqual(posts[0]["query"], {})

    def test_not_connected_asks_for_one_click_not_a_token(self):
        self.connected = False
        out = self.run_py("""
import json, social, vault
try:
    social.draft(["linkedin"], "Hello")
    err = None
except social.SocialError as e:
    err = str(e)
print(json.dumps({"error": err, "asked": list(vault.requests())}))
""")
        self.assertIn("Connections page", out["error"])
        self.assertNotIn("token", out["error"].lower())
        self.assertEqual(out["asked"], [])  # no "Add a LinkedIn access token" form for the owner


if __name__ == "__main__":
    unittest.main()
