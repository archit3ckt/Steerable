"""What building a routine cost, across every attempt (builder.costs): first build, the fixes after
its practice run, the owner's changes, retries.

    python3 -m unittest tests.test_build_costs -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402


class BuildCostsTest(unittest.TestCase):
    def setUp(self):
        self.co = Company()

    def tearDown(self):
        self.co.close()

    def test_cost_adds_up_across_attempts(self):
        self.co.builds({
            "b1": {"id": "b1", "workflow": "invoices", "task": "x", "status": "revised", "opened": "2026-10-20T08:00:00+00:00",
                   "cost_usd": 1.2, "turns": 30},
            "b2": {"id": "b2", "workflow": "invoices", "task": "x", "status": "revised", "opened": "2026-10-20T08:10:00+00:00",
                   "prev": "b1", "cost_usd": 0.4, "turns": 8},
            "b3": {"id": "b3", "workflow": "invoices", "task": "x", "status": "ready", "opened": "2026-10-20T08:20:00+00:00",
                   "prev": "b2", "cost_usd": 0.3, "turns": 6, "catalog": "overdue_invoices"},
            "b4": {"id": "b4", "workflow": "weekly", "task": "y", "status": "ready", "opened": "2026-10-19T08:00:00+00:00",
                   "cost_usd": 0.5},
        })
        out = {c["workflow"]: c for c in self.co.py("import builder, json; print(json.dumps(builder.costs()))")}
        self.assertEqual(out["invoices"]["builds"], 3)
        self.assertAlmostEqual(out["invoices"]["cost_usd"], 1.9)
        self.assertEqual(out["invoices"]["turns"], 44)
        self.assertEqual(out["invoices"]["catalog"], "overdue_invoices")
        self.assertEqual(out["weekly"]["builds"], 1)
        self.assertEqual(out["weekly"]["turns"], 0)


if __name__ == "__main__":
    unittest.main()
