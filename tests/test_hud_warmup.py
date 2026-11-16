"""HUD warm-up (Owner 2026-11-16): the first HUD of a process came up 0.2-0.3 s after the cab (live: the first update step starts the key listener, the first show creates and paints the native window; every later show is instant).
The managed HUD controller pays those first-use costs ONCE, while the HUD is hidden, through Overlay.warm_up(rect) at the BVE client area's real size.

W1  hidden and idle: the Overlay's warm_up is called ONCE with the BVE client rect; one `hud-warmup` line; nothing is shown, linked, owned or updated
W2  not before a BVE window exists: searched every WINDOW_SEARCH_INTERVAL_S at most; nothing reported while it is missing; done as soon as it appears
W3  a minimized BVE window is not warmed (the next search)
W4  the search gives up after WARMUP_MAX_TRIES, silently, and never again
W5  not while ACTIVE (a late start in an active state shows the HUD as before; nothing is warmed on the way)
W6  an exception in warm_up is reported once (hud-warmup-failed) and never repeated; the HUD still works
W7  an Overlay without warm_up (every other fake) is marked done: no search, no line
W8  after the warm-up the first HUD behaves exactly as before (one show, one link, one owner call, the update steps)
W9  the real Overlay: warm_up shows nothing, keeps the window hidden, applies the rect without showing, paints once (grab), starts the key listener through the keyboard module
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import managed_hud as mh  # noqa: E402
import managed_state as ms  # noqa: E402
import test_managed_hud_e4 as e4  # noqa: E402


class WarmOverlay(e4.FakeOverlay):
    def __init__(self):
        super().__init__()
        self.warm_calls = []
        self.warm_error = None

    def warm_up(self, rect):
        self.warm_calls.append(rect)
        if self.warm_error is not None:
            raise self.warm_error


class WarmCase(e4.ControllerCase):
    def setUp(self):
        super().setUp()
        self.overlay = WarmOverlay()
        self.overlay.z_api = self.api
        self.hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log, update_step=lambda o: self.steps.append(1),
                                           timer=self.timer, clock=self.clock)

    def tick_seconds(self, seconds, step=0.02):
        for _ in range(int(round(seconds / step))):
            self.pump(1)


class W_Controller(WarmCase):
    def test_W1_idle_hidden_calls_warm_up_once_with_the_client_rect(self):
        self.hud.start()
        self.pump(60)
        self.assertEqual(self.overlay.warm_calls, [self.api.rect])
        self.assertEqual(len(self.log.events("hud-warmup")), 1)
        self.assertRegex(self.log.events("hud-warmup")[0], r"ms=\d+ tries=1")
        self.assertEqual((self.overlay.shows, self.overlay.hides, self.api.owner_calls, self.overlay.geoms, len(self.steps)), (0, 0, [], [], 0))
        self.assertEqual(self.log.events("hud-window-linked"), [])

    def test_W2_waits_for_the_bve_window_and_searches_at_most_every_interval(self):
        self.api.alive = False
        self.hud.start()
        self.tick_seconds(2.0)
        self.assertEqual(self.overlay.warm_calls, [])
        self.assertEqual(self.log.events("hud-warmup"), [])
        self.assertLessEqual(self.api.searches, int(2.0 / mh.WINDOW_SEARCH_INTERVAL_S) + 1)
        self.assertGreaterEqual(self.api.searches, 3)
        self.api.alive = True
        self.tick_seconds(1.0)
        self.assertEqual(len(self.overlay.warm_calls), 1)
        self.assertEqual(len(self.log.events("hud-warmup")), 1)

    def test_W3_a_minimized_window_is_not_warmed(self):
        self.api.iconic = True
        self.hud.start()
        self.tick_seconds(1.5)
        self.assertEqual(self.overlay.warm_calls, [])
        self.api.iconic = False
        self.tick_seconds(1.0)
        self.assertEqual(len(self.overlay.warm_calls), 1)

    def test_W4_gives_up_after_the_tries_and_never_again(self):
        self.api.alive = False
        self.hud.start()
        self.tick_seconds(mh.WARMUP_MAX_TRIES * mh.WINDOW_SEARCH_INTERVAL_S + 3.0)
        searches = self.api.searches
        self.api.alive = True
        self.tick_seconds(3.0)
        self.assertEqual((self.overlay.warm_calls, self.log.events("hud-warmup"), self.log.events("hud-warmup-failed")), ([], [], []))
        self.assertEqual(self.api.searches, searches)                             # no search any more

    def test_W5_not_while_active(self):
        self.publish(True, True, 1)
        self.hud.start()
        self.pump(20)
        self.assertEqual(self.overlay.warm_calls, [])
        self.assertTrue(self.overlay.visible)

    def test_W6_an_exception_is_reported_once_and_not_repeated(self):
        self.overlay.warm_error = RuntimeError("boom")
        self.hud.start()
        self.tick_seconds(3.0)
        self.assertEqual(len(self.overlay.warm_calls), 1)
        self.assertEqual(len(self.log.events("hud-warmup-failed")), 1)
        self.assertEqual(self.log.events("hud-warmup"), [])
        self.publish(True, True, 1)
        self.pump(10)
        self.assertTrue(self.overlay.visible)                                     # the HUD still works

    def test_W7_an_overlay_without_warm_up_is_marked_done(self):
        plain = e4.FakeOverlay()
        plain.z_api = self.api
        hud = mh.ManagedHudController(plain, self.reader, self.api, self.args, self.log, update_step=lambda o: None, timer=self.timer, clock=self.clock)
        hud.start()
        for _ in range(100):
            self.clock.t += 0.02
            hud.tick()
        self.assertEqual((self.api.searches, self.log.events("hud-warmup"), self.log.events("hud-warmup-failed")), (0, [], []))

    def test_W8_the_first_hud_after_the_warm_up_behaves_as_before(self):
        self.hud.start()
        self.pump(60)
        self.publish(True, True, 1)
        self.pump(10)
        self.assertEqual((self.overlay.shows, self.api.owner_calls, len(self.log.events("hud-update-start")), len(self.log.events("hud-show"))), (1, [(1000, 5000)], 1, 1))
        self.assertEqual(len(self.steps), 10)
        self.assertEqual(len(self.overlay.warm_calls), 1)                         # still just the one


class W_RealOverlay(unittest.TestCase):
    def test_W9_the_real_overlay_warm_up_shows_nothing(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        import main
        app = QApplication.instance() or QApplication(sys.argv[:1])
        calls = []

        class Kb(object):
            @staticmethod
            def is_pressed(name):
                calls.append(name)
                return False

        real_kb = main.keyboard
        main.keyboard = Kb
        ov = main.Overlay(0)
        try:
            ov.timer.stop()
            before_visible = ov.isVisible()
            ov.warm_up((10, 20, 800, 450))
            self.assertEqual((before_visible, ov.isVisible()), (False, False))
            self.assertEqual(calls, ["f24"])                                      # only the start of the key listener, a key nothing uses
            self.assertEqual(ov.client_rect_physical(), (10, 20, 800, 450))
            self.assertEqual((ov.geometry().width(), ov.geometry().height()), (800, 450))
        finally:
            main.keyboard = real_kb
            try:
                ov.close()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
