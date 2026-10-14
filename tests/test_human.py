"""Moving and typing like a person (scripts/browser.py): the paths and rhythms themselves, and,
with Python Playwright and a Chromium, what a page sees of them.

    python3 -m unittest tests.test_human
"""
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

try:
    import playwright  # noqa: F401
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

PAGE = """<html><body style="margin:0">
<button id="go" style="position:absolute;left:700px;top:500px;width:200px;height:60px">Go</button>
<input id="q" style="position:absolute;left:100px;top:100px;width:400px;height:40px">
<div style="height:3000px"></div>
<script>
window.seen = {moves: [], clicks: [], keys: []};
addEventListener('mousemove', e => seen.moves.push([e.clientX, e.clientY, performance.now()]));
addEventListener('mousedown', e => seen.down = performance.now());
addEventListener('mouseup', e => seen.clicks.push([e.clientX, e.clientY, performance.now() - seen.down]));
addEventListener('keydown', e => seen.keys.push(performance.now()));
</script></body></html>"""

DRIVE = """
import http.server, json, sys, threading, time
sys.path.insert(0, 'scripts')
from playwright.sync_api import sync_playwright
import browser
headers = {}
class Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        headers.update({k.lower(): v for k, v in self.headers.items()})
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
        self.wfile.write(open('page.html', 'rb').read())
    def log_message(self, *args): pass
site = http.server.HTTPServer(('127.0.0.1', 0), Site)
threading.Thread(target=site.serve_forever, daemon=True).start()
with sync_playwright() as pw:
    context = browser.launch(pw)
    page = browser.first_page(context)
    h = browser.Human(page, seed=7)
    began = time.time()
    h.goto(f'http://localhost:{site.server_address[1]}/')  # opens it, then takes a moment to read
    read_for = time.time() - began
    about = page.evaluate('async () => ({langs: navigator.languages, ua: navigator.userAgent, webdriver: navigator.webdriver, '
                          'hints: await navigator.userAgentData.getHighEntropyValues(["platformVersion", "bitness", "fullVersionList"])})')
    h.click('#go')
    h.type('#q', 'pothos 6 inch')
    h.scroll(600)
    # A live login's replay: the owner's own path, click and rhythm.
    browser.replay_moves(page, [[300, 300, 0], [320, 310, 16], [350, 330, 16], [900, 900, 20]])
    browser.replay_click(page, 350, 330, 140)
    browser.replay_typing(page, 'ab', [0, 120])
    print(json.dumps({**page.evaluate('seen'), 'value': page.input_value('#q'), 'scrolled': page.evaluate('scrollY'),
                      'about': about, 'acceptLanguage': headers.get('accept-language'), 'readFor': read_for}))
    browser.close(context)
"""


class PathsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "template/scripts", cls.tmp / "scripts")
        sys.path.insert(0, str(cls.tmp / "scripts"))
        import browser
        cls.b = browser

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(cls.tmp / "scripts"))
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_pointer_path_curves_and_arrives(self):
        for seed in range(30):
            rng = random.Random(seed)
            start = (rng.uniform(0, 1279), rng.uniform(0, 799))
            end = (rng.uniform(0, 1279), rng.uniform(0, 799))
            path = self.b.pointer_path(start, end, rng)
            self.assertEqual((round(path[-1][0], 6), round(path[-1][1], 6)), (round(end[0], 6), round(end[1], 6)))
            self.assertTrue(all(0 <= x < 1280 and 0 <= y < 800 and wait >= 0 for x, y, wait in path))
            self.assertLessEqual(sum(wait for _, _, wait in path), 2000)
            dist = math.hypot(end[0] - start[0], end[1] - start[1])
            if dist > 200:
                self.assertGreaterEqual(len(path), 12)
                # Not a straight line: somewhere it's well off the direct way.
                off = max(abs((end[0] - start[0]) * (start[1] - y) - (start[0] - x) * (end[1] - start[1])) / dist for x, y, _ in path)
                self.assertGreater(off, 3)
                # Slow, fast, slow: the middle step covers more ground than the first.
                steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip([(*start, 0)] + path, path)]
                self.assertGreater(steps[len(steps) // 2], steps[0])
        self.assertEqual(self.b.pointer_path((5, 5), (5, 5)), [(5, 5, 0.0)])

    def test_two_paths_between_the_same_points_differ(self):
        a = self.b.pointer_path((100, 100), (900, 600), random.Random(1))
        b = self.b.pointer_path((100, 100), (900, 600), random.Random(2))
        self.assertNotEqual(a, b)

    def test_typing_is_uneven(self):
        gaps = self.b.typing_gaps("hello there, world", random.Random(3))
        self.assertEqual((len(gaps), gaps[0]), (18, 0.0))
        self.assertTrue(all(g >= 35 for g in gaps[1:]))
        self.assertGreater(len({round(g) for g in gaps}), 10)  # not one fixed delay


@unittest.skipUnless(HAVE_PLAYWRIGHT, "needs Python Playwright")
class PageTest(unittest.TestCase):
    def test_what_the_page_sees(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(REPO / "template/scripts", tmp / "scripts")
            (tmp / "page.html").write_text(PAGE)
            out = subprocess.run([sys.executable, "-c", DRIVE], cwd=tmp, capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr)
            seen = json.loads(out.stdout.strip().splitlines()[-1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        human_click, field_click, replayed = seen["clicks"]
        # The pointer travelled to the button (many positions on the way), and landed inside
        # it but not on its exact centre (800, 530); the button was held down for a moment.
        before = [m for m in seen["moves"] if m[2] < seen["moves"][-1][2]]
        self.assertGreater(len(before), 20)
        self.assertTrue(700 <= human_click[0] <= 900 and 500 <= human_click[1] <= 560)
        self.assertNotEqual((round(human_click[0]), round(human_click[1])), (800, 530))
        self.assertGreater(human_click[2], 30)
        self.assertTrue(100 <= field_click[0] <= 500 and 100 <= field_click[1] <= 140)
        # Typed key by key, at an uneven pace.
        self.assertEqual(seen["value"], "pothos 6 inch")
        gaps = [b - a for a, b in zip(seen["keys"][:13], seen["keys"][1:13])]
        self.assertGreater(max(gaps) - min(gaps), 20)
        self.assertEqual(seen["scrolled"], 600)
        # The replay: the owner's path ends where they clicked, held about as long as they held it.
        self.assertEqual((replayed[0], replayed[1]), (350, 330))
        self.assertTrue(120 <= replayed[2] <= 260, replayed[2])
        self.assertIn([320, 310], [m[:2] for m in seen["moves"]])
        self.assertGreater(seen["keys"][-1] - seen["keys"][-2], 100)
        # It took a moment to read the page it opened.
        self.assertGreater(seen["readFor"], 0.4)
        # What a desktop Chrome says about itself: its languages, and the system details sites may ask for.
        about = seen["about"]
        self.assertEqual((about["langs"], seen["acceptLanguage"]), (["en-US", "en"], "en-US,en;q=0.9"))
        self.assertNotIn("Headless", about["ua"])
        self.assertFalse(about["webdriver"])
        self.assertRegex(about["hints"]["platformVersion"], r"^\d+\.\d+")
        self.assertEqual(about["hints"]["bitness"], "64")
        self.assertTrue(about["hints"]["fullVersionList"])


if __name__ == "__main__":
    unittest.main()
