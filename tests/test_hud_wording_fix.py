"""HUD Semantics Fix (Owner 2026-11-14): three local display contracts of the Python HUD.

  HUD-0  the red popup says 採点を中断します。 (the menu item 採点を中断する is unchanged; no user-facing 採点を中止します。 is left)
  HUD-1  free driving never shows the timing label (採時): only 停車 or 通過; the 5 s alternation is kept only while a scoring Run is ACTIVE on a timing station
  HUD-2  the sign of the stop distance follows the SAME rounded text it signs (root: the sign was decided by the raw value d < -0.01 while the magnitude was the ROUNDED abs(d),
         so -0.01 < d <= -0.005 showed a positive 0.01 once)

Display only: no score, no stop judgement and no arrival judgement is read or written here (the rest is pinned by the existing suites).
"""
import glob
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import official_target_wire_fixture as F  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None
TIMING, STOP, PASS = "採時", "停車", "通過"
T_PHASE_TIMING = 36000000          # int(t / 5 s) % 2 == 0: the timing phase of the alternation
T_PHASE_OTHER = 36005000           # the other phase


class H0_Wording(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            return fh.read()

    def test_HUD_0_R1_the_menu_item_is_unchanged(self):
        src = self.read("main.py")
        self.assertIn('self.menu_items_on = ["運転を再開する", "採点を中断する", "選択した駅からやり直す", "環境設定"]', src)
        self.assertIn('selected == "採点を中断する"', src)
        self.assertNotIn("採点を中止する", src)

    def test_HUD_0_R2_the_red_popup_says_chudan(self):
        import scoring_logic
        self.assertEqual(scoring_logic.ILLEGAL_MOVE_TEXTS, ("不正な移動が検知されました。", "採点を中断します。"))

    def test_HUD_0_R3_no_user_facing_chushi_wording_is_left(self):
        old = "採点を中止します"
        for path in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn(old, fh.read(), os.path.basename(path))




if __name__ == "__main__":
    unittest.main(verbosity=2)
