"""The browser extension's side of the engine (scripts/extension.py, sites.import_login): pairing
with a one-time code, and keeping a login from the owner's own browser.

    python3 -m unittest tests.test_extension
"""
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accounts import CompanyApi  # noqa: E402

SOON = time.time() + 86400


def chrome_cookie(name, value, domain, **more):
    """A cookie as chrome.cookies gives it."""
    return {"name": name, "value": value, "domain": domain, "path": "/", "secure": True, "httpOnly": True,
            "sameSite": "lax", "hostOnly": not domain.startswith("."), "session": False, "expirationDate": SOON, **more}


class ExtensionTest(CompanyApi, unittest.TestCase):
    def pair(self) -> str:
        code = self.call("POST", "/v1/extension/code")[1]["code"]
        return self.call("POST", "/v1/extension/pair", {"code": code, "browser": "Chrome on Maya's laptop"})[1]["token"]

    def test_pairing_with_a_one_time_code(self):
        self.assertEqual(self.call("GET", "/v1/extension")[1], {"paired": False, "pairedAt": None, "browser": None})
        self.assertEqual(self.call("POST", "/v1/extension/pair", {"code": "ABCD-EFGH"})[0], 400)  # no code was made

        status, made = self.call("POST", "/v1/extension/code")
        self.assertEqual(status, 200)
        self.assertRegex(made["code"], r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        status, body = self.call("POST", "/v1/extension/pair", {"code": "ZZZZ-ZZZZ"})
        self.assertEqual((status, body["error"]), (400, "That isn't the code on your dashboard. Check it and try again."))
        # Typed loosely is fine; the token comes back once and only its hash is kept.
        status, body = self.call("POST", "/v1/extension/pair", {"code": made["code"].lower().replace("-", " "), "browser": "Chrome"})
        self.assertEqual(status, 200)
        token = body["token"]
        self.assertGreater(len(token), 30)
        self.assertNotIn(token, (self.root / ".cache/extension.json").read_text())
        self.assertEqual(self.call("POST", "/v1/extension/pair", {"code": made["code"]})[0], 400)  # it worked once
        paired = self.call("GET", "/v1/extension")[1]
        self.assertEqual((paired["paired"], paired["browser"]), (True, "Chrome"))

        # A few wrong guesses and the code is gone.
        code = self.call("POST", "/v1/extension/code")[1]["code"]
        for _ in range(5):
            self.call("POST", "/v1/extension/pair", {"code": "ZZZZ-ZZZZ"})
        self.assertIn("expired", self.call("POST", "/v1/extension/pair", {"code": code})[1]["error"])

        self.assertEqual(self.call("POST", "/v1/extension/unpair")[1]["paired"], False)
        self.assertEqual(self.call("POST", "/v1/extension/status", {"token": token})[0], 401)

    def test_a_login_from_the_owners_browser(self):
        token = self.pair()
        login = {"token": token, "startUrl": "https://app.supplier.example/orders", "name": "Supplier portal", "cookies": [
            chrome_cookie("session", "abc123", "app.supplier.example"),
            chrome_cookie("sso", "xyz", ".supplier.example", sameSite="no_restriction"),
            chrome_cookie("tab", "1", "app.supplier.example", session=True, expirationDate=None),
            chrome_cookie("old", "gone", "app.supplier.example", expirationDate=time.time() - 60),
            chrome_cookie("other", "not-theirs", ".elsewhere.example"),
            chrome_cookie("sibling", "no", "shop.supplier.example"),
        ]}
        self.assertEqual(self.call("POST", "/v1/extension/logins", {**login, "token": "nope"})[0], 401)
        self.assertEqual(self.call("POST", "/v1/extension/logins", login), (200, {"site": "app.supplier.example"}))

        stored = json.loads((self.root / ".cache/sites/app.supplier.example.json").read_text())
        kept = {c["name"]: c for c in stored["storageState"]["cookies"]}
        self.assertEqual(sorted(kept), ["session", "sso", "tab"])  # not the expired one, nor other sites'
        self.assertEqual((kept["session"]["domain"], kept["sso"]["domain"], kept["sso"]["sameSite"], kept["tab"]["expires"]),
                         ("app.supplier.example", ".supplier.example", "None", -1))
        self.assertEqual((stored["source"], stored["startUrl"]), ("browser", "https://app.supplier.example/orders"))

        saved = self.call("GET", "/v1/sites")[1]
        self.assertEqual([(s["site"], s["name"], s["source"], s["status"]) for s in saved],
                         [("app.supplier.example", "Supplier portal", "browser", "ACTIVE")])
        self.assertNotIn("abc123", json.dumps(saved))
        self.assertEqual(self.call("POST", "/v1/extension/status", {"token": token})[1],
                         {"sites": [{"site": "app.supplier.example", "name": "Supplier portal", "status": "ACTIVE"}]})

        # Sites that forbid automated use, a site with no login, and plain http are refused.
        for url, why in (("https://www.linkedin.com/feed", "doesn't allow automated"), ("http://app.supplier.example/", "https://")):
            status, body = self.call("POST", "/v1/extension/logins", {**login, "startUrl": url})
            self.assertEqual(status, 400)
            self.assertIn(why, body["error"])
        status, body = self.call("POST", "/v1/extension/logins", {**login, "cookies": [chrome_cookie("x", "y", ".elsewhere.example")]})
        self.assertEqual((status, body["error"]), (400, "Your browser has no login for that site yet. Log in there first."))


if __name__ == "__main__":
    unittest.main()
