"""Website logins: the engine's side (scripts/integrations.py).

A fake gateway hands out a saved session and a fake site checks it, so this drives a real
headless Chromium through site_browser(). Needs Python Playwright and a Chromium: set
CHROMIUM_PATH if Playwright's own isn't installed. Skipped without them.

    python3 -m unittest tests.test_sites
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

try:
    import playwright  # noqa: F401
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False


class Site(http.server.BaseHTTPRequestHandler):
    """A site with a members area: logged in only with the right session cookie."""
    posts: list = []

    def do_GET(self):
        logged_in = "sid=good" in (self.headers.get("Cookie") or "")
        body = ('<p id="account">Welcome back</p><form method="post" action="/order"><button>Order</button></form>'
                if logged_in else '<form><input name="password"></form>')
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(f"<html><body>{body}</body></html>".encode())

    def do_POST(self):
        Site.posts.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class Gateway(http.server.BaseHTTPRequestHandler):
    calls: list = []
    cookie = "good"
    site_port = 0

    def _reply(self):
        Gateway.calls.append({"method": self.command, "path": self.path, "context": self.headers.get("X-Steerable-Context"),
                              "dry": self.headers.get("X-Steerable-Dry-Run")})
        if self.path == "/x":
            body, status = {"available": [], "connected": [
                {"provider": "site:portal.test", "site": "portal.test", "name": "Supplier portal", "account": "Supplier portal", "status": "ACTIVE"},
                {"provider": "stripe", "name": "Stripe", "account": "rk", "status": "ACTIVE", "mcp": True}]}, 200
        elif self.path == "/x/site/portal.test/session":
            if not (self.headers.get("X-Steerable-Context") == "routine" or self.headers.get("X-Steerable-Dry-Run") == "1"):
                body, status = {"error": "Website logins are only used by routines the owner approved."}, 403
            else:
                state = {"cookies": [{"name": "sid", "value": Gateway.cookie, "domain": "127.0.0.1", "path": "/", "expires": -1,
                                      "httpOnly": True, "secure": False, "sameSite": "Lax"}], "origins": []}
                body, status = {"site": "portal.test", "name": "Supplier portal", "storageState": state,
                                "startUrl": f"http://127.0.0.1:{Gateway.site_port}/account"}, 200
        else:
            body, status = {"ok": True}, 200
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _reply

    def log_message(self, *args):
        pass


def serve(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class SitesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site, cls.gateway = serve(Site), serve(Gateway)
        Gateway.site_port = cls.site.server_address[1]
        cls.root = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "template/scripts", cls.root / "scripts")
        cls.env = {**{k: v for k, v in os.environ.items() if k not in ("STEERABLE_CONTEXT", "STEERABLE_DRY_RUN")},
                   "STEERABLE_GATEWAY_URL": f"http://127.0.0.1:{cls.gateway.server_address[1]}",
                   "ANTHROPIC_API_KEY": "sk-steerable-test-token"}

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown()
        cls.gateway.shutdown()
        shutil.rmtree(cls.root, ignore_errors=True)

    def run_script(self, script: str, **env) -> subprocess.CompletedProcess:
        Gateway.calls.clear()
        Site.posts.clear()
        return subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts')\n" + script],
                              cwd=self.root, capture_output=True, text=True, env={**self.env, **env}, timeout=120)

    def test_helpers(self):
        out = self.run_script("""
import json
from integrations import IntegrationError, browser_session, site_expired, sites
print(json.dumps([s["site"] for s in sites()]))
try:
    browser_session("portal.test")
except IntegrationError as e:
    print(json.dumps({"status": e.status}))
""")
        self.assertEqual(out.returncode, 0, out.stderr)
        listed, refused = [json.loads(line) for line in out.stdout.splitlines()]
        self.assertEqual(listed, ["portal.test"])
        self.assertEqual(refused, {"status": 403})  # the chat never gets a session

        out = self.run_script('from integrations import browser_session, site_expired\n'
                              'print(browser_session("Portal.TEST")["name"]); site_expired("portal.test")', STEERABLE_CONTEXT="routine")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "Supplier portal")
        self.assertEqual([(c["method"], c["path"], c["context"]) for c in Gateway.calls],
                         [("GET", "/x/site/portal.test/session", "routine"), ("POST", "/x/site/portal.test/expired", "routine")])

    @unittest.skipUnless(HAVE_PLAYWRIGHT, "needs Python Playwright")
    def test_site_browser(self):
        drive = """
from integrations import IntegrationError, site_browser
try:
    with site_browser("portal.test", logged_in="#account") as page:
        print(page.locator("#account").inner_text())
        page.get_by_role("button", name="Order").click()
        page.wait_for_timeout(300)
except IntegrationError as e:
    print("expired", e.connect)
"""
        Gateway.cookie = "good"
        out = self.run_script(drive, STEERABLE_CONTEXT="routine")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "Welcome back")
        self.assertEqual(Site.posts, ["/order"])

        # A dry run can look but not submit.
        out = self.run_script(drive, STEERABLE_DRY_RUN="1")
        self.assertEqual(out.stdout.strip(), "Welcome back", out.stderr)
        self.assertEqual(Site.posts, [])

        # Logged out: the owner is asked to log in again.
        Gateway.cookie = "stale"
        out = self.run_script(drive, STEERABLE_CONTEXT="routine")
        self.assertEqual(out.stdout.strip(), "expired site:portal.test", out.stderr)
        self.assertIn(("POST", "/x/site/portal.test/expired"), [(c["method"], c["path"]) for c in Gateway.calls])


if __name__ == "__main__":
    unittest.main()
