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

    # ---- HUD-2 ----
    def dist(self, sc, d):
        sc.step({"loc": 1000.0 - d, "machine": dict(self.MACHINE), "official": {"state": "K", "index": 2}, "own": self.RUN, "time_ms": T_PHASE_TIMING})
        return sc.hud["dist"]

    def test_HUD_2_R1_to_R8_the_sign_follows_the_rounded_text(self):
        cases = ((0.030, "0.03 m"), (0.020, "0.02 m"), (0.0149, "0.01 m"), (0.010, "0.01 m"), (0.0051, "0.01 m"), (0.0049, "0.00 m"), (0.0001, "0.00 m"), (0.0, "0.00 m"),
                 (-0.0001, "0.00 m"), (-0.0049, "0.00 m"), (-0.0051, "-0.01 m"), (-0.006, "-0.01 m"), (-0.0100, "-0.01 m"), (-0.0149, "-0.01 m"), (-0.020, "-0.02 m"), (-0.030, "-0.03 m"))
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            for d, want in cases:
                self.assertEqual(self.dist(sc, d), want, "d=%r" % d)

    def test_HUD_2_R5_symmetry_and_the_0_01_sequence_of_the_recording(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            seq = [self.dist(sc, d) for d in (0.03, 0.02, 0.01, 0.003, -0.004, -0.007, -0.012)]
            self.assertEqual(seq, ["0.03 m", "0.02 m", "0.01 m", "0.00 m", "0.00 m", "-0.01 m", "-0.01 m"])
            for k in range(0, 400):
                d = k / 20000.0 + 0.00003
                pos, neg = self.dist(sc, d), self.dist(sc, -d)
                self.assertEqual(neg, pos if pos == "0.00 m" else "-" + pos, "d=%r" % d)
                self.assertFalse(neg.startswith("-0.00"), "d=%r" % d)

    def test_HUD_2_X1_the_displayed_0_00_and_the_scored_0_cm_are_the_same_range_and_no_exact_zero_is_needed(self):
        # Owner addendum 2026-11-14: HUD "0.00 m" = every raw |d| that '%.2f' rounds to 0.00 (|d| < 0.005, never d == 0.0); the scoring 0 cm = apply_stop_score: x_cm = int(round(abs(round(d, 2)) * 100)) < 1
        # (the SAME exact-double rounding, the same range, one contract); the HUD reads next_loc - location, the scoring p_loc - location (the same sign). Read-only: the scoring function is only CALLED on a stub.
        import types
        import random
        import scoring_logic as S
        points = []
        original = S.add_score_popup
        S.add_score_popup = lambda self, add, *a, **k: points.append(add)
        try:
            stub = types.SimpleNamespace(is_scoring_mode=True, is_stopped_out_of_range=False, bve_margin_f=5.0, bve_margin_b=5.0)
            rng = random.Random(20261114)
            values = [0.0, 1e-12, -1e-12, 0.00499999, -0.00499999, 0.005, -0.005, 0.00500001, -0.00500001, 0.0149, 0.015, -0.015, 0.0250, 0.125, -0.125, 0.995, -0.995, 0.99, -0.99]
            values += [rng.uniform(-1.0, 1.0) for _ in range(300)] + [rng.uniform(-0.02, 0.02) for _ in range(300)]
            with F.Scene(self.vec) as sc:
                sc.load_list("L4")
                for d_req in values:
                    text = self.dist(sc, d_req)
                    d = 1000.0 - (1000.0 - d_req)         # the d the HUD really computes (next_loc - location in doubles); the scoring is called with the same double
                    shown = abs(float(text.split(" ")[0]))
                    del points[:]
                    zero = S.apply_stop_score(stub, d, 100.0)
                    scored_cm = 100 - points[0] // 5 if points else 100
                    self.assertEqual(text == "0.00 m", zero, "d=%r text=%s" % (d, text))                      # the same range: HUD 0.00 m <=> the scored 0 cm
                    self.assertEqual(round(shown * 100), scored_cm, "d=%r text=%s points=%s" % (d, text, points))   # the shown cm are the scored cm
                    self.assertEqual(text.startswith("-"), d < 0 and shown > 0, "d=%r text=%s" % (d, text))
                    self.assertFalse(text.startswith("-0.00"), "d=%r" % d)
        finally:
            S.add_score_popup = original

    def test_HUD_2_R12_units_digits_and_larger_distances_are_unchanged(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            for d, want in ((2.0, "2.00 m"), (-3.0, "-3.00 m"), (-0.5, "-0.50 m"), (50.0, "50.0 m"), (-6.0, "-6.0 m"), (-4.96, "-5.0 m")):
                self.assertEqual(self.dist(sc, d), want, "d=%r" % d)




if __name__ == "__main__":
    unittest.main(verbosity=2)
