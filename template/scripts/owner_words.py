"""Words for the owner: AI-written text the app shows (decisions, the timeline) without anything
technical in it. The owner hears the big picture: what it means for them, and what only they can
do. Technical detail (code, scripts, commands, permissions, tests, commits) is the system's.

    owner_words.say(text)              # now: technical sentences left out, a plain rewrite on its way
    owner_words.say(text, wait=True)   # the plain rewrite (for background work, which can wait)

Rewrites are made once by the fast model and kept in .cache/owner_words.json.
"""
import hashlib
import json
import re
import threading

from common import CACHE

STORE = CACHE / "owner_words.json"
KEEP = 500
FALLBACK = "I'm taking care of it."

# Words that only mean something technical. Business words that are also technical ones (a store
# branch, imports, containers, a discount code, a customer database) are left out on purpose.
TECHNICAL = re.compile(
    r"\b(python|scripts?|\w+\.(?:py|js|ts|json|sh)|commit(?:ted|s)?|git|worktree|repo(?:sitory)?|"
    r"permissions?|bash|shell|command line|terminal|stdout|stderr|traceback|exception|stack ?trace|"
    r"exit code|error code|status code|apis?|json|https?|endpoints?|sdk|cron|heartbeat|workflows?|"
    r"incidents?|dry[- ]run|env(?:ironment)? var\w*|\.env|sqlite|schema|claude code|mcp|regex|"
    r"subprocess|docker|runtime|debug\w*|standards? check|the tools? (?:here )?refused|unit tests?|"
    r"syntax error|parser?|selectors?|headless|playwright|chromium|timed? ?out)\b|(?<![\w.])\.env\b",
    re.IGNORECASE,
)

PROMPT = """Rewrite this message from an AI chief operating officer to the business owner it works for.

The owner is busy and not technical. Keep only the big picture: what this means for them, and what
(if anything) only they can do. Leave out every technical detail: no code, scripts, files, Python,
commands, tools, permissions, tests, commits, systems or errors. If it's about a technical problem
that isn't theirs to fix, say in a few words that you're handling it. One or two short sentences, in
the same language, as the COO ("I"). Reply with only the message.

<message>
{text}
</message>"""

_lock = threading.Lock()
_pending: set[str] = set()


def technical(text: str) -> bool:
    return bool(TECHNICAL.search(text or ""))


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def _read() -> dict:
    try:
        return json.loads(STORE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _keep(key: str, plain: str) -> None:
    with _lock:
        data = _read()
        data[key] = plain
        if len(data) > KEEP:
            data = dict(list(data.items())[-KEEP:])
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        tmp.replace(STORE)


def without_technical(text: str) -> str:
    """The text with its technical sentences left out (or the fallback, if that's all of it)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in sentences if s and not technical(s)]
    return " ".join(kept) if kept else FALLBACK


def _rewrite(text: str) -> str:
    import agent

    out = str(agent.complete(PROMPT.format(text=text[:3000]), source="owner_words", tier="fast",
                             max_tokens=300, budget_usd="0.02")).strip().strip('"').strip()
    return out if out and not technical(out) else without_technical(text)


def _rewrite_later(key: str, text: str) -> None:
    try:
        _keep(key, _rewrite(text))
    except Exception:  # noqa: BLE001  (no AI right now: the plain cut stays until next time)
        pass
    finally:
        with _lock:
            _pending.discard(key)


def say(text: str, wait: bool = False) -> str:
    """Text fit to show the owner. Text with nothing technical in it comes back as it is."""
    if not text or not technical(text):
        return text
    key = _key(text)
    known = _read().get(key)
    if known:
        return known
    if wait:
        try:
            plain = _rewrite(text)
        except Exception:  # noqa: BLE001
            return without_technical(text)
        _keep(key, plain)
        return plain
    with _lock:
        start = key not in _pending
        _pending.add(key)
    if start:
        threading.Thread(target=_rewrite_later, args=(key, text), daemon=True).start()
    return without_technical(text)
