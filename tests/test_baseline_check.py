"""package/baseline_check.py: the guard that makes a baseline raise safe (omission, partial pair, degradation, unlisted files, ledger consistency). Offline: synthetic files, no BVE, no deployed DLL."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "package"))
import baseline_check as B  # noqa: E402


def fake_dll(path, names, literals=(), pad=2000):
    """Bytes that look like the two heaps the fingerprint reads: UTF-8 identifiers and UTF-16 literals."""
    data = b"MZ\x90\x00" + b"\x00" * 60
    for n in names:
        data += n.encode("ascii") + b"\x00"
    for s in literals:
        data += b"\x01" + s.encode("utf-16-le") + b"\x00\x00"       # a length / flag byte in front, as in the real user-string heap
    data += b"\x01" * pad
    open(path, "wb").write(data)
    return path


class Env(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="bc_")
        self.dep = os.path.join(self.d, "deploy")
        os.makedirs(self.dep)
        self.base_names = ["FeatureOne", "FeatureTwo", "HeartbeatTick"]
        self.base_lits = ["SR_ESTABLISHED line", "pause-pulse-stats"]
        self.arts = []
        for name, pair in (("TScoring.TelemetryB.dll", "Current"), ("TScoring.BridgeB.dll", "Current"), ("TScoring.InputDevice.dll", None)):
            p = fake_dll(os.path.join(self.dep, name), self.base_names + [name.replace(".", "")], self.base_lits)
            a = {"name": name, "deploy": [p], "baseline": {"sha256": B.sha256_file(p), "sourceCommit": "abc12345" + "0" * 32, "promotedAt": "2026-11-16", "size": os.path.getsize(p)}, "rollback": [],
                 "fingerprint": "baselines/%s.%s.strings" % (name, B.sha256_file(p)[:8])}
            if pair:
                a["pair"] = pair
            self.arts.append(a)
        self.manifest_path = os.path.join(self.d, "artifact-baselines.json")
        os.makedirs(os.path.join(self.d, "baselines"))
        for a in self.arts:
            open(os.path.join(self.d, a["fingerprint"]), "w", encoding="utf-8").write("\n".join(sorted(B.fingerprint_file(a["deploy"][0]))) + "\n")
        self.manifest = {"schema": "ts-artifact-baselines/1", "artifacts": self.arts}
        json.dump(self.manifest, open(self.manifest_path, "w", encoding="utf-8"))
        self.fp_root = self.d
        self._orig = (B.HERE, B.FP_DIR)
        B.HERE = self.d
        B.FP_DIR = os.path.join(self.d, "baselines")

    def tearDown(self):
        B.HERE, B.FP_DIR = self._orig
        shutil.rmtree(self.d, ignore_errors=True)

    def cand(self, name, names=None, lits=None, pad=2000, tag="v2"):
        return fake_dll(os.path.join(self.d, "cand-" + name), (names if names is not None else self.base_names) + [name.replace(".", ""), tag], lits if lits is not None else self.base_lits, pad)


class A_Verify(Env):
    def test_a_consistent_deployment_is_accepted(self):
        self.assertEqual(B.verify(self.manifest), [])

    def test_a_wrong_sha_in_any_deploy_location_is_found(self):
        open(self.arts[0]["deploy"][0], "ab").write(b"x")
        self.assertTrue(any(f.startswith("sha-mismatch") for f in B.verify(self.manifest)))

    def test_an_unlisted_tscoring_dll_in_a_deploy_folder_is_found(self):
        fake_dll(os.path.join(self.dep, "TScoring.Stray.dll"), ["Stray"])
        self.assertTrue(any("unlisted" in f for f in B.verify(self.manifest)))

    def test_the_caller_in_two_places_must_match_in_both(self):
        second = os.path.join(self.d, "second", "TScoring.InputDevice.dll")
        os.makedirs(os.path.dirname(second))
        shutil.copy(self.arts[2]["deploy"][0], second)
        self.arts[2]["deploy"].append(second)
        self.assertEqual(B.verify(self.manifest), [])
        open(second, "ab").write(b"y")
        self.assertTrue(any(f.startswith("sha-mismatch") and "second" in f for f in B.verify(self.manifest)))

    def test_a_missing_fingerprint_file_is_found(self):
        os.remove(os.path.join(self.d, self.arts[0]["fingerprint"]))
        self.assertTrue(any("fingerprint file missing" in f for f in B.verify(self.manifest)))


class B_Plan(Env):
    def plan(self, cands, unchanged, **kw):
        return B.plan(self.manifest, cands, unchanged, kw.pop("live", "live evidence"), kw.pop("owner", None), None, allowed=kw.pop("allowed", {}))

    def full(self):
        return {"TScoring.TelemetryB.dll": self.cand("TScoring.TelemetryB.dll"), "TScoring.BridgeB.dll": self.cand("TScoring.BridgeB.dll")}

    def test_a_complete_raise_with_the_caller_declared_unchanged_is_accepted(self):
        f, d = self.plan(self.full(), ["TScoring.InputDevice.dll"])
        self.assertEqual(f, [])
        self.assertTrue(d["TScoring.TelemetryB.dll"]["changed"])

    def test_an_artifact_that_is_neither_raised_nor_declared_unchanged_is_an_omission(self):
        f, _ = self.plan(self.full(), [])
        self.assertTrue(any(x.startswith("OMISSION") and "InputDevice" in x for x in f), f)

    def test_raising_only_one_member_of_a_pair_is_refused_without_an_owner_approval(self):
        f, _ = self.plan({"TScoring.TelemetryB.dll": self.cand("TScoring.TelemetryB.dll")}, ["TScoring.BridgeB.dll", "TScoring.InputDevice.dll"])
        self.assertTrue(any(x.startswith("PARTIAL PAIR") for x in f), f)
        f2, _ = B.plan(self.manifest, {"TScoring.TelemetryB.dll": self.cand("TScoring.TelemetryB.dll")}, ["TScoring.BridgeB.dll", "TScoring.InputDevice.dll"], "live", "OWNER-1", None, allowed={})
        self.assertFalse(any(x.startswith("PARTIAL PAIR") for x in f2), f2)

    def test_a_lost_feature_is_a_degradation_unless_the_removal_is_allowed_with_a_reason(self):
        cands = self.full()
        cands["TScoring.TelemetryB.dll"] = self.cand("TScoring.TelemetryB.dll", names=["FeatureOne", "FeatureTwo"])           # HeartbeatTick lost
        f, d = self.plan(cands, ["TScoring.InputDevice.dll"])
        self.assertTrue(any(x.startswith("DEGRADATION") and "HeartbeatTick" in x for x in f), f)
        allowed = {("TScoring.TelemetryB.dll", "n:HeartbeatTick"): {"reason": "replaced"}}
        f2, d2 = self.plan(cands, ["TScoring.InputDevice.dll"], allowed=allowed)
        self.assertEqual(f2, [])
        self.assertEqual(d2["TScoring.TelemetryB.dll"]["allowed_removals_used"], ["n:HeartbeatTick"])

    def test_a_lost_string_literal_is_a_degradation(self):
        cands = self.full()
        cands["TScoring.BridgeB.dll"] = self.cand("TScoring.BridgeB.dll", lits=["SR_ESTABLISHED line"])                   # pause-pulse-stats lost
        f, _ = self.plan(cands, ["TScoring.InputDevice.dll"])
        self.assertTrue(any("DEGRADATION" in x and "pause-pulse-stats" in x for x in f), f)

    def test_a_much_smaller_candidate_is_a_degradation(self):
        cands = self.full()
        cands["TScoring.TelemetryB.dll"] = self.cand("TScoring.TelemetryB.dll", pad=1)
        self.arts[0]["baseline"]["size"] = 100000
        f, _ = self.plan(cands, ["TScoring.InputDevice.dll"])
        self.assertTrue(any("of the baseline size" in x for x in f), f)

    def test_a_raise_without_live_evidence_is_refused(self):
        f, _ = self.plan(self.full(), ["TScoring.InputDevice.dll"], live="")
        self.assertTrue(any("no live evidence" in x for x in f), f)

    def test_an_unchanged_artifact_that_is_also_a_candidate_is_a_contradiction(self):
        f, _ = self.plan(self.full(), ["TScoring.InputDevice.dll", "TScoring.BridgeB.dll"])
        self.assertTrue(any("contradiction" in x for x in f), f)


class C_Promote(Env):
    def test_promote_keeps_the_old_baseline_as_a_rollback_entry_and_moves_the_baseline(self):
        cands = {"TScoring.TelemetryB.dll": self.cand("TScoring.TelemetryB.dll"), "TScoring.BridgeB.dll": self.cand("TScoring.BridgeB.dll")}
        f, d = B.plan(self.manifest, cands, ["TScoring.InputDevice.dll"], "live", None, None, allowed={})
        self.assertEqual(f, [])
        new = B.promote(self.manifest, d, "evidence", "f" * 40, "2026-11-18")
        a = [x for x in new["artifacts"] if x["name"] == "TScoring.TelemetryB.dll"][0]
        self.assertEqual(a["baseline"]["sha256"], d["TScoring.TelemetryB.dll"]["sha256"])
        self.assertEqual(a["rollback"][-1]["sha256"], self.arts[0]["baseline"]["sha256"])
        caller = [x for x in new["artifacts"] if x["name"] == "TScoring.InputDevice.dll"][0]
        self.assertEqual(caller["baseline"]["sha256"], self.arts[2]["baseline"]["sha256"])                       # unchanged stays


class D_Repository(unittest.TestCase):
    def test_the_repository_manifest_is_consistent_with_the_telemetry_a_ledger_and_lists_every_deployed_tscoring_artifact(self):
        m = json.load(open(os.path.join(ROOT, "package", "artifact-baselines.json"), encoding="utf-8"))
        self.assertEqual(m["schema"], "ts-artifact-baselines/1")
        names = sorted(a["name"] for a in m["artifacts"])
        self.assertEqual(names, ["TScoring.BridgeA.dll", "TScoring.BridgeB.dll", "TScoring.InputDevice.dll", "TScoring.TelemetryA.dll", "TScoring.TelemetryB.dll"])
        ledger = json.load(open(os.path.join(ROOT, "package", "capabilities", "TScoring.TelemetryA.json"), encoding="utf-8"))
        ta = [a for a in m["artifacts"] if a["name"] == "TScoring.TelemetryA.dll"][0]
        self.assertEqual(ta["baseline"]["sha256"].upper(), ledger["baseline"]["sha256"].upper())
        self.assertEqual(ta["baseline"]["sourceCommit"], ledger["baseline"]["sourceCommit"])
        for a in m["artifacts"]:
            self.assertTrue(os.path.exists(os.path.join(ROOT, "package", a["fingerprint"])), a["name"])
            self.assertEqual(len(a["baseline"]["sha256"]), 64)
            if a["name"] == "TScoring.InputDevice.dll":
                self.assertEqual(len(a["deploy"]), 2)                          # BVE6 and BVE5 Input Devices
        pairs = {}
        for a in m["artifacts"]:
            if a.get("pair"):
                pairs.setdefault(a["pair"], set()).add((a["baseline"]["promotedAt"], a["baseline"]["sourceCommit"]))
        self.assertTrue(all(len(v) == 1 for v in pairs.values()), pairs)        # a pair is always raised together

    def test_allowed_removals_have_reason_and_owner_reference(self):
        for e in json.load(open(os.path.join(ROOT, "package", "baselines", "allowed-removals.json"), encoding="utf-8"))["allowed"]:
            self.assertTrue(e["reason"] and e["ownerRef"] and e["artifact"] and e["string"])


if __name__ == "__main__":
    unittest.main()
