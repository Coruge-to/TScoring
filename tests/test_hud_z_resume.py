"""HUD Z order on resume (Owner 2026-11-16): after a Tick stop (the scenario selection screen loading takes BVE's UI thread for ~5-6 s) the Tick comes back (WAITING -> ACTIVE) and the HUD's place in the
Z order is finalised ONCE, with the rule of the first show: directly above the BVE window, below every window that lies over it. Live: BVE5 22:18:34.4 (and the first BVE6 screenshot): after the first scenario
list load the HUD lay OVER the list window until the list was clicked (Z log `HUD > SCN > BVE`, the 2nd..4th loads were right).

Z1  the HUD lies over the list window when the Tick comes back: it goes directly under the list window (one place_below)
Z2  the order is already right: nothing is placed (one Z query, no Z operation)
Z3  once per resume: a thousand active Ticks later nothing is polled or corrected, drift while shown is not fought
Z4  nothing happens while the Tick is stopped (WAITING): a drift is not fought and no Z operation is made
Z5  every resume does it once (three Tick stops: three corrections)
Z6  a reload (the Session ends and the HUD is re-shown) still finalises exactly once (the show path), not twice
Z7  a minimized BVE window at the resume: nothing is placed while it is minimized; the show after the restore finalises once (+ the one recheck)
Z8  the re-ordering that Windows does for ~0.1-0.3 s after BVE answers again: a first look inside it (HUD > BVE > list: the HUD already is directly above BVE) does nothing, the recheck 0.4 s later\n    finds HUD > list > BVE and puts the HUD directly under the list (live 23:34:06.9)
Z9  the recheck happens ONCE per resume (a thousand more Ticks: nothing)
Z10 a HUD that is hidden before the recheck is due is not looked at (the next show places it)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import test_managed_hud_e4 as e4  # noqa: E402

SELECT, OTHER, HUD, BVE = e4.SELECT, e4.OTHER, e4.HUD, 5000


class Z_Resume(e4.ControllerCase):
    def activate(self, z):
        self.api.z = list(z)
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(3)

    def stop_ticks(self):
        self.publish(True, False, 1)
        self.pump(40)

    def resume(self):
        self.publish(True, True, 1)
        self.pump(5)

    def test_Z1_hud_over_the_list_window_goes_directly_under_it(self):
        self.activate([SELECT, BVE])
        self.stop_ticks()
        self.api.z = [HUD, SELECT, BVE]                      # what BVE's recovery did (live)
        self.api.z_calls.clear()
        self.resume()
        self.assertEqual(self.api.z, [SELECT, HUD, BVE])
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])
        self.assertEqual((self.overlay.shows, self.overlay.hides), (1, 0))

    def test_Z2_an_order_that_is_already_right_is_left_alone(self):
        self.activate([SELECT, BVE])
        self.stop_ticks()
        self.api.z_calls.clear()
        queries = self.api.z_queries
        self.resume()
        self.assertEqual(self.api.z, [SELECT, HUD, BVE])
        self.assertEqual(self.api.z_calls, [])
        self.assertEqual(self.api.z_queries, queries + 1)    # the one look

    def test_Z3_once_per_resume_never_polled(self):
        self.activate([SELECT, BVE])
        self.stop_ticks()
        self.api.z = [HUD, SELECT, BVE]
        self.resume()
        self.pump(40)                                        # the one recheck (0.4 s after the first look) is over
        self.api.z_calls.clear()
        queries = self.api.z_queries
        self.api.z = [HUD, OTHER, SELECT, BVE]               # drift while the HUD stays shown
        self.pump(1000)
        self.assertEqual(self.api.z, [HUD, OTHER, SELECT, BVE])
        self.assertEqual((self.api.z_calls, self.api.z_queries), ([], queries))

    def test_Z4_nothing_while_the_tick_is_stopped(self):
        self.activate([SELECT, BVE])
        self.stop_ticks()
        self.api.z = [HUD, SELECT, BVE]
        self.api.z_calls.clear()
        queries = self.api.z_queries
        self.pump(300)                                       # still WAITING
        self.assertEqual(self.api.z, [HUD, SELECT, BVE])
        self.assertEqual((self.api.z_calls, self.api.z_queries), ([], queries))

    def test_Z5_every_resume_does_it_once(self):
        self.activate([SELECT, BVE])
        for _ in range(3):
            self.stop_ticks()
            self.api.z = [HUD, SELECT, BVE]
            self.api.z_calls.clear()
            self.resume()
            self.assertEqual((self.api.z, self.api.z_calls), ([SELECT, HUD, BVE], [(HUD, SELECT)]))

    def test_Z6_a_reload_reshow_finalises_exactly_once(self):
        self.activate([SELECT, BVE])
        self.publish(False, False, 1)                        # the Session ends: the HUD is hidden
        self.pump(5)
        self.api.z_calls.clear()
        queries = self.api.z_queries
        self.publish(True, True, 2)
        self.pump(60)
        self.assertEqual(self.api.z, [SELECT, HUD, BVE])
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])
        self.assertEqual(self.api.z_queries, queries + 1)    # the show path only: the resume flag does not add a second look

    def test_Z7_minimized_at_the_resume(self):
        self.activate([SELECT, BVE])
        self.stop_ticks()
        self.api.z = [HUD, SELECT, BVE]
        self.api.iconic = True
        self.api.z_calls.clear()
        self.resume()
        self.assertEqual(self.api.z_calls, [])               # nothing is placed while BVE is minimized
        queries = self.api.z_queries
        self.api.iconic = False
        self.pump(60)
        self.assertEqual(self.api.z, [SELECT, HUD, BVE])
        self.assertEqual(len(self.api.z_calls), 1)
        self.assertEqual(self.api.z_queries, queries + 2)    # the show path finalises once (the pending resume does not add a second look there) + the one recheck 0.4 s later


    def test_Z8_the_recheck_after_the_reordering_has_settled(self):
        self.activate([SELECT, BVE])
        self.stop_ticks()
        self.api.z = [HUD, BVE, SELECT]                      # Windows' transient state: the list is under BVE for a moment
        self.api.z_calls.clear()
        self.publish(True, True, 1)
        self.pump(3)                                         # the first look: HUD is directly above BVE: nothing to do
        self.assertEqual(self.api.z_calls, [])
        self.api.z = [HUD, SELECT, BVE]                      # settled: the list came back above BVE, still under the HUD
        self.pump(30)                                        # 0.6 s: the recheck
        self.assertEqual(self.api.z, [SELECT, HUD, BVE])
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])

    def test_Z9_the_recheck_happens_once(self):
        self.activate([SELECT, BVE])
        self.stop_ticks()
        self.resume()
        self.pump(40)
        queries = self.api.z_queries
        self.pump(1000)
        self.assertEqual(self.api.z_queries, queries)

    def test_Z10_a_hidden_hud_is_not_looked_at(self):
        self.activate([SELECT, BVE])
        self.stop_ticks()
        self.resume()                                        # 5 ticks = 0.1 s: the recheck is pending
        self.publish(False, False, 1)                        # the Session ends: the HUD is hidden
        self.pump(5)
        queries = self.api.z_queries
        self.pump(60)
        self.assertEqual(self.api.z_queries, queries)

    def test_Z11_a_recheck_that_was_pending_when_the_hud_was_hidden_does_not_run_after_the_next_show(self):
        self.activate([SELECT, BVE])
        self.stop_ticks()
        self.resume()                                        # the recheck is pending
        self.publish(False, False, 1)                        # hidden before it is due
        self.pump(40)                                        # 0.8 s: it would be overdue
        queries = self.api.z_queries
        self.publish(True, True, 2)                          # the HUD is shown again: the show path places it once
        self.pump(60)
        self.assertEqual(self.api.z_queries, queries + 1)


if __name__ == "__main__":
    unittest.main()
