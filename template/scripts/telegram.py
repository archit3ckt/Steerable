"""Minimal Telegram Bot API client plus the owner's chat binding.

The owner connects their own bot on the dashboard's Connections page: they paste the token
from @BotFather (kept in .cache/telegram-token, or TELEGRAM_BOT_TOKEN in the environment), then
open a one-time link, t.me/<bot>?start=<code>. Only the chat that brings a valid code becomes
the owner's chat, so nobody else can claim the bot by finding it first. Every other chat is
ignored. To re-link, make a new link (or `python scripts/telegram.py link` in a terminal).
"""
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from common import CACHE, env

STATE = CACHE / "telegram.json"
TOKEN_FILE = CACHE / "telegram-token"
MAX_LEN = 4000  # Telegram's limit is 4096
LINK_MINUTES = 30


class TelegramError(RuntimeError):
    """Something the owner can be shown as is."""


def token() -> str:
    if t := env("TELEGRAM_BOT_TOKEN"):
        return t
    try:
        return TOKEN_FILE.read_text().strip()
    except FileNotFoundError:
        return ""


def _call(method: str, _timeout: int = 30, _token: str | None = None, **params):
    base = env("TELEGRAM_API_BASE", "https://api.telegram.org")  # a stand-in, for tests
    url = f"{base}/bot{_token or token()}/{method}"
    data = urllib.parse.urlencode(
        {k: json.dumps(v) if isinstance(v, (dict, list)) else v
         for k, v in params.items() if v is not None}).encode()
    with urllib.request.urlopen(url, data=data, timeout=_timeout) as r:
        return json.load(r)["result"]


def state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s))


def owner_chat() -> int | None:
    return state().get("chat_id")


def configured() -> bool:
    return bool(token() and owner_chat())


# ---------- connecting (the dashboard, through the agent API) ----------

def set_token(new: str) -> dict:
    """Check a bot token with Telegram, keep it, and make a link for the owner to open."""
    new = new.strip()
    if env("TELEGRAM_BOT_TOKEN"):
        raise TelegramError("This bot is set in the server's settings (TELEGRAM_BOT_TOKEN). Change it there.")
    if ":" not in new or len(new) < 30:
        raise TelegramError("That doesn't look like a bot token. Copy the whole line @BotFather gave you.")
    try:
        me = _call("getMe", _timeout=15, _token=new)
    except urllib.error.HTTPError:
        raise TelegramError("Telegram didn't accept that token. Copy it again from @BotFather.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise TelegramError("Couldn't reach Telegram. Check the server's internet connection.") from None
    CACHE.mkdir(exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(new)
    tmp.chmod(0o600)
    tmp.replace(TOKEN_FILE)
    s = state()
    if s.get("bot") != me.get("username"):  # another bot: its chat and updates start over
        s = {k: v for k, v in s.items() if k == "session_id"}
    s["bot"] = me.get("username")
    save_state(s)
    return new_link() if not s.get("chat_id") else status()


def new_link() -> dict:
    """A one-time link that binds the chat that opens it."""
    if not token():
        raise TelegramError("Connect a bot first.")
    s = state()
    if not s.get("bot"):
        s["bot"] = _call("getMe", _timeout=15).get("username")
    s["link"] = {"code": secrets.token_urlsafe(16), "until": time.time() + LINK_MINUTES * 60}
    save_state(s)
    return status()


def claim(code: str, chat_id: int) -> bool:
    """The chat brought a code: bind it if the code is the current one and still good."""
    s = state()
    link = s.get("link") or {}
    if not code or not link or link["until"] < time.time() or not secrets.compare_digest(code, link["code"]):
        return False
    s["chat_id"] = chat_id
    s.pop("link", None)
    save_state(s)
    return True


def disconnect() -> None:
    """Unlink the owner's chat and forget the token (unless it comes from the environment)."""
    s = state()
    for key in ("chat_id", "link", "offset"):
        s.pop(key, None)
    if not env("TELEGRAM_BOT_TOKEN"):
        s.pop("bot", None)
        TOKEN_FILE.unlink(missing_ok=True)
    save_state(s)


def status() -> dict:
    s = state()
    if token() and not s.get("bot"):  # a bot from the settings: learn its name once
        try:
            s["bot"] = _call("getMe", _timeout=10).get("username")
            save_state(s)
        except (urllib.error.URLError, TimeoutError, OSError, KeyError):
            pass
    link = s.get("link")
    live = link and link["until"] > time.time()
    return {"connected": bool(token()), "bot": s.get("bot"), "linked": bool(s.get("chat_id")),
            "linkUrl": f"https://t.me/{s['bot']}?start={link['code']}" if live and s.get("bot") else None,
            "fromSettings": bool(env("TELEGRAM_BOT_TOKEN"))}


# ---------- talking ----------

def send_to(chat: int, text: str) -> None:
    _call("sendMessage", chat_id=chat, text=text[:MAX_LEN], disable_web_page_preview="true")


def send(text: str, buttons: list[list[tuple[str, str]]] | None = None) -> None:
    """Send to the owner. buttons: rows of (label, callback_data)."""
    chat = owner_chat()
    if not chat:
        return
    chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)] or [""]
    for n, chunk in enumerate(chunks):
        markup = None
        if buttons and n == len(chunks) - 1:
            markup = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                                          for row in buttons]}
        _call("sendMessage", chat_id=chat, text=chunk, reply_markup=markup,
              disable_web_page_preview="true")


def typing() -> None:
    if chat := owner_chat():
        _call("sendChatAction", chat_id=chat, action="typing")


def get_updates(offset: int, timeout: int = 50) -> list[dict]:
    return _call("getUpdates", _timeout=timeout + 10, offset=offset, timeout=timeout,
                 allowed_updates=["message", "callback_query"])


def download(file_id: str) -> bytes:
    """A file someone sent the bot (Telegram lets bots fetch files up to 20 MB)."""
    path = _call("getFile", file_id=file_id)["file_path"]
    base = env("TELEGRAM_API_BASE", "https://api.telegram.org")
    with urllib.request.urlopen(f"{base}/file/bot{token()}/{path}", timeout=60) as r:
        return r.read()


def attachment(msg: dict) -> tuple[str, str, int] | None:
    """(file id, name, size) of the photo or file in a message, if it has one. For a photo,
    the largest size Telegram made."""
    if msg.get("photo"):
        biggest = max(msg["photo"], key=lambda p: p.get("file_size") or p.get("width", 0))
        return biggest["file_id"], f"photo-{msg.get('message_id', '')}.jpg", biggest.get("file_size") or 0
    if doc := msg.get("document"):
        return doc["file_id"], doc.get("file_name") or "file", doc.get("file_size") or 0
    return None


def answer_callback(callback_id: str, text: str = "") -> None:
    _call("answerCallbackQuery", callback_query_id=callback_id, text=text)


if __name__ == "__main__":
    # In a terminal: `python scripts/telegram.py link` prints a link to bind your chat.
    if sys.argv[1:] == ["link"]:
        try:
            print(new_link()["linkUrl"] or "No bot username yet: check the token.")
        except TelegramError as e:
            sys.exit(str(e))
    else:
        print(json.dumps(status(), indent=1))
