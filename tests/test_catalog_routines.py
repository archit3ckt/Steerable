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
        env = self.co.env(STEERABLE_GATEWAY_URL=self.gw.url, ANTHROPIC_API_KEY="tok", ANTHROPIC_BASE_URL=self.gw.url,
                          STEERABLE_WORKFLOW=self.entry,
                          **({"STEERABLE_DRY_RUN": "1"} if dry else {"STEERABLE_CONTEXT": "routine"}))
        proc = subprocess.run([sys.executable, f"workflows/{self.entry}.py", self.task], cwd=self.co.root,
                              capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        return [line for line in proc.stdout.splitlines() if line.strip()]

    def told(self) -> list[str]:
        chat = self.co.root / "logs/chat.jsonl"
        return [json.loads(line)["text"] for line in chat.read_text().splitlines()] if chat.exists() else []

    def rows(self, table: str) -> list[dict]:
        code = (f"import json, library\nthere = {table!r} in [t['name'] for t in library.tables()]\n"
                f"print(json.dumps([r['cells'] for r in library.table({table!r}).rows()] if there else []))")
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
        told = self.told()[0]
        self.assertIn("Stripe hasn't let me send reminders yet", told)
        self.assertNotIn("key", told.lower())  # the owner isn't technical: no keys, scopes or settings screens
        self.assertEqual({r["Status"] for r in self.rows("Invoice reminders")}, {"Not sent"})


class WeeklyNumbersTest(CatalogRoutineTest):
    entry = "weekly_numbers"
    task = "Send me last week's numbers  @workflow:weekly_numbers  every:weekly"

    def setUp(self):
        super().setUp()
        from datetime import datetime, timedelta, timezone
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        last = today - timedelta(days=today.weekday() + 7)
        in_last, in_prev = int((last + timedelta(days=1)).timestamp()), int((last - timedelta(days=6)).timestamp())
        self.week = last.date().isoformat()

        def charge(i, pounds, at, status="succeeded"):
            return {"id": f"ch_{i}", "amount": pounds * 100, "currency": "gbp", "status": status, "paid": status == "succeeded", "created": at}

        items = {"charges": [charge(1, 100, in_last), charge(2, 50, in_last), charge(3, 25, in_last),
                             charge(4, 999, in_last, "failed"), charge(5, 100, in_prev), charge(6, 50, in_prev)],
                 "refunds": [{"id": "re_1", "amount": 1000, "currency": "gbp", "status": "succeeded", "created": in_last}],
                 "customers": [{"id": "cus_1", "created": in_last}, {"id": "cus_2", "created": in_last},
                               {"id": "cus_3", "created": in_prev}]}

        def lister(kind):
            def answer(query, body):
                lo, hi = int(query["created[gte]"][0]), int(query["created[lt]"][0])
                return {"data": [x for x in items[kind] if lo <= x["created"] < hi], "has_more": False}
            return answer

        self.gw = FakeGateway({("GET", f"/x/stripe/api.stripe.com/v1/{k}"): lister(k) for k in items})

    def test_practice_run_reports_and_keeps_nothing(self):
        lines = self.run_it(dry=True)
        self.assertEqual(lines[-1], "Last week: 175.00 GBP from 3 payments (up 17% on the week before)")
        self.assertIn("Would tell the owner", "\n".join(lines))
        self.assertEqual(self.rows("Weekly numbers"), [])
        self.assertEqual(self.gw.posts(), [])

    def test_keeps_the_week_once(self):
        self.run_it(dry=False)
        told = self.told()[0]
        self.assertIn("Sales: 175.00 GBP from 3 payments (up 17% on the week before)", told)
        self.assertIn("Refunds: 10.00 GBP (none the week before)", told)
        self.assertIn("New customers: 2 (up 100% on the week before)", told)
        self.run_it(dry=False)
        rows = self.rows("Weekly numbers")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Week"], self.week)
        self.assertEqual(rows[0]["Sales"], 175)
        self.assertTrue((self.co.root / "files/reports/weekly_numbers.md").exists())


def mail(mid, sender, to, subject, days_ago, sent):
    return {"id": mid, "labelIds": ["SENT"] if sent else ["INBOX"], "internalDate": str(int((time.time() - days_ago * DAY) * 1000)),
            "payload": {"headers": [{"name": "From", "value": sender}, {"name": "To", "value": to},
                                    {"name": "Subject", "value": subject}, {"name": "Message-ID", "value": f"<{mid}@mail>"}]}}


class EmailFollowUpsTest(CatalogRoutineTest):
    entry = "email_follow_ups"
    task = "Follow up on emails that got no reply  @workflow:email_follow_ups  every:weekdays"
    me = "Sam <sam@shop.test>"

    def setUp(self):
        super().setUp()
        self.threads = {
            "t1": [mail("m1", self.me, "Jane Doe <jane@client.test>", "Quote for 40 cakes", 5, True)],  # waiting
            "t2": [mail("m2", self.me, "bob@client.test", "Order", 6, True),
                   mail("m3", "bob@client.test", self.me, "Re: Order", 4, False)],  # Bob answered
            "t3": [mail("m4", self.me, "noreply@service.test", "Account", 6, True)],  # never followed up
            "t4": [mail("m5", self.me, "amy@client.test", "Hello", 1, True)],  # too recent
        }
        gmail = "/x/google/gmail.googleapis.com/gmail/v1/users/me"
        routes = {("GET", f"{gmail}/profile"): {"emailAddress": "sam@shop.test"},
                  ("GET", f"{gmail}/threads"): lambda q, b: {"threads": [{"id": t} for t in self.threads]},
                  ("POST", f"{gmail}/messages/send"): lambda q, b: {"id": "sent1", "threadId": json.loads(b)["threadId"]}}
        for tid in self.threads:
            routes[("GET", f"{gmail}/threads/{tid}")] = (lambda tid: lambda q, b: {"id": tid, "messages": self.threads[tid]})(tid)
        self.gw = FakeGateway(routes)

    def test_practice_run_writes_nothing(self):
        lines = self.run_it(dry=True)
        self.assertEqual(lines[-1], "Would follow up on 1 email with no reply")
        self.assertEqual(self.gw.posts(), [])
        self.assertFalse((self.co.root / "drafts").exists())

    def test_drafts_once_then_notes_the_reply(self):
        lines = self.run_it(dry=False)
        self.assertEqual(lines[-1], "Wrote follow-ups on 1 email with no reply")
        draft = (self.co.root / "drafts/email_follow_ups-t1.md").read_text()
        self.assertIn("Hi Jane,", draft)
        self.assertIn('about "Quote for 40 cakes"', draft)
        self.assertIn("Jane Doe <jane@client.test>", self.told()[0])
        self.assertEqual(self.gw.posts(), [])  # drafts only, unless the owner said to send
        self.assertEqual(self.run_it(dry=False)[-1], "No emails waiting on a reply")
        self.threads["t1"].append(mail("m9", "jane@client.test", self.me, "Re: Quote for 40 cakes", 0, False))
        self.run_it(dry=False)
        self.assertEqual([r["Status"] for r in self.rows("Follow-ups")], ["Replied"])
        self.assertIn("Replied since: Jane Doe <jane@client.test>.", self.told()[-1])

    def test_sends_when_the_owner_said_so(self):
        path = self.co.root / "workflows/email_follow_ups.py"
        path.write_text(path.read_text().replace('"SEND": False', '"SEND": True'))
        lines = self.run_it(dry=False)
        self.assertEqual(lines[-1], "Followed up on 1 email with no reply")
        [post] = self.gw.posts()
        self.assertTrue(post["path"].endswith("/messages/send"))
        self.assertEqual([r["Status"] for r in self.rows("Follow-ups")], ["Sent"])


class ProposalFollowUpsTest(CatalogRoutineTest):
    entry = "proposal_follow_ups"
    task = "Follow up on proposals that got no answer  @workflow:proposal_follow_ups  every:weekdays"
    me = "Sam <sam@shop.test>"

    def setUp(self):
        super().setUp()
        self.threads = {
            "p1": [mail("q1", self.me, "Dana Lee <dana@acme.test>", "Proposal: brand workshop", 5, True)],
            "p2": [mail("q2", self.me, "omar@beta.test", "Quote for the Q1 audit", 12, True)],
            "p3": [mail("q3", self.me, "kim@gamma.test", "Proposal", 8, True),
                   mail("q4", "kim@gamma.test", self.me, "Re: Proposal", 6, False)],  # answered
            "p4": [mail("q5", self.me, "lee@delta.test", "Proposal for March", 1, True)],  # too soon
        }
        gmail = "/x/google/gmail.googleapis.com/gmail/v1/users/me"
        routes = {("GET", f"{gmail}/profile"): {"emailAddress": "sam@shop.test"},
                  ("GET", f"{gmail}/threads"): lambda q, b: {"threads": [{"id": t} for t in self.threads]},
                  ("POST", f"{gmail}/messages/send"): lambda q, b: {"id": "s1", "threadId": json.loads(b)["threadId"]}}
        for tid in self.threads:
            routes[("GET", f"{gmail}/threads/{tid}")] = (lambda tid: lambda q, b: {"id": tid, "messages": self.threads[tid]})(tid)
        self.gw = FakeGateway(routes)

    def test_practice_run_sends_nothing(self):
        self.assertEqual(self.run_it(dry=True)[-1], "Would nudge 2 proposals with no answer")
        self.assertEqual(self.gw.posts(), [])

    def test_nudges_once_then_waits_for_the_next(self):
        self.assertEqual(self.run_it(dry=False)[-1], "Wrote nudges for 2 proposals with no answer")
        self.assertIn("I wanted to check you got the proposal", (self.co.root / "drafts/proposal_follow_ups-proposal-p1.md").read_text())
        self.assertIn("Dana Lee <dana@acme.test>", self.told()[0])
        # the next morning: the 12-day-old one isn't nudged again straight away, though only drafted
        self.assertEqual(self.run_it(dry=False)[-1], "No proposals waiting on a nudge")
        rows = {r["Subject"]: r for r in self.rows("Proposals")}
        self.assertEqual(rows["Quote for the Q1 audit"]["Nudges"], 1)
        self.threads["p1"].append(mail("q9", "dana@acme.test", self.me, "Re: Proposal: brand workshop", 0, False))
        self.run_it(dry=False)
        self.assertEqual({r["Subject"]: r["Status"] for r in self.rows("Proposals")}["Proposal: brand workshop"], "Answered")


class MeetingPrepTest(CatalogRoutineTest):
    entry = "meeting_prep"
    task = "Prepare a brief before each client meeting  @workflow:meeting_prep  every:daily"

    def setUp(self):
        super().setUp()
        from datetime import datetime, timedelta, timezone
        soon = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(timespec="seconds")
        self.upcoming = [
            {"id": "e1", "summary": "Workshop kickoff", "start": {"dateTime": soon},
             "attendees": [{"email": "sam@shop.test", "self": True}, {"email": "dana@acme.test", "displayName": "Dana Lee"}]},
            {"id": "e2", "summary": "Team sync", "start": {"dateTime": soon},
             "attendees": [{"email": "sam@shop.test", "self": True}, {"email": "jo@shop.test"}]},  # only colleagues
            {"id": "e3", "summary": "Holiday", "start": {"date": soon[:10]}, "attendees": [{"email": "x@acme.test"}]},  # all day
        ]
        past = [{"id": "old", "start": {"dateTime": "2026-09-14T10:00:00+00:00"}}]
        gmail = "/x/google/gmail.googleapis.com/gmail/v1/users/me"
        calendar = "/x/google/www.googleapis.com/calendar/v3/calendars/primary/events"
        email = mail("m1", "Dana Lee <dana@acme.test>", "sam@shop.test", "Agenda for the kickoff", 2, False)
        email["snippet"] = "Here are the three things we'd like to cover"
        self.gw = FakeGateway({
            ("GET", f"{gmail}/profile"): {"emailAddress": "sam@shop.test"},
            ("GET", calendar): lambda q, b: {"items": past if "q" in q else self.upcoming},
            ("GET", f"{gmail}/messages"): {"messages": [{"id": "m1"}]},
            ("GET", f"{gmail}/messages/m1"): email,
        })

    def test_practice_run_keeps_nothing(self):
        self.assertEqual(self.run_it(dry=True)[-1], "Would brief 1 upcoming meeting")
        self.assertEqual(self.rows("Meeting briefs"), [])

    def test_briefs_each_meeting_once(self):
        self.assertEqual(self.run_it(dry=False)[-1], "Briefed 1 upcoming meeting")
        [row] = self.rows("Meeting briefs")
        self.assertEqual(row["With"], "Dana Lee")
        self.assertEqual(row["Last met"], "2026-09-14")
        self.assertIn("Agenda for the kickoff: Here are the three things", row["Brief"])
        self.assertIn("Workshop kickoff with Dana Lee", self.told()[0])
        self.assertEqual(self.run_it(dry=False)[-1], "No upcoming meetings need a brief")
        self.assertEqual(self.gw.posts(), [])  # it only reads


class CallRecapsTest(CatalogRoutineTest):
    entry = "call_recaps"
    task = "Write a recap after each client call  @workflow:call_recaps  every:3h"

    def setUp(self):
        super().setUp()
        self.co.py("""
import json, library
t = library.table("Call notes", columns="Client:text, Email:text, Date:date, Notes:longtext, Recap:status(To do|Drafted|Sent|Skipped)")
t.add({"Client": "Acme", "Email": "dana@acme.test", "Date": "2026-10-20", "Notes": "Agreed 3-month pilot. Dana sends data by Fri 24th. I send revised scope Monday."})
t.add({"Client": "Beta", "Email": "omar@beta.test", "Date": "2026-10-19", "Notes": "Old call", "Recap": "Drafted"})
print(json.dumps(1))
""")
        self.asked = []
        answer = {"subject": "Recap: pilot", "email": "Hi Dana,\n\nThanks for the call...\n\nThanks",
                  "actions": [{"what": "Send the data", "who": "Client", "due": "2026-10-24"},
                              {"what": "Send the revised scope", "who": "You", "due": "next week"}]}

        def messages(q, body):
            self.asked.append(json.loads(body))
            return {"content": [{"type": "text", "text": json.dumps(answer)}], "usage": {"input_tokens": 900, "output_tokens": 300}}

        gmail = "/x/google/gmail.googleapis.com/gmail/v1/users/me"
        self.gw = FakeGateway({("POST", "/v1/messages"): messages, ("POST", f"{gmail}/messages/send"): {"id": "s1"}})

    def test_practice_run_writes_nothing_down(self):
        self.assertEqual(self.run_it(dry=True)[-1], "Would recap 1 call")
        self.assertEqual(self.rows("Action items"), [])
        self.assertEqual(sorted(r["Recap"] for r in self.rows("Call notes")), ["Drafted", "To do"])

    def test_recap_and_action_items_once(self):
        self.assertEqual(self.run_it(dry=False)[-1], "Recapped 1 call")
        self.assertEqual(len(self.asked), 1)  # only the call waiting
        self.assertIn("Dana sends data by Fri 24th", self.asked[0]["messages"][0]["content"][-1]["text"])
        items = {r["What"]: r for r in self.rows("Action items")}
        self.assertEqual(items["Send the data"]["Due"], "2026-10-24")
        self.assertEqual(items["Send the data"]["Who"], "Client")
        self.assertNotIn("Due", items["Send the revised scope"])  # not a date: left empty
        self.assertTrue((self.co.root / "drafts").exists())
        self.assertIn("Recaps ready for your calls with Acme", self.told()[0])
        self.assertEqual(self.gw.posts()[0]["path"], "/v1/messages")  # drafted, not sent
        self.assertEqual(self.run_it(dry=False)[-1], "No calls waiting for a recap")
        self.assertEqual(len(self.asked), 1)


class MonthlyClientReportTest(CatalogRoutineTest):
    entry = "monthly_client_report"
    task = "Send me last month by client  @workflow:monthly_client_report  every:monthly"

    def setUp(self):
        super().setUp()
        from datetime import datetime, timedelta, timezone
        first = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = (first - timedelta(days=1)).replace(day=1)
        self.label = start.strftime("%B %Y")
        self.month = start.date().isoformat()
        at = lambda day, hour: (start + timedelta(days=day, hours=hour)).isoformat()  # noqa: E731
        me = {"email": "sam@shop.test", "self": True}
        events = [
            {"id": "a", "start": {"dateTime": at(2, 9)}, "end": {"dateTime": at(2, 10)}, "attendees": [me, {"email": "dana@acme.test"}]},
            {"id": "b", "start": {"dateTime": at(9, 9)}, "end": {"dateTime": at(9, 9.5)}, "attendees": [me, {"email": "lee@acme.test"}]},
            {"id": "c", "start": {"dateTime": at(5, 14)}, "end": {"dateTime": at(5, 15)}, "attendees": [me, {"email": "jo@gmail.com"}]},
            {"id": "d", "start": {"dateTime": at(6, 8)}, "end": {"dateTime": at(6, 9)}, "attendees": [me, {"email": "kim@shop.test"}]},  # a colleague
        ]
        paid_at = int((start + timedelta(days=10)).timestamp())
        invoices = [{"id": "in_1", "customer_email": "ap@acme.test", "amount_paid": 400000, "status_transitions": {"paid_at": paid_at}},
                    {"id": "in_2", "customer_email": "pay@beta.test", "amount_paid": 50000, "status_transitions": {"paid_at": paid_at}}]
        counts = {"acme.test": 23, "beta.test": 4, "jo@gmail.com": 7}
        gmail = "/x/google/gmail.googleapis.com/gmail/v1/users/me"
        self.gw = FakeGateway({
            ("GET", f"{gmail}/profile"): {"emailAddress": "sam@shop.test"},
            ("GET", "/x/google/www.googleapis.com/calendar/v3/calendars/primary/events"): {"items": events},
            ("GET", "/x/stripe/api.stripe.com/v1/invoices"): {"data": invoices, "has_more": False},
            ("GET", f"{gmail}/messages"): lambda q, b: {"resultSizeEstimate": next(n for k, n in counts.items() if f"from:{k} " in q["q"][0])},
        })

    def test_practice_run_keeps_nothing(self):
        self.assertEqual(self.run_it(dry=True)[-1], f"{self.label}: 3 clients (practice run)")
        self.assertEqual(self.rows("Client months"), [])

    def test_the_month_by_client(self):
        self.assertEqual(self.run_it(dry=False)[-1], f"{self.label}: 3 clients")
        rows = {r["Client"]: r for r in self.rows("Client months")}
        self.assertEqual(set(rows), {"acme.test", "beta.test", "jo@gmail.com"})  # not the colleague
        self.assertEqual((rows["acme.test"]["Meetings"], rows["acme.test"]["Hours"], rows["acme.test"]["Emails"], rows["acme.test"]["Invoiced"]), (2, 1.5, 23, 4000))
        self.assertEqual(rows["beta.test"]["Meetings"], 0)  # invoiced only
        self.assertEqual(rows["acme.test"]["Month"], self.month)
        self.assertIn("- acme.test: 2 meetings (1.5 h), 23 emails, 4,000.00 invoiced", self.told()[0])
        self.run_it(dry=False)
        self.assertEqual(len(self.rows("Client months")), 3)  # the same month again: no duplicates


class LeadTriageTest(CatalogRoutineTest):
    entry = "lead_triage"
    task = "Pick out new leads from my email and draft a reply  @workflow:lead_triage  every:3h"

    def setUp(self):
        super().setUp()
        def message(mid, sender, subject, snippet):
            m = mail(mid, sender, "sam@shop.test", subject, 0, False)
            m.update(threadId=f"t{mid}", snippet=snippet)
            return m
        self.inbox = {
            "m1": message("m1", "Dana Lee <dana@newco.test>", "Brand workshop", "Hi, could you send a quote for a brand workshop in May?"),
            "m2": message("m2", "Weekly <news@letters.test>", "This week in design", "Top 10 stories"),
            "m3": message("m3", "Omar <omar@client.test>", "One more thing", "Can you quote the follow-up work too?"),  # already a client
            "m4": message("m4", "Max <max@agency.test>", "Grow your agency", "We help consultants get more clients with ads."),
        }
        gmail = "/x/google/gmail.googleapis.com/gmail/v1/users/me"

        def listing(q, b):
            query = q["q"][0]
            if query.startswith("in:sent"):
                return {"messages": [{"id": "x"}] if "omar@client.test" in query else [], "resultSizeEstimate": 0}
            return {"messages": [{"id": k} for k in self.inbox]}

        routes = {("GET", f"{gmail}/profile"): {"emailAddress": "sam@shop.test"}, ("GET", f"{gmail}/messages"): listing,
                  ("POST", f"{gmail}/messages/send"): {"id": "s1"}}
        for k, m in self.inbox.items():
            routes[("GET", f"{gmail}/messages/{k}")] = m
        self.gw = FakeGateway(routes)

    def test_practice_run_keeps_nothing(self):
        self.assertEqual(self.run_it(dry=True)[-1], "Would keep 1 new lead")
        self.assertEqual(self.rows("Leads"), [])

    def test_picks_the_lead_and_drafts_a_reply_once(self):
        self.assertEqual(self.run_it(dry=False)[-1], "Found 1 new lead")
        [lead] = self.rows("Leads")
        self.assertEqual((lead["Name"], lead["Email"], lead["Status"]), ("Dana Lee", "dana@newco.test", "New"))
        self.assertIn("Hi Dana,", (self.co.root / "drafts/lead_triage-lead-m1.md").read_text())
        self.assertIn("Dana Lee (dana@newco.test)", self.told()[0])
        self.assertEqual(self.run_it(dry=False)[-1], "No new leads")  # each email is looked at once

    def test_sends_when_the_owner_said_so(self):
        path = self.co.root / "workflows/lead_triage.py"
        path.write_text(path.read_text().replace('"SEND": False', '"SEND": True'))
        self.assertEqual(self.run_it(dry=False)[-1], "Found 1 new lead")
        self.assertEqual([p["path"].rsplit("/", 1)[-1] for p in self.gw.posts()], ["send"])
        self.assertEqual(self.rows("Leads")[0]["Status"], "Replied")


class TestimonialRequestsTest(CatalogRoutineTest):
    entry = "testimonial_requests"
    task = "Ask happy clients for a testimonial  @workflow:testimonial_requests  every:weekly"

    def setUp(self):
        super().setUp()
        def inv(iid, name, email, amount, paid_days_ago):
            return {"id": iid, "number": iid.upper(), "customer_name": name, "customer_email": email, "amount_paid": amount * 100,
                    "status_transitions": {"paid_at": int(time.time()) - paid_days_ago * DAY}}
        invoices = [inv("in_1", "Dana Lee", "dana@acme.test", 1200, 10), inv("in_2", "Beta", "pay@beta.test", 100, 10),  # too small
                    inv("in_3", "Gamma Co", "ap@gamma.test", 900, 2),  # too soon
                    inv("in_4", "Dana Lee", "dana@acme.test", 800, 30)]  # the same client: one request
        self.gw = FakeGateway({("GET", "/x/stripe/api.stripe.com/v1/invoices"): {"data": invoices, "has_more": False},
                               ("POST", "/x/google/gmail.googleapis.com/gmail/v1/users/me/messages/send"): {"id": "s1"}})

    def test_practice_run_keeps_nothing(self):
        self.assertEqual(self.run_it(dry=True)[-1], "Would ask 1 client for a testimonial")
        self.assertEqual(self.rows("Testimonial requests"), [])

    def test_asks_once(self):
        self.assertEqual(self.run_it(dry=False)[-1], "Asked 1 client for a testimonial")
        [row] = self.rows("Testimonial requests")
        self.assertEqual((row["Email"], row["Invoice"], row["Status"]), ("dana@acme.test", "IN_1", "Asked"))
        self.assertIn("Hi Dana,", (self.co.root / "drafts/testimonial_requests-testimonial-dana-acme-test.md").read_text())
        self.assertIn("Dana Lee paid recently", self.told()[0])
        self.assertEqual(self.gw.posts(), [])
        self.assertEqual(self.run_it(dry=False)[-1], "No clients to ask for a testimonial")


if __name__ == "__main__":
    unittest.main()
