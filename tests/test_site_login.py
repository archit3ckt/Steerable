"""Website logins, self-hosted (scripts/sites.py): the owner logs in through a live browser the
engine runs, the dashboard shows its picture and forwards input through the agent API, and
routines then get a browser that's already logged in. And when a routine needs a login, its
problem becomes a "Log in to …" decision instead of instructions to edit files.

The live part drives a real headless Chromium: it needs Python Playwright (CHROMIUM_PATH if
Playwright's own browser isn't installed), and is skipped without it.

    python3 -m unittest tests.test_site_login
"""
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from test_agent_api import TOKEN, build_company

try:
    import playwright  # noqa: F401
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False


class Site(http.server.BaseHTTPRequestHandler):
    """A members area: a login form, and a session cookie once the right password is sent."""

    def do_GET(self):
        logged_in = "sid=good" in (self.headers.get("Cookie") or "")
        body = ('<p id="account">Welcome back</p>' if logged_in else
                '<form method="post" action="/login"><input name="password" autofocus style="width:600px;height:80px"></form>')
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(f"<html><body style='margin:0'>{body}</body></html>".encode())

    def do_POST(self):
        form = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        self.send_response(303)
        if form == "password=secret":
            self.send_header("Set-Cookie", "sid=good; Path=/")
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *args):
        pass


class Api:
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "bloom"
        build_company(self.root)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.env = {k: v for k, v in os.environ.items() if k not in ("STEERABLE_GATEWAY_URL", "ANTHROPIC_API_KEY")}
        self.env.update({"AGENT_API_PORT": str(self.port), "HOME": str(self.tmp),
                         "PATH": f"{self.root / 'fakebin'}{os.pathsep}{os.environ['PATH']}"})
        self.proc = subprocess.Popen([sys.executable, "scripts/agent_api.py"], cwd=self.root, env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(5)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, method, path, body=None, raw=False):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
                return r.status, data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


@unittest.skipUnless(HAVE_PLAYWRIGHT, "needs Python Playwright")
class LiveLoginTest(Api, unittest.TestCase):
    def test_log_in_through_the_dashboard_then_a_routine_is_logged_in(self):
        site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=site.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{site.server_address[1]}/"
        try:
            # Sites whose terms forbid it, and addresses that aren't https, are refused.
            self.assertEqual(self.call("POST", "/v1/sites/sessions", {"url": "https://www.facebook.com/"})[0], 400)
            self.assertEqual(self.call("POST", "/v1/sites/sessions", {"url": "http://example.com/"}),
                             (400, {"error": "Use the site's https:// address."}))

            status, body = self.call("POST", "/v1/sites/sessions", {"url": url})
            self.assertEqual(status, 200, body)
            sid = body["id"]
            status, image = self.call("GET", f"/v1/sites/sessions/{sid}/frame", raw=True)
            self.assertEqual((status, image[:2]), (200, b"\xff\xd8"))  # a JPEG of the page
            # Not logged in yet: nothing to save.
            status, body = self.call("POST", f"/v1/sites/sessions/{sid}/save", {"name": "Supplier portal"})
            self.assertEqual(status, 400)
            self.assertIn("doesn't look like you're logged in", body["error"])

            # The owner clicks the field, types the password and presses Enter, as on the picture.
            for step in ({"kind": "click", "x": 100, "y": 30}, {"kind": "type", "text": "secret"}, {"kind": "key", "key": "Enter"}):
                self.assertEqual(self.call("POST", f"/v1/sites/sessions/{sid}/input", step), (200, {"ok": True}))
            self.assertEqual(self.call("POST", f"/v1/sites/sessions/{sid}/input", {"kind": "key", "key": "F12"})[0], 400)
            time.sleep(1)
            self.assertTrue(self.call("GET", f"/v1/sites/sessions/{sid}")[1]["url"].startswith(url))
            self.assertEqual(self.call("POST", f"/v1/sites/sessions/{sid}/save", {"name": "Supplier portal"}),
                             (200, {"site": "127.0.0.1"}))
            self.assertEqual(self.call("GET", f"/v1/sites/sessions/{sid}/frame")[0], 404)  # closed on save

            saved = self.call("GET", "/v1/sites")[1]
            self.assertEqual([(s["site"], s["name"], s["status"]) for s in saved], [("127.0.0.1", "Supplier portal", "ACTIVE")])
            self.assertNotIn("sid", json.dumps(saved))  # the session never leaves the engine
            stored = self.root / ".cache/sites/127.0.0.1.json"
            self.assertEqual(oct(stored.stat().st_mode & 0o777), "0o600")
            profile = self.root / ".cache/sites/profiles/127.0.0.1"
            self.assertTrue(profile.is_dir())  # kept, so the site sees the same device next time

            # A routine gets a browser that's already logged in.
            script = ("import sys\nsys.path.insert(0, 'scripts')\nfrom integrations import site_browser, connected\n"
                      "with site_browser('127.0.0.1', logged_in='#account') as page:\n"
                      "    print(page.locator('#account').inner_text())\n"
                      "    print(page.evaluate('[navigator.userAgent.includes(\"Headless\"), navigator.webdriver, navigator.plugins.length > 0]'))\n"
                      "print([c['provider'] for c in connected()])")
            out = subprocess.run([sys.executable, "-c", script], cwd=self.root, env=self.env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            # Like an ordinary Chrome to the site, not an automated one.
            self.assertEqual(out.stdout.splitlines(), ["Welcome back", "[False, False, True]", "['site:127.0.0.1']"])

            self.assertEqual(self.call("POST", "/v1/sites/127.0.0.1/remove"), (200, {"ok": True}))
            self.assertEqual(self.call("GET", "/v1/sites")[1], [])
            self.assertFalse(profile.exists())

            # A live login that's cancelled without saving leaves no profile behind.
            sid = self.call("POST", "/v1/sites/sessions", {"url": url})[1]["id"]
            self.assertTrue(profile.is_dir())
            self.assertEqual(self.call("POST", f"/v1/sites/sessions/{sid}/cancel")[0], 200)
            self.assertFalse(profile.exists())
        finally:
            site.shutdown()


@unittest.skipUnless(HAVE_PLAYWRIGHT, "needs Python Playwright")
class BrowserLoginTest(Api, unittest.TestCase):
    def test_a_login_from_the_owners_own_browser_works_in_a_routine(self):
        """The extension hands over the cookies the owner's browser has; a routine is logged in with them."""
        site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=site.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{site.server_address[1]}/"
        try:
            code = self.call("POST", "/v1/extension/code")[1]["code"]
            token = self.call("POST", "/v1/extension/pair", {"code": code})[1]["token"]
            cookie = {"name": "sid", "value": "good", "domain": "127.0.0.1", "path": "/", "hostOnly": True, "session": True,
                      "httpOnly": False, "secure": False, "sameSite": "unspecified"}
            self.assertEqual(self.call("POST", "/v1/extension/logins", {"token": token, "startUrl": url, "name": "Supplier portal", "cookies": [cookie]}),
                             (200, {"site": "127.0.0.1"}))
            script = ("import sys\nsys.path.insert(0, 'scripts')\nfrom integrations import site_browser\n"
                      "with site_browser('127.0.0.1', logged_in='#account') as page:\n"
                      "    print(page.locator('#account').inner_text())")
            out = subprocess.run([sys.executable, "-c", script], cwd=self.root, env=self.env, capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "Welcome back", out.stderr)
        finally:
            site.shutdown()


class Shop(http.server.BaseHTTPRequestHandler):
    """A site to sign up to: email, password, and the code it emails."""
    accounts: dict = {}

    def do_GET(self):
        if "sid=member" in (self.headers.get("Cookie") or ""):
            body = '<p id="account">Your shop account</p>'
        else:
            field = "display:block;width:600px;height:80px;margin:0;font-size:24px"
            body = (f'<form method="post" action="/signup"><input name="email" style="{field}">'
                    f'<input name="password" type="password" style="{field}"><input name="code" style="{field}">'
                    '<button>Sign up</button></form>')
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(f"<html><body style='margin:0'>{body}</body></html>".encode())

    def do_POST(self):
        from urllib.parse import parse_qs
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()).items()}
        Shop.accounts[form.get("email")] = form
        self.send_response(303)
        if form.get("code") == "482913" and len(form.get("password", "")) == 20:
            self.send_header("Set-Cookie", "sid=member; Path=/; Max-Age=86400")
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *args):
        pass


@unittest.skipUnless(HAVE_PLAYWRIGHT, "needs Python Playwright")
class SignupTest(Api, unittest.TestCase):
    def test_the_owner_signs_the_coo_up_and_a_routine_uses_its_account(self):
        from test_accounts import Imap, mail, start_imap
        shop = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Shop)
        threading.Thread(target=shop.serve_forever, daemon=True).start()
        imap = start_imap()
        Imap.inbox = []
        signup = f"http://127.0.0.1:{shop.server_address[1]}/signup"
        try:
            self.call("POST", "/v1/mailbox", {"address": "juno@bloom.test", "imapHost": "127.0.0.1",
                                              "imapPort": imap.server_address[1], "password": Imap.password, "security": "none"})
            out = subprocess.run([sys.executable, "scripts/accounts.py", "propose", "127.0.0.1", "--name", "The shop",
                                  "--why", "To reorder supplies.", "--signup", signup], cwd=self.root, env=self.env,
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            # Not until the owner says yes.
            self.assertEqual(self.call("POST", "/v1/sites/sessions", {"url": signup, "account": "127.0.0.1"})[0], 400)
            self.call("POST", "/v1/decisions/account:127.0.0.1", {"optionId": "create"})

            sid = self.call("POST", "/v1/sites/sessions", {"url": signup, "account": "127.0.0.1"})[1]["id"]
            def step(**body):
                return self.call("POST", f"/v1/sites/sessions/{sid}/input", body)
            self.assertEqual(step(kind="fill", field="phone")[0], 400)  # no phone set
            self.assertIn("No code has arrived", step(kind="fill", field="code")[1]["error"])
            self.assertEqual(step(kind="click", x=100, y=40), (200, {"ok": True}))
            step(kind="fill", field="email")
            step(kind="click", x=100, y=120)
            step(kind="fill", field="password")

            # The shop emails a code; the sign-up screen finds it.
            Imap.inbox = [mail("127 Shop <hello@shop.test>", "Your code", "Your verification code is 482913.")]
            for _ in range(30):  # the screen checks every few seconds
                info = self.call("GET", f"/v1/sites/sessions/{sid}")[1]
                if info.get("mail"):
                    break
                time.sleep(0.5)
            self.assertEqual(info["mail"]["code"], "482913")
            step(kind="click", x=100, y=200)
            step(kind="fill", field="code")
            step(kind="key", key="Enter")
            time.sleep(1)
            self.assertEqual(self.call("POST", f"/v1/sites/sessions/{sid}/save", {"name": "The shop"}), (200, {"site": "127.0.0.1"}))

            # The shop got the COO's address and its generated password, which the owner can see.
            password = self.call("POST", "/v1/accounts/127.0.0.1/password")[1]["password"]
            self.assertEqual(Shop.accounts["juno@bloom.test"]["password"], password)
            account = self.call("GET", "/v1/accounts/127.0.0.1")[1]
            self.assertEqual((account["status"], account["email"], account["name"]), ("ACTIVE", "juno@bloom.test", "The shop"))

            script = ("import sys\nsys.path.insert(0, 'scripts')\nfrom integrations import site_browser\n"
                      "with site_browser('127.0.0.1', logged_in='#account') as page:\n"
                      "    print(page.locator('#account').inner_text())")
            out = subprocess.run([sys.executable, "-c", script], cwd=self.root, env=self.env, capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "Your shop account", out.stderr)
            self.assertIsNotNone(self.call("GET", "/v1/accounts/127.0.0.1")[1]["lastUsed"])
        finally:
            shop.shutdown()
            imap.shutdown()
            imap.server_close()


class LoginDecisionTest(Api, unittest.TestCase):
    def test_a_routine_that_needs_a_login_asks_for_one(self):
        # The problem-fixer found the reply tracker needs the owner's Reddit account.
        incidents = json.loads((self.root / ".cache/incidents.json").read_text())
        inc = incidents["iabc12345"]
        inc["verdict"] = {**inc["verdict"], "fix_ready": False, "actions": [], "needs_connection": "site:old.reddit.com",
                          "summary": "The reply tracker needs your Reddit account to read replies to your answers.",
                          "recommendation": "Add REDDIT_INBOX_RSS to .env."}
        (self.root / ".cache/incidents.json").write_text(json.dumps(incidents))

        d = next(d for d in self.call("GET", "/v1/decisions")[1] if d["id"] == "incident:iabc12345")
        self.assertEqual(d["connect"], {"provider": "site:old.reddit.com", "label": "Log in to old.reddit.com"})
        self.assertEqual([o["id"] for o in d["options"]], ["retry", "keep-paused"])
        self.assertEqual(d["recommendation"], {"optionId": "retry", "why": "Log in to old.reddit.com (one tap, above), then try again."})
        self.assertNotIn(".env", json.dumps(d))

        # After logging in, "Done, try again" restarts the routine.
        self.assertEqual(self.call("POST", "/v1/decisions/incident:iabc12345", {"optionId": "retry"})[0], 200)
        tasks = (self.root / "tasks.md").read_text()
        line = next(line for line in tasks.splitlines() if "@workflow:answer_questions" in line)
        self.assertNotIn("paused:", line)
        self.assertNotIn("incident:iabc12345", [d["id"] for d in self.call("GET", "/v1/decisions")[1]])


if __name__ == "__main__":
    unittest.main()
