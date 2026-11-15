"""KF-FIX (Owner 2026-11-15, O-3): the LEDGER-DRIVEN artifact guard test that replaces the fixed SHA pins of `test_guard_protected_dlls_are_byte_identical`.

The authority is package/capabilities/TScoring.TelemetryA.json (the Capability ledger: contract, baseline, build -> accept -> deploy -> accept(live) -> promote history, rollback
assets) judged by package/artifact_guard.py (the DLL is read by reflection, never executed). Nothing in this file contains a SHA of an installed DLL as an expectation: the only
SHA-256 values that matter are the ones the ledger records.

  A  LedgerIntegrity            the ledger itself is consistent (baseline = the promote entry, the stage order, every stage entry is a Jump ON Formal artifact, the contract)       S1
  B  GuardRejectsTheOldArtifacts the guard, run on the REAL ledger with injected readers, rejects the Jump OFF baselines (17CA7159, B0640455), a same-SHA capability loss, a
                                 baseline that lost a feature bit, a missing stage, and accepts the baseline itself                                                                   S1
  C  FixtureIdentity            the explicit test fixture (tests/fixtures/legacy-telemetry-a/, see tests/fixture_support.py) IS the ledger baseline: fixture SHA-256, executionCompiledIn,
                                 featureBits, LegacyJumpExec, BuildRole, formalCandidate (sidecar), tokens, the accepted / deployed / promoted identity chain and no loss of a capability
                                 of the baseline. Absent fixture: PRECONDITION-MISSING (skip) in a development run, a PRECONDITION failure in the release gate (TS_RELEASE_GATE=1).    S1
  D  DeployedIdentity           the DLL INSTALLED on this machine is the ledger baseline (SHA, capabilities, chain). Reads a file outside the repository, so it is a post-deployment
                                 gate (S3): it runs only with TS_RELEASE_GATE=1 or TS_CHECK_DEPLOYED=1. A FAIL here is NEVER a known failure and never goes into a baseline file.   S3

The reflection reader (Tools/Read-TelemetryACapability.ps1, Windows PowerShell) is the same one the guard uses; a reader that cannot run is a refusal ("unknown = not accepted"), so
in C and D a reader failure is a FAIL, not a skip.
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "package"), HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import artifact_guard as G  # noqa: E402
import fixture_support as FX  # noqa: E402

DEPLOYED = os.environ.get("TS_DEPLOYED_TELEMETRYA", r"C:\Users\Public\Documents\BveEx\Legacy\Extensions\TScoring.TelemetryA.dll")


def ledger():
    return G.read_json(G.DEFAULT_LEDGER)


def reader_from(caps, sha, size=181248, assembly="TScoring.TelemetryA"):
    """An injected reader answering what the reflection reader would answer for an artifact with the capability record `caps` (the shape of the ledger / sidecar)."""
    def read(_path):
        return {"ok": True, "sha256": sha, "sizeBytes": size, "assemblyName": assembly, "assemblyVersion": "0.14.0.0",
                "executionCompiledIn": bool(caps["executionCompiledIn"]), "featureBits": int(caps["featureBits"]), "jumpCapabilityAdvertised": bool(caps["jumpCapabilityAdvertised"]),
                "metadata": ({"TScoring.LegacyJumpExec": "true" if caps["legacyJumpExec"] else "false", "TScoring.BuildRole": caps["buildRole"]} if caps["buildRole"] else {}),
                "capabilityTokens": list(caps["tokens"])}
    return read


def sidecar_for(tmp, rec_sha, caps, commit):
    path = os.path.join(tmp, "x.dll.capability.json")
    side = {"schema": G.SIDECAR_SCHEMA, "component": "TScoring.TelemetryA", "host": "Legacy", "sourceCommit": commit, "configuration": "Release", "msbuildArgs": "t", "buildScriptSha256": "S" * 64,
            "buildRole": caps["buildRole"], "legacyJumpExec": caps["legacyJumpExec"], "executionCompiledIn": caps["executionCompiledIn"], "featureBits": caps["featureBits"],
            "jumpCapabilityAdvertised": caps["jumpCapabilityAdvertised"], "capabilityTokens": caps["tokens"], "sha256": rec_sha, "sizeBytes": 181248, "rootsMatched": True,
            "sourceOnRemoteAtBuild": True, "formalCandidate": caps["legacyJumpExec"] and caps["buildRole"] == "Formal", "builtAtUtc": ""}
    G.write_json(path, side)
    return path


class A_LedgerIntegrity(unittest.TestCase):
    def setUp(self):
        self.ledger = ledger()

    def test_the_ledger_has_the_schema_the_component_and_the_formal_contract(self):
        L = self.ledger
        self.assertEqual(L["schema"], G.LEDGER_SCHEMA)
        self.assertEqual(L["component"], "TScoring.TelemetryA")
        c = L["contract"]
        self.assertIs(c["legacyJumpExec"], True)
        self.assertEqual(c["buildRole"], "Formal")
        self.assertIs(c["jumpCapabilityAdvertised"], True)
        self.assertGreaterEqual(int(c["minFeatureBits"]), 1)
        self.assertEqual(sorted(c["requiredTokens"]), ["ACCELZ", "PTPAIR", "PseudoTurnbackPairCodec"])

    def test_the_baseline_is_a_formal_jump_on_artifact_and_equals_the_last_promote_entry(self):
        L = self.ledger
        base = L["baseline"]
        promotes = [h for h in L["history"] if h["stage"] == "promote"]
        self.assertTrue(promotes, "the baseline changes ONLY by a promote entry")
        last = promotes[-1]
        self.assertEqual(base["sha256"], last["sha256"])
        self.assertEqual(base["sourceCommit"], last["sourceCommit"])
        self.assertEqual(base["capabilities"], last["capabilities"])
        caps = base["capabilities"]
        self.assertIs(caps["legacyJumpExec"], True)
        self.assertIs(caps["executionCompiledIn"], True)
        self.assertIs(caps["jumpCapabilityAdvertised"], True)
        self.assertEqual(caps["buildRole"], "Formal")
        self.assertGreaterEqual(caps["featureBits"], int(L["contract"]["minFeatureBits"]))
        for token in L["contract"]["requiredTokens"]:
            self.assertIn(token, caps["tokens"])
        self.assertRegex(base["sha256"], r"^[0-9A-F]{64}$")
        self.assertTrue(base.get("promotedAt") and base.get("closeRef"))

    def test_the_baseline_went_through_build_accept_deploy_live_accept_promote_in_this_order_with_the_same_sha_and_capabilities(self):
        L = self.ledger
        sha = L["baseline"]["sha256"]
        stages = [h for h in L["history"] if h["sha256"] == sha]
        order = [h["stage"] for h in stages]
        i = 0
        for want in ("build", "accept", "deploy", "accept", "promote"):          # accept twice: the pre-deployment acceptance and the LIVE acceptance after the deployment
            while i < len(order) and order[i] != want:
                i += 1
            self.assertLess(i, len(order), "stage %r is missing (in order) for the baseline: %s" % (want, order))
            i += 1
        for h in stages:
            self.assertEqual(h["capabilities"], L["baseline"]["capabilities"], h["stage"])
            self.assertEqual(h["sourceCommit"], L["baseline"]["sourceCommit"], h["stage"])

    def test_every_stage_entry_of_the_history_is_a_formal_jump_on_artifact(self):
        L = self.ledger
        c = L["contract"]
        for h in L["history"]:
            caps = h["capabilities"]
            self.assertIs(caps["legacyJumpExec"], c["legacyJumpExec"], h)
            self.assertIs(caps["executionCompiledIn"], True, h)
            self.assertEqual(caps["buildRole"], c["buildRole"], h)
            self.assertGreaterEqual(caps["featureBits"], int(c["minFeatureBits"]), h)
            for token in c["requiredTokens"]:
                self.assertIn(token, caps["tokens"], h)

    def test_the_jump_off_assets_are_rollback_assets_only_never_a_stage_entry(self):
        L = self.ledger
        stage_shas = {h["sha256"] for h in L["history"]}
        for asset in L["rollbackAssets"]:
            caps = asset["capabilities"]
            if not caps["executionCompiledIn"]:
                self.assertNotIn(asset["sha256"], stage_shas, "a Jump OFF artifact must never appear as build / accept / deploy / promote: " + asset["sha256"][:8])
        self.assertNotEqual(L["baseline"]["sha256"], "17CA7159C4C6F891CC4EF626047A44180F1001668393AAA70A6C2647C9185C17")


class B_GuardRejectsTheOldArtifacts(unittest.TestCase):
    """The artifact guard on the REAL ledger with injected readers (no DLL, no machine state): the RED side of the guard."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp(prefix="ts-guard-")
        cls.L = ledger()
        cls.base = cls.L["baseline"]

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def promote(self, caps, sha, deployed_caps=None, deployed_sha=None, ledger_path=None, owner_approval=None):
        dll = os.path.join(self.tmp, "x.dll")
        open(dll, "wb").close()
        side = sidecar_for(self.tmp, sha, caps, self.base["sourceCommit"])
        deployed = os.path.join(self.tmp, "deployed.dll")
        open(deployed, "wb").close()
        calls = {dll: reader_from(caps, sha), deployed: reader_from(deployed_caps or caps, deployed_sha or sha)}
        verdict, rec = G.check("promote", dll, sidecar=side, ledger_path=ledger_path or G.DEFAULT_LEDGER, deployed=deployed, remote_ref="x", owner_approval=owner_approval,
                               reader=lambda p: calls[p](p), git_check=lambda commit, ref: True)
        return verdict, rec

    def codes(self, verdict):
        return sorted(c for c, _ in verdict.findings)

    def test_the_ledger_baseline_itself_is_accepted_at_promote(self):
        verdict, rec = self.promote(self.base["capabilities"], self.base["sha256"])
        self.assertEqual(self.codes(verdict), [], verdict.lines())
        self.assertEqual(rec["sha256"], self.base["sha256"])

    def test_the_old_jump_off_baselines_are_refused_with_the_capability_reasons(self):
        for asset in self.L["rollbackAssets"]:
            if asset["capabilities"]["executionCompiledIn"]:
                continue
            verdict, _ = self.promote(asset["capabilities"], asset["sha256"])
            codes = self.codes(verdict)
            self.assertFalse(verdict.accepted, asset["sha256"][:8])
            for code in ("jump-off", "metadata-missing", "feature-bits", "jump-not-advertised"):
                self.assertIn(code, codes, "%s: %s" % (asset["sha256"][:8], codes))

    def test_the_same_sha_with_a_lost_capability_is_refused(self):
        for key, value in (("executionCompiledIn", False), ("jumpCapabilityAdvertised", False), ("featureBits", 3), ("legacyJumpExec", False), ("buildRole", "DiagnosticJumpOff")):
            caps = copy.deepcopy(self.base["capabilities"])
            caps[key] = value
            verdict, _ = self.promote(caps, self.base["sha256"])
            self.assertFalse(verdict.accepted, key)

    def test_a_deployed_file_that_is_not_the_candidate_is_refused(self):
        verdict, _ = self.promote(self.base["capabilities"], self.base["sha256"], deployed_sha="C" * 64)
        self.assertIn("deployed-sha-differs", self.codes(verdict))
        lost = copy.deepcopy(self.base["capabilities"])
        lost["featureBits"] = 0
        lost["executionCompiledIn"] = False
        verdict, _ = self.promote(self.base["capabilities"], self.base["sha256"], deployed_caps=lost)
        self.assertIn("deployed-capability-differs", self.codes(verdict))

    def test_a_candidate_that_loses_a_capability_of_the_baseline_needs_an_owner_approval(self):
        """Ledger with a baseline that has MORE than the candidate (feature bit 8): the candidate loses it -> capability-regression; the approval id lets it pass."""
        L2 = copy.deepcopy(self.L)
        L2["baseline"]["capabilities"]["featureBits"] = 15
        path = os.path.join(self.tmp, "ledger-higher-baseline.json")
        G.write_json(path, L2)
        verdict, _ = self.promote(self.base["capabilities"], self.base["sha256"], ledger_path=path)
        self.assertIn("capability-regression", self.codes(verdict))
        verdict, _ = self.promote(self.base["capabilities"], self.base["sha256"], ledger_path=path, owner_approval="OWNER-APPROVAL-TEST")
        self.assertNotIn("capability-regression", self.codes(verdict))

    def test_a_missing_stage_is_refused(self):
        for stage in ("build", "accept", "deploy"):
            L2 = copy.deepcopy(self.L)
            L2["history"] = [h for h in L2["history"] if h["stage"] != stage]
            path = os.path.join(self.tmp, "ledger-no-%s.json" % stage)
            G.write_json(path, L2)
            verdict, _ = self.promote(self.base["capabilities"], self.base["sha256"], ledger_path=path)
            self.assertIn("%s-entry-missing" % stage, self.codes(verdict), stage)

    def test_every_rollback_asset_that_loses_a_capability_is_refused_without_an_owner_approval_and_passes_with_one(self):
        for asset in self.L["rollbackAssets"]:
            reader = reader_from(asset["capabilities"], asset["sha256"])
            verdict, rec = G.check("rollback", os.path.join(self.tmp, "x.dll"), reader=reader)
            lost = G.lost_capabilities(self.base["capabilities"], rec)
            if lost:
                self.assertIn("capability-regression", self.codes(verdict), asset["sha256"][:8])
                verdict2, _ = G.check("rollback", os.path.join(self.tmp, "x.dll"), reader=reader, owner_approval="OWNER-APPROVAL-TEST")
                self.assertNotIn("capability-regression", self.codes(verdict2), asset["sha256"][:8])


class C_FixtureIdentity(unittest.TestCase):
    """The explicit fixture IS the ledger baseline (the artifact the LJX-1 / interop tests run against)."""

    @classmethod
    def setUpClass(cls):
        cls.dll = FX.require_telemetry_a()                      # skip (PRECONDITION-MISSING) in a development run, a PRECONDITION failure in the release gate
        cls.sidecar = FX.require_sidecar()
        cls.L = ledger()
        cls.base = cls.L["baseline"]
        cls.cap = G.read_dll_capability(cls.dll)                # the reflection reader (never executes the DLL); one read for the whole class
        if not cls.cap.get("ok"):
            raise AssertionError("the capability reader failed on the fixture (unknown = not accepted): %s" % cls.cap.get("error"))
        cls.verdict, cls.rec = G.check("promote", cls.dll, sidecar=cls.sidecar, deployed=cls.dll, remote_ref="HEAD", reader=lambda p: cls.cap)

    def test_the_reflection_reader_can_read_the_fixture(self):
        self.assertTrue(self.cap.get("ok"), "the capability reader failed (unknown = not accepted): %s" % self.cap.get("error"))

    def test_the_fixture_sha256_and_size_are_the_ledger_baseline(self):
        self.assertEqual(self.cap["sha256"].upper(), self.base["sha256"])
        self.assertEqual(self.cap["sizeBytes"], self.base["sizeBytes"])

    def test_execution_is_compiled_in_and_the_feature_bits_are_the_baseline_bits(self):
        self.assertIs(self.rec["executionCompiledIn"], True)
        self.assertEqual(self.rec["featureBits"], self.base["capabilities"]["featureBits"])
        self.assertIs(self.rec["jumpCapabilityAdvertised"], True)

    def test_legacy_jump_exec_and_the_build_role_are_the_formal_ones(self):
        self.assertIs(self.rec["legacyJumpExec"], True)
        self.assertEqual(self.rec["buildRole"], "Formal")
        self.assertEqual(self.cap["metadata"].get("TScoring.LegacyJumpExec"), "true")
        self.assertEqual(self.cap["metadata"].get("TScoring.BuildRole"), "Formal")

    def test_the_sidecar_says_it_is_a_formal_candidate_and_says_the_same_as_the_dll(self):
        side = G.read_json(self.sidecar)
        self.assertIs(side["formalCandidate"], True)
        self.assertEqual(side["sha256"].upper(), self.cap["sha256"].upper())
        self.assertEqual(side["featureBits"], self.cap["featureBits"])
        self.assertEqual(side["sourceCommit"], self.base["sourceCommit"])

    def test_the_tokens_are_a_superset_of_the_baseline_tokens(self):
        for token in self.base["capabilities"]["tokens"]:
            self.assertIn(token, self.rec["tokens"])

    def test_no_capability_of_the_previous_baseline_is_lost(self):
        self.assertEqual(G.lost_capabilities(self.base["capabilities"], self.rec), [])

    def test_the_artifact_guard_accepts_the_fixture_as_the_promoted_deployed_accepted_built_artifact(self):
        """accepted = deployed = promoted identity: the guard's promote stage on the real ledger (build -> accept -> deploy entries of the same SHA and capabilities, the deployed file is the
        candidate, the source commit is on the branch)."""
        self.assertEqual(self.verdict.findings, [], self.verdict.lines())


@unittest.skipUnless(os.environ.get("TS_RELEASE_GATE") == "1" or os.environ.get("TS_CHECK_DEPLOYED") == "1",
                     "SUITE-S3: the deployed-identity check reads the DLL INSTALLED on this machine; it is a post-deployment gate (TS_RELEASE_GATE=1 or TS_CHECK_DEPLOYED=1)")
class D_DeployedIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(DEPLOYED):
            raise AssertionError("%s the deployed Legacy TelemetryA is absent: %s" % (FX.PRECONDITION_PREFIX, DEPLOYED))
        cls.dll = FX.require_telemetry_a()
        cls.sidecar = FX.require_sidecar()
        cls.L = ledger()
        cls.base = cls.L["baseline"]
        cls.reads = {cls.dll: G.read_dll_capability(cls.dll), DEPLOYED: G.read_dll_capability(DEPLOYED)}
        cls.verdict, cls.rec = G.check("promote", cls.dll, sidecar=cls.sidecar, deployed=DEPLOYED, remote_ref="HEAD", reader=lambda p: cls.reads[p])

    def test_the_installed_dll_is_the_ledger_baseline(self):
        dep = self.reads[DEPLOYED]
        self.assertTrue(dep.get("ok"), "reader failed on the installed DLL: %s" % dep.get("error"))
        self.assertEqual(dep["sha256"].upper(), self.base["sha256"], "installed %s vs ledger baseline %s" % (dep["sha256"][:8], self.base["sha256"][:8]))

    def test_the_installed_capabilities_are_the_baseline_capabilities_and_none_is_lost(self):
        caps = G.capabilities_of(self.reads[DEPLOYED])
        self.assertEqual(G.lost_capabilities(self.base["capabilities"], caps), [])
        self.assertTrue(G.same_capabilities(caps, dict(self.base["capabilities"])))

    def test_accepted_deployed_promoted_identity(self):
        self.assertEqual(self.verdict.findings, [], self.verdict.lines())


if __name__ == "__main__":
    unittest.main()
