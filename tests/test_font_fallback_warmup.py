"""Phase FW-1 - the fallback-font warm-up (Owner 2026-11-18: the scoring settings page 3/3 is sometimes slow to appear).

The first paint of page 3/3 spent 0.3 s (1.6 s with a busy BVE) in ONE text whose subscript digits (U+2081..U+2083) are missing from the bundled font: Windows
searches a fallback font once per process. utils.warm_font_fallbacks draws those glyphs once at start-up. These tests pin
  (A) the warm-up text covers every subscript digit that any menu text draws,
  (B) the real Overlay calls the warm-up exactly once, with its description font, while it is built,
  (C) the warm-up itself draws without error.
They cannot measure the saving: that needs the real Windows platform plugin (wp3_first_open.py with WP3_QPA=windows in the handoff folder
first-completion-v1-20261118), a measurement and not a pass/fail test.

    C:\\Python314\\python.exe -B -m unittest tests.test_font_fallback_warmup -v
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_QT = importlib.util.find_spec("PyQt6") is not None
SUBSCRIPTS = "".join(chr(c) for c in range(0x2080, 0x209D))          # the Unicode block of subscript digits / signs / letters

_CHILD = r'''
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT_PLACEHOLDER)
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import main

class Signal(object):
    def connect(self, slot):
        pass

class StubUdp(object):
    def __init__(self, parent=None):
        self.readyRead = Signal()
    def bind(self, a, p):
        return True
    def localPort(self):
        return 0
    def hasPendingDatagrams(self):
        return False
    def close(self):
        pass
    def writeDatagram(self, *a):
        return 0

calls = []
real = main.warm_font_fallbacks
main.warm_font_fallbacks = lambda font, *a, **k: (calls.append(font), real(font, *a, **k))[1]
main.QUdpSocket = StubUdp
main.write_desktop_log = lambda *a, **k: None
o = main.Overlay()
print(json.dumps({"calls": len(calls), "is_desc_font": bool(calls) and calls[0] is o.font_desc}))
'''


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


class WarmupText(unittest.TestCase):
    def test_every_subscript_character_drawn_by_the_menus_is_in_the_warm_up_text(self):
        sys.path.insert(0, ROOT)
        import utils
        drawn = set()
        for source in ("menu_ui.py", "main.py", "managed_hud.py", "scoring_logic.py"):
            drawn |= {ch for ch in read(source) if ch in SUBSCRIPTS}
        self.assertTrue(drawn, "the menu sources no longer draw any subscript digit (page 3/3 changed): review FALLBACK_WARM_TEXT and this test")
        missing = sorted(ch for ch in drawn if ch not in utils.FALLBACK_WARM_TEXT)
        self.assertEqual(missing, [], "subscript characters drawn by the menus but absent from utils.FALLBACK_WARM_TEXT: %r" % missing)

    def test_the_warm_up_text_has_the_three_digits_of_the_theoretical_value_line(self):
        sys.path.insert(0, ROOT)
        import utils
        for code in (0x2081, 0x2082, 0x2083):
            self.assertIn(chr(code), utils.FALLBACK_WARM_TEXT)


@unittest.skipUnless(HAS_QT, "PyQt6 is not installed")
class WarmupRuns(unittest.TestCase):
    def test_the_overlay_calls_the_warm_up_once_with_its_description_font(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
        done = subprocess.run([sys.executable, "-B", "-c", _CHILD.replace("ROOT_PLACEHOLDER", repr(ROOT))], capture_output=True, encoding="utf-8",
                              errors="replace", env=env, cwd=ROOT, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-600:])
        result = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(result["calls"], 1)
        self.assertTrue(result["is_desc_font"])

    def test_the_warm_up_draws_without_error(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        code = ("import sys; sys.path.insert(0, %r)\n"
                "from PyQt6.QtGui import QFont\nfrom PyQt6.QtWidgets import QApplication\napp = QApplication([])\n"
                "import utils\nutils.warm_font_fallbacks(QFont('sans-serif', 25, QFont.Weight.Bold))\nprint('ok')\n") % ROOT
        done = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-600:])
        self.assertIn("ok", done.stdout)


if __name__ == "__main__":
    unittest.main()
