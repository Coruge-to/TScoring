"""Speed limit advance probe (speed_limit_probe.py; Owner 2026-11-17): an observation tool that records the judgement of the red / blue blink warnings as a time series.

Contract:
  P-1  OFF by default: without the flag file nothing is created and nothing is written
  P-2  ON while the flag file exists: one CSV (header = COLUMNS, every row has as many fields), the red warning of a ground limit shows up with the numbers the judgement used
       (red value, distance, deceleration distance, warning distance, the speed the distance was calculated for); removing the flag closes the file
  P-3  the judgement is NOT changed: the same telemetry gives the same flash state with the probe off and on (the real Overlay and scoring_logic, as tests/si1_flash_probe.py runs them)
  P-4  nothing it does can raise into the caller (an object without attributes, an unwritable directory)
  P-5  the evaluation record carries warn_dist and calc_v and scoring_logic calls the probe right after the existing debug log (source pin)
"""
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import speed_limit_probe as P  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None


class FakeClock(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Probe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="limitprobe")
        self.saved = (P._probe.directory, P._probe.clock)
        P._probe.close()
        P._probe.directory = self.tmp
        P._probe.next_check = 0.0
        self.clock = FakeClock()
        P._probe.clock = self.clock

    def tearDown(self):
        P._probe.close()
        P._probe.directory, P._probe.clock = self.saved
        P._probe.next_check = 0.0
        shutil.rmtree(self.tmp, ignore_errors=True)

    def flag(self, on):
        path = os.path.join(self.tmp, P.FLAG_NAME)
        if on:
            open(path, "w").close()
        elif os.path.exists(path):
            os.remove(path)

    def csvs(self):
        return [f for f in os.listdir(self.tmp) if f.endswith(".csv")]

    def test_P_1_off_by_default(self):
        class O(object):
            bve_location = 100.0
        for _ in range(5):
            self.clock.t += 3.0
            P.note(O(), 36000.0, 0.016, False, 70.0, 0.0, [], [], None, None, 0.0)
        self.assertEqual(os.listdir(self.tmp), [])

    @unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
    def test_P_2_and_P_3_a_ground_red_is_recorded_with_the_judgement_numbers_and_the_judgement_is_unchanged(self):
        import test_ground_limits_si1 as G
        seqs = {"red": [G.line(1500 + 25 * i, 70, 70, 70, "2500.0=60.0", t=36000000 + 1000 * i) for i in range(40)]}
        off = G.run_probe(seqs)["red"]
        self.assertEqual(self.csvs(), [])
        self.flag(True)
        P._probe.next_check = 0.0
        ticks = [1000.0]

        def stepping_clock():                                  # every call of the probe is 100 ms later than the one before (a drive of 40 steps)
            ticks[0] += 0.1
            return ticks[0]
        P._probe.clock = stepping_clock
        on = G.run_probe(seqs)["red"]
        P._probe.close()
        self.assertEqual(off, on, "P-3: the probe must not change what the HUD shows")
        files = self.csvs()
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.tmp, files[0]), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0].split(","), list(P.COLUMNS))
        self.assertGreater(len(lines), 5)
        rows = [dict(zip(P.COLUMNS, l.split(","))) for l in lines[1:]]
        for l in lines[1:]:
            self.assertEqual(len(l.split(",")), len(P.COLUMNS), l)
        red = [r for r in rows if r["color"] == "RED"]
        self.assertTrue(red, "the red warning of the 60 km/h limit at 2500 m must appear in the record")
        r = red[0]
        self.assertEqual(float(r["red_val"]), 60.0)
        self.assertEqual(r["blink_active"], "1")
        for k in ("red_dist_m", "red_decel_m", "red_warn_m", "red_calc_v", "red_urgency_m"):
            self.assertNotEqual(r[k], "", k)
        self.assertLessEqual(float(r["red_dist_m"]), float(r["red_warn_m"]) + 1e-6, "a warning is shown only inside the warning distance")
        # the first row of the recording is before any warning, the speed and the position are the telemetry's
        self.assertEqual(float(rows[0]["speed_kmh"]), 70.0)

    def test_P_2b_removing_the_flag_closes_the_file(self):
        class O(object):
            bve_location = 1.0
            bve_speed = 10.0
        self.flag(True)
        P.note(O(), 1.0, 0.016, False, 70.0, 0.0, [], [], None, None, 0.0)
        self.assertIsNotNone(P._probe.file)
        self.flag(False)
        self.clock.t += P.CHECK_EVERY_S + 0.1
        P.note(O(), 2.0, 0.016, False, 70.0, 0.0, [], [], None, None, 0.0)
        self.assertIsNone(P._probe.file)

    def test_P_2c_rows_are_rate_limited_but_a_change_of_the_shown_state_is_written_at_once(self):
        class O(object):
            bve_location = 1.0
            bve_speed = 10.0
            disp_limit = 70.0
            limit_color = (255, 255, 255)
            blink_active = False
        self.flag(True)
        o = O()
        P.note(o, 1.0, 0.016, False, 70.0, 0.0, [], [], None, None, 0.0)
        for i in range(20):                                    # 20 calls inside one millisecond-scale: only the first row
            self.clock.t += 0.001
            P.note(o, 1.0 + i * 0.001, 0.016, False, 70.0, 0.0, [], [], None, None, 0.0)
        self.assertEqual(P._probe.rows, 1)
        o.limit_color = (200, 20, 20)
        o.blink_active = True
        self.clock.t += 0.001
        P.note(o, 1.1, 0.016, False, 70.0, 0.0, [], [], {"val": 60.0, "loc": 2500.0, "dist": 900.0, "decel_dist": 800.0, "urgency": 100.0, "type": "map", "warn_dist": 1000.0, "calc_v": 70.0}, None, 1.5)
        self.assertEqual(P._probe.rows, 2, "the state change (white -> red blink) is written without waiting for the interval")
        self.clock.t += 0.06
        P.note(o, 1.2, 0.016, False, 70.0, 0.0, [], [], None, None, 0.0)
        self.assertEqual(P._probe.rows, 3)

    def test_P_4_nothing_raises(self):
        self.flag(True)
        P.note(object(), None, None, None, None, None, None, None, None, None, None)
        P.note(None, "x", "y", 1, 2, 3, [("bad",)], [{"val": object()}], {"val": 1}, {"val": 2}, "z")
        # an unwritable directory (a file where the directory should be)
        bad = os.path.join(self.tmp, "afile")
        open(bad, "w").close()
        P._probe.close()
        P._probe.directory = bad
        P._probe.next_check = 0.0
        P.note(object(), 1.0, 0.016, False, 70.0, 0.0, [], [], None, None, 0.0)

    def test_P_5_the_evaluation_carries_warn_dist_and_calc_v_and_the_probe_is_called_after_the_debug_log(self):
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("'warn_dist': warn_dist, 'calc_v': calc_v", src)
        self.assertIn("import speed_limit_probe\n", src)
        i = src.index("    write_limit_debug_log(\n        self,")
        j = src.index("    speed_limit_probe.note(self, current_time, dt, is_waiting_tail, target_val, target_loc, future_targets, active_reds, active_red, active_blue, blink_cycle if self.blink_active else 0.0, blue_suppressed)")
        self.assertGreater(j, i)
        self.assertLess(j - i, 600, "right after the existing debug log")
        self.assertIsNone(re.search(r"speed_limit_probe\.[a-z_]+\(", src[:i]), "no other call of the probe before the judgement is complete")


if __name__ == "__main__":
    unittest.main()
