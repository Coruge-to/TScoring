"""Phase H-1 (Owner 2026-11-17): the heartbeat of the Current Telemetry (Class1.cs, ScoringPlugin) does not read the host from its timer thread.

The behaviour is proven by Handshake/Tests/Test-HeartbeatBveReadH1.ps1 (a PowerShell fixture on the built DLL: RED on the DLL before H-1, GREEN after; 7 mutants killed, 1 equivalent). These pins keep the SOURCE shape
the fixture cannot reach (the constructor, Dispose, the handler body):
  S-1  HeartbeatTimer_Elapsed and ComposeHeartbeat contain no BveHacker access (the host is read on the UI thread only: the constructor seed and the scenario events)
  S-2  the constructor seeds the flag from the host ONCE and subscribes the three scenario events also when there is no synchronization context; only the pulse timer needs the context
  S-3  Dispose raises heartbeatDisposed as its first statement; the handler checks it before composing and before sending
  S-4  the scenario event handlers set / clear the flag (Opened, Closed -> false; Created -> true) and still feed the gate
  S-5  heartbeatScenarioActive and heartbeatDisposed are volatile (written on the UI thread, read on the pool thread)
  S-6  the datagram text and the 100 ms rule are unchanged (STATUS:LOADED:PAUSED / RUNNING; send through the router only with a client and a router)
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASS1 = os.path.join(ROOT, "TsScoringPlugin", "TsScoringPlugin", "Class1.cs")


def method_body(src, signature):
    i = src.index(signature)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError("unbalanced " + signature)


class H1_Source(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CLASS1, encoding="utf-8") as f:
            cls.src = f.read()
        cls.handler = method_body(cls.src, "private void HeartbeatTimer_Elapsed(")
        cls.compose = method_body(cls.src, "internal static byte[] ComposeHeartbeat(")
        cls.dispose = method_body(cls.src, "public override void Dispose()")

    def test_S_1_the_heartbeat_does_not_access_the_host(self):
        for name, body in (("HeartbeatTimer_Elapsed", self.handler), ("ComposeHeartbeat", self.compose)):
            self.assertNotIn("BveHacker", body, name)
            self.assertNotIn("IsScenarioCreated", body, name)

    def test_S_2_the_constructor_seeds_once_and_subscribes_without_a_context(self):
        i = self.src.index("pulseContext = System.Threading.SynchronizationContext.Current;")
        block = self.src[i:i + 1800]
        subscribe = block.index("BveHacker.ScenarioOpened += OnPulseScenarioOpened;")
        context_if = block.index("if (pulseContext != null)")
        self.assertLess(subscribe, context_if, "the events are subscribed BEFORE (outside) the context condition")
        self.assertLess(block.index("BveHacker.ScenarioCreated += OnPulseScenarioCreated;"), context_if)
        self.assertLess(block.index("pulseEventsSubscribed = true;"), context_if)
        self.assertIn("if (BveHacker.IsScenarioCreated) { heartbeatScenarioActive = true; pulseGate.OnScenarioCreated(); }", block)
        timer = block.index("pulseTimer = new System.Threading.Timer(")
        self.assertGreater(timer, context_if, "the pulse TIMER is still created only with a context, after the events (S05 fail closed)")
        # the host is read for the heartbeat at ONE place only: the constructor seed
        seed = [m.start() for m in re.finditer(r"heartbeatScenarioActive = true; pulseGate\.OnScenarioCreated\(\)", self.src)]
        self.assertEqual(len(seed), 1)

    def test_S_3_dispose_raises_the_flag_first_and_the_handler_checks_it_twice(self):
        inner = self.dispose[self.dispose.index("{") + 1:].lstrip()
        first = inner.split("\n", 1)[0].strip()
        self.assertTrue(first.startswith("heartbeatDisposed = true;"), first)
        self.assertEqual(self.handler.count("if (heartbeatDisposed) return;"), 2)
        self.assertLess(self.handler.index("if (heartbeatDisposed) return;"), self.handler.index("ComposeHeartbeat("))
        last = self.handler.rindex("if (heartbeatDisposed) return;")
        self.assertLess(last, self.handler.index(".Send("))

    def test_S_4_the_event_handlers_drive_the_flag_and_still_feed_the_gate(self):
        for name, value, call in (("OnPulseScenarioOpened(ScenarioOpenedEventArgs e)", "false", "pulseGate.OnScenarioOpenedOrClosed();"),
                                  ("OnPulseScenarioClosed(EventArgs e)", "false", "pulseGate.OnScenarioOpenedOrClosed();"),
                                  ("OnPulseScenarioCreated(ScenarioCreatedEventArgs e)", "true", "pulseGate.OnScenarioCreated();")):
            body = method_body(self.src, "private void " + name)
            self.assertIn("heartbeatScenarioActive = %s;" % value, body, name)
            self.assertIn(call, body, name)

    def test_S_5_the_two_flags_are_volatile(self):
        self.assertIn("private volatile bool heartbeatScenarioActive;", self.src)
        self.assertIn("private volatile bool heartbeatDisposed;", self.src)

    def test_S_6_the_datagram_and_the_100_ms_rule_are_unchanged(self):
        self.assertIn('(now - lastTick).TotalMilliseconds > 100;', self.compose)
        self.assertIn('string statusSuffix = isPaused ? "PAUSED" : "RUNNING";', self.compose)
        self.assertIn('Encoding.UTF8.GetBytes($"STATUS:LOADED:{statusSuffix}")', self.compose)
        self.assertIn("if (udpClient != null && currentRouter != null) currentRouter.Begin().Send(TSScoringPlugin.DataPlane.DataPlaneMessageTypes.Heartbeat, hbBytes);", self.handler)
        self.assertIn("heartbeatTimer = new Timer(50);", self.src)


if __name__ == "__main__":
    unittest.main()
