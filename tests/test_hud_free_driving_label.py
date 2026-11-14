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


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class H12_Overlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = F.harness_init()
        if env:
            raise unittest.SkipTest("the real Overlay can not run here: " + env)
        cls.vec = F.load_vectors()

    @classmethod
    def tearDownClass(cls):
        left = F.harness_leftovers()
        if left:
            raise AssertionError("the run wrote into the redirected profile: %s" % left)

    MACHINE = {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}
    FREE = {"mode": False, "finished": False}
    RUN = {"mode": True, "finished": False}
    DONE = {"mode": True, "finished": True}

    def label(self, sc, own, official, time_ms):
        sc.step({"loc": 500.0, "machine": dict(self.MACHINE), "official": official, "own": own, "time_ms": time_ms})
        return sc.hud["label"]

    def labels_over_phases(self, sc, own, official):
        return {self.label(sc, own, official, t) for t in (T_PHASE_TIMING, T_PHASE_OTHER, T_PHASE_TIMING + 10000, T_PHASE_OTHER + 10000)}

    # ---- HUD-1 ----
    def test_HUD_1_R1_R3_R4_free_driving_stop_station_shows_only_stop(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L5P")
            sc.o.setting_start_idx, sc.o.setting_end_idx = 0, 4
            self.assertEqual(self.labels_over_phases(sc, self.FREE, {"state": "K", "index": 1}), {STOP})     # a timing station (the default): still no timing label

    def test_HUD_1_R2_R3_R4_free_driving_pass_station_shows_only_pass(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L5P")
            sc.o.setting_start_idx, sc.o.setting_end_idx = 0, 4
            self.step_free_to_pass_station(sc)
            self.assertEqual(self.labels_over_phases(sc, self.FREE, {"state": "K", "index": 2}), {PASS})

    def step_free_to_pass_station(self, sc):
        self.label(sc, self.FREE, {"state": "K", "index": 2}, T_PHASE_TIMING)

    def test_HUD_1_R5_scoring_timing_stop_station_alternates(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            sc.o.setting_start_idx, sc.o.setting_end_idx = 0, 3
            self.assertEqual(self.label(sc, self.RUN, {"state": "K", "index": 2}, T_PHASE_TIMING), TIMING)
            self.assertEqual(self.label(sc, self.RUN, {"state": "K", "index": 2}, T_PHASE_OTHER), STOP)
            self.assertTrue(sc.o.hud_target_timing)

    def test_HUD_1_R7_scoring_non_timing_station_does_not_blink(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            sc.o.setting_start_idx, sc.o.setting_end_idx = 0, 3
            sc.o.active_next_sta_timing = False
            self.assertEqual(self.labels_over_phases(sc, self.RUN, {"state": "K", "index": 2}), {STOP})

    def test_HUD_1_R8_R9_after_finish_or_abort_free_driving_display_returns(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            sc.o.setting_start_idx, sc.o.setting_end_idx = 0, 3
            self.assertEqual(self.label(sc, self.RUN, {"state": "K", "index": 2}, T_PHASE_TIMING), TIMING)
            self.assertEqual(self.labels_over_phases(sc, self.DONE, {"state": "K", "index": 2}), {STOP})      # finished
            self.assertEqual(self.labels_over_phases(sc, self.FREE, {"state": "K", "index": 2}), {STOP})      # aborted (the scoring mode is off)

    def test_HUD_1_R10_a_restarted_run_alternates_again(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            sc.o.setting_start_idx, sc.o.setting_end_idx = 0, 3
            self.assertEqual(self.labels_over_phases(sc, self.FREE, {"state": "K", "index": 2}), {STOP})
            self.assertEqual(self.label(sc, self.RUN, {"state": "K", "index": 2}, T_PHASE_TIMING), TIMING)
            self.assertEqual(self.label(sc, self.RUN, {"state": "K", "index": 2}, T_PHASE_OTHER), STOP)



if __name__ == "__main__":
    unittest.main(verbosity=2)
