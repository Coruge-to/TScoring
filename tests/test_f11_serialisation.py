"""F11 / F12 serialisation (Owner 2026-11-16, fault tolerance).

Live 22:54:47 (BVE5, F11 pressed repeatedly): the Python log said on / off / on / on - overlapping window state changes of the BVE window (style, maximise, size; BVE's D3D device
is reset by each) - and BVE5's WinForms went into a size-change recursion of about 7400 levels and died of a stack overflow (dump analysis). A window state change is now carried
out ONE AT A TIME: F11 and F12 (they share is_borderless_fullscreen) are ignored for Overlay.F11_COOLDOWN_S (0.8 s) after one was carried out.

G1  a second F11 right after the first is ignored (one deferred request, one state change)
G2  after the cooldown the next F11 is carried out (it restores)
G3  F12 right after F11 is ignored; F12 after the cooldown works
G4  a burst of 50 F11 presses 20 ms apart: ONE change carried out; one `window-fullscreen-ignored` line at the 1st and at the 10th ignored press, none more
G5  after the cooldown a new burst starts a new count (one line again at n=1)
G6  the cooldown is measured from the change that was carried out, not from the ignored presses (pressing for a long time does not extend it)
G7  a missing / invalid BVE window and BVE's native fullscreen return before the gate: they do not use up the cooldown
G8  the default cooldown is 0.8 s and positive
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sia_rig as R  # noqa: E402
from test_characterization_sia1 import Base  # noqa: E402


class G_Serialised(Base):
    def setUp(self):
        super().setUp()
        self.events = []
        self.o.input_event_sink = lambda name, **kw: self.events.append((name, kw))
        self.o.F11_COOLDOWN_S = 0.8                      # the gate ON (the rig turns it off for the characterisation tests)
        R.FakeQTimer.pending = []

    def ignored(self):
        return [e for e in self.events if e[0] == "window-fullscreen-ignored"]

    def test_G1_a_second_F11_right_after_the_first_is_ignored(self):
        self.tap("f11")
        self.tap("f11")
        self.assertEqual(len(R.FakeQTimer.pending), 1)
        R.FakeQTimer.flush()
        self.assertTrue(self.o.is_borderless_fullscreen)
        self.assertEqual(len(self.ignored()), 1)

    def test_G2_after_the_cooldown_the_next_F11_restores(self):
        self.tap("f11")
        R.FakeQTimer.flush()
        self.assertTrue(self.o.is_borderless_fullscreen)
        self.clock.now += 0.9
        self.tap("f11")
        self.assertFalse(self.o.is_borderless_fullscreen)
        self.assertEqual(self.ignored(), [])

    def test_G3_f12_right_after_f11_is_ignored_and_works_after_the_cooldown(self):
        self.tap("f11")
        R.FakeQTimer.flush()
        self.gui.calls.clear()
        self.tap("f12")
        self.assertTrue(self.o.is_borderless_fullscreen)                 # F12 did nothing
        self.assertEqual([c[0] for c in self.gui.calls if c[0] in ("SetWindowLong", "SetWindowPos", "SendMessage")], [])
        self.assertEqual([e[1]["key"] for e in self.ignored()], ["f12"])
        self.clock.now += 0.9
        self.tap("f12")
        self.assertFalse(self.o.is_borderless_fullscreen)

    def test_G4_a_burst_of_fifty_presses_carries_out_one_change_and_logs_twice(self):
        for _ in range(30):                                              # 30 x 0.02 s = 0.6 s: inside the 0.8 s cooldown
            self.tap("f11")
            self.clock.now += 0.02
        self.assertEqual(len(R.FakeQTimer.pending), 1)                   # one deferred request: ONE change was carried out
        self.assertEqual([e[1]["n"] for e in self.ignored()], [1, 10])   # the 1st and the 10th ignored press, none more (29 were ignored)
        self.assertEqual({e[1]["key"] for e in self.ignored()}, {"f11"})

    def test_G5_after_the_cooldown_a_new_burst_counts_again(self):
        for _ in range(12):
            self.tap("f11")
            self.clock.now += 0.02
        R.FakeQTimer.flush()
        self.clock.now += 1.0
        self.events.clear()
        for _ in range(3):
            self.tap("f11")
            self.clock.now += 0.02
        self.assertEqual([e[1]["n"] for e in self.ignored()], [1])       # the first press of the new burst restored; the 2nd (n=1) and 3rd (n=2) were ignored: one line

    def test_G6_the_cooldown_is_measured_from_the_change_not_from_the_ignored_presses(self):
        self.tap("f11")
        R.FakeQTimer.flush()
        for _ in range(30):                                              # 30 x 0.03 s = 0.9 s of presses: the 0.8 s from the change are over before the last
            self.clock.now += 0.03
            self.tap("f11")
        self.assertFalse(self.o.is_borderless_fullscreen)                # one of them was carried out after 0.8 s: the restore

    def test_G7_no_window_and_native_fullscreen_do_not_use_up_the_cooldown(self):
        self.gui.valid = set()
        self.tap("f11")
        self.assertEqual(self.o._f11_busy_until, 0.0)
        self.gui.valid = {self.HWND}
        self.o._bve_in_native_fullscreen = lambda: True
        self.tap("f11")
        self.assertEqual(self.o._f11_busy_until, 0.0)
        self.o._bve_in_native_fullscreen = lambda: False
        self.tap("f11")
        R.FakeQTimer.flush()
        self.assertTrue(self.o.is_borderless_fullscreen)

    def test_G8_the_default_cooldown_is_positive(self):
        import main
        self.assertEqual(main.Overlay.F11_COOLDOWN_S, 0.8)


if __name__ == "__main__":
    unittest.main()
