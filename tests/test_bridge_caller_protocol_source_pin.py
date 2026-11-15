"""KF-FIX / KF-09 (Owner 2026-11-16, option A): a MAINTAINED source pin for the Bridge, the Caller and the Handshake protocol sources.

What it is: a provisional CHANGE-CONTROL contract. It detects that the sources below were changed WITHOUT an Owner decision; it is NOT a Capability check of a deployed DLL (that is
tests/test_artifact_deployed_identity.py and package/artifact_guard.py, for the Legacy TelemetryA only). It replaces the retired
`test_managed_input_sia3...test_the_senders_the_bridges_the_caller_and_the_protocol_are_unchanged_since_si_a_started`, which demanded an empty diff against a 2026-10 commit for ever.

Scope (relative to TsScoringPlugin/Handshake/): EVERY file under Bridge/, Caller/ and Shared/ (the Handshake protocol: HandshakeProtocol.cs, AppProtocol.cs, ObservationLog.cs), except
build outputs (directories bin / obj / out / dist / .vs / packages / logs and the extensions .log .user .dll .pdb .exe .cache .suo). A file that is added, deleted or renamed changes the
SET and fails; a changed byte changes the SHA-256 and fails. The SHA-256 is that of the content as Git stores it (CRLF -> LF like the Git clean filter, the same rule as the blob identities
of package/source-package-manifest.json), so the pin holds in an LF clone and in a CRLF work tree alike.

THE UPDATE CONTRACT (Owner 2026-11-16). A FAILURE OF THIS TEST IS NEVER A KNOWN FAILURE and must never go into a baseline file (tools refuse it). It is cleared ONLY by an intended product
change, and then the pin is updated in the SAME commit as the change or in the contract commit directly after it, together with a new entry at the END of PIN_UPDATES that records:
    stage          the stage / work item that changed the sources
    ownerContract  the Owner decision / contract that allows it (date and wording or document)
    files          the changed files (relative paths; added / removed files included)
    reason         why they changed
    newSha         {file: new SHA-256} for every file in `files` (a removed file maps to None)
    tests          the tests that cover the change
    liveRequired   True / False: is a BVE live acceptance required for this change
    commit         the commit (or "this commit")
`test_every_pin_is_recorded_in_the_update_ledger` fails if PINNED differs from what the ledger says, so a pin cannot be re-baselined silently.

Retirement condition: when Caller / Bridge are integrated into the source package manifest, the package guard and the Capability ledger (separate stage KF-FIX-5), this pin may be retired
with a ledger entry naming the replacing detectors.
"""
import hashlib
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HS = os.path.join(ROOT, "TsScoringPlugin", "Handshake")
SCOPE_DIRS = ("Bridge", "Caller", "Shared")
SKIP_DIRS = {"bin", "obj", "out", "dist", ".vs", "packages", "logs"}
SKIP_EXT = (".log", ".user", ".dll", ".pdb", ".exe", ".cache", ".suo")
REQUIRED_KEYS = ("stage", "ownerContract", "files", "reason", "newSha", "tests", "liveRequired", "commit")

# The pinned sources at the formal tree f96a618 (taken 2026-11-16; unchanged by the KF-FIX commits).
PINNED = {
    "Bridge/Legacy/TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj": "7F11C74FC6B4A3B397D4599153DCECE07935B1FFB21FFE5D6612E2A55040F6EB",
    "Bridge/Legacy/src/AssemblyInfo.cs": "9DB7851B675A015624311E5181E54B5B81F454F68388AEC697FF1629DFC1FCB7",
    "Bridge/Legacy/src/TsScoringLegacyBridge.cs": "402FB3EE9602194FCCF590BAAD4368C2B23C12EEF75E99D420C8C91C649C673F",
    "Bridge/TSScoringPlugin.BveEx.Bridge.Prototype.csproj": "F2F849515A6437E0A273065C797B2FF5D7E8A559150600CACA40669C2589C0F6",
    "Bridge/src/AssemblyInfo.cs": "C12250D0A9EB3CF044AB254F9A51576F34D2DDD9DAAA6EB13D4351AC91B63104",
    "Bridge/src/HandshakeControlPlane.cs": "0CB47394BC0A97CF8FA960BA7450DA5D2E2198EF499D2AD76102C3D953F196DE",
    "Bridge/src/ScenarioObserver.cs": "A0232B030E03B802180AF82FB7187F6B93A597B247D8C22E2D8E8B80B5168C00",
    "Bridge/src/ScenarioReadyPublisher.cs": "2E0C70038FC7E6A7C58927EBB13A6C02324A263121982CBD8CAE5BF93617C885",
    "Bridge/src/ScenarioReadyTracker.cs": "9C357AED54D4229E53597A16BC0944749D421A1AF8119DD90E1E33A59CCD59D1",
    "Bridge/src/TsScoringBridgePrototype.cs": "A29D6824BB0237802F1D560D92B4DA3A179FEFB7BFD78BCF8A8A79A9BA7DDAD4",
    "Caller/TSScoringPlugin.Caller.InputDevice.csproj": "CEBE7CF0FD70F07CC9234DE40E8E2FFB1416C8B01A1A0E4199158A71634A393E",
    "Caller/src/AppController.cs": "28FE0F5B180F26184AF148E25C6693DCC206E3A7A1C49B9E9034396C7E1F36B6",
    "Caller/src/AppDirectoryPublisher.cs": "CB2DD29E86AFD4E55B938E56C95BB3DBE390E73D41DF35E324519D61987730D2",
    "Caller/src/AppProcessManager.cs": "3C6B23EF471DE544B6E1EB3EA7A3CB4ECB59470F6E2917474856CBEA7307CAE1",
    "Caller/src/AppStatePublisher.cs": "F6E6745AB65CBCAE2F118C9ED185B9305E8BD68ABACC3B350E2CA15240D1AF71",
    "Caller/src/AssemblyInfo.cs": "F2AD297F468F63EE8F909E741A8D49A6776C07EC256B7FE2293137E79E129E69",
    "Caller/src/BveWindowMessageObserver.cs": "6E4FD08FE9F19E51FA50BB17EF25A188AC9E1A6A5ABD8331559256C340E5AAB3",
    "Caller/src/DrivingActivityState.cs": "B643C3FC6EB77CFFB2EF1DA29F4C90D6FC6C419B9EBFD564FAA9A46CC2B85639",
    "Caller/src/F11CloseProtocol.cs": "FE5BA894B5AB83CC9341B9BCD4B747FCEEEEFE74193E3A7E30103C8993A41924",
    "Caller/src/HandshakeSession.cs": "B93C1FC2FC745BF6EF859DF19CD0F2AE5BE4699AE5FC39EDE79D48C75EFC12AE",
    "Caller/src/InitialDefaultsLauncher.cs": "5EC41F87E4DF8E8E3BADE67E3FF6EB740E50D8B412BBF33DA9D70D23BAB27EF6",
    "Caller/src/InitialDefaultsWindow.cs": "3B6167A8002C26E07FC3D3F87690070EB1E5FC266796A6F3F24775DBCE87F6C4",
    "Caller/src/LauncherConfig.cs": "B8F560879550E0A371F8804A5AD6DA001763C735974FE5F4803BF5ED59F52D05",
    "Caller/src/TsScoringCallerInputDevice.cs": "2E5F87E763358D4A2826545E7A3BF82E9D891107788533647270DA4CD657E666",
    "Shared/AppProtocol.cs": "364E0EB8712C4E110B25C1218EF646DF892E425990A6CC4E973AB49153BAB6EA",
    "Shared/HandshakeProtocol.cs": "D0A31B0BBCC66374DD5D2CF2D345BEFBB8535FE6AC06157E934E076BD05435A3",
    "Shared/ObservationLog.cs": "0646C87DF749248FE354BECBF938290564B4E378BA68FA3D92CA2113E7329773",
}

# The update ledger: ONE entry per intended change of the pinned sources, oldest first, appended at the end. See the module docstring for the contract.
PIN_UPDATES = [
    {
        "stage": "KF-FIX KF-09 (initial pin)",
        "ownerContract": "Owner 2026-11-16, KF-09 option A: a maintained blob SHA-256 source pin for the Bridge / Caller / Handshake protocol sources as a provisional change-control "
                         "contract, replacing the retired SI-A diff test; Caller / Bridge integration into the manifest / package guard / Capability ledger stays a separate stage (KF-FIX-5)",
        "files": sorted(PINNED),
        "reason": "initial pin of the 27 source files at the formal tree f96a6181 (no product change; the sources are exactly those of the accepted formal baseline)",
        "newSha": dict(PINNED),
        "tests": ["test_bridge_caller_protocol_source_pin.A_SourcePin"],
        "liveRequired": False,
        "commit": "this commit (KF-FIX KF-09)",
    },
]


def clean(data):
    """What the Git clean filter stores: CRLF -> LF, unless the bytes are binary or hold a lone CR (the rule of tests/test_stationindex_package_st3e0.py)."""
    if b"\x00" in data or re.search(rb"\r(?!\n)", data):
        return data
    return data.replace(b"\r\n", b"\n")


def current_files(handshake_root=HS):
    """{relative path under Handshake/: SHA-256 of the content as Git stores it} of every file of the scope that is not a build output."""
    found = {}
    for scope in SCOPE_DIRS:
        base = os.path.join(handshake_root, scope)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
            for name in filenames:
                if name.lower().endswith(SKIP_EXT):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, handshake_root).replace("\\", "/")
                with open(path, "rb") as fh:
                    found[rel] = hashlib.sha256(clean(fh.read())).hexdigest().upper()
    return found


def set_difference(now, pinned):
    """(added, removed, renamed): a removed path whose content (SHA) reappears under an added path is reported as a rename."""
    added = sorted(set(now) - set(pinned))
    removed = sorted(set(pinned) - set(now))
    renamed = []
    for old in list(removed):
        for new in list(added):
            if now[new] == pinned[old]:
                renamed.append((old, new))
                removed.remove(old)
                added.remove(new)
                break
    return added, removed, renamed


GUIDANCE = ("This is a CHANGE-CONTROL failure, never a known failure. If the change is intended: update PINNED and append an entry to PIN_UPDATES (stage, ownerContract, files, reason, newSha, "
            "tests, liveRequired, commit) in the same commit as the product change or in the contract commit directly after it.")


class A_SourcePin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.now = current_files()

    def test_the_set_of_pinned_files_is_exactly_the_set_of_the_sources(self):
        added, removed, renamed = set_difference(self.now, PINNED)
        self.assertEqual((added, removed, renamed), ([], [], []), "files ADDED %s, REMOVED %s, RENAMED %s. %s" % (added, removed, renamed, GUIDANCE))

    def test_every_pinned_file_has_the_pinned_sha256(self):
        changed = sorted(k for k in PINNED if k in self.now and self.now[k] != PINNED[k])
        self.assertEqual(changed, [], "content CHANGED: %s. %s" % (["%s (%s -> %s)" % (k, PINNED[k][:8], self.now[k][:8]) for k in changed], GUIDANCE))

    def test_the_scope_covers_the_bridge_the_caller_and_the_handshake_protocol(self):
        for rel in ("Shared/HandshakeProtocol.cs", "Shared/AppProtocol.cs", "Shared/ObservationLog.cs", "Bridge/src/HandshakeControlPlane.cs", "Caller/src/HandshakeSession.cs",
                    "Bridge/TSScoringPlugin.BveEx.Bridge.Prototype.csproj", "Bridge/Legacy/TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj", "Caller/TSScoringPlugin.Caller.InputDevice.csproj"):
            self.assertIn(rel, PINNED, "the pin scope lost " + rel)
        for scope in SCOPE_DIRS:
            self.assertTrue([k for k in PINNED if k.startswith(scope + "/")], "no pinned file under " + scope)

    def test_every_pin_is_recorded_in_the_update_ledger(self):
        latest = {}
        for i, entry in enumerate(PIN_UPDATES):
            for key in REQUIRED_KEYS:
                self.assertIn(key, entry, "PIN_UPDATES[%d] lacks %r" % (i, key))
            for text in ("stage", "ownerContract", "reason", "commit"):
                self.assertTrue(str(entry[text]).strip(), "PIN_UPDATES[%d].%s is empty" % (i, text))
            self.assertIsInstance(entry["liveRequired"], bool, "PIN_UPDATES[%d].liveRequired must be True / False" % i)
            self.assertTrue(entry["tests"], "PIN_UPDATES[%d].tests is empty" % i)
            self.assertEqual(sorted(entry["files"]), sorted(entry["newSha"]), "PIN_UPDATES[%d]: files and newSha differ" % i)
            for path, sha in entry["newSha"].items():
                latest[path] = sha
        recorded = {k: v for k, v in latest.items() if v is not None}
        self.assertEqual(recorded, PINNED, "PINNED differs from what the update ledger says (a pin cannot be re-baselined without an entry in PIN_UPDATES)")

    def test_the_comparison_ignores_the_line_ending_of_the_work_tree(self):
        self.assertEqual(hashlib.sha256(clean(b"a\r\nb\r\n")).hexdigest(), hashlib.sha256(clean(b"a\nb\n")).hexdigest())
        self.assertNotEqual(hashlib.sha256(clean(b"a\nb\n")).hexdigest(), hashlib.sha256(clean(b"a\nb \n")).hexdigest())

    def test_the_helpers_report_an_added_a_removed_and_a_renamed_file(self):
        pinned = {"Caller/src/A.cs": "1" * 64, "Caller/src/B.cs": "2" * 64, "Shared/C.cs": "3" * 64}
        now = {"Caller/src/A.cs": "1" * 64, "Caller/src/B2.cs": "2" * 64, "Shared/D.cs": "4" * 64}
        added, removed, renamed = set_difference(now, pinned)
        self.assertEqual((added, removed, renamed), (["Shared/D.cs"], ["Shared/C.cs"], [("Caller/src/B.cs", "Caller/src/B2.cs")]))


if __name__ == "__main__":
    unittest.main()
