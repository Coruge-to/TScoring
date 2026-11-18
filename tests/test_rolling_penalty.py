"""E-4 (beta requirement list): the ROLLING penalty (転動) itself - a characterization of the CURRENT contract, nothing here changes a line of product code.

Contract (scoring_logic.update_physics_and_scoring, the door-open branch):
  * the door-open edge (bve_door 1, prev_door 0) sets the reference position door_open_loc and starts a rolling event (roll_event_id + 1);
  * while the door stays open the rolling distance is |bve_location - door_open_loc|; every full 0.05 m is ONE step, every step deducts 500;
  * only the steps not yet deducted count (roll_penalty_count); the deduction is shown in ONE popup per rolling event (text "転動 -N", N accumulates; score_details["roll"]);
  * a complete stop after moving (speed 0.0 after speed != 0) ends the event: the next rolling starts a NEW popup (event id + 1);
  * the setting "rolling" OFF stops ONLY this deduction (no popup, no score change); closing the door resets the reference and the count; an official jump is never rolling (test_characterization_sia1).
The default of the setting is ON (it was always on; ON / OFF can be switched before the scoring start: tests/test_initial_defaults_rolling.py).
The product is driven through the REAL update_physics_and_scoring (tests/pt_scene.py).

    C:\\Python314\\python.exe -B -m unittest tests.test_rolling_penalty -v
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TMP = {}
STEP = 0.05
PENALTY = 500
CATEGORY = "転動"


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-roll-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    for k, v in _TMP["saved"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _TMP["dir"].cleanup()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["roll"])
        import config
        import main
        import scoring_logic
        import pt_scene
        cls.cfg, cls.main, cls.S, cls.P = config, main, scoring_logic, pt_scene

    def doors_open_at_a(self, rolling=True):
        """A plain station (no pseudo-turnback pair): the approach, the stop 0.3 m short of the mark, the door-open edge. Returns (scene, reference position)."""
        s = self.P.Scene(self, with_pairs=False)
        o = s.o
        o.pen_roll = bool(rolling)
        o.setting_start_idx, o.setting_end_idx = 0, 4
        o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
        o.bve_next_time = self.P.T0 + 90000
        s.approach("plain")
        s.stop_at(0.3)
        s.open_door()
        s.step(2)                                       # the door stays open, the train stands
        return s, o.door_open_loc

    def roll_to(self, s, ref, distance, speed=0.0):
        """one tick with the train `distance` m from the reference position, the door open"""
        s.step(1, bve_door=1, bve_speed=speed, bve_location=ref + distance)

    def rolls(self, s):
        return [p for p in s.o.popups if p.get("category") == CATEGORY]

    def roll_score(self, s):
        return s.o.score_details["roll"]


class A_Steps(Base):
    def test_R01_a_standing_train_with_the_door_open_is_not_penalised(self):
        s, ref = self.doors_open_at_a()
        s.step(5, bve_door=1)
        self.assertEqual(self.roll_score(s), 0)
        self.assertEqual(self.rolls(s), [])

    def test_R02_less_than_one_step_is_free(self):
        s, ref = self.doors_open_at_a()
        self.roll_to(s, ref, STEP - 0.001)
        self.assertEqual(self.roll_score(s), 0)
        self.assertEqual(self.rolls(s), [])

    def test_R03_one_full_step_deducts_500_in_one_popup(self):
        s, ref = self.doors_open_at_a()
        self.roll_to(s, ref, STEP)
        self.assertEqual(self.roll_score(s), -PENALTY)
        popups = self.rolls(s)
        self.assertEqual([p["text"] for p in popups], ["転動 -500"])
        self.assertEqual(popups[0]["type"], "neg")

    def test_R04_several_steps_in_one_tick_deduct_500_each(self):
        s, ref = self.doors_open_at_a()
        self.roll_to(s, ref, 0.12)                       # int(0.12 / 0.05) = 2 steps
        self.assertEqual(self.roll_score(s), -2 * PENALTY)
        self.assertEqual([p["text"] for p in self.rolls(s)], ["転動 -1000"])

    def test_R05_the_distance_is_measured_both_ways_from_the_reference(self):
        s, ref = self.doors_open_at_a()
        self.roll_to(s, ref, -0.07)                      # rolling backwards: |d| = 0.07 -> 1 step
        self.assertEqual(self.roll_score(s), -PENALTY)


class B_Events(Base):
    def test_R06_one_event_accumulates_in_one_popup(self):
        s, ref = self.doors_open_at_a()
        self.roll_to(s, ref, 0.06, speed=0.3)
        self.roll_to(s, ref, 0.11, speed=0.3)            # still moving: 2 steps in total, one more deducted
        popups = self.rolls(s)
        self.assertEqual(len(popups), 1)
        self.assertEqual(popups[0]["text"], "転動 -1000")
        self.assertEqual(self.roll_score(s), -2 * PENALTY)

    def test_R07_the_same_distance_is_never_deducted_twice(self):
        s, ref = self.doors_open_at_a()
        self.roll_to(s, ref, 0.06, speed=0.3)
        for _ in range(5):
            self.roll_to(s, ref, 0.06, speed=0.3)
        self.assertEqual(self.roll_score(s), -PENALTY)

    def test_R08_a_complete_stop_after_moving_starts_a_new_event_and_a_new_popup(self):
        s, ref = self.doors_open_at_a()
        self.roll_to(s, ref, 0.06, speed=0.3)            # event 1: one step
        self.roll_to(s, ref, 0.06, speed=0.0)            # the complete stop ends the event
        self.roll_to(s, ref, 0.11, speed=0.3)            # event 2: one more step -> a NEW popup
        popups = self.rolls(s)
        self.assertEqual(len(popups), 2)
        self.assertEqual(sorted(p["text"] for p in popups), ["転動 -500", "転動 -500"])
        self.assertNotEqual(popups[0].get("roll_event_id"), popups[1].get("roll_event_id"))
        self.assertEqual(self.roll_score(s), -2 * PENALTY)

    def test_R09_the_score_follows_the_details(self):
        s, ref = self.doors_open_at_a()
        before = s.o.score
        self.roll_to(s, ref, 0.06, speed=0.3)
        self.roll_to(s, ref, 0.16, speed=0.3)
        self.assertEqual(self.roll_score(s), -3 * PENALTY)
        self.assertEqual(s.o.score - before, -3 * PENALTY)


class C_SettingAndDoor(Base):
    def test_R10_rolling_off_deducts_nothing_and_shows_nothing(self):
        s, ref = self.doors_open_at_a(rolling=False)
        self.roll_to(s, ref, 0.30, speed=0.3)
        self.assertEqual(self.roll_score(s), 0)
        self.assertEqual(self.rolls(s), [])
        self.assertEqual(s.o.roll_penalty_count, 0)

    def test_R11_closing_the_door_resets_the_reference_and_the_count(self):
        s, ref = self.doors_open_at_a()
        self.roll_to(s, ref, 0.06, speed=0.3)
        s.step(1, bve_door=0, bve_speed=0.0)
        self.assertEqual(s.o.roll_penalty_count, 0)
        self.assertEqual(s.o.door_open_loc, s.o.bve_location)

    def test_R12_the_next_door_open_edge_is_a_new_reference_and_a_new_event(self):
        s, ref = self.doors_open_at_a()
        event_before = s.o.roll_event_id
        self.roll_to(s, ref, 0.06, speed=0.3)
        s.step(1, bve_door=0, bve_speed=0.0)
        s.step(1, bve_door=1, bve_speed=0.0)             # the door opens again, where the train stands now
        self.assertEqual(s.o.roll_event_id, event_before + 1)
        self.assertEqual(s.o.door_open_loc, s.o.bve_location)
        total_before = self.roll_score(s)
        s.step(3, bve_door=1)                            # standing: nothing more
        self.assertEqual(self.roll_score(s), total_before)

    def test_R13_the_official_jump_is_never_rolling(self):
        s, ref = self.doors_open_at_a()
        s.step(1, bve_door=1, is_official_jumping=True, bve_location=ref + 5.0)
        self.assertEqual(self.roll_score(s), 0)
        self.assertEqual(s.o.roll_penalty_count, 0)


class D_Source(unittest.TestCase):
    def test_P01_the_step_the_penalty_and_the_gate_are_the_ones_pinned_here(self):
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("/ 0.05)", text)                                    # the rolling step
        self.assertIn("penalty_points = 500 * new_penalty_count", text)    # the deduction per step
        self.assertIn('scoring_settings.value(self, "rolling")', text)     # the gate (the running snapshot)


if __name__ == "__main__":
    unittest.main()
