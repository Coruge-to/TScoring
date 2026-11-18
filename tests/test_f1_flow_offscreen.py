"""The F1 menu autonomous test flow (tests/live/f1_flow.py) run against the REAL Overlay, offscreen, without BVE: the Transport calls the real key handlers
(_on_f1, handle_menu_down / up / enter / backspace) and the live probe (tests/live/probe/sitecustomize.py, switched on with TSPROBE_FORCE=1) writes the same log lines as
in a live run, so the flow, its checks and its verdicts are exercised on every regression run. The live run (tests/live/f1_autonomous.py, BVE + the real keyboard path)
only adds the key injection.

  (A) the flow PASSES on the real Overlay: the F1 pages, the Backspace returns, the environment switches, the ENV-1 interlock, the revert, the close / reopen
  (B) the flow FAILS (a check, not INCONCLUSIVE) when the ENV-1 interlock is broken
  (C) the flow is INCONCLUSIVE, never FAIL, when the keys do not arrive
  (D) the probe is inert without TSPROBE_LOG; the log line parser reads what the probe writes

    C:\\Python314\\python.exe -B -m unittest tests.test_f1_flow_offscreen -v
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "tests", "live")
PROBE = os.path.join(LIVE, "probe")
HAS_QT = importlib.util.find_spec("PyQt6") is not None

_CHILD = r'''
import json, os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT_PLACEHOLDER)
sys.path.insert(0, LIVE_PLACEHOLDER)
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import main
import f1_flow

class Signal(object):
    def connect(self, slot):
        pass

class StubUdp(object):
    def __init__(self, parent=None):
        self.readyRead = Signal()
    def bind(self, a, p):
        return True
    def localPort(self):
        return 0
    def hasPendingDatagrams(self):
        return False
    def close(self):
        pass
    def writeDatagram(self, *a):
        return 0

main.QUdpSocket = StubUdp
main.write_desktop_log = lambda *a, **k: None
time.sleep(0.7)                                   # the probe thread installs its wrappers within 0.1 s of main's import
mode = MODE_PLACEHOLDER
if mode == "interlock":                            # a deliberately broken ENV-1 contract: switching the limit off no longer touches the advance
    main.initial_defaults.set_speed_limit = lambda disp, enabled: disp.__setitem__("limit", bool(enabled))
o = main.Overlay()
o.resize(1920, 1080)
o.show()
app.processEvents()


class Direct(object):
    def press(self, key):
        if mode == "dead":
            return
        if key == "F1":
            o._on_f1(False)
        elif key == "DOWN":
            o.handle_menu_down()
        elif key == "UP":
            o.handle_menu_up()
        elif key == "ENTER":
            o.handle_menu_enter(False)
        elif key == "BACKSPACE":
            o.handle_menu_backspace(False)
        app.processEvents()


flow = f1_flow.Flow(Direct(), f1_flow.ProbeLog(LOG_PLACEHOLDER), require_armed=False, key_timeout=(0.4 if mode == "dead" else 2.0), settle=0.02, log=lambda *a: None)
result = flow.run()
print("RESULT " + json.dumps({"verdict": result["verdict"], "why": result["why"], "failed": [c["name"] for c in result["checks"] if not c["ok"]], "checks": len(result["checks"])}))
'''


def run_child(mode):
    log = tempfile.mktemp(suffix=".probe.log")
    code = (_CHILD.replace("ROOT_PLACEHOLDER", repr(ROOT)).replace("LIVE_PLACEHOLDER", repr(LIVE)).replace("MODE_PLACEHOLDER", repr(mode)).replace("LOG_PLACEHOLDER", repr(log)))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=PROBE, TSPROBE_FORCE="1", TSPROBE_LOG=log, PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT, timeout=180)
    try:
        lines = [l for l in done.stdout.splitlines() if l.startswith("RESULT ")]
        return done, (json.loads(lines[-1][7:]) if lines else None), log
    finally:
        pass


@unittest.skipUnless(HAS_QT, "PyQt6 is not installed")
class FlowOnTheRealOverlay(unittest.TestCase):
    def test_a_the_flow_passes(self):
        done, result, log = run_child("normal")
        self.addCleanup(lambda: os.path.exists(log) and os.remove(log))
        self.assertIsNotNone(result, done.stderr[-800:])
        self.assertEqual(result["verdict"], "PASS", result)
        self.assertGreaterEqual(result["checks"], 20)

    def test_b_a_broken_interlock_is_a_failed_check(self):
        done, result, log = run_child("interlock")
        self.addCleanup(lambda: os.path.exists(log) and os.remove(log))
        self.assertIsNotNone(result, done.stderr[-800:])
        self.assertEqual(result["verdict"], "FAIL", result)
        self.assertTrue(any("forces the speed limit advance OFF" in name for name in result["failed"]), result["failed"])

    def test_c_keys_that_do_not_arrive_are_inconclusive_not_a_failure(self):
        done, result, log = run_child("dead")
        self.addCleanup(lambda: os.path.exists(log) and os.remove(log))
        self.assertIsNotNone(result, done.stderr[-800:])
        self.assertEqual(result["verdict"], "INCONCLUSIVE", result)


class ProbeAndParser(unittest.TestCase):
    def test_d_the_probe_does_nothing_without_a_log_variable(self):
        log = tempfile.mktemp(suffix=".probe.log")
        env = {k: v for k, v in os.environ.items() if not k.startswith("TSPROBE")}
        env["PYTHONPATH"] = PROBE
        done = subprocess.run([sys.executable, "-B", "-c", "import sitecustomize, threading; print(len(threading.enumerate()))"], capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "1", "the probe must not start a thread without TSPROBE_LOG")
        self.assertFalse(os.path.exists(log))

    def test_e_the_parser_reads_the_lines_the_probe_writes(self):
        sys.path.insert(0, LIVE)
        import f1_flow
        e = f1_flow.parse_line("15:38:25.615 t=428656.0 ENTER state=6->10 cursor=6 cursor_after=0 dur=0.29 stations=43 disp=11111111")
        self.assertEqual(e["kind"], "ENTER")
        self.assertEqual(e["kv"]["state"], "6->10")
        self.assertEqual(e["kv"]["disp"], "11111111")
        self.assertIsNone(f1_flow.parse_line("not a probe line"))


if __name__ == "__main__":
    unittest.main()
