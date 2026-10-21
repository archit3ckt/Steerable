"""A table's rows as cards (a "cards" view, like monday's and Teable's), and a new table keeping its "All rows"
grid first even when its first view is added in code (the COO's library.py view).

    python3 -m unittest tests.test_library_cards -v
"""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_helpers import Company  # noqa: E402


class LibraryCardsTest(unittest.TestCase):
    def setUp(self):
        self.co = Company()

    def tearDown(self):
        self.co.close()

    def test_cards_view_after_the_grid(self):
        self.co.py("import json, library; library.table('Clients', columns='Name:text, Photo:files'); print(json.dumps(1))")
        proc = subprocess.run([sys.executable, "scripts/library.py", "view", "Clients", "Gallery", "--type", "cards"],
                              cwd=self.co.root, capture_output=True, text=True, env=self.co.env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        views = self.co.py("import json, library; print(json.dumps([(v['name'], v['type']) for v in library.table('Clients').views()]))")
        self.assertEqual(views, [["All rows", "grid"], ["Gallery", "cards"]])

    def test_an_unnamed_cards_view_is_called_cards(self):
        made = self.co.py("import json, library; t = library.table('Clients', columns='Name:text'); "
                          "print(json.dumps(t.save_view(None, kind='cards')['name']))")
        self.assertEqual(made, "Cards")


if __name__ == "__main__":
    unittest.main()
