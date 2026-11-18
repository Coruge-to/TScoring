"""OD-X11 v2 (Owner 2026-11-15): the formal TelemetryA is a Jump ON build, and the BUILT artifact is guarded by package/artifact_guard.py (separate from package/source_package.py).

  A  source contract: the csproj default is Jump ON, Jump OFF needs three conditions (guard target), AssemblyMetadata, the formal build script has no LegacyJumpExec parameter
  B  the guard stages build / accept / deploy / promote / rollback (injected capability reader + a temporary ledger)
  C  the real old DLLs (17CA7159 Jump OFF, EDEB5766 Jump ON without metadata) are REJECTED as formal candidates (skipped when the evidence copies are absent)
  D  the MSBuild contract matrix on the real csproj (skipped when MSBuild is absent)
  E  the ledger, the scripts (ASCII-only, PowerShell parse)
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "package")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import artifact_guard as G  # noqa: E402

TOOLS = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Tools")
CSPROJ = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "TSScoringPlugin.AtsExLegacy.Telemetry.csproj")
MSBUILD = r"C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe"
EVIDENCE = r"C:\Users\tsuru\Documents\TS-Scoring-Claude-Handoff\csender-range-v1-20261115"
SHA_ON = "A" * 64
SHA_OTHER = "B" * 64
COMMIT = "0f7c1827e9281fad97ca5f5c2a3c43de97e5545a"


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def formal_cap(sha=SHA_ON, **over):
    cap = {"ok": True, "sha256": sha, "sizeBytes": 180736, "assemblyName": "TScoring.TelemetryA", "assemblyVersion": "0.14.0.0", "executionCompiledIn": True, "featureBits": 7, "jumpCapabilityAdvertised": True,
           "metadata": {"TScoring.LegacyJumpExec": "true", "TScoring.BuildRole": "Formal"}, "capabilityTokens": ["ACCELZ", "PTPAIR", "PseudoTurnbackPairCodec"]}
    cap.update(over)
    return cap


# The ledger as committed with the OD-X11 v2 contract (70e45cb): no history, the Jump OFF 17CA7159 baseline. The stage tests run from this frozen
# initial state, not from the live repository ledger, which moves on at every promote (the first promote of D6E6E324 on 2026-11-15).
INITIAL_LEDGER = json.loads(r'''{
  "schema": "ts-capability-ledger/1",
  "component": "TScoring.TelemetryA",
  "host": "Legacy",
  "contract": {
    "legacyJumpExec": true,
    "buildRole": "Formal",
    "jumpCapabilityAdvertised": true,
    "minFeatureBits": 1,
    "requiredTokens": [
      "ACCELZ",
      "PTPAIR",
      "PseudoTurnbackPairCodec"
    ],
    "note": "OD-X11 v2 (Owner 2026-11-15): the formal TelemetryA has the Legacy Jump execution ON. Jump OFF is a diagnostic / comparison build only and is never a formal candidate, deployed under the formal name or promoted."
  },
  "baseline": {
    "sha256": "17CA7159C4C6F891CC4EF626047A44180F1001668393AAA70A6C2647C9185C17",
    "sourceCommit": "721510833e3b5597f3b905251379838b95eed329",
    "sizeBytes": 180736,
    "capabilities": {
      "legacyJumpExec": false,
      "executionCompiledIn": false,
      "jumpCapabilityAdvertised": false,
      "featureBits": 0,
      "buildRole": "",
      "tokens": [
        "ACCELZ",
        "PTPAIR",
        "PseudoTurnbackPairCodec"
      ]
    },
    "promotedAt": "2026-11-15 (debt A Global Final Close)",
    "closeRef": "hud-semantics-fix-v1-20261114-1/global-final-close.md",
    "contractCompliant": false,
    "regression": "Jump OFF (built without /p:LegacyJumpExec=true); the 2026-11-10 baseline 9F0B0919 was Jump ON. Superseded by the first OD-X11 v2 formal promote."
  },
  "history": [],
  "rollbackAssets": [
    {
      "sha256": "17CA7159C4C6F891CC4EF626047A44180F1001668393AAA70A6C2647C9185C17",
      "capabilities": {
        "legacyJumpExec": false,
        "executionCompiledIn": false,
        "jumpCapabilityAdvertised": false,
        "featureBits": 0,
        "buildRole": "",
        "tokens": [
          "ACCELZ",
          "PTPAIR",
          "PseudoTurnbackPairCodec"
        ]
      },
      "path": "csender-range-v1-20261115/candidate/TScoring.TelemetryA.dll",
      "note": "current baseline before OD-X11 v2; Jump OFF; kept as capability-regression evidence, guard RED input and rollback asset (a rollback to it loses the Jump capability of any v2 baseline: Owner approval id required)"
    },
    {
      "sha256": "EDEB5766BEAF1C7E6F8974828001E7AFF885BB4C92092735B398DC891C89D640",
      "capabilities": {
        "legacyJumpExec": true,
        "executionCompiledIn": true,
        "jumpCapabilityAdvertised": true,
        "featureBits": 7,
        "buildRole": "",
        "tokens": [
          "ACCELZ",
          "PTPAIR",
          "PseudoTurnbackPairCodec"
        ]
      },
      "path": "csender-range-v1-20261115/candidate-ljx/TScoring.TelemetryA.dll",
      "note": "acceptance build of 7215108 (Jump ON, no AssemblyMetadata); not a formal candidate under OD-X11 v2; kept as evidence"
    },
    {
      "sha256": "B0640455305E2C99D0DB6D560E11570B5705B6A21434079079EF52A5C5540220",
      "capabilities": {
        "legacyJumpExec": false,
        "executionCompiledIn": false,
        "jumpCapabilityAdvertised": false,
        "featureBits": 0,
        "buildRole": "",
        "tokens": [
          "ACCELZ",
          "PTPAIR",
          "PseudoTurnbackPairCodec"
        ]
      },
      "path": "csender-range-v1-20261115/dll-baseline/TScoring.TelemetryA.dll",
      "note": "PP-13 baseline (2026-11-14); Jump OFF; kept as capability-regression evidence"
    }
  ]
}''')


class Env(object):
    """A temporary directory with a ledger, a fake DLL file and its sidecar; the capability reader is injected (a dict by file name)."""

    def __init__(self, test):
        self.dir = tempfile.mkdtemp(prefix="ts-artifact-")
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.ledger_path = os.path.join(self.dir, "ledger.json")
        G.write_json(self.ledger_path, json.loads(json.dumps(INITIAL_LEDGER)))
        self.caps = {}

    def dll(self, name="TScoring.TelemetryA.dll", cap=None, sidecar=True, sidecar_over=None):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as fh:
            fh.write(b"fake dll " + name.encode())
        cap = cap or formal_cap()
        self.caps[path] = cap
        if sidecar:
            side = {"schema": G.SIDECAR_SCHEMA, "component": "TScoring.TelemetryA", "host": "Legacy", "sourceCommit": COMMIT, "configuration": "Release", "buildRole": "Formal", "legacyJumpExec": True,
                    "executionCompiledIn": True, "featureBits": cap.get("featureBits"), "jumpCapabilityAdvertised": True, "sha256": cap.get("sha256"), "sizeBytes": cap.get("sizeBytes"), "rootsMatched": True,
                    "formalCandidate": True}
            side.update(sidecar_over or {})
            G.write_json(G.sidecar_path(path), side)
        return path

    def reader(self, path):
        return self.caps.get(path, {"ok": False, "error": "unknown-file"})

    def check(self, stage, dll, **kw):
        kw.setdefault("ledger_path", self.ledger_path)
        kw.setdefault("reader", self.reader)
        kw.setdefault("git_check", lambda commit, ref: True)
        verdict, rec = G.check(stage, dll, **kw)
        return verdict, rec

    def record(self, stage, dll, **kw):
        verdict, rec = self.check(stage, dll, **kw)
        assert verdict.accepted, verdict.lines()
        return G.record(stage, rec, self.ledger_path, "test", kw.get("owner_approval"), "t")

    def codes(self, verdict):
        return sorted(c for c, _ in verdict.findings)


class A_SourceContract(unittest.TestCase):
    def test_the_source_contract_is_accepted(self):
        self.assertEqual(G.static_findings(), [])

    def test_the_csproj_default_is_jump_on_and_jump_off_is_guarded(self):
        text = read(CSPROJ)
        self.assertIn("<LegacyJumpExec Condition=\"'$(LegacyJumpExec)' == ''\">true</LegacyJumpExec>", text)
        for code in ("TSCORING-JUMP-VALUE", "TSCORING-JUMPOFF-NOT-DIAGNOSTIC", "TSCORING-JUMPOFF-FORMAL-OUTPUT"):
            self.assertIn(code, text)
        self.assertIn("<DefineConstants>TRACE</DefineConstants>", text)                     # the base symbol set carries no Jump symbol
        self.assertIn("TSCORING_DIAGNOSTIC_JUMP_OFF", text)
        self.assertIn("<TScoringBuildRole>Formal</TScoringBuildRole>", text)
        self.assertIn("<TScoringBuildRole>DiagnosticJumpOff</TScoringBuildRole>", text)

    def test_assembly_metadata_pairs_with_the_compile_symbols(self):
        text = read(os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "src", "AssemblyInfo.cs"))
        self.assertRegex(text, r"#if LEGACY_JUMP_EXEC\s+\[assembly: AssemblyMetadata\(\"TScoring\.LegacyJumpExec\", \"true\"\)\]\s+\[assembly: AssemblyMetadata\(\"TScoring\.BuildRole\", \"Formal\"\)\]")
        self.assertRegex(text, r"#elif TSCORING_DIAGNOSTIC_JUMP_OFF\s+\[assembly: AssemblyMetadata\(\"TScoring\.LegacyJumpExec\", \"false\"\)\]\s+\[assembly: AssemblyMetadata\(\"TScoring\.BuildRole\", \"DiagnosticJumpOff\"\)\]")

    def test_the_formal_build_script_fixes_the_property_and_has_no_parameter_for_it(self):
        text = read(os.path.join(TOOLS, "Build-Formal-TelemetryA.ps1"))
        param_block = text[text.index("param("):text.index(")\nSet-StrictMode")]
        self.assertNotIn("LegacyJumpExec", param_block)
        self.assertIn("'/p:LegacyJumpExec=true'", text)
        for needle in ("show --check", "two clean roots", "'fa', 'fb'", "_rejected", "make-sidecar", "check --stage build", "/p:PathMap=", "source_package.py", "package guard"):
            self.assertIn(needle, text, needle)
        self.assertNotIn("diag-jumpoff\\'", text.replace("diag-jumpoff'", "").replace("diag-jumpoff\\", "")) if False else None
        self.assertIn("must not be under a diag-jumpoff folder", text)
        self.assertIn("$rejected = Join-Path $WorkParent '_rejected'", text)                                             # a refused build is parked here, never in the formal output
        self.assertIn("must not be deployed", text)

    def test_the_diagnostic_build_script_is_jump_off_only_and_goes_to_the_diag_folder(self):
        text = read(os.path.join(TOOLS, "Build-Diag-TelemetryA-JumpOff.ps1"))
        self.assertIn("/p:LegacyJumpExec=false", text)
        self.assertIn("/p:TScoringDiagnosticJumpOff=true", text)
        self.assertIn("diag-jumpoff", text)
        self.assertIn("--diagnostic", text)

    def test_the_scripts_are_ascii_only_and_parse_in_windows_powershell(self):
        for name in ("Build-Formal-TelemetryA.ps1", "Build-Diag-TelemetryA-JumpOff.ps1", "Test-ArtifactIdentity.ps1", "Read-TelemetryACapability.ps1"):
            path = os.path.join(TOOLS, name)
            with open(path, "rb") as fh:
                data = fh.read()
            self.assertEqual([b for b in data if b > 127], [], name)
            cmd = "$t=$null;$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e);@($e).Count" % path
            out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True, text=True).stdout.strip()
            self.assertEqual(out, "0", name)


class B_GuardStages(unittest.TestCase):
    def test_build_accepts_a_formal_candidate_and_names_every_reason_it_refuses(self):
        e = Env(self)
        self.assertTrue(e.check("build", e.dll())[0].accepted)
        off = formal_cap(executionCompiledIn=False, featureBits=0, jumpCapabilityAdvertised=False, metadata={"TScoring.LegacyJumpExec": "false", "TScoring.BuildRole": "DiagnosticJumpOff"})
        codes = e.codes(e.check("build", e.dll("off.dll", cap=off))[0])
        for code in ("jump-off", "build-role", "feature-bits", "jump-not-advertised"):
            self.assertIn(code, codes)
        self.assertIn("metadata-missing", e.codes(e.check("build", e.dll("old.dll", cap=formal_cap(metadata={})))[0]))                       # a build before v2 (no metadata)
        self.assertIn("metadata-flag-mismatch", e.codes(e.check("build", e.dll("mm.dll", cap=formal_cap(metadata={"TScoring.LegacyJumpExec": "false", "TScoring.BuildRole": "Formal"})))[0]))
        self.assertIn("sidecar-absent", e.codes(e.check("build", e.dll("ns.dll", sidecar=False))[0]))
        self.assertIn("token-missing", e.codes(e.check("build", e.dll("tk.dll", cap=formal_cap(capabilityTokens=["ACCELZ"])))[0]))
        self.assertIn("capability-unreadable", e.codes(e.check("build", e.dll("bad.dll", cap={"ok": False, "error": "x"}))[0]))
        self.assertIn("dll-absent", e.codes(e.check("build", os.path.join(e.dir, "nope.dll"))[0]))

    def test_the_sidecar_must_say_the_same_as_the_dll(self):
        e = Env(self)
        for over, code in (({"sha256": SHA_OTHER}, "sidecar-sha-mismatch"), ({"sizeBytes": 1}, "sidecar-size-mismatch"), ({"legacyJumpExec": False}, "sidecar-capability"),
                           ({"formalCandidate": False}, "sidecar-not-formal"), ({"buildRole": "DiagnosticJumpOff"}, "sidecar-not-formal"), ({"featureBits": 3}, "sidecar-featurebits-mismatch"),
                           ({"rootsMatched": False}, "sidecar-roots"), ({"sourceCommit": "zz"}, "sidecar-source-commit"), ({"configuration": "Debug"}, "sidecar-configuration"),
                           ({"schema": "x"}, "sidecar-schema"), ({"jumpCapabilityAdvertised": False}, "sidecar-not-advertised")):
            with self.subTest(code=code, over=over):
                self.assertIn(code, e.codes(e.check("build", e.dll("s.dll", sidecar_over=over))[0]))

    def test_the_diagnostic_jump_off_build_is_rejected_at_every_stage(self):
        e = Env(self)
        off = formal_cap(sha=SHA_OTHER, executionCompiledIn=False, featureBits=0, jumpCapabilityAdvertised=False, metadata={"TScoring.LegacyJumpExec": "false", "TScoring.BuildRole": "DiagnosticJumpOff"})
        dll = e.dll("diag.dll", cap=off, sidecar_over={"legacyJumpExec": False, "executionCompiledIn": False, "buildRole": "DiagnosticJumpOff", "formalCandidate": False, "featureBits": 0, "jumpCapabilityAdvertised": False})
        for stage in ("build", "accept", "deploy", "promote"):
            self.assertFalse(e.check(stage, dll, deployed=dll, remote_ref="origin/x")[0].accepted, stage)

    def test_the_stages_require_the_previous_ones_with_the_same_sha_and_capabilities(self):
        e = Env(self)
        dll = e.dll()
        self.assertIn("build-entry-missing", e.codes(e.check("accept", dll)[0]))
        e.record("build", dll)
        self.assertTrue(e.check("accept", dll)[0].accepted)
        self.assertIn("accept-entry-missing", e.codes(e.check("deploy", dll)[0]))
        e.record("accept", dll)
        self.assertTrue(e.check("deploy", dll)[0].accepted)
        self.assertIn("deploy-entry-missing", e.codes(e.check("promote", dll, deployed=dll, remote_ref="origin/x")[0]))
        e.record("deploy", dll)
        self.assertTrue(e.check("promote", dll, deployed=dll, remote_ref="origin/x")[0].accepted)

    def test_promote_compares_the_deployed_file_and_the_remote(self):
        e = Env(self)
        dll = e.dll()
        for stage in ("build", "accept", "deploy"):
            e.record(stage, dll)
        other = e.dll("deployed-other.dll", cap=formal_cap(sha=SHA_OTHER))
        self.assertIn("deployed-sha-differs", e.codes(e.check("promote", dll, deployed=other, remote_ref="origin/x")[0]))
        self.assertIn("deployed-path-missing", e.codes(e.check("promote", dll, remote_ref="origin/x")[0]))
        weaker = e.dll("deployed-weaker.dll", cap=formal_cap(featureBits=3))
        self.assertIn("deployed-capability-differs", e.codes(e.check("promote", dll, deployed=weaker, remote_ref="origin/x")[0]))
        self.assertIn("remote-ref-missing", e.codes(e.check("promote", dll, deployed=dll)[0]))
        self.assertIn("source-not-on-remote", e.codes(e.check("promote", dll, deployed=dll, remote_ref="origin/x", git_check=lambda c, r: False)[0]))

    def test_a_ledger_entry_of_another_capability_set_is_not_a_previous_stage(self):
        e = Env(self)
        dll = e.dll()
        e.record("build", dll)
        ledger = G.read_json(e.ledger_path)
        ledger["history"][0]["capabilities"]["featureBits"] = 3
        G.write_json(e.ledger_path, ledger)
        self.assertIn("build-capability-differs", e.codes(e.check("accept", dll)[0]))

    def test_no_capability_of_the_baseline_may_be_lost_without_an_owner_approval(self):
        e = Env(self)
        ledger = G.read_json(e.ledger_path)
        ledger["baseline"]["capabilities"] = {"legacyJumpExec": True, "executionCompiledIn": True, "jumpCapabilityAdvertised": True, "featureBits": 15, "buildRole": "Formal", "tokens": ["ACCELZ", "PTPAIR", "PseudoTurnbackPairCodec", "EXTRA"]}
        G.write_json(e.ledger_path, ledger)
        dll = e.dll()
        e.record("build", dll)
        e.record("accept", dll)
        codes = e.codes(e.check("deploy", dll)[0])
        self.assertIn("capability-regression", codes)
        self.assertTrue(e.check("deploy", dll, owner_approval="OWNER-APPROVAL-1")[0].accepted)

    def test_rollback_needs_a_registered_asset_and_does_not_lose_capability_silently(self):
        e = Env(self)
        ledger = G.read_json(e.ledger_path)
        ledger["baseline"]["capabilities"] = {"legacyJumpExec": True, "executionCompiledIn": True, "jumpCapabilityAdvertised": True, "featureBits": 7, "buildRole": "Formal", "tokens": ["ACCELZ", "PTPAIR", "PseudoTurnbackPairCodec"]}
        G.write_json(e.ledger_path, ledger)
        asset_cap = formal_cap(sha=G.read_json(e.ledger_path)["rollbackAssets"][0]["sha256"], executionCompiledIn=False, featureBits=0, jumpCapabilityAdvertised=False,
                               metadata={"TScoring.LegacyJumpExec": "false", "TScoring.BuildRole": ""})
        asset = e.dll("asset.dll", cap=asset_cap)
        self.assertIn("capability-regression", e.codes(e.check("rollback", asset)[0]))                      # Jump ON -> OFF
        self.assertTrue(e.check("rollback", asset, owner_approval="OWNER-APPROVAL-2")[0].accepted)
        stranger = e.dll("stranger.dll", cap=formal_cap(sha=SHA_OTHER))
        self.assertIn("rollback-asset-unregistered", e.codes(e.check("rollback", stranger)[0]))

    def test_only_a_promote_entry_changes_the_baseline(self):
        e = Env(self)
        before = G.read_json(e.ledger_path)["baseline"]
        dll = e.dll()
        for stage in ("build", "accept", "deploy"):
            e.record(stage, dll)
            self.assertEqual(G.read_json(e.ledger_path)["baseline"], before, stage)
        e.record("promote", dll, deployed=dll, remote_ref="origin/x")
        after = G.read_json(e.ledger_path)["baseline"]
        self.assertEqual(after["sha256"], SHA_ON)
        self.assertTrue(after["capabilities"]["legacyJumpExec"])

    def test_a_build_never_writes_accepted_deployed_or_promoted(self):
        e = Env(self)
        dll = e.dll()
        side = G.read_json(G.sidecar_path(dll))
        for key in ("accepted", "deployed", "promoted"):
            self.assertNotIn(key, side)
        e.record("build", dll)
        self.assertEqual([x["stage"] for x in G.read_json(e.ledger_path)["history"]], ["build"])

    def test_make_sidecar_writes_from_the_dll_and_marks_a_diagnostic_build_not_formal(self):
        e = Env(self)
        dll = e.dll(sidecar=False)
        path, side = G.make_sidecar(dll, COMMIT, "args", "S" * 64, True, False, reader=e.reader)
        self.assertTrue(side["formalCandidate"])
        self.assertEqual(side["sha256"], SHA_ON)
        off = e.dll("off.dll", cap=formal_cap(executionCompiledIn=False, featureBits=0, jumpCapabilityAdvertised=False, metadata={"TScoring.LegacyJumpExec": "false", "TScoring.BuildRole": "DiagnosticJumpOff"}), sidecar=False)
        _, side = G.make_sidecar(off, COMMIT, "args", "S" * 64, False, False, formal=False, reader=e.reader)
        self.assertFalse(side["formalCandidate"])
        self.assertFalse(side["legacyJumpExec"])

    def test_promote_needs_the_accept_entry_itself_not_only_build_and_deploy(self):
        e = Env(self)
        dll = e.dll()
        caps = {"legacyJumpExec": True, "executionCompiledIn": True, "jumpCapabilityAdvertised": True, "featureBits": 7, "buildRole": "Formal", "tokens": ["ACCELZ", "PTPAIR", "PseudoTurnbackPairCodec"]}
        ledger = G.read_json(e.ledger_path)
        ledger["history"] = [{"stage": "build", "sha256": SHA_ON, "capabilities": caps}, {"stage": "deploy", "sha256": SHA_ON, "capabilities": caps}]
        G.write_json(e.ledger_path, ledger)
        self.assertIn("accept-entry-missing", e.codes(e.check("promote", dll, deployed=dll, remote_ref="origin/x")[0]))

    def test_losing_feature_bits_alone_is_a_capability_regression(self):
        e = Env(self)
        ledger = G.read_json(e.ledger_path)
        ledger["baseline"]["capabilities"] = {"legacyJumpExec": True, "executionCompiledIn": True, "jumpCapabilityAdvertised": True, "featureBits": 15, "buildRole": "Formal", "tokens": ["ACCELZ", "PTPAIR", "PseudoTurnbackPairCodec"]}
        G.write_json(e.ledger_path, ledger)
        dll = e.dll()
        e.record("build", dll)
        e.record("accept", dll)
        verdict = e.check("deploy", dll)[0]
        self.assertEqual(e.codes(verdict), ["capability-regression"])
        self.assertIn("featureBits", verdict.findings[0][1])


@unittest.skipUnless(os.path.isfile(os.path.join(EVIDENCE, "candidate", "TScoring.TelemetryA.dll")) and os.path.isfile(G.READER), "the evidence copies of the old DLLs are absent")
class C_RealOldDlls(unittest.TestCase):
    def verdict(self, name):
        dll = os.path.join(EVIDENCE, name, "TScoring.TelemetryA.dll")
        side = os.path.join(tempfile.gettempdir(), "no-such-sidecar.json")
        verdict, rec = G.check("build", dll, sidecar=side)
        return verdict, rec

    def test_17ca7159_the_jump_off_baseline_is_not_a_formal_candidate(self):
        verdict, rec = self.verdict("candidate")
        self.assertTrue(rec["sha256"].startswith("17CA7159"))
        codes = sorted(c for c, _ in verdict.findings)
        for code in ("metadata-missing", "jump-off", "feature-bits", "jump-not-advertised"):
            self.assertIn(code, codes)

    def test_edeb5766_the_acceptance_build_without_metadata_is_not_a_formal_candidate(self):
        verdict, rec = self.verdict("candidate-ljx")
        self.assertTrue(rec["sha256"].startswith("EDEB5766"))
        self.assertTrue(rec["executionCompiledIn"])
        codes = sorted(c for c, _ in verdict.findings)
        self.assertIn("metadata-missing", codes)                       # Jump ON, but it was built before the v2 contract: not a candidate
        self.assertNotIn("jump-off", codes)

    def test_b0640455_the_pp13_baseline_is_jump_off(self):
        verdict, rec = self.verdict("dll-baseline")
        self.assertFalse(rec["executionCompiledIn"])
        self.assertIn("jump-off", [c for c, _ in verdict.findings])


@unittest.skipUnless(os.path.isfile(MSBUILD), "MSBuild is absent")
class D_MsbuildContractMatrix(unittest.TestCase):
    """The REAL csproj, six cases (OD-X11 v2 item 6): unset -> true; true -> true; false + all diagnostic conditions -> false; false with a missing condition / a bad value -> MSBuild Error."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ts-msb-matrix-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self, tag, extra, out_name):
        out = os.path.join(self.tmp, out_name) + "\\"
        cmd = [MSBUILD, CSPROJ, "/t:Rebuild", "/p:Configuration=Release", "/p:OutputPath=" + out, "/p:IntermediateOutputPath=" + os.path.join(self.tmp, "obj-" + tag) + "\\", "/v:minimal", "/nologo", "/nr:false", "/m:1"] + extra
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return p.returncode, p.stdout + p.stderr, os.path.join(out, "TScoring.TelemetryA.dll")

    def capability(self, dll):
        return G.read_dll_capability(dll)

    def test_unset_and_true_are_jump_on_formal_and_identical(self):
        rc1, _, dll1 = self.build("default", [], "out-default")
        rc2, _, dll2 = self.build("true", ["/p:LegacyJumpExec=true"], "out-true")
        self.assertEqual((rc1, rc2), (0, 0))
        c1, c2 = self.capability(dll1), self.capability(dll2)
        for c in (c1, c2):
            self.assertTrue(c["ok"] and c["executionCompiledIn"] and c["jumpCapabilityAdvertised"])
            self.assertEqual(c["metadata"], {"TScoring.LegacyJumpExec": "true", "TScoring.BuildRole": "Formal"})
        self.assertEqual(c1["sha256"], c2["sha256"])

    def test_false_without_the_diagnostic_conditions_is_an_msbuild_error(self):
        rc, out, dll = self.build("false-bare", ["/p:LegacyJumpExec=false"], "out-fbare")
        self.assertNotEqual(rc, 0)
        self.assertIn("TSCORING-JUMPOFF-NOT-DIAGNOSTIC", out)
        self.assertFalse(os.path.exists(dll))
        rc, out, dll = self.build("false-flag", ["/p:LegacyJumpExec=false", "/p:TScoringDiagnosticJumpOff=true"], "out-fflag")
        self.assertNotEqual(rc, 0)
        self.assertIn("TSCORING-JUMPOFF-FORMAL-OUTPUT", out)
        self.assertFalse(os.path.exists(dll))
        rc, out, dll = self.build("maybe", ["/p:LegacyJumpExec=maybe"], "out-maybe")
        self.assertNotEqual(rc, 0)
        self.assertIn("TSCORING-JUMP-VALUE", out)

    def test_false_with_all_conditions_is_the_diagnostic_build_and_the_guard_rejects_it(self):
        rc, out, dll = self.build("diag", ["/p:LegacyJumpExec=false", "/p:TScoringDiagnosticJumpOff=true"], "diag-jumpoff")
        self.assertEqual(rc, 0, out)
        cap = self.capability(dll)
        self.assertFalse(cap["executionCompiledIn"])
        self.assertEqual(cap["metadata"], {"TScoring.LegacyJumpExec": "false", "TScoring.BuildRole": "DiagnosticJumpOff"})
        G.make_sidecar(dll, COMMIT, "diag", "S" * 64, False, False, formal=False)
        verdict, _ = G.check("build", dll)
        self.assertFalse(verdict.accepted)
        self.assertIn("jump-off", [c for c, _ in verdict.findings])


class E_LedgerAndClose(unittest.TestCase):
    def test_the_ledger_is_the_repository_contract_with_the_regression_evidence(self):
        ledger = G.read_json(G.DEFAULT_LEDGER)
        self.assertEqual(ledger["schema"], G.LEDGER_SCHEMA)
        self.assertEqual(ledger["component"], "TScoring.TelemetryA")
        self.assertTrue(ledger["contract"]["legacyJumpExec"])
        self.assertEqual(ledger["contract"]["buildRole"], "Formal")
        by_sha = {a["sha256"][:8]: a for a in ledger["rollbackAssets"]}
        # kept as evidence / guard RED input / rollback assets, none deleted; every earlier baseline stays an ordinary rollback target (a later promote ADDS one: this test no longer needs a hand edit for that)
        self.assertTrue({"17CA7159", "B0640455", "D6E6E324", "EDEB5766", "BEAE0167"} <= set(by_sha), sorted(by_sha))
        # since the first OD-X11 v2 promote (D6E6E324, 2026-11-15) the baseline is a Jump ON formal build and the Jump OFF 17CA7159 is an emergency,
        # capability-losing rollback that needs an Owner approval id and is never selected automatically
        # S05 pulse gate fix (on purpose; Owner 2026-11-16): the baseline moved on to BEAE0167 (source cfb66e1), promoted after the formal live acceptance
        base = ledger["baseline"]
        # 2026-11-18: the expected baseline is no longer a literal here. It is the TelemetryA entry of package/artifact-baselines.json (the single source of truth that baseline_check.py guards), so a raise cannot leave the two out of step.
        manifest = json.load(open(os.path.join(os.path.dirname(os.path.abspath(G.__file__)), "artifact-baselines.json"), encoding="utf-8"))
        expected = [a for a in manifest["artifacts"] if a["name"] == "TScoring.TelemetryA.dll"][0]["baseline"]["sha256"]
        self.assertEqual(base["sha256"].upper(), expected.upper())
        self.assertTrue(base["capabilities"]["legacyJumpExec"])
        self.assertTrue(base["capabilities"]["executionCompiledIn"])
        self.assertEqual(base["capabilities"]["featureBits"], 7)
        self.assertEqual(base["capabilities"]["buildRole"], "Formal")
        self.assertEqual([h["stage"] for h in ledger["history"] if h["sha256"] == base["sha256"]][-1], "promote")                   # the baseline's own last stage is its promote
        self.assertEqual([h["stage"] for h in ledger["history"] if h["sha256"][:8] == "BEAE0167"][-1], "promote")                   # earlier baselines' own promotes stay in the history
        self.assertEqual([h["stage"] for h in ledger["history"] if h["sha256"][:8] == "D6E6E324"][-1], "promote")
        self.assertTrue(by_sha["17CA7159"]["requiresOwnerApprovalId"])
        self.assertFalse(by_sha["17CA7159"]["automaticSelection"])

    def test_the_close_script_is_read_only_and_checks_the_identities(self):
        text = read(os.path.join(TOOLS, "Test-ArtifactIdentity.ps1"))
        for needle in ("ACCEPTED SHA = DEPLOYED SHA = PROMOTED SHA", "ACCEPTED / DEPLOYED / PROMOTED CAPABILITIES", "--stage promote", "--stage rollback", "WER / CrashDump", "ARTIFACT-IDENTITY PASS"):
            self.assertIn(needle, text, needle)
        for forbidden in ("Copy-Item", "Move-Item", "Remove-Item", "Set-Content", "WriteAllText", "WriteAllBytes", "record --stage"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_the_capability_reader_never_executes_the_dll(self):
        text = read(os.path.join(TOOLS, "Read-TelemetryACapability.ps1"))
        self.assertIn("ReflectionOnlyLoad", text)
        self.assertNotIn("Assembly]::Load(", text.replace("ReflectionOnlyLoad(", ""))
        self.assertNotIn("LoadFrom", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
