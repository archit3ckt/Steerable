"""Alerts to the owner: a Telegram ping, email if SMTP is set, and always logs/alerts.md.

Each alert key fires at most once a day, so a task that fails on every heartbeat
doesn't flood anyone. Telegram pings respect the owner's attention: at most
MAX_PINGS a day and none in quiet hours. Anything held back goes into the next
daily brief instead.

    from alert import alert
    alert("workflow:demo", "Workflow demo failed", details)
"""
import json
import smtplib
import ssl
import sys
from datetime import date, datetime
from email.message import EmailMessage

import telegram
from common import CACHE, COMPANY, LOGS, env, now_iso

ALERTS_MD = LOGS / "alerts.md"
SENT = CACHE / "alerts_sent.json"
BRIEF_QUEUE = CACHE / "brief_queue.json"
MAX_PINGS = 2
QUIET_START, QUIET_END = 22, 8  # local hours


def queue_for_brief(line: str) -> None:
    q = json.loads(BRIEF_QUEUE.read_text()) if BRIEF_QUEUE.exists() else []
    q.append(line)
    BRIEF_QUEUE.write_text(json.dumps(q))


def _ping(subject: str, body: str, sent: dict) -> None:
    hour, today = datetime.now().hour, date.today().isoformat()
    pings = sent.get("_pings", {})
    quiet = hour >= QUIET_START or hour < QUIET_END
    if not telegram.configured() or quiet or pings.get(today, 0) >= MAX_PINGS:
        queue_for_brief(subject)
        return
    try:
        telegram.send(f"⚠️ {subject}\n\n{body[:1500]}\n\nReply here if you want me to look into it.")
        sent["_pings"] = {today: pings.get(today, 0) + 1}
    except Exception:
        queue_for_brief(subject)


def _send_email(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = env("SMTP_USER")
    msg["To"] = env("ALERT_TO")
    msg["Subject"] = f"[{COMPANY} ops] {subject}"
    msg.set_content(body)
    with smtplib.SMTP_SSL(env("SMTP_HOST"), int(env("SMTP_PORT", "465")),
                          context=ssl.create_default_context(), timeout=30) as s:
        s.login(env("SMTP_USER"), env("SMTP_PASS"))
        s.send_message(msg)


def alert(key: str, subject: str, body: str = "") -> bool:
    """Returns True if the alert went out, False if it already fired today."""
    sent = json.loads(SENT.read_text()) if SENT.exists() else {}
    today = date.today().isoformat()
    if sent.get(key) == today:
        return False
    with ALERTS_MD.open("a") as f:
        f.write(f"\n## {now_iso()} — {subject}\n\n{body}\n")
    if all(env(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "ALERT_TO")):
        try:
            _send_email(subject, body)
        except Exception as e:  # never let alerting crash the caller
            with ALERTS_MD.open("a") as f:
                f.write(f"\n(email failed: {e})\n")
    _ping(subject, body, sent)
    sent[key] = today
    SENT.write_text(json.dumps(sent))
    return True


if __name__ == "__main__":
    # python scripts/alert.py test  -> sends a test alert (ignores the daily limit)
    SENT.unlink(missing_ok=True)
    alert("test", "Test alert", "If you can read this, alerts work.")
    print("Alert written to logs/alerts.md"
          + (" and emailed." if env("SMTP_HOST") else ". Email not configured."))
