"""Spend tracking and the monthly budget cap.

Every paid API call is recorded in logs/spend.jsonl. Before a paid call, scripts
call `check()`, which raises BudgetExceeded once this month's spend reaches the cap:

- Signed in with a Claude subscription (no API key): no cap. The subscription is the limit, and
  what's recorded is only Claude Code's estimate of what it would cost on the API.
- With your own API key: MONTHLY_BUDGET_USD (from .env), since that's real money.

In Steerable Cloud the gateway decides instead (the plan's allowance plus top-ups, nothing while
the workspace is paused), so check() asks it: GET <STEERABLE_GATEWAY_URL>/budget.

CLI:
    python scripts/budget.py status                     # month to date vs cap
    python scripts/budget.py add 1.25 "manual: session"  # log spend made elsewhere
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from common import CACHE, LOGS, env, now_iso

SPEND_LOG = LOGS / "spend.jsonl"

# USD per million tokens (input, output). Update if pricing changes.
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "jev": (0.042, 0.00),  # TypeSafe Jev: input only, output is free
}


class BudgetExceeded(RuntimeError):
    pass


def subscription() -> bool:
    """Is Claude Code signed in with a Claude subscription rather than an API key? Asked once
    every 10 minutes (claude auth status), and kept in .cache so every script shares it."""
    if env("ANTHROPIC_API_KEY") or env("STEERABLE_GATEWAY_URL"):
        return False
    seen = CACHE / "auth.json"
    try:
        known = json.loads(seen.read_text())
        if known["at"] > time.time() - 600:
            return known["subscription"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    try:
        out = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=20).stdout
        yes = json.loads(out).get("authMethod") == "claude.ai"
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, AttributeError):
        return False
    seen.write_text(json.dumps({"subscription": yes, "at": time.time()}))
    return yes


def cap() -> float:
    return float(env("MONTHLY_BUDGET_USD", "20"))


def limit() -> float | None:
    """This month's cap in dollars, or None when there isn't one (a Claude subscription)."""
    return None if subscription() else cap()


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = PRICES.get(model, max(PRICES.values()))  # unknown model: assume priciest
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


def month_spend(month: str | None = None) -> float:
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    if not SPEND_LOG.exists():
        return 0.0
    total = 0.0
    for line in SPEND_LOG.read_text().splitlines():
        e = json.loads(line)
        if e["ts"].startswith(month):
            total += e["cost_usd"]
    return total


def gateway_budget() -> dict | None:
    """{"spentUsd", "capUsd", "paused"} from Steerable Cloud's gateway, or None without one."""
    base, token = env("STEERABLE_GATEWAY_URL"), env("ANTHROPIC_API_KEY")
    if not base or not token:
        return None
    req = urllib.request.Request(base.rstrip("/") + "/budget", headers={"x-api-key": token})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            budget = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None  # can't tell: let the gateway refuse if it must
    return budget if {"spentUsd", "capUsd", "paused"} <= budget.keys() else None


def check(expected_usd: float = 0.0) -> None:
    budget = gateway_budget()
    if budget:
        if budget["paused"]:
            raise BudgetExceeded("This workspace is paused because there's no plan. The owner can choose one in Billing.")
        if budget["spentUsd"] + expected_usd >= budget["capUsd"]:
            raise BudgetExceeded("This month's included AI work is used up. It resets on the 1st, or the owner can add more in Billing.")
        return
    most = limit()
    if most is None:
        return
    spent = month_spend()
    if spent + expected_usd >= most:
        raise BudgetExceeded(f"This month's AI spending limit (${most:.0f}, on your API key) is reached. It starts again on the 1st.")


def record(source: str, cost_usd: float, model: str = "",
           input_tokens: int = 0, output_tokens: int = 0, note: str = "") -> float:
    entry = {"ts": now_iso(), "source": source, "model": model,
             "input_tokens": input_tokens, "output_tokens": output_tokens,
             "cost_usd": round(cost_usd, 6), "note": note}
    SPEND_LOG.parent.mkdir(exist_ok=True)
    with SPEND_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return cost_usd


def record_usage(source: str, model: str, usage) -> float:
    """Record an Anthropic `response.usage` object. Returns the cost."""
    inp = (usage.input_tokens + (usage.cache_creation_input_tokens or 0)
           + (usage.cache_read_input_tokens or 0))
    return record(source, cost_of(model, inp, usage.output_tokens), model,
                  inp, usage.output_tokens)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "add":
        record("manual", float(sys.argv[2]), note=" ".join(sys.argv[3:]))
    spent, most = month_spend(), limit()
    print(f"Month to date: ${spent:.4f} (estimated), no cap: a Claude subscription" if most is None else
          f"Month to date: ${spent:.4f} of ${most:.2f} cap ({spent / most * 100:.1f}%)")
