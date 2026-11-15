"""KF-FIX (Owner 2026-11-15, O-4): the explicit TEST FIXTURE contract for the formal Legacy TelemetryA DLL. This module is a helper, not a test (its name does not match test*.py).

What it is
  * The tests that need the built Legacy TelemetryA DLL (the LJX-1 served plane, the plane interop 2A, the artifact guard fixture identity) take it from ONE place,
        tests/fixtures/legacy-telemetry-a/TScoring.TelemetryA.dll            (+ .capability.json sidecar + fixture-manifest.json)
    which is NOT tracked by Git (the DLL is a build artifact, never a source). It is placed explicitly from the formal build artifact by `place` below, and ONLY if its SHA-256
    is the SHA-256 of the baseline of the Capability ledger (package/capabilities/TScoring.TelemetryA.json).
  * `TsScoringPlugin/Handshake/Telemetry/Legacy/out/` is a scratch folder of the builds. It is NEVER read by this contract: an arbitrary DLL there is not evidence of anything
    (the one that used to be there, E40D271C, was a copy of an old Jump ON build).

Outcomes (never mixed with a product failure)
  * fixture absent, normal development run          -> unittest.SkipTest("PRECONDITION-MISSING: ...")           (skipped, reported by the runner as PRECONDITION-MISSING)
  * fixture absent, release gate (TS_RELEASE_GATE=1) -> AssertionError("[PRECONDITION] PRECONDITION-MISSING ...")  (a FAIL of the gate; the runner counts it as a PRECONDITION failure,
                                                                                                                     not as a product failure)
  * fixture present but it is not the ledger baseline / its manifest is wrong -> AssertionError("[PRECONDITION] PRECONDITION-MISMATCH ...") in both modes (a wrong artifact is never used)

Command line (read-only except `place`, which writes only under tests/fixtures/legacy-telemetry-a/):
    python tests/fixture_support.py check
    python tests/fixture_support.py place --dll <formal TScoring.TelemetryA.dll> [--sidecar <its .capability.json>]
"""
import argparse
import hashlib
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE_DIR = os.path.join(HERE, "fixtures", "legacy-telemetry-a")
DLL_NAME = "TScoring.TelemetryA.dll"
FIXTURE_DLL = os.path.join(FIXTURE_DIR, DLL_NAME)
FIXTURE_SIDECAR = FIXTURE_DLL + ".capability.json"
FIXTURE_MANIFEST = os.path.join(FIXTURE_DIR, "fixture-manifest.json")
LEDGER = os.path.join(ROOT, "package", "capabilities", "TScoring.TelemetryA.json")
RELEASE_GATE_ENV = "TS_RELEASE_GATE"
MISSING = "PRECONDITION-MISSING"
MISMATCH = "PRECONDITION-MISMATCH"
PRECONDITION_PREFIX = "[PRECONDITION]"


def release_gate():
    return os.environ.get(RELEASE_GATE_ENV, "") == "1"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ledger_baseline():
    """The baseline record of the Capability ledger (the only authority for what the fixture must be)."""
    return read_json(LEDGER)["baseline"]


def inspect():
    """(state, detail): state is 'ok', MISSING or MISMATCH. Looks only under tests/fixtures/legacy-telemetry-a/ (never at out/)."""
    if not os.path.isfile(FIXTURE_DLL):
        return MISSING, "no %s (place it with: python tests/fixture_support.py place --dll <formal build artifact>)" % os.path.relpath(FIXTURE_DLL, ROOT)
    base = ledger_baseline()["sha256"].upper()
    actual = sha256_file(FIXTURE_DLL)
    if actual != base:
        return MISMATCH, "fixture SHA-256 %s is not the ledger baseline %s" % (actual[:8], base[:8])
    if not os.path.isfile(FIXTURE_MANIFEST):
        return MISSING, "no fixture-manifest.json next to the fixture DLL"
    try:
        manifest = read_json(FIXTURE_MANIFEST)
    except Exception:
        return MISMATCH, "fixture-manifest.json is unreadable"
    if str(manifest.get("sha256", "")).upper() != actual or str(manifest.get("ledgerBaselineSha256", "")).upper() != base:
        return MISMATCH, "fixture-manifest.json does not describe this DLL / this ledger baseline"
    return "ok", actual


def _raise_for(state, detail):
    if state == "ok":
        return
    text = "%s %s: %s" % (PRECONDITION_PREFIX, state, detail)
    if state == MISSING and not release_gate():
        raise unittest.SkipTest("%s: %s" % (state, detail))
    raise AssertionError(text + (" (release gate)" if release_gate() else ""))


def require_telemetry_a():
    """The path of the fixture DLL, or a skip / a precondition failure (see the module docstring). Never falls back to out/."""
    _raise_for(*inspect())
    return FIXTURE_DLL


def require_sidecar():
    """The sidecar of the fixture (needed by the artifact guard): same outcomes as require_telemetry_a."""
    require_telemetry_a()
    if not os.path.isfile(FIXTURE_SIDECAR):
        _raise_for(MISSING, "no %s" % os.path.basename(FIXTURE_SIDECAR))
    return FIXTURE_SIDECAR


def place(dll, sidecar=None):
    """Place the formal build artifact as the fixture. Refuses (ValueError) anything whose SHA-256 is not the ledger baseline. Writes only under FIXTURE_DIR."""
    base = ledger_baseline()["sha256"].upper()
    actual = sha256_file(dll)
    if actual != base:
        raise ValueError("refused: %s has SHA-256 %s, the ledger baseline is %s" % (dll, actual[:8], base[:8]))
    if sidecar is not None:
        side = read_json(sidecar)
        if str(side.get("sha256", "")).upper() != actual:
            raise ValueError("refused: the sidecar describes %s, not %s" % (str(side.get("sha256", ""))[:8], actual[:8]))
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    with open(dll, "rb") as src, open(FIXTURE_DLL, "wb") as dst:
        dst.write(src.read())
    if sidecar is not None:
        with open(sidecar, "rb") as src, open(FIXTURE_SIDECAR, "wb") as dst:
            dst.write(src.read())
    manifest = {"schema": "ts-test-fixture/1", "component": "TScoring.TelemetryA", "sha256": actual, "sizeBytes": os.path.getsize(FIXTURE_DLL),
                "sourcePath": os.path.abspath(dll), "sidecarPlaced": sidecar is not None, "ledgerBaselineSha256": base,
                "placedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": "test fixture only; the formal artifact is the build output + the Capability ledger, never this copy"}
    with open(FIXTURE_MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description="KF-FIX test fixture contract for the formal Legacy TelemetryA DLL")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p = sub.add_parser("place")
    p.add_argument("--dll", required=True)
    p.add_argument("--sidecar")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        state, detail = inspect()
        print("%s %s" % (state, detail))
        return 0 if state == "ok" else 1
    try:
        manifest = place(args.dll, args.sidecar)
    except ValueError as exc:
        print(str(exc))
        return 1
    print("placed %s (%d bytes) from %s" % (manifest["sha256"][:8], manifest["sizeBytes"], manifest["sourcePath"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
