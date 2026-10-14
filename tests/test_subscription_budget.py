"""No monthly cap on a Claude subscription; the cap still holds with an API key (budget.py)."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"
SCRIPT = ("import sys; sys.path.insert(0, 'scripts')\nfrom budget import check, record, BudgetExceeded\n"
          "record('chat', 25.0)\ntry:\n    check(); print('ok')\nexcept BudgetExceeded as e:\n    print('stopped:', e)")


class SubscriptionBudgetTest(unittest.TestCase):
    def run_with(self, auth_method: str, api_key: str = "") -> str:
        tmp = Path(tempfile.mkdtemp())
        try:
            root = tmp / "co"
            shutil.copytree(TEMPLATE, root)
            (root / ".env").write_text("COMPANY_NAME=Co\nMONTHLY_BUDGET_USD=20\n")
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            (bin_dir / "claude").write_text(f"#!/bin/sh\necho '{json.dumps({'loggedIn': True, 'authMethod': auth_method})}'\n")
            (bin_dir / "claude").chmod(stat.S_IRWXU)
            env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "STEERABLE_GATEWAY_URL")}
            env.update(MONTHLY_BUDGET_USD="20", PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", **({"ANTHROPIC_API_KEY": api_key} if api_key else {}))
            out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            return out.stdout.strip()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_subscription_has_no_cap(self):
        self.assertEqual(self.run_with("claude.ai"), "ok")

    def test_api_key_keeps_its_cap(self):
        out = self.run_with("claude.ai", api_key="sk-ant-test")
        self.assertTrue(out.startswith("stopped: This month's AI spending limit ($20"), out)
        self.assertTrue(self.run_with("apiKey").startswith("stopped:"))


if __name__ == "__main__":
    unittest.main()
