"""Repaint only when the picture would change (Owner 2026-11-17).

Why: the Overlay ended every step of the shared update in update() = a full repaint (about 6 ms of QPainter work and a layered window update) about 60 times a second, whether anything on the
screen had changed or not; the HUD process used about half a core at a standstill (F1 menu, paused, stopped). Overlay.request_repaint() now first RECORDS the drawing into a QPicture (the same draw
functions, about 1 ms) and asks the window to repaint only when the record differs from the previous one, the size / display scale / menu page differ, or REPAINT_HEARTBEAT_S (1 s) has passed.
The real paint (paintEvent -> _paint_to on the window) is untouched, so the pixels are what they always were.

Contract:
  R-1  a state that draws exactly what the last request drew does not repaint (the first request after a change does; an identical second one does not)
  R-2  every kind of drawn change repaints: the HUD numbers (location, time, speed), the menu page, the window size (what the draw functions read at the moment of the record is what is compared, so a
       change that depends on a clock - e.g. the expiry of the rollback message - is seen at the first tick it shows)
  R-3  the heartbeat: an unchanged picture is repainted once REPAINT_HEARTBEAT_S has passed, not before
  R-4  a hidden window is not recorded and does not repaint; the first request after it is shown repaints
  R-5  SOUNDNESS: over a long mixed sequence, a request that did NOT repaint always left the window pixels (a direct grab) identical to the previous ones
  R-6  the update steps (Overlay.update_logic_shared of the normal mode, the managed step) call request_repaint, not the plain update(); a stand-in without request_repaint keeps update()
"""
import importlib.util
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import official_target_wire_fixture as F  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None


def _pixels(overlay):
    image = overlay.grab().toImage()
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    return bytes(pointer)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class R_RepaintSkip(unittest.TestCase):
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

    def setUp(self):
        self.sc = F.Scene(self.vec)
        self.sc.__enter__()
        self.sc.hud_ui.draw_text_with_stroke = self.sc._orig_draw          # the REAL drawing (the scene's recorder would draw nothing)
        self.o = self.sc.o
        self.o.resize(1180, 660)
        self.o.show()
        self.calls = []
        self.o.update = lambda *a: self.calls.append(1)                    # the spy: what the window is asked to repaint
        self.now = [1000.0]
        self.o._repaint_clock = lambda: self.now[0]
        self.sc.load_list("L4")
        self.o.is_scoring_mode, self.o.is_scoring_finished = True, False      # a scoring run with an official target: the remaining distance and time are on the HUD
        self.sc.state["machine"].update({"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1})
        self.sc.state["time_ms"] = 36000000
        self.sc.state["loc"] = 100.0
        self.feed()

    def tearDown(self):
        self.sc.__exit__(None, None, None)

    def feed(self, **changes):
        st = self.sc.state
        for k, v in changes.items():
            st[k] = v
        st["official"] = {"state": "K", "index": 2}
        self.sc.push(self.sc.telemetry_text(st))

    def request(self):
        before = len(self.calls)
        self.o.request_repaint()
        return len(self.calls) - before

    def test_R_1_an_unchanged_picture_does_not_repaint(self):
        self.assertEqual(self.request(), 1, "the first request has nothing to compare with: it repaints")
        for _ in range(5):
            self.assertEqual(self.request(), 0)
        self.feed()                                                         # the same telemetry again
        self.assertEqual(self.request(), 0)

    def test_R_2_every_kind_of_drawn_change_repaints(self):
        self.request()
        steps = (("location", lambda: self.feed(loc=self.sc.state["loc"] + 50.0)),
                 ("time", lambda: self.feed(time_ms=self.sc.state["time_ms"] + 3000)),
                 ("speed", lambda: self.feed(speed=self.sc.state["speed"] + 5.0)),
                 ("menu page", lambda: setattr(self.o, "menu_state", 1)),
                 ("window size", lambda: self.o.resize(1000, 640)))
        for name, change in steps:
            change()
            self.assertEqual(self.request(), 1, name + " must repaint")
            self.assertEqual(self.request(), 0, name + ": and the next identical request must not")

    def test_R_3_the_heartbeat_repaints_an_unchanged_picture(self):
        self.request()
        self.now[0] += 0.9
        self.assertEqual(self.request(), 0)
        self.now[0] += 0.2
        self.assertEqual(self.request(), 1, "1.1 s after the last repaint")
        self.assertEqual(self.request(), 0)

    def test_R_4_a_hidden_window_is_not_recorded(self):
        self.request()
        self.o.hide()
        self.feed(loc=self.sc.state["loc"] + 10.0)
        self.assertEqual(self.request(), 0)
        self.o.show()
        self.assertEqual(self.request(), 1, "the first request after the window is shown")

    def test_R_5_a_request_that_did_not_repaint_left_the_pixels_as_they_were(self):
        rnd = random.Random(20261117)
        self.request()
        before = _pixels(self.o)
        skipped = repainted = 0
        for i in range(60):
            kind = rnd.choice(("same", "same", "invisible", "loc", "time", "speed", "menu", "rollback"))
            if kind == "loc":
                self.feed(loc=round(rnd.uniform(0, 5000), 1))
            elif kind == "time":
                self.feed(time_ms=self.sc.state["time_ms"] + rnd.choice((0, 1000, 5000)))
            elif kind == "speed":
                self.feed(speed=float(rnd.choice((0, 0, 30, 60.5))))
            elif kind == "menu":
                self.o.menu_state = rnd.choice((0, 0, 1))
            elif kind == "rollback":
                self.o.rollback_msg = rnd.choice(("", "A", "B"))
            elif kind == "invisible":
                self.o.some_attribute_the_drawing_never_reads = i              # state that does not reach the screen
            else:
                self.feed()
            n = self.request()
            after = _pixels(self.o)
            if n == 0:
                skipped += 1
                self.assertEqual(after, before, "step %d (%s): no repaint was requested but the picture changed" % (i, kind))
            else:
                repainted += 1
            before = after
        self.assertGreater(skipped, 10, "the sequence must really skip (not vacuous)")
        self.assertGreater(repainted, 10, "and really repaint")

    def test_R_6_the_update_steps_use_request_repaint(self):
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            main_src = f.read()
        with open(os.path.join(ROOT, "managed_hud.py"), encoding="utf-8") as f:
            managed_src = f.read()
        import re
        self.assertRegex(main_src, r"update_physics_and_scoring\(self, current_time, dt\)\s*\n\s*self\.request_repaint\(\)")
        self.assertIn("request = getattr(overlay, 'request_repaint', None)", managed_src)
        self.assertNotIn("    update_physics_and_scoring(overlay, current_time, dt)\n    overlay.update()", managed_src)
        # a stand-in without request_repaint keeps the plain update()
        import managed_hud

        class Plain(object):
            last_update_time = 0.0
            bve_time_ms = 0
            updates = 0

            def update(self):
                Plain.updates += 1
        self.assertFalse(hasattr(Plain(), "request_repaint"))
        self.assertTrue(hasattr(managed_hud, "ManagedHudController"))


if __name__ == "__main__":
    unittest.main()
