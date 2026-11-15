"""KF-FIX (Owner 2026-11-15, O-6): which quality suite a test belongs to. A helper, not a test (its name does not match test*.py).

  S1  deterministic regular product regression (headless; fake GUI / recorder rigs, AST / document / contract checks, offscreen Qt). The default. Expected result: FAIL 0.
  S2  Windows real-desktop / Z-order regression: real windows, real foreground, real window geometry / DPI. It is a FORMAL quality gate of its own (not optional), but it
      depends on the state of the desktop, so its result is counted SEPARATELY and never mixed into the product failure count of S1.
  S3  BVE live acceptance (manual / Owner operation; Test-ArtifactIdentity, the live checklists). Not unittest-runnable headless.

A test is S2 when its class or function carries @desktop_only("<why>"). The suite is selected by the environment variable TS_SUITE:
    TS_SUITE=s1   S2 tests are skipped with "SUITE-DESKTOP: ..." (the S1 run; the runner reports those skips as S2 members, not as a defect)
    TS_SUITE=s2   everything runs (the runner passes the explicit list of S2 test ids, taken from the marker `__ts_suite__`)
    unset         everything runs (the historical `python -m unittest discover` behaviour)
"""
import os
import unittest

SUITE_ENV = "TS_SUITE"
S2 = "S2"


def current_suite():
    return (os.environ.get(SUITE_ENV, "") or "").strip().lower() or "all"


def desktop_only(reason):
    """Mark a class / function as S2 (real desktop). Under TS_SUITE=s1 it is skipped with the prefix SUITE-DESKTOP."""
    def decorate(obj):
        obj.__ts_suite__ = S2
        obj.__ts_suite_reason__ = reason
        if current_suite() == "s1":
            return unittest.skip("SUITE-DESKTOP: " + reason)(obj)
        return obj
    return decorate
