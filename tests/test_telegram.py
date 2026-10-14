"""The owner's own Telegram bot, connected from the dashboard: the token is checked and kept by
the engine, and only the chat that opens the one-time link is bound. A fake Telegram API stands
in for api.telegram.org (TELEGRAM_API_BASE).

    python3 -m unittest tests.test_telegram -v
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
import urllib.parse
import urllib.request
from pathlib import Path

from test_agent_api import TOKEN, build_company

BOT_TOKEN = "123456789:" + "A" * 35


class FakeTelegram(http.server.BaseHTTPRequestHandler):
    sent: list = []

    def do_POST(self):
        params = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()))
        token, method = self.path.split("/")[1].removeprefix("bot"), self.path.split("/")[2]
        if token != BOT_TOKEN:
            self.send_response(401)
            self.end_headers()
            return
        result = True
        if method == "getFile":
            result = {"file_id": params["file_id"], "file_path": f"docs/{params['file_id']}"}
        elif method == "getMe":
            result = {"id": 1, "is_bot": True, "username": "bloom_coo_bot"}
        elif method == "sendMessage":
            FakeTelegram.sent.append((int(params["chat_id"]), params["text"]))
        data = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    FILES = {"p1": b"\x89PNG\r\n\x1a\nphoto-one", "p2": b"\x89PNG\r\n\x1a\nphoto-two", "x1": b"MZ"}

    def do_GET(self):
        token, _, path = self.path.removeprefix("/file/bot").partition("/")
        data = self.FILES.get(path.removeprefix("docs/")) if token == BOT_TOKEN else None
        self.send_response(200 if data else 404)
        self.end_headers()
        self.wfile.write(data or b"")

    def log_message(self, *args):
        pass


class TelegramTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "bloom"
        build_company(cls.root)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.env = {k: v for k, v in os.environ.items() if k != "TELEGRAM_BOT_TOKEN"}
        cls.env.update({"AGENT_API_PORT": str(cls.port), "HOME": str(cls.tmp),
                        "TELEGRAM_API_BASE": f"http://127.0.0.1:{cls.fake.server_address[1]}",
                        "PATH": f"{cls.root / 'fakebin'}{os.pathsep}{os.environ['PATH']}"})
        cls.proc = subprocess.Popen([sys.executable, "scripts/agent_api.py"], cwd=cls.root, env=cls.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.fake.shutdown()
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

    def messages(self, *msgs: tuple[int, str]) -> dict:
        """Hand messages to the bridge as Telegram would deliver them; return the state after."""
        code = ("import json, sys\nsys.path.insert(0, 'scripts')\nimport bridge, telegram\n"
                f"for chat, text in {list(msgs)!r}:\n"
                "    bridge.handle_message({'chat': {'id': chat, 'type': 'private'}, 'text': text})\n"
                "print(json.dumps(telegram.state()))")
        out = subprocess.run([sys.executable, "-c", code], cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_connect_link_and_disconnect(self):
        self.assertEqual(self.call("GET", "/v1/telegram")[1],
                         {"connected": False, "bot": None, "linked": False, "linkUrl": None, "fromSettings": False})
        self.assertEqual(self.call("POST", "/v1/telegram/token", {"token": "nope"})[0], 400)
        status, body = self.call("POST", "/v1/telegram/token", {"token": "123456789:" + "B" * 35})
        self.assertEqual((status, body["error"]), (400, "Telegram didn't accept that token. Copy it again from @BotFather."))

        status, body = self.call("POST", "/v1/telegram/token", {"token": BOT_TOKEN})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["connected"])
        self.assertEqual(body["bot"], "bloom_coo_bot")
        self.assertFalse(body["linked"])
        self.assertTrue(body["linkUrl"].startswith("https://t.me/bloom_coo_bot?start="))
        code = body["linkUrl"].split("start=")[1]
        token_file = self.root / ".cache/telegram-token"
        self.assertEqual(token_file.read_text(), BOT_TOKEN)
        self.assertEqual(oct(token_file.stat().st_mode & 0o777), "0o600")
        self.assertNotIn(BOT_TOKEN, json.dumps(body))

        # Whoever finds the bot first can't take it: only the link's code binds a chat, once.
        FakeTelegram.sent.clear()
        state = self.messages((666, "/start"), (666, "/start guess"), (42, f"/start {code}"), (777, f"/start {code}"))
        self.assertEqual(state["chat_id"], 42)
        self.assertNotIn("link", state)
        self.assertEqual([chat for chat, _ in FakeTelegram.sent], [666, 666, 42])  # once bound, others get silence
        self.assertTrue(FakeTelegram.sent[0][1].startswith("To connect, open the Telegram link"))
        self.assertIn("COO", FakeTelegram.sent[2][1])
        self.assertTrue(self.call("GET", "/v1/telegram")[1]["linked"])

        # A stranger's later messages are ignored.
        FakeTelegram.sent.clear()
        self.messages((666, "what's the revenue?"))
        self.assertEqual(FakeTelegram.sent, [])

        # Disconnecting forgets the chat and the token.
        body = self.call("POST", "/v1/telegram/disconnect")[1]
        self.assertEqual((body["connected"], body["linked"]), (False, False))
        self.assertFalse(token_file.exists())
        self.assertEqual(self.call("POST", "/v1/telegram/link"), (400, {"error": "Connect a bot first."}))

    def test_photos_and_files(self):
        """Photos and files sent to the bot go to the COO like the app's attachments; an album is one message."""
        (self.root / ".cache/telegram-token").write_text(BOT_TOKEN)
        (self.root / ".cache/telegram.json").write_text(json.dumps({"chat_id": 42}))
        chat = {"id": 42, "type": "private"}
        album = [{"message_id": 7, "chat": chat, "media_group_id": "g1", "caption": "My shop, two angles",
                  "photo": [{"file_id": "small", "file_size": 10, "width": 90}, {"file_id": "p1", "file_size": 17, "width": 1280}]},
                 {"message_id": 8, "chat": chat, "media_group_id": "g1",
                  "photo": [{"file_id": "p2", "file_size": 17, "width": 1280}]}]
        odd = {"message_id": 9, "chat": chat, "document": {"file_id": "x1", "file_name": "setup.exe", "file_size": 2}}
        code = ("import json, sys\nsys.path.insert(0, 'scripts')\nimport bridge\n"
                f"bridge.handle_message({album[0]!r}, {album[1:]!r})\n"
                f"bridge.handle_message({odd!r})\n")
        FakeTelegram.sent.clear()
        out = subprocess.run([sys.executable, "-c", code], cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        replies = [text for chat_id, text in FakeTelegram.sent if chat_id == 42]
        # One answer for the album, naming both photos (the fake COO echoes its prompt).
        self.assertEqual(len([r for r in replies if r.startswith("Got it")]), 1)
        self.assertIn("My shop, two angles", replies[0])
        self.assertEqual(replies[0].count("files/"), 2)
        self.assertIn("photo-7.jpg", replies[0])
        self.assertIn("setup.exe", replies[-1])  # the odd file: a plain reason, and no COO turn
        self.assertNotIn("Got it", replies[-1])
        mine = [json.loads(line) for line in (self.root / "logs/chat.jsonl").read_text().splitlines()][-2]
        self.assertEqual((mine["from"], [f["name"] for f in mine["files"]]), ("you", ["photo-7.jpg", "photo-8.jpg"]))
        saved = sorted(p.read_bytes() for p in (self.root / "files").rglob("*-photo-*.jpg"))
        self.assertEqual(saved, [FakeTelegram.FILES["p1"], FakeTelegram.FILES["p2"]])


if __name__ == "__main__":
    unittest.main()
