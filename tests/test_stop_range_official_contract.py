"""Stop range = the BVE official contract (Owner 2026-11-15). The BVE 5 and BVE 6 conductor judge the stop range on RAW doubles as a half-open interval (static analysis of both BveTs.exe, identical):
    in range  =  v + margin1 <= loc < v + margin2          (v = stop position, loc = train position)
    in terms of the TScoring distance d = v - loc:   -margin_f < d <= margin_b      (the overrun end d == -margin_f is OUT, the short end d == +margin_b is IN)
Colour rule of the HUD distance: in range = green (scored); short of the range = white (not scored); beyond the overrun end = red (not scored). The display is rounded to 0.01 m, the judgement never is, so
"2.00" may be white or green and "-2.00" may be green or red. Display only + the python judgements; the C# senders, the Caller and the protocol are not touched.

  A  static: no judgement of the author-defined range keeps the overrun end inside any more (`-margin_f <= ...`)
  B  apply_stop_score (the scored stop position) / turnback_train_state.in_range (the re-stop wait): the boundary values
  C  the HUD distance colour of the real Overlay at the boundary values (PyQt6 needed)
"""
import importlib.util
import os
import re
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import scoring_logic as S  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None
OLD_FORM = re.compile(r"-\s*(self\.)?(bve_|hud_target_)?margin_f\s*<=")


class A_NoClosedOverrunEnd(unittest.TestCase):
    def test_no_judgement_keeps_the_overrun_end_inside(self):
        for name in ("scoring_logic.py", "hud_ui.py", "pseudo_turnback_machine.py", "main.py", "managed_input.py"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
                code = fh.read()
            hits = [m.group(0) for m in OLD_FORM.finditer(code)]
            self.assertEqual(hits, [], name)
            # the multi-line form: `-self.bve_margin_f` on one line, `<= d` on the next
            self.assertIsNone(re.search(r"-self\.bve_margin_f\s*\n\s*<=", code), name)


class B_Judgements(unittest.TestCase):
    def score_of(self, d, margin=0.5):
        points = []
        original = S.add_score_popup
        S.add_score_popup = lambda self, add, *a, **k: points.append(add)
        try:
            stub = types.SimpleNamespace(is_scoring_mode=True, is_stopped_out_of_range=False, bve_margin_f=margin, bve_margin_b=margin)
            zero = S.apply_stop_score(stub, d, 100.0)
        finally:
            S.add_score_popup = original
        return zero, points

    def test_R1_the_overrun_end_exactly_is_out_of_range_and_scores_nothing(self):
        self.assertEqual(self.score_of(-0.5), (False, []))

    def test_R2_just_inside_the_overrun_end_is_scored(self):
        zero, points = self.score_of(-0.4999)
        self.assertEqual(points, [5 * (100 - 50)])

    def test_R3_the_short_end_exactly_is_in_range_and_scored(self):
        zero, points = self.score_of(0.5)
        self.assertEqual(points, [250])

    def test_R4_just_beyond_the_short_end_is_out_of_range(self):
        self.assertEqual(self.score_of(0.5000001), (False, []))

    def test_R5_the_zero_centimetre_stop_and_a_plain_stop_are_unchanged(self):
        self.assertEqual(self.score_of(0.0), (True, [500]))
        self.assertEqual(self.score_of(0.004), (True, [500]))
        self.assertEqual(self.score_of(-0.004), (True, [500]))
        self.assertEqual(self.score_of(0.3)[1], [5 * (100 - 30)])

    def restop_in_range(self, location, a_position=100.0, mf=0.5, mb=0.5):
        stub = types.SimpleNamespace(bve_speed=0.0, bve_location=location, turnback_machine=types.SimpleNamespace(stop_range=(a_position, mf, mb)))
        return S.turnback_train_state(stub)[1]

    def test_R6_the_restop_wait_uses_the_same_half_open_range(self):
        self.assertFalse(self.restop_in_range(100.5))      # d = -0.5: the overrun end, out
        self.assertTrue(self.restop_in_range(100.4999))    # d just inside
        self.assertTrue(self.restop_in_range(99.5))        # d = +0.5: the short end, in
        self.assertFalse(self.restop_in_range(99.4999))    # d just beyond the short end, out


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class C_HudColour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import official_target_wire_fixture as F
        cls.F = F
        env = F.harness_init()
        if env:
            raise unittest.SkipTest("the real Overlay can not run here: " + env)
        cls.vec = F.load_vectors()

    @classmethod
    def tearDownClass(cls):
        left = cls.F.harness_leftovers()
        if left:
            raise AssertionError("the run wrote into the redirected profile: %s" % left)

    def colour_of(self, sc, d):
        import config
        drawn = []
        sc.hud_ui.draw_text_with_stroke = lambda painter, text, font, color, *a, **k: drawn.append((text, color))
        sc.step({"loc": 1000.0 - d, "official": {"state": "K", "index": 1, "loc": 1000.0, "mb": 2.0, "mf": 2.0}, "own": {"mode": False, "finished": False}})
        rows = [(tx, co) for tx, co in drawn if tx.endswith(" m") and tx.replace(" m", "").replace("-", "").replace(".", "").isdigit()]
        self.assertEqual(len(rows), 1, rows)
        names = {config.COLOR_N: "green", config.COLOR_B_EMG: "red", config.COLOR_WHITE: "white"}
        return rows[0][0], names[rows[0][1]]

    def test_R7_the_colours_at_the_boundary_values(self):
        with self.F.Scene(self.vec) as sc:
            sc.load_list("L4")
            cases = ((2.01, "2.01 m", "white"), (2.0001, "2.00 m", "white"), (2.0, "2.00 m", "green"), (1.9951, "2.00 m", "green"), (1.99, "1.99 m", "green"), (0.0, "0.00 m", "green"),
                     (-1.99, "-1.99 m", "green"), (-1.9951, "-2.00 m", "green"), (-1.9999, "-2.00 m", "green"), (-2.0, "-2.00 m", "red"), (-2.0001, "-2.00 m", "red"), (-2.0049, "-2.00 m", "red"), (-2.01, "-2.01 m", "red"))
            for d, text, colour in cases:
                self.assertEqual(self.colour_of(sc, d), (text, colour), "d=%r" % d)

    def test_R8_both_colours_exist_for_the_same_displayed_text(self):
        with self.F.Scene(self.vec) as sc:
            sc.load_list("L4")
            self.assertEqual({self.colour_of(sc, d) for d in (2.0001, 2.0)}, {("2.00 m", "white"), ("2.00 m", "green")})
            self.assertEqual({self.colour_of(sc, d) for d in (-1.9999, -2.0)}, {("-2.00 m", "green"), ("-2.00 m", "red")})


if __name__ == "__main__":
    unittest.main(verbosity=2)
