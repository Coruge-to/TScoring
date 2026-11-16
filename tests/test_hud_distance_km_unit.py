"""HUD remaining distance, case C (Owner 2026-11-16): the "km" unit is drawn SMALL in the slot of " m".

Defect that opened this: on the real Windows Qt platform one HUD digit is 28 px, so "-999.99 km" (10 characters, 280 px) plus the label "停車" (108 px) and the 6 px outline did not fit the
380 px label+value width (LABEL_WIDTH): the "-" touched / overlapped the label in every display size (the HUD is one logical layout scaled as a whole).

Contract (display only: the text of the distance, its rounding, its sign and its colour are NOT changed; test_hud_distance_sign.py keeps pinning them):
  C-1  the display text is unchanged: "9999.9 m", "10.000 km", "99.999 km", "100.00 km", "999.99 km" (the fixture reads the number and the unit back as one text)
  C-2  an "m" distance is ONE text right-aligned at the right edge (as before); a "km" distance is TWO texts: the digits right-aligned at (right edge - advance of " m") and the unit "km",
       right-aligned at the right edge, in a font of DIST_KM_UNIT_POINT_SIZE (smaller than FONT_SIZE_UI), in the SAME colour as the digits
  C-3  therefore the digits of "9999.9 m" and of "10.000 km" end at the same x, and the km unit ends where the m ends
  C-4  the widest value ("-999.99 km") fits: its digits, the slot of " m", the label and both outlines are inside LABEL_WIDTH (measured with the real font metrics of the Overlay)
  C-5  LABEL_WIDTH is not widened for this (the layout of every other row is untouched)
  C1   the digit rule of the m range changes its edge from 4.95 m to 9.995 m (two decimals below 10 m): class C1_TwoDecimalsBelow10m
  C3   case C2 / C3-d: small km/h, decimal point and slash tuned, inner kerning of the brake text, default-text threshold: class C3_UnitsGlyphsAndHandleKerning
"""
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
T_PHASE_TIMING = 36000000


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class C_KmUnit(unittest.TestCase):
    MACHINE = {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}
    RUN = {"mode": True, "finished": False}

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

    def draw(self, sc, d):
        """Step the HUD to the remaining distance d and return (display text, the draw_text_with_stroke calls of that frame as (text, font, color, x, align))."""
        calls = []
        original = sc.hud_ui.draw_text_with_stroke

        def capture(painter, text, font, color, outline, x, y, align="left", *a, **k):
            calls.append((text, font, color, x, align))
            return original(painter, text, font, color, outline, x, y, align, *a, **k)

        sc.hud_ui.draw_text_with_stroke = capture
        try:
            sc.step({"loc": 1000.0 - d, "machine": dict(self.MACHINE), "official": {"state": "K", "index": 2}, "own": self.RUN, "time_ms": T_PHASE_TIMING})
        finally:
            sc.hud_ui.draw_text_with_stroke = original
        return sc.hud["dist"], calls

    @staticmethod
    def right_edge(sc):
        import config
        scale = sc.o.height() / config.BASE_SCREEN_H
        return sc.o.width() / scale - config.MARGIN_RIGHT

    def test_C_1_the_display_text_is_unchanged(self):
        cases = ((9999.949, "9999.9 m"), (9999.95, "10.000 km"), (12345.678, "12.346 km"), (99999.499, "99.999 km"), (99999.5, "100.00 km"), (999990.0, "999.99 km"),
                 (-9999.949, "-9999.9 m"), (-9999.95, "-10.000 km"), (-99999.5, "-100.00 km"), (-999990.0, "-999.99 km"))
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            for d, want in cases:
                self.assertEqual(self.draw(sc, d)[0], want, "d=%r" % d)

    def test_C_2_m_is_one_text_and_km_is_digits_plus_a_small_unit_in_the_same_colour(self):
        import config
        from PyQt6.QtGui import QFontMetrics
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            right = self.right_edge(sc)
            slot = QFontMetrics(sc.o.font_ui).horizontalAdvance(" m")
            text, calls = self.draw(sc, 9999.949)
            row = [c for c in calls if c[0] == "9999.9 m"]
            self.assertEqual(len(row), 1, text)                                          # ONE text, as before
            self.assertEqual((row[0][3], row[0][4]), (right, "right"))
            self.assertFalse(any(c[0] == "km" for c in calls))
            for d in (9999.95, -9999.95, 99999.5, -999990.0):
                text, calls = self.draw(sc, d)
                number, unit = text.rsplit(" ", 1)
                self.assertEqual(unit, "km", text)
                i = next(k for k, c in enumerate(calls) if c[0] == "km")
                digits, small = calls[i - 1], calls[i]
                self.assertEqual(digits[0], number, text)
                self.assertEqual((digits[3], digits[4]), (right - slot, "right"), text)  # the digits end where the digits of the m rows end
                self.assertEqual((small[3], small[4]), (right, "right"), text)           # the unit ends at the right edge, like the m
                self.assertEqual(small[1].pointSize(), config.DIST_KM_UNIT_POINT_SIZE, text)
                self.assertLess(small[1].pointSize(), config.FONT_SIZE_UI)
                self.assertEqual(digits[1].pointSize(), config.FONT_SIZE_UI)             # the digits keep the full size
                self.assertEqual(small[2], digits[2], "the unit has the colour of the digits: " + text)

    def test_C_3_the_digits_of_the_m_rows_and_the_km_rows_end_at_the_same_x(self):
        from PyQt6.QtGui import QFontMetrics
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            right = self.right_edge(sc)
            slot = QFontMetrics(sc.o.font_ui).horizontalAdvance(" m")
            _t, m_calls = self.draw(sc, 9999.949)
            m_row = next(c for c in m_calls if c[0] == "9999.9 m")
            m_digits_end = m_row[3] - slot                                               # "9999.9 m" is right-aligned: its digits end one slot left of the right edge
            _t, km_calls = self.draw(sc, 9999.95)
            km_digits = next(c for k, c in enumerate(km_calls) if k + 1 < len(km_calls) and km_calls[k + 1][0] == "km")
            self.assertEqual(km_digits[3], m_digits_end)

    def test_C_4_the_widest_value_fits_between_the_label_and_the_right_edge(self):
        import config
        from PyQt6.QtGui import QFontMetrics
        with F.Scene(self.vec) as sc:
            fm = QFontMetrics(sc.o.font_ui)
            widest = fm.horizontalAdvance("-999.99") + fm.horizontalAdvance(" m")        # digits + the slot of " m" (the km unit sits inside the slot)
            need = fm.horizontalAdvance("停車") + widest + config.OUTLINE_WIDTH            # the label, the value and the outline (3 px each side) must not touch
            self.assertLessEqual(need, config.LABEL_WIDTH, "label %d + value %d + outline %d > LABEL_WIDTH %d" % (fm.horizontalAdvance("停車"), widest, config.OUTLINE_WIDTH, config.LABEL_WIDTH))
            self.assertLess(fm.horizontalAdvance("km") * config.DIST_KM_UNIT_POINT_SIZE / config.FONT_SIZE_UI, fm.horizontalAdvance(" m") + 1)   # the small km is as wide as the slot or less

    def test_C_5_the_label_width_is_364(self):
        # case C3-d (Owner 2026-11-16): the km / km/h units are small, so the label+value width is 364 (380 + 12 - 28), not widened
        import config
        self.assertEqual(config.LABEL_WIDTH, 364)

    def test_C_6_the_unit_size_is_30_and_the_units_stay_inside_their_slots(self):
        # case C4-30 (Owner 2026-11-17): the km / km/h units are 30 (was 28); the digits keep their place, the units stay inside the slots of " m" / " km/h"
        import config
        from PyQt6.QtGui import QFont, QFontMetrics
        self.assertEqual(config.DIST_KM_UNIT_POINT_SIZE, 30)
        with F.Scene(self.vec) as sc:
            unit_font = QFont(sc.o.font_ui)
            unit_font.setPointSize(config.DIST_KM_UNIT_POINT_SIZE)
            ufm, fm = QFontMetrics(unit_font), QFontMetrics(sc.o.font_ui)
            self.assertLess(ufm.horizontalAdvance("km"), fm.horizontalAdvance(" m"))
            self.assertLess(ufm.horizontalAdvance("km/h"), fm.horizontalAdvance(" km/h") - fm.horizontalAdvance("0"))


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class C1_TwoDecimalsBelow10m(unittest.TestCase):
    """Case C1 (Owner 2026-11-16): the digit rule of the m range changes its edge from 4.95 m to 9.995 m: below 10 m two decimals (up to 9.99 m), from 10 m one decimal (10.0 m, never 10.00 m).
    Nothing else of the text changes (the sign, the km rows, the 0.00 m range: test_hud_distance_sign.py)."""
    MACHINE = {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}
    RUN = {"mode": True, "finished": False}

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

    def dist(self, sc, d):
        sc.step({"loc": 1000.0 - d, "machine": dict(self.MACHINE), "official": {"state": "K", "index": 2}, "own": self.RUN, "time_ms": T_PHASE_TIMING})
        return sc.hud["dist"]

    def test_C1_1_the_edge_is_9_995_m_for_both_signs(self):
        cases = ((4.94, "4.94 m"), (4.949, "4.95 m"), (4.95, "4.95 m"), (5.0, "5.00 m"), (6.0, "6.00 m"), (9.0, "9.00 m"), (9.949, "9.95 m"), (9.95, "9.95 m"), (9.99, "9.99 m"),
                 (9.994, "9.99 m"), (9.9949, "9.99 m"), (9.995, "10.0 m"), (9.999, "10.0 m"), (10.0, "10.0 m"), (10.04, "10.0 m"), (10.06, "10.1 m"), (50.0, "50.0 m"), (9999.949, "9999.9 m"))
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            for x, want in cases:
                self.assertEqual(self.dist(sc, x), want, "d=%r" % x)
                self.assertEqual(self.dist(sc, -x), "-" + want, "d=%r" % -x)

    def test_C1_2_the_text_never_shows_10_00_m_and_never_goes_backwards_across_the_edge(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            seen = []
            for k in range(0, 3001):
                x = 9.90 + k * 0.0001
                text = self.dist(sc, x)
                self.assertNotEqual(text, "10.00 m", "x=%r" % x)
                seen.append(float(text.split(" ")[0]))
            self.assertEqual(seen, sorted(seen))                                         # 9.90 ... 9.99, then 10.0 ...: non-decreasing


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class C3_UnitsGlyphsAndHandleKerning(unittest.TestCase):
    """Case C2 / C3-d (Owner 2026-11-16): the km/h of the speed and the limit are small units too (digits one digit to the right), the decimal point is centred in its cell and the slash is as tall as the k
    (utils.glyph_tune_of), the brake text of the handle row is kerned INSIDE a text (degree sign, full-width and half-width brackets; utils.kerned_text_layout / kerned_text_width), and the handle row
    keeps the author's text up to a shrink ratio of HANDLE_DEFAULT_TEXT_RATIO. Every expectation is derived from the real font metrics of the Overlay (the real Windows platform differs from offscreen)."""
    MACHINE = {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}
    RUN = {"mode": True, "finished": False}

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

    def frame(self, sc, speed, limit):
        calls = []
        original = sc.hud_ui.draw_text_with_stroke

        def capture(painter, text, font, color, outline, x, y, align="left", *a, **k):
            calls.append((text, font, color, x, align, dict(k)))
            return original(painter, text, font, color, outline, x, y, align, *a, **k)

        sc.hud_ui.draw_text_with_stroke = capture
        try:
            sc.step({"loc": 1000.0 - 7.53, "machine": dict(self.MACHINE), "official": {"state": "K", "index": 2}, "own": self.RUN, "time_ms": 36000000, "speed": speed,
                     "set_attrs": {"effective_limit": limit, "disp_limit": limit, "blink_active": False}})
        finally:
            sc.hud_ui.draw_text_with_stroke = original
        return calls

    def test_C3_1_kmh_is_a_small_unit_and_the_digits_end_one_digit_right_of_the_old_place(self):
        import config
        from PyQt6.QtGui import QFontMetrics
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            fm = QFontMetrics(sc.o.font_ui)
            right = C_KmUnit.right_edge(sc)
            slot = fm.horizontalAdvance(" km/h") - fm.horizontalAdvance("0")          # the old slot was " km/h": one digit less
            calls = self.frame(sc, 53.0, 130.0)
            units = [i for i, c in enumerate(calls) if c[0] == "km/h"]
            self.assertEqual(len(units), 2, [c[0] for c in calls])                   # the speed row and the limit row
            self.assertEqual([calls[i - 1][0] for i in units], ["53.0", "130"])
            for i in units:
                digits, unit = calls[i - 1], calls[i]
                self.assertEqual((digits[3], digits[4]), (right - slot, "right"))
                self.assertEqual((unit[3], unit[4]), (right, "right"))
                self.assertEqual(unit[1].pointSize(), config.DIST_KM_UNIT_POINT_SIZE)
                self.assertEqual(digits[1].pointSize(), config.FONT_SIZE_UI)
                self.assertEqual(unit[2], digits[2])
                self.assertTrue(digits[5].get("tune_glyphs") and unit[5].get("tune_glyphs"), "the value rows are drawn with the glyph tune")

    def test_C3_2_the_decimal_point_is_centred_and_the_slash_is_as_tall_as_the_k(self):
        import utils
        from PyQt6.QtGui import QFontMetrics
        with F.Scene(self.vec) as sc:
            for font in (sc.o.font_ui,):
                fm = QFontMetrics(font)
                tune = utils.glyph_tune_of(font)
                zero, dot, k, slash = fm.tightBoundingRect("0"), fm.tightBoundingRect("."), fm.tightBoundingRect("k"), fm.tightBoundingRect("/")
                zero_centre = zero.x() + zero.width() / 2.0
                self.assertLessEqual(abs(dot.x() + dot.width() / 2.0 + tune["dot_dx"] - zero_centre), 0.51, "the decimal point sits on the ink centre of the digits")
                self.assertGreater(tune["dot_dx"], 0)
                scaled_height = slash.height() * tune["slash_scale"]
                self.assertLessEqual(abs(scaled_height - k.height()), 1.01, "the slash is as tall as the k")
                self.assertLessEqual(tune["slash_scale"], 1.0)
                slash_bottom = (slash.y() + slash.height()) * tune["slash_scale"] + tune["slash_ty"]
                self.assertLessEqual(abs(slash_bottom - (k.y() + k.height())), 0.51, "the slash stands on the bottom of the k")

    def test_C3_3_the_tuned_text_path_keeps_the_cells_of_the_characters(self):
        import utils
        from PyQt6.QtGui import QFontMetrics
        with F.Scene(self.vec) as sc:
            font = sc.o.font_ui
            fm = QFontMetrics(font)
            plain = utils.tuned_text_path(font, fm, "0123", 0, 0).boundingRect()
            from PyQt6.QtGui import QPainterPath
            reference = QPainterPath()
            reference.addText(0, 0, font, "0123")
            self.assertEqual((round(plain.x(), 2), round(plain.width(), 2)), (round(reference.boundingRect().x(), 2), round(reference.boundingRect().width(), 2)), "text without . or / is drawn as before")

    def test_C3_4_the_inner_kerning_of_the_brake_text(self):
        import main
        import utils
        from PyQt6.QtGui import QFontMetrics
        with F.Scene(self.vec) as sc:
            fm = QFontMetrics(sc.o.font_ui)
            ko = main.KERNING_OFFSETS

            def width(s):
                return utils.kerned_text_width(s, fm, ko)

            def adv(s):
                return fm.horizontalAdvance(s)
            # text without a kerned character: the old end-of-text rule (the advance minus the cut of the LAST character), unchanged
            for s in ("OFF", "ゆるめ", "電制3", "常用5", "EB", "70°", "ブレーキメ", "メ", "切"):
                want = adv(s) - ko.get(s[-1], 0)
                self.assertEqual(width(s), want, s)
            # a degree sign / a full-width closing bracket INSIDE a text is cut like at its end; the half-width pair is cut by 3 px anywhere; the full-width opening bracket loses its left blank
            self.assertEqual(width("70°(電制3)"), adv("70°(電制3)") - ko["°"] - 3 - ko[")"], "degree sign inside, ( by 3 on the left, ) by 3 on the right")
            self.assertEqual(width("A）B"), adv("A）B") - ko["）"])
            self.assertEqual(width("（電制３）"), adv("（電制３）") - utils.KERN_LEFT_OFFSETS["（"] - ko["）"])
            self.assertEqual(width("(A)"), adv("(A)") - utils.KERN_LEFT_OFFSETS["("] - ko[")"])
            self.assertEqual(ko[")"], 3)
            self.assertEqual(utils.KERN_LEFT_OFFSETS["("], 3)
            # メ is an END-of-text rule only (Owner: only the degree sign and the brackets move inside)
            self.assertEqual(width("メA"), adv("メA"))
            layout = utils.kerned_text_layout("70°(電制3)", fm, ko)
            self.assertIsNotNone(layout)
            positions, total = layout
            self.assertEqual(len(positions), len("70°(電制3)"))
            self.assertEqual(positions, sorted(positions), "the glyphs keep their order")
            self.assertEqual(total, width("70°(電制3)"))
            self.assertIsNone(utils.kerned_text_layout("電制3", fm, ko), "a text without a kerned character keeps the old layout")

    def test_C3_5_the_default_text_threshold_keeps_the_author_text_up_to_491_px_at_364(self):
        import config
        self.assertEqual(config.HANDLE_DEFAULT_TEXT_RATIO, 0.74)

        def default_text(width_px):
            return min(1.0, config.LABEL_WIDTH / width_px) < config.HANDLE_DEFAULT_TEXT_RATIO
        self.assertFalse(default_text(491))
        self.assertTrue(default_text(492))
        self.assertFalse(default_text(300))                                          # an author text that fits is never replaced


if __name__ == "__main__":
    unittest.main(verbosity=2)
