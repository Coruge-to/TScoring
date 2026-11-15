"""Backward pseudo-turnback Jump contract (Owner 2026-11-15, live reproduced on Current BVE 6; the Legacy Run 1 image is the same mechanism).
The official Jump of a pseudo-turnback may go FORWARD, BACKWARD (the target time is before the current BVE time: the train arrived at A later than the planned departure of B) or ZERO in BVE time; in every case
the Run stays ON, the landing at B is NOT an ordinary arrival (no stop score, no ordinary checkpoint), the B checkpoint of the turnback is created, turnback_establish_b completes and the Run goes on.
Live evidence (Current, 2026-11-15 18:04:10): jump_lock True -> False in the time-rewind branch of Overlay._advance_scoring_clock_and_score (main.py), then evaluate_arrival -> create_save_data (B, ordinary) ->
create_turnback_b_checkpoint False -> turnback_stop_scoring (silent). The rig drives the REAL product functions with the real event order `complete_first` (tests/tbg_c01_rig.py) through the Overlay clock method.
The product is Python-only and shared by Current and Legacy: both host labels run the same code, the telemetry transport is not part of it.
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

import pseudo_turnback_machine as M  # noqa: E402

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-bwjump-")
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


HOSTS = ("Legacy", "Current")          # the same Python product; the label only documents that both are covered


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["bwjump"])
        import main
        import scoring_logic
        import pt_scene
        cls.main, cls.S, cls.P = main, scoring_logic, pt_scene

    # B departs at b_dep_ms (the planned Jump time is b_dep - 15 s in the rig); the A arrival is at about T0 + 85 s
    FORWARD_DEP = None                      # the rig default: B at T0 + 150 s -> Jump +about 50 s ahead
    BACKWARD_DEP = None                     # set in setUp

    def setUp(self):
        self.BACKWARD_DEP = self.P.T0 + 40000

    def flow(self, order="complete_first", b_dep_ms=None, operational=True, run_after=6, spy=True):
        import tbg_c01_rig as R
        f = R.Flow(self, operational=operational, order=order)
        s = f.scene
        o = s.o
        if b_dep_ms is not None:
            s.sl[2]["raw_dep"] = b_dep_ms
        f.calls = []
        if spy:
            for name in ("apply_stop_score", "close_range_fix_previous_stop"):
                original = getattr(self.S, name)

                def make(nm, orig):
                    def wrapper(*a, **k):
                        f.calls.append(nm)
                        return orig(*a, **k)
                    return wrapper
                setattr(self.S, name, make(name, original))
                self.addCleanup(setattr, self.S, name, original)

        def clock_tick(advance_ms=16, wall_advance=None, **fields):
            if s.auto_fix and s._fix_key != (o.setting_start_idx, o.setting_end_idx):
                s._fix_key = (o.setting_start_idx, o.setting_end_idx)
                s.fix()
            for k, v in fields.items():
                setattr(o, k, v)
            o.bve_time_ms += advance_ms
            s.n += 1
            o._advance_scoring_clock_and_score(o.bve_time_ms / 1000.0)
        s.tick = clock_tick
        o.last_update_time = o.bve_time_ms / 1000.0
        f.to_arrival_at_a()
        f.to_request()
        f.calls.clear()                                  # the arrival at A (before the request) legitimately scores; only the landing window is observed
        f.score_before = o.score
        f.details_before = dict(o.score_details)
        f.saves_before = len(o.save_data)
        f.jump_time = o.jump_expectation.time_ms
        f.request_time = o.bve_time_ms
        f.land()
        f.after(run_after)
        return f

    def assert_run_continues(self, f, label=""):
        o = f.o
        self.assertTrue(o.is_scoring_mode, "%s: Mode OFF (%r, events %r)" % (label, getattr(o, "internal_abort_reason", ""), f.names()))
        self.assertEqual(getattr(o, "internal_abort_reason", ""), "")
        self.assertEqual(len(o.save_data), f.saves_before + 1, "%s: checkpoints %r" % (label, [(c["station_name"], c["score"], c.get("origin")) for c in o.save_data]))
        self.assertEqual(o.save_data[-1].get("origin"), "turnback", label)
        self.assertEqual(o.save_data[-1]["score"], f.score_before, label)                   # 11: the B checkpoint score is the score before the Jump
        self.assertEqual(o.score, f.score_before, label)                                    # no stop score at the landing
        self.assertEqual(f.calls, [], "%s: ordinary arrival functions ran %r" % (label, f.calls))   # 8
        self.assertEqual(f.fail_reasons(), [], label)                                        # 12 no (silent) failure
        self.assertEqual(f.stop_callers, [], label)
        self.assertEqual(f.scene.machine.state, M.IDLE, label)


class A_ForwardBackwardZero(Base):
    def test_1_3_forward_jump_both_pair_kinds(self):
        for host in HOSTS:
            for operational in (True, False):
                with self.subTest(host=host, operational=operational):
                    f = self.flow(b_dep_ms=self.FORWARD_DEP, operational=operational)
                    self.assertGreater(f.jump_time, f.request_time)
                    self.assert_run_continues(f, "forward")

    def test_2_4_backward_jump_both_pair_kinds(self):
        for host in HOSTS:
            for operational in (True, False):
                with self.subTest(host=host, operational=operational):
                    f = self.flow(b_dep_ms=self.BACKWARD_DEP, operational=operational)
                    self.assertLess(f.jump_time, f.request_time)
                    self.assert_run_continues(f, "backward")

    def test_5_zero_difference_is_processed_deterministically(self):
        """Jump time == the request time: no rewind (current_time is not < last_update_time), the same result as a forward Jump."""
        import tbg_c01_rig as R
        probe = self.flow(b_dep_ms=self.FORWARD_DEP)
        request_time = probe.request_time
        # the rig plans the Jump at B departure - 15 s: make B depart exactly 15 s after the request time
        f = self.flow(b_dep_ms=request_time + 15000)
        self.assertEqual(f.jump_time, f.request_time)
        self.assert_run_continues(f, "zero")

    def test_6_backward_with_detect_first_order_keeps_the_run(self):
        f = self.flow(order="detect_first", b_dep_ms=self.BACKWARD_DEP)
        self.assert_run_continues(f, "detect_first backward")


class B_BStaysTheOwnerOfTheLockUntilTheFirstDeparture(Base):
    def test_13_jump_lock_ownership_and_release(self):
        f = self.flow(b_dep_ms=self.BACKWARD_DEP)
        o = f.o
        self.assertTrue(o.jump_lock)                                                         # kept through the rewinding tick and after B is established
        f.depart_b_only("close_then_go")
        self.assertFalse(o.jump_lock)                                                        # released by the first departure from B (scoring_logic: first departure rule)

    def test_13b_the_lock_is_set_by_the_request_and_never_dropped_while_B_is_pending(self):
        import tbg_c01_rig as R
        f = R.Flow(self, operational=True)
        s = f.scene
        o = s.o
        s.sl[2]["raw_dep"] = self.P.T0 + 40000
        seen = []
        original = self.S.turnback_b_pending if hasattr(self.S, "turnback_b_pending") else None
        self.assertIsNotNone(original, "turnback_b_pending is the pinned definition of the waiting window")
        # run the whole chain with the clock method and record jump_lock on every tick while the machine is pending
        def clock_tick(advance_ms=16, wall_advance=None, **fields):
            if s.auto_fix and s._fix_key != (o.setting_start_idx, o.setting_end_idx):
                s._fix_key = (o.setting_start_idx, o.setting_end_idx)
                s.fix()
            for k, v in fields.items():
                setattr(o, k, v)
            o.bve_time_ms += advance_ms
            s.n += 1
            o._advance_scoring_clock_and_score(o.bve_time_ms / 1000.0)
            if self.S.turnback_b_pending(o):
                seen.append(bool(o.jump_lock))
        s.tick = clock_tick
        o.last_update_time = o.bve_time_ms / 1000.0
        f.to_arrival_at_a()
        f.to_request()
        f.land()
        f.after(6)
        self.assertTrue(seen and all(seen), seen)

    def test_8b_the_window_does_not_depend_on_the_value_of_jump_lock(self):
        for operational in (True, False):
            with self.subTest(operational=operational):
                self.late_target_case(operational)

    def late_target_case(self, operational):
        """F2 is a second, independent guard: even when something lowers jump_lock while B is awaited (the telemetry target of B is late), the landing is not an ordinary arrival; B is established after the target arrives."""
        import tbg_c01_rig as R
        f = R.Flow(self, operational=True, order="complete_first")
        s = f.scene
        o = s.o
        s.sl[2]["raw_dep"] = self.P.T0 + 40000
        f.calls = []
        for name in ("apply_stop_score", "close_range_fix_previous_stop"):
            original = getattr(self.S, name)

            def make(nm, orig):
                def wrapper(*a, **k):
                    f.calls.append(nm)
                    return orig(*a, **k)
                return wrapper
            setattr(self.S, name, make(name, original))
            self.addCleanup(setattr, self.S, name, original)

        def clock_tick(advance_ms=16, wall_advance=None, **fields):
            if s.auto_fix and s._fix_key != (o.setting_start_idx, o.setting_end_idx):
                s._fix_key = (o.setting_start_idx, o.setting_end_idx)
                s.fix()
            for k, v in fields.items():
                setattr(o, k, v)
            o.bve_time_ms += advance_ms
            s.n += 1
            o._advance_scoring_clock_and_score(o.bve_time_ms / 1000.0)
        s.tick = clock_tick
        o.last_update_time = o.bve_time_ms / 1000.0
        f.to_arrival_at_a()
        f.to_request()
        f.calls.clear()
        score_before = o.score
        exp = o.jump_expectation
        b = s.sl[exp.station_index]
        s.step(3)
        o.bve_time_ms = exp.time_ms
        for k, v in dict(bve_jump_count=getattr(o, "bve_jump_count", 0) + 1, bve_location=b["location"], bve_speed=0.0, bve_door=0, bve_arr_idx=exp.station_index, bve_arr_seq=o.bve_arr_seq + 1).items():
            setattr(o, k, v)                                                                  # the telemetry names B as the arrived station, but NEXTLOC / the target is still A's (late)
        s.complete()
        s.step(2)
        self.assertTrue(self.S.turnback_b_pending(o))                                         # settled, B awaited
        o.jump_lock = False                                                                   # lowered by "somebody"
        self.assertTrue(self.S.jump_locked(o))
        s.step(3, bve_speed=0.0, bve_door=0 if operational else 1)        # the door-edge pair: the doors open at B (an ordinary arrival, if it were not suppressed)
        self.assertEqual(f.calls, [], f.calls)
        self.assertTrue(o.is_scoring_mode)
        s.step(1, bve_next_loc=b["location"], bve_tgt_idx=exp.station_index)                  # the target of B arrives: B is established
        s.step(2)
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual(o.save_data[-1].get("origin"), "turnback")
        self.assertEqual(o.save_data[-1]["score"], score_before)
        self.assertEqual(f.calls, [])

class C_OrdinaryArrivalSuppressionWindow(Base):
    def test_8_9_suppressed_while_B_is_pending_and_released_after(self):
        f = self.flow(b_dep_ms=self.BACKWARD_DEP)
        self.assertEqual(f.calls, [])                                                        # 8: nothing ordinary ran at the landing
        self.assertFalse(self.S.turnback_b_pending(f.o))                                     # 9: the window is closed after B is established
        f.depart_b_and_arrive_c()                                                            # the ordinary arrival at C is processed again
        self.assertIn("create_save_data", f.names())
        self.assertTrue(f.o.is_scoring_mode)

    def test_pending_definition_is_the_machine_state_only(self):
        import tbg_c01_rig as R
        f = R.Flow(self, operational=True)
        o = f.scene.o
        self.assertFalse(self.S.turnback_b_pending(o))
        f.to_arrival_at_a()
        self.assertFalse(self.S.turnback_b_pending(o))                                       # RECOGNIZED / ARMED: not pending (the Jump is not requested yet)
        f.to_request()
        self.assertTrue(self.S.turnback_b_pending(o))                                        # REQUESTED
        o.is_scoring_mode = False
        self.assertFalse(self.S.turnback_b_pending(o))                                       # a Run that is not active owns nothing


class D_ExistingContractsStay(Base):
    def test_6_7_start_and_retry_style_rewind_still_releases_the_lock(self):
        """No chain pending (START / Retry / the user's time change): the time-rewind branch keeps its meaning: jump_lock False."""
        import tbg_c01_rig as R
        f = R.Flow(self, operational=True)
        s = f.scene
        o = s.o
        o.jump_lock = True
        self.assertFalse(self.S.turnback_b_pending(o))
        o.last_update_time = o.bve_time_ms / 1000.0 + 10.0                                   # the next tick is in the past
        o._advance_scoring_clock_and_score(o.bve_time_ms / 1000.0)
        self.assertFalse(o.jump_lock)

    def test_10_a_failed_jump_keeps_the_explicit_failure_path(self):
        import tbg_c01_rig as R
        f = R.Flow(self, operational=True)
        s = f.scene
        o = s.o
        f.to_arrival_at_a()
        f.to_request()
        exp = o.jump_expectation
        b = s.sl[exp.station_index]
        s.step(3)
        o.bve_time_ms = exp.time_ms
        for k, v in dict(bve_jump_count=getattr(o, "bve_jump_count", 0) + 1, bve_location=b["location"], bve_speed=0.0, bve_door=0, bve_next_loc=b["location"], bve_tgt_idx=exp.station_index).items():
            setattr(o, k, v)
        o._note_jump_complete(s.completion_text(idx=0))                                      # a completion that does not prove the request
        o._settle_jump_complete()
        s.step(3)
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(o.internal_abort_reason, "jump")
        self.assertFalse(self.S.turnback_b_pending(o))                                       # the window ends with the failure

    def test_14_generation_change_ends_the_window_and_the_run_as_before(self):
        import tbg_c01_rig as R
        f = R.Flow(self, operational=True)
        s = f.scene
        o = s.o
        f.to_arrival_at_a()
        f.to_request()
        self.assertTrue(self.S.turnback_b_pending(o))
        o.apply_telemetry_text("SCENARIO_ID:777")
        s.step(2)
        self.assertFalse(o.is_scoring_mode)
        self.assertFalse(self.S.turnback_b_pending(o))
        self.assertEqual(len(o.save_data), 0)


class E_Static(unittest.TestCase):
    def test_the_rewind_branches_do_not_write_jump_lock_unconditionally(self):
        import ast
        for rel in ("main.py", "managed_hud.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            hits = []
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    test_src = ast.unparse(node.test)
                    if "last_update_time" in test_src and "<" in test_src:
                        for sub in ast.walk(node):
                            if isinstance(sub, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "jump_lock" for t in sub.targets):
                                hits.append((rel, sub.lineno))
            self.assertTrue(hits, rel)
            # every such write is inside a guard on turnback_b_pending
            for rel_, line in hits:
                with open(os.path.join(ROOT, rel_), encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
                window = "\n".join(lines[max(0, line - 4):line])
                self.assertIn("turnback_b_pending", window, "%s:%d writes jump_lock in the rewind branch without the pending guard" % (rel_, line))


    def test_the_arrival_and_scoring_gates_read_jump_locked_not_the_raw_lock(self):
        """F2 (static): in the arrival / departure / scoring-step functions the lock is read through jump_locked(self); the only raw read left is the release of the lock at the first departure (the owner's release)."""
        import ast
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        raw = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in ("evaluate_arrival", "evaluate_departure", "update_physics_and_scoring", "update_basic_braking_first_stop"):
                count = 0
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "getattr" and len(sub.args) >= 2 and isinstance(sub.args[1], ast.Constant) and sub.args[1].value == "jump_lock":
                        count += 1
                raw[node.name] = count
        # update_physics_and_scoring: the departure release (`if getattr(self, 'jump_lock', False): self.jump_lock = False`) and the JUMP detection's own lock write are the owners' accesses
        self.assertEqual(raw, {"evaluate_arrival": 0, "evaluate_departure": 0, "update_physics_and_scoring": 1, "update_basic_braking_first_stop": 0}, raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
