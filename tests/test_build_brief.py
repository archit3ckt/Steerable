"""The builder is handed what it would otherwise look up (builder._brief): the company's memory, the
board, the library's tables, the other routines and the routine template, so it starts writing
instead of exploring.

    python3 -m unittest tests.test_build_brief -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402

PROMPTS = """
import builder, json, library
library.table("Clients", columns="Name:text, Email:text")
b = {"workflow": "remind", "task": "Remind clients  @workflow:remind  every:weekly", "title": "Remind clients"}
new = builder._prompt(b, "/wt")
change = builder._prompt({**b, "change": "Also text them"}, "/wt")
print(json.dumps({"new": new, "change": change, "brief": builder._brief()}))
"""


class BuildBriefTest(unittest.TestCase):
    def setUp(self):
        self.co = Company()
        (self.co.root / "memory/company.md").write_text("# Company\n\nBakery in Leeds, two shops.\n")
        (self.co.root / "workflows/job_scan.py").write_text('"""Find new jobs worth applying to."""\nprint("ok")\n')

    def tearDown(self):
        self.co.close()

    def test_prompt_carries_the_brief(self):
        out = self.co.py(PROMPTS)
        first = (self.co.root / "workflows/_template.py").read_text().splitlines()[0]
        for prompt in (out["new"], out["change"]):
            self.assertIn("Bakery in Leeds", prompt)
            self.assertIn("Clients", prompt)
            self.assertIn("Email", prompt)
            self.assertIn(first, prompt)
            self.assertIn("job_scan: Find new jobs worth applying to.", prompt)
            self.assertIn("don't read them again", prompt)
        self.assertNotIn("Read memory/", out["new"])

    def test_brief_cuts_long_memory(self):
        (self.co.root / "memory/decisions.md").write_text("# Decisions\n" + "x" * 10_000 + "\nLATEST DECISION\n")
        brief = self.co.py(PROMPTS)["brief"]
        section = brief.split("memory/decisions.md")[1].split("\n### ")[0]
        self.assertLessEqual(len(section), 4_200)
        self.assertIn("LATEST DECISION", section)  # the newest part is kept
        self.assertIn("(earlier part left out)", section)


if __name__ == "__main__":
    unittest.main()
