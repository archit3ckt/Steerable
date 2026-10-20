"""The catalog's routines against a fake gateway that answers like the services do: a practice run
sends nothing and says what it would do, a live run does it once, and a second run doesn't repeat it.

    python3 -m unittest tests.test_catalog_routines -v
"""
import json
import shutil
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import TEMPLATE, Company  # noqa: E402

DAY = 86400


class FakeGateway:
    """Answers /x/<provider>/<host>/<path> from `routes`: {(method, path): answer or function(query, body)}.
    Keeps every request in `seen`."""

    def __init__(self, routes: dict):
        self.routes, self.seen = routes, []
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def answer(self, method):
                parts = urlsplit(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else b""
                dry = self.headers.get("X-Steerable-Dry-Run") == "1"
                gateway.seen.append({"method": method, "path": parts.path, "query": parse_qs(parts.query), "dry": dry})
                route = gateway.routes.get((method, parts.path))
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                status, value = 200, route(parse_qs(parts.query), body) if callable(route) else route
                if isinstance(value, tuple):
                    status, value = value
                if dry and method != "GET":
                    status, value = 200, {"dry_run": True}
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self.answer("GET")

            def do_POST(self):
                self.answer("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def posts(self) -> list[dict]:
        return [s for s in self.seen if s["method"] == "POST"]

    def close(self):
        self.server.shutdown()


class CatalogRoutineTest(unittest.TestCase):
    entry = ""
    task = ""

    def setUp(self):
        self.co = Company()
        for f in ("routine.py", "routine.flow.json"):
            shutil.copyfile(TEMPLATE / "scripts/catalog" / self.entry / f,
                            self.co.root / "workflows" / f.replace("routine", self.entry))

    def tearDown(self):
        self.co.close()
        if getattr(self, "gw", None):
            self.gw.close()

    def run_it(self, dry: bool) -> list[str]:
        env = self.co.env(STEERABLE_GATEWAY_URL=self.gw.url, ANTHROPIC_API_KEY="tok", STEERABLE_WORKFLOW=self.entry,
                          **({"STEERABLE_DRY_RUN": "1"} if dry else {"STEERABLE_CONTEXT": "routine"}))
        proc = subprocess.run([sys.executable, f"workflows/{self.entry}.py", self.task], cwd=self.co.root,
                              capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        return [line for line in proc.stdout.splitlines() if line.strip()]

    def told(self) -> list[str]:
        chat = self.co.root / "logs/chat.jsonl"
        return [json.loads(line)["text"] for line in chat.read_text().splitlines()] if chat.exists() else []

    def rows(self, table: str) -> list[dict]:
        code = f"import json, library; print(json.dumps([r['cells'] for r in library.table({table!r}).rows()]))"
        return self.co.py(code)


def invoice(iid, client, email, cents, due_days_ago, status="open"):
    return {"id": iid, "number": iid.upper(), "customer_name": client, "customer_email": email, "amount_due": cents,
            "amount_remaining": cents, "currency": "gbp", "due_date": int(time.time()) - due_days_ago * DAY, "status": status}


class OverdueInvoicesTest(CatalogRoutineTest):
    entry = "overdue_invoices"
    task = "Remind clients about overdue invoices  @workflow:overdue_invoices  every:weekly"

    def gateway(self, send_status: int = 200) -> None:
        invoices = [invoice("in_1", "Acme Ltd", "ap@acme.test", 120000, 10),
                    invoice("in_2", "Beta Co", "pay@beta.test", 45050, 5),
                    invoice("in_3", "Gamma", "g@gamma.test", 9900, 1)]  # only a day late: not yet

        def listing(query, body):
            cutoff = int(query["due_date[lt]"][0])
            return {"data": [i for i in invoices if i["due_date"] < cutoff], "has_more": False}

        base = "/x/stripe/api.stripe.com/v1/invoices"
        routes = {("GET", base): listing}
        for i in invoices:
            routes[("POST", f"{base}/{i['id']}/send")] = (send_status, {"error": "This key can't do that."}) \
                if send_status != 200 else {**i, "status": "open"}
            routes[("GET", f"{base}/{i['id']}")] = i
        self.gw = FakeGateway(routes)

    def test_practice_run_sends_nothing(self):
        self.gateway()
        lines = self.run_it(dry=True)
        self.assertEqual(lines[-1], "Would remind 2 clients about overdue invoices")
        self.assertEqual(self.gw.posts(), [])

    def test_reminds_once_then_waits(self):
        self.gateway()
        lines = self.run_it(dry=False)
        self.assertEqual(lines[-1], "Reminded 2 clients about overdue invoices")
        self.assertEqual(sorted(p["path"].split("/")[-2] for p in self.gw.posts()), ["in_1", "in_2"])
        self.assertIn("Acme Ltd: invoice IN_1, 1,200.00 GBP, 10 days overdue", self.told()[0])
        rows = {r["Invoice"]: r for r in self.rows("Invoice reminders")}
        self.assertEqual(rows["IN_1"]["Reminders"], 1)
        self.assertEqual(rows["IN_1"]["Status"], "Reminded")
        self.gw.seen.clear()
        lines = self.run_it(dry=False)  # the same week: nothing again
        self.assertEqual(lines[-1], "Reminded 0 clients about overdue invoices")
        self.assertEqual(self.gw.posts(), [])
        self.assertEqual(len(self.rows("Invoice reminders")), 2)

    def test_read_only_key_tells_the_owner_what_to_change(self):
        self.gateway(send_status=403)
        lines = self.run_it(dry=False)
        self.assertEqual(lines[-1], "Found 2 overdue invoices, but Stripe didn't let me send reminders")
        self.assertIn("Invoices: Write", self.told()[0])
        self.assertEqual({r["Status"] for r in self.rows("Invoice reminders")}, {"Not sent"})


if __name__ == "__main__":
    unittest.main()
