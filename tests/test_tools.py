"""Services the owner connects themselves (scripts/tools.py) and approvals for their tools
(scripts/approvals.py), end to end: a fake vendor with an MCP server and an OAuth server
(discovery, dynamic registration, PKCE, refresh), a self-hosted company (no gateway) and its
agent API over HTTP, and the approvals server spoken to over stdio as Claude Code would.

    python3 -m unittest tests.test_tools -v
"""
import base64
import hashlib
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
import urllib.parse
import urllib.request
from pathlib import Path

from test_agent_api import TOKEN, build_company

REDIRECT = "http://localhost:3100/connections/callback"
TOOLS = [
    {"name": "list_items", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
    {"name": "create_item", "inputSchema": {"type": "object"}},
    {"name": "delete_item", "inputSchema": {"type": "object"}, "annotations": {"destructiveHint": True}},
]


class Vendor(http.server.BaseHTTPRequestHandler):
    """A service with an MCP server that asks you to sign in, and its authorization server."""
    clients: dict = {}
    codes: dict = {}
    tokens: dict = {}  # access token -> still good
    grants: list = []
    calls: list = []
    expires_in = 1  # the first token expires at once, so using it means refreshing

    def _send(self, status, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        for k, v in {"Content-Type": "application/json", **(headers or {})}.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def base(self):
        return f"http://{self.headers['Host']}"

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/.well-known/oauth-protected-resource/mcp":
            return self._send(200, {"resource": f"{self.base()}/mcp", "authorization_servers": [f"{self.base()}/auth"]})
        if url.path == "/.well-known/oauth-authorization-server/auth":
            return self._send(200, {"issuer": f"{self.base()}/auth", "authorization_endpoint": f"{self.base()}/auth/authorize",
                                    "token_endpoint": f"{self.base()}/auth/token", "registration_endpoint": f"{self.base()}/auth/register"})
        if url.path == "/auth/authorize":  # the owner signs in and agrees; back to the dashboard
            assert q["client_id"] in Vendor.clients and q["redirect_uri"] in Vendor.clients[q["client_id"]]
            assert q["code_challenge_method"] == "S256" and q["resource"] == f"{self.base()}/mcp"
            code = f"code-{len(Vendor.codes)}"
            Vendor.codes[code] = q
            return self._send(302, headers={"Location": f"{q['redirect_uri']}?code={code}&state={q['state']}"})
        self._send(404, {})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        path = urllib.parse.urlsplit(self.path).path
        if path == "/auth/register":
            body = json.loads(raw)
            cid = f"client-{len(Vendor.clients)}"
            Vendor.clients[cid] = body["redirect_uris"]
            return self._send(201, {"client_id": cid})
        if path == "/auth/token":
            form = dict(urllib.parse.parse_qsl(raw))
            Vendor.grants.append(form["grant_type"])
            if form["grant_type"] == "authorization_code":
                asked = Vendor.codes.pop(form["code"])
                challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                if challenge != asked["code_challenge"] or form["redirect_uri"] != asked["redirect_uri"]:
                    return self._send(400, {"error": "invalid_grant"})
            elif form.get("refresh_token") != "refresh-1":
                return self._send(400, {"error": "invalid_grant"})
            access = f"access-{len(Vendor.grants)}"
            Vendor.tokens[access] = True
            expires, Vendor.expires_in = Vendor.expires_in, 3600
            return self._send(200, {"access_token": access, "refresh_token": "refresh-1", "expires_in": expires})
        if path in ("/mcp", "/open-mcp"):
            auth = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if path == "/mcp" and not Vendor.tokens.get(auth):
                return self._send(401, {"error": "unauthorized"}, {
                    "WWW-Authenticate": f'Bearer resource_metadata="{self.base()}/.well-known/oauth-protected-resource/mcp"'})
            m = json.loads(raw)
            if "id" not in m:
                return self._send(202)
            Vendor.calls.append({"path": path, "method": m["method"], "params": m.get("params"), "auth": auth})
            if m["method"] == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "acme", "version": "1"}}
            elif m["method"] == "tools/list":
                result = {"tools": TOOLS}
            else:
                result = {"content": [{"type": "text", "text": f"did {m['params']['name']}"}]}
            return self._send(200, {"jsonrpc": "2.0", "id": m["id"], "result": result}, {"Mcp-Session-Id": "acme-1"})
        self._send(404, {})

    def log_message(self, *args):
        pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class ToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vendor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Vendor)
        threading.Thread(target=cls.vendor.serve_forever, daemon=True).start()
        cls.vendor_url = f"http://127.0.0.1:{cls.vendor.server_address[1]}"
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "bloom"
        build_company(cls.root)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        (cls.tmp / "home").mkdir()
        # Self-hosted: no gateway.
        cls.env = {k: v for k, v in os.environ.items() if k not in ("STEERABLE_GATEWAY_URL", "ANTHROPIC_API_KEY")}
        cls.env.update({"AGENT_API_PORT": str(cls.port), "HOME": str(cls.tmp / "home"), "COO_NAME": "Juno",
                        "PATH": f"{cls.root / 'fakebin'}{os.pathsep}{os.environ['PATH']}"})
        cls.proc = subprocess.Popen([sys.executable, "scripts/agent_api.py"], cwd=cls.root, env=cls.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError(cls.proc.stdout.read().decode())

    @classmethod
    def tearDownClass(cls):
        cls.vendor.shutdown()
        cls.proc.terminate()
        cls.proc.wait(5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def script(self, code: str, **env) -> list:
        out = subprocess.run([sys.executable, "-c", "import json, sys\nsys.path.insert(0, 'scripts')\n" + code],
                             cwd=self.root, capture_output=True, text=True, env={**self.env, **env})
        self.assertEqual(out.returncode, 0, out.stderr)
        return [json.loads(line) for line in out.stdout.splitlines()]

    def ask(self, *calls: tuple[str, dict]) -> list[dict]:
        """Talk to approvals.py over stdio, as Claude Code does with --permission-prompt-tool."""
        lines = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        lines += [{"jsonrpc": "2.0", "id": n + 1, "method": "tools/call",
                   "params": {"name": "ask", "arguments": {"tool_name": t, "input": i, "tool_use_id": f"u{n}"}}}
                  for n, (t, i) in enumerate(calls)]
        out = subprocess.run([sys.executable, "scripts/approvals.py"], cwd=self.root, env=self.env, text=True,
                             input="".join(json.dumps(m) + "\n" for m in lines), capture_output=True, timeout=30)
        replies = [json.loads(line) for line in out.stdout.splitlines()]
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "steerable-approvals")
        return [json.loads(r["result"]["content"][0]["text"]) for r in replies[1:]]

    def wait_for(self, check, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if value := check():
                return value
            time.sleep(0.2)
        self.fail("timed out waiting")

    # Tests run in name order.

    def test_00_catalog(self):
        status, body = self.call("GET", "/v1/tools")
        self.assertEqual(status, 200)
        ids = [c["id"] for c in body["catalog"]]
        self.assertIn("notion", ids)
        self.assertIn("firecrawl", ids)
        self.assertNotIn("slack", ids)  # needs a registered app: not for self-hosters
        self.assertEqual(body["connected"], [])
        self.assertFalse(body["claudeAccount"])  # the fake claude has no account
        self.assertFalse(body["throughSteerable"])
        stripe = next(c for c in body["catalog"] if c["id"] == "stripe")
        self.assertEqual(stripe["auth"]["type"], "apikey")
        self.assertEqual(self.call("POST", "/v1/tools/connect", {"id": "stripe"}),
                         (400, {"error": "Paste your Restricted key first."}))
        self.assertEqual(self.call("POST", "/v1/tools/connect", {"id": "stripe", "key": "nope"})[0], 400)
        self.assertEqual(self.call("POST", "/v1/tools/connect", {"url": "ftp://x"}), (400, {"error": "Use the server's https:// address."}))

    def test_01_sign_in(self):
        status, body = self.call("POST", "/v1/tools/connect",
                                 {"url": f"{self.vendor_url}/mcp", "name": "Acme CRM", "redirectUri": REDIRECT})
        self.assertEqual(status, 200, body)
        # The owner's browser goes there, signs in, and comes back to the dashboard with a code.
        try:
            urllib.request.build_opener(NoRedirect).open(body["authorizeUrl"])
            self.fail("expected a redirect")
        except urllib.error.HTTPError as e:
            back = urllib.parse.urlsplit(e.headers["Location"])
        self.assertEqual(f"{back.scheme}://{back.netloc}{back.path}", REDIRECT)
        q = dict(urllib.parse.parse_qsl(back.query))
        status, body = self.call("POST", "/v1/tools/callback", {"state": q["state"], "code": q["code"]})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["connected"]["id"], "acme_crm")
        self.assertEqual(body["connected"]["readOnly"], ["list_items"])
        self.assertEqual(body["connected"]["destructive"], ["delete_item"])
        # A code works once.
        self.assertEqual(self.call("POST", "/v1/tools/callback", {"state": q["state"], "code": q["code"]})[0], 400)
        # Nothing secret leaves the engine.
        overview = json.dumps(self.call("GET", "/v1/tools")[1])
        self.assertNotIn("access-", overview)
        self.assertNotIn("refresh-1", overview)
        self.assertEqual(oct((self.root / ".cache/tools/connected.json").stat().st_mode & 0o777), "0o600")

    def test_02_chat_config(self):
        # The first token expired at once, so building the config refreshes it.
        (args, rules), = self.script("from integrations import claude_mcp_args\nprint(json.dumps(claude_mcp_args()))")
        self.assertIn("refresh_token", Vendor.grants)
        config = json.loads((self.root / ".cache/mcp-live.json").read_text())["mcpServers"]
        self.assertEqual(config["acme_crm"]["url"], f"{self.vendor_url}/mcp")
        self.assertTrue(config["acme_crm"]["headers"]["Authorization"].startswith("Bearer access-"))
        self.assertTrue(Vendor.tokens[config["acme_crm"]["headers"]["Authorization"][7:]])
        self.assertEqual(config["approvals"]["type"], "stdio")
        self.assertNotIn("steerable", config)  # playbooks come with Steerable Cloud
        self.assertEqual(args[args.index("--permission-prompt-tool") + 1], "mcp__approvals__ask")
        self.assertEqual(rules, ["mcp__acme_crm__list_items"])  # only reads are allowed outright
        # The builder (a dry run) gets the same reads and no approvals.
        (dry_args, dry_rules), = self.script("from integrations import claude_mcp_args\nprint(json.dumps(claude_mcp_args(dry_run=True)))")
        self.assertNotIn("--permission-prompt-tool", dry_args)
        self.assertEqual(dry_rules, ["mcp__acme_crm__list_items"])
        # And the chat passes them on, in default mode so only approvals decides.
        self.call("POST", "/v1/chat", {"text": "What's in the CRM?"})
        argv = json.loads((self.root / ".cache/last_claude_argv.json").read_text())
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "default")
        self.assertIn("mcp__approvals__ask", argv)
        self.assertIn("mcp__acme_crm__list_items", argv)

    def test_03_approvals(self):
        create = ("mcp__acme_crm__create_item", {"name": "Dana", "note": "wholesale"})
        send = ("mcp__claude_ai_Gmail__send_message", {"to": "dana@example.com", "body": "Hi"})
        answers = self.ask(("mcp__acme_crm__list_items", {}), create, ("mcp__claude_ai_Gmail__search_threads", {"q": "x"}),
                           send, ("Bash", {"command": "rm -rf /"}), ("mcp__approvals__ask", {}), create)
        self.assertEqual([a["behavior"] for a in answers], ["allow", "deny", "allow", "deny", "deny", "deny", "deny"])
        self.assertEqual(answers[0]["updatedInput"], {})
        self.assertIn("Waiting for the owner's OK: create item in Acme CRM", answers[1]["message"])

        decisions = [d for d in self.call("GET", "/v1/decisions")[1] if d["id"].startswith("tool:")]
        self.assertEqual(len(decisions), 2)  # asking twice doesn't ask the owner twice
        d_create = next(d for d in decisions if "Acme CRM" in d["title"])
        d_send = next(d for d in decisions if "Gmail" in d["title"])
        self.assertEqual(d_create["title"], "Juno wants to create item in Acme CRM")
        self.assertEqual([o["id"] for o in d_create["options"]], ["once", "always", "decline"])
        self.assertIn({"label": "Name", "value": "Dana"}, d_create["facts"])
        self.assertEqual(json.loads(d_create["draft"]["body"]), create[1])

        # Allow once: the COO is asked to do it, and that exact call (only) goes through.
        self.assertEqual(self.call("POST", f"/v1/decisions/{d_create['id']}", {"optionId": "once"})[0], 200)
        self.wait_for(lambda: "The owner allowed it: create item in Acme CRM" in (self.root / "logs/chat.jsonl").read_text())
        changed = ("mcp__acme_crm__create_item", {"name": "Someone else"})
        self.assertEqual([a["behavior"] for a in self.ask(changed, create, create)], ["deny", "allow", "deny"])

        # Always: this tool runs from now on, until the owner stops it.
        self.call("POST", f"/v1/decisions/{d_send['id']}", {"optionId": "always"})
        self.assertEqual(self.ask(("mcp__claude_ai_Gmail__send_message", {"to": "x@example.com"}))[0]["behavior"], "allow")
        always = self.call("GET", "/v1/tools")[1]["alwaysAllowed"]
        self.assertEqual(always, [{"tool": send[0], "service": "Gmail", "what": "send message"}])
        self.call("POST", "/v1/tools/always", {"tool": send[0]})
        self.assertEqual(self.ask(("mcp__claude_ai_Gmail__send_message", {"to": "y@example.com"}))[0]["behavior"], "deny")

        # Deleting is never always-allowed; declining tells the chat.
        self.ask(("mcp__acme_crm__delete_item", {"id": 4}))
        pending = [d for d in self.call("GET", "/v1/decisions")[1] if d["id"].startswith("tool:")]
        d_delete = next(d for d in pending if "delete item" in d["title"])
        self.assertEqual([o["id"] for o in d_delete["options"]], ["once", "decline"])
        for d in pending:
            self.assertEqual(self.call("POST", f"/v1/decisions/{d['id']}", {"optionId": "decline"})[0], 200)
        self.assertIn("OK, I won't delete item in Acme CRM.", (self.root / "logs/chat.jsonl").read_text())
        self.assertEqual([d for d in self.call("GET", "/v1/decisions")[1] if d["id"].startswith("tool:")], [])

    def test_04_routines(self):
        Vendor.calls.clear()
        out = self.script("from integrations import mcp_call, connected\n"
                          "print(json.dumps(mcp_call('acme_crm', 'create_item', {'name': 'x'})))\n"
                          "print(json.dumps([c['provider'] for c in connected()]))")
        self.assertEqual(out, ["did create_item", ["acme_crm"]])
        dry = self.script("from integrations import mcp_call\n"
                          "print(json.dumps(mcp_call('acme_crm', 'create_item', {})))\n"
                          "print(json.dumps(mcp_call('acme_crm', 'list_items', {})))", STEERABLE_DRY_RUN="1")
        self.assertTrue(dry[0].startswith("Dry run:"))
        self.assertEqual(dry[1], "did list_items")
        self.assertEqual([c["params"]["name"] for c in Vendor.calls if c["method"] == "tools/call"], ["create_item", "list_items"])

    def test_05_server_without_sign_in_and_disconnect(self):
        status, body = self.call("POST", "/v1/tools/connect", {"url": f"{self.vendor_url}/open-mcp", "name": "Open data"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["connected"]["id"], "open_data")
        self.assertEqual(self.call("POST", "/v1/tools/open_data/disconnect")[0], 200)
        self.assertEqual(self.call("POST", "/v1/tools/open_data/disconnect"), (400, {"error": "That isn't connected."}))
        self.assertEqual([c["id"] for c in self.call("GET", "/v1/tools")[1]["connected"]], ["acme_crm"])


if __name__ == "__main__":
    unittest.main()
