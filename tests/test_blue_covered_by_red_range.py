"""The blue "the limit rises" blink is not shown when the point where the limit rises already lies inside the red range of the next lower limit (Owner 2026-11-17, option B).

Why: while the tail of the train is still in the lower zone the HUD blinks the HIGHER limit in blue (tail wait). If the point where the tail clears (the limit really rises) is already inside the warning range of a
LOWER limit ahead, the higher limit can never be used: the red warning for the lower limit starts before / at that point and takes the display over, so the blue only blinks for a moment (or for a long while with no use)
and is replaced by the red. Two live recordings (2026-11-17) showed it: 85 -> 55 (blue 2 blinks, then red 55) and 120 -> 60 (blue 6 blinks, then red 60 from 5.5 m before the limit rises).

Contract:
  B-1  the pure rule (blue_covered_by_red_range): a limit candidate beyond the raise point whose distance from the raise point is within its warning distance covers the blue; none, or one outside the range
       (or one before the raise point), does not
  B-2  120 -> 60 (the geometry of the second recording): no blue at all, the display stays the current limit (white), and the red 60 starts where it started before (the first step inside the warning distance)
  B-3  85 -> 55 (the geometry of the first recording): no blue, the red 55 starts at its warning distance
  B-4  the same tail wait with the lower limit far beyond the raise point (outside the red range): the blue is shown as before
  B-5  without any lower limit ahead the blue is shown as before (test_ground_limits_si1 keeps pinning it); the red is never changed by the rule (only the blue is)
  B-6  source pin: the rule is applied to the blue candidate only, after it is built and before the display reads it
"""
import importlib.util
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HAS_QT = importlib.util.find_spec("PyQt6") is not None


class B_Rule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import scoring_logic
        cls.rule = staticmethod(scoring_logic.blue_covered_by_red_range)

    def ev(self, dist, warn):
        return {"loc": 0.0, "val": 60.0, "dist": dist, "decel_dist": 0.0, "urgency": 0.0, "type": "map", "warn_dist": warn, "calc_v": 90.0}

    def test_B_1_the_rule(self):
        r = self.rule
        self.assertFalse(r([], 200.0))
        self.assertTrue(r([self.ev(623.0, 429.0)], 200.0), "the limit is 423 m beyond the raise point and its warning distance is 429 m")
        self.assertTrue(r([self.ev(629.0, 429.0)], 200.0), "exactly on the edge: 429 <= 429")
        self.assertFalse(r([self.ev(630.0, 429.0)], 200.0), "430 m beyond the raise point: the red range starts just after it (blue, then red: fine)")
        self.assertFalse(r([self.ev(150.0, 429.0)], 200.0), "a limit BEFORE the raise point is not a limit of the raised zone")
        self.assertFalse(r([self.ev(200.0, 429.0)], 200.0), "at the raise point itself it is not beyond it")
        self.assertTrue(r([self.ev(2000.0, 100.0), self.ev(400.0, 429.0)], 200.0), "any candidate may cover it")
        self.assertFalse(r([self.ev(2000.0, 100.0), self.ev(900.0, 429.0)], 200.0))
        self.assertFalse(r([{"dist": 400.0}], 200.0), "a record without a warning distance covers nothing")


def telemetry_steps(G, locs, tail_head_of, limits, train, clear_end, speed, t0=36000000):
    out = []
    for i, loc in enumerate(locs):
        tail, head = tail_head_of(loc)
        clear = max(0.0, clear_end - loc) if head > tail else 0
        out.append(G.line(loc, speed, tail, head, limits, clear=clear, train=train, sig=1000, t=t0 + 500 * i))
    return out


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class B_Behaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_ground_limits_si1 as G
        cls.G = G
        seqs = {}
        # 120 -> 60: the head enters the 120 zone at 80295, the train is 211.7 m long (the tail clears at 80506.7), the 60 limit is at 80930 (the second recording)
        locs2 = [80296.0 + 4 * k for k in range(70)]
        th2 = lambda loc: (90.0, 120.0) if loc < 80506.7 else (120.0, 120.0)
        seqs["b120_60"] = telemetry_steps(G, locs2, th2, "80930.0=60.0_81430.0=120.0_81570.0=85.0", 211.7, 80506.7, 88.0)
        cls.locs2 = locs2
        # 85 -> 55 (the first recording): head at 8475, train 144 m (tail clears at 8619), the 55 limit at 8750
        locs1 = [8476.0 + 4 * k for k in range(60)]
        th1 = lambda loc: (75.0, 85.0) if loc < 8619.0 else (85.0, 85.0)
        seqs["b85_55"] = telemetry_steps(G, locs1, th1, "8750.0=55.0_9000.0=85.0", 144.0, 8619.0, 70.0)
        cls.locs1 = locs1
        # the same 120 zone but the lower limit is far beyond the raise point: outside the red range
        seqs["far"] = telemetry_steps(G, locs2[:40], th2, "81800.0=60.0_82300.0=120.0", 211.7, 80506.7, 88.0)
        # a tail wait with nothing lower ahead (the blue of test_ground_limits_si1)
        seqs["plain"] = [G.line(1010 + i, 40, 50, 90, "", clear=90 - i, sig=100, t=36000000 + 1000 * i) for i in range(40)]
        cls.res = G.run_probe(seqs)

    def first(self, steps, color):
        return next((i for i, s in enumerate(steps) if s["color"] == color), None)

    def test_B_2_120_to_60_has_no_blue_and_the_red_starts_where_it_started(self):
        steps = self.res["b120_60"]
        self.assertTrue(all(s["color"] != "blue" for s in steps), "no blue at all: " + str([(self.locs2[i], s["color"]) for i, s in enumerate(steps) if s["color"] == "blue"][:3]))
        self.assertTrue(all(s["blue"] == "None" for s in steps))
        red = self.first(steps, "red")
        self.assertIsNotNone(red)
        # before the rule the red began at the first step within the warning distance (429 m to 80930): 80504 on this 4 m grid
        self.assertEqual(self.locs2[red], 80504.0)
        # until the red starts the HUD shows the current limit, white
        for i in range(red):
            self.assertEqual((steps[i]["color"], steps[i]["blink"], steps[i]["disp"]), ("white", False, 90.0), self.locs2[i])
        self.assertEqual(steps[red]["red"], "60.0")

    def test_B_3_85_to_55_has_no_blue_and_the_red_starts_at_its_warning_distance(self):
        steps = self.res["b85_55"]
        self.assertTrue(all(s["color"] != "blue" for s in steps))
        red = self.first(steps, "red")
        self.assertIsNotNone(red)
        self.assertLessEqual(8750.0 - self.locs1[red], 249.0)
        self.assertGreater(8750.0 - self.locs1[red - 1], 249.0 - 0.0001, "the first step inside the warning distance")
        self.assertEqual(steps[red]["red"], "55.0")

    def test_B_4_a_lower_limit_far_beyond_the_raise_point_does_not_remove_the_blue(self):
        steps = self.res["far"]
        self.assertIsNotNone(self.first(steps, "blue"))
        b = steps[self.first(steps, "blue")]
        self.assertEqual(b["blue"], "120.0")

    def test_B_5_without_a_lower_limit_the_blue_is_shown(self):
        steps = self.res["plain"]
        self.assertIsNotNone(self.first(steps, "blue"))

    def test_B_6_source_pin(self):
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("def blue_covered_by_red_range(", src)
        i = src.index("    active_blue = {'val': target_val, 'dist': max(1.0, dist_for_blue), 'type': target_type}")
        j = src.index("blue_covered_by_red_range(future_evals, ", i)
        k = src.index("    # 制限速度診断に使用する現在の判定状態を保存する")
        self.assertTrue(i < j < k, "the rule is applied right after the blue candidate is built and before the display reads it")
        self.assertIsNone(re.search(r"active_red\s*=\s*None\s*\n\s*if .*blue_covered", src))


if __name__ == "__main__":
    unittest.main()
