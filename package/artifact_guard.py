"""OD-X11 v2 - the ARTIFACT guard: built DLLs, their SHA-256 / capability / metadata / sidecar and the accepted -> deployed -> promoted ledger (Owner 2026-11-15).

Split of duties (Owner ruling):
  package/source_package.py : the SOURCE package - manifest, source blobs, content checks (never looks at a built file).
  package/artifact_guard.py : the BUILT artifact - DLL bytes, capability, AssemblyMetadata, sidecar, ledger stages (this module).

What it protects: on 2026-11-10 the formal Legacy TelemetryA had the Jump execution ON (acceptance build); later rebuilds without /p:LegacyJumpExec=true silently produced the Jump OFF default build and were promoted because only
the SHA and the deterministic build were checked. From now on a promoted DLL must carry the SAME SHA and the SAME capabilities as the one that was built, accepted (live) and deployed, and no capability of the previous
baseline may be lost without an explicit Owner approval.

Stages (each one checks the previous ones):
  build     the DLL + its sidecar are a FORMAL candidate (Jump ON, BuildRole Formal, metadata = compiled-in flag = sidecar, formalCandidate true).
  accept    build + the ledger holds a `build` entry of the same SHA and capabilities; records the live acceptance evidence.
  deploy    build + the ledger holds an `accept` entry (same SHA / capabilities) + no capability of the baseline is lost (unless approved).
  promote   build + the ledger holds build -> accept -> deploy of the same SHA / capabilities; the DEPLOYED file (--deployed) is the same SHA; the source commit is on the remote (--remote-ref).
  rollback  the target asset is in the ledger rollbackAssets with SHA + capabilities; losing a capability of the current baseline needs an Owner approval id.

The diagnostic Jump OFF build (TScoring.BuildRole=DiagnosticJumpOff, formalCandidate=false) is REJECTED at every stage (it is a comparison build only: never deployed under the formal name, never promoted).
Reading the DLL is done by Tools/Read-TelemetryACapability.ps1 (reflection-only, from the DLL itself); tests inject a reader. Standard library only. Exit status: 0 ACCEPT, 1 REJECT, 2 usage.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
READER = os.path.join(REPO, "TsScoringPlugin", "Handshake", "Tools", "Read-TelemetryACapability.ps1")
DEFAULT_LEDGER = os.path.join(HERE, "capabilities", "TScoring.TelemetryA.json")
SIDECAR_SCHEMA = "ts-artifact-capability/1"
LEDGER_SCHEMA = "ts-capability-ledger/1"
STAGES = ("build", "accept", "deploy", "promote", "rollback")
CAPABILITY_KEYS = ("legacyJumpExec", "executionCompiledIn", "jumpCapabilityAdvertised", "featureBits", "buildRole")
SHA_RE = re.compile(r"^[0-9A-F]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def sidecar_path(dll):
    return dll + ".capability.json"


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def read_dll_capability(dll):
    """The default reader: Tools/Read-TelemetryACapability.ps1 (reflection-only). Returns the dict of the script; ok False carries `error`."""
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", READER, "-Dll", dll], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        out = p.stdout.strip().splitlines()
        return json.loads(out[-1]) if out else {"ok": False, "error": "reader-no-output"}
    except Exception as exc:                      # a reader that cannot run is a refusal, never an acceptance
        return {"ok": False, "error": "reader-failed:%s" % type(exc).__name__}


def capabilities_of(cap):
    """The comparable capability record of a reader result (the SAME fields everywhere: sidecar, ledger, reader)."""
    meta = cap.get("metadata") or {}
    return {
        "legacyJumpExec": str(meta.get("TScoring.LegacyJumpExec", "")).lower() == "true",
        "executionCompiledIn": bool(cap.get("executionCompiledIn")),
        "jumpCapabilityAdvertised": bool(cap.get("jumpCapabilityAdvertised")),
        "featureBits": int(cap.get("featureBits") or 0),
        "buildRole": str(meta.get("TScoring.BuildRole", "")),
        "tokens": sorted(cap.get("capabilityTokens") or []),
    }


def lost_capabilities(old, new):
    """Capabilities the previous baseline had (boolean true / bits / tokens) that the new artifact lacks."""
    lost = []
    for key in ("legacyJumpExec", "executionCompiledIn", "jumpCapabilityAdvertised"):
        if old.get(key) and not new.get(key):
            lost.append(key)
    if (old.get("featureBits") or 0) & ~(new.get("featureBits") or 0):
        lost.append("featureBits")
    for token in old.get("tokens") or []:
        if token not in (new.get("tokens") or []):
            lost.append("token:" + token)
    return lost


class Verdict(object):
    def __init__(self):
        self.findings = []

    def refuse(self, code, text=""):
        self.findings.append((code, text))

    @property
    def accepted(self):
        return not self.findings

    def lines(self):
        return ["  finding: %s%s" % (c, (" - " + t) if t else "") for c, t in self.findings]


def check_build(dll, sidecar, ledger, reader, verdict):
    """The FORMAL candidate rules. Returns the capability record read from the DLL (or None)."""
    if not os.path.isfile(dll):
        verdict.refuse("dll-absent", dll)
        return None
    cap = reader(dll)
    if not cap.get("ok"):
        verdict.refuse("capability-unreadable", str(cap.get("error")))
        return None
    caps = capabilities_of(cap)
    meta = cap.get("metadata") or {}
    contract = (ledger or {}).get("contract", {})
    if cap.get("assemblyName") != "TScoring.TelemetryA":
        verdict.refuse("assembly-name", str(cap.get("assemblyName")))
    # the three expressions of the build contract must agree: compiled-in const, AssemblyMetadata, sidecar
    if "TScoring.LegacyJumpExec" not in meta or "TScoring.BuildRole" not in meta:
        verdict.refuse("metadata-missing", "TScoring.LegacyJumpExec / TScoring.BuildRole are not in the DLL (a build before OD-X11 v2 is not a formal candidate)")
    if caps["legacyJumpExec"] != caps["executionCompiledIn"]:
        verdict.refuse("metadata-flag-mismatch", "AssemblyMetadata %r vs compiled-in %r" % (meta.get("TScoring.LegacyJumpExec"), caps["executionCompiledIn"]))
    if not caps["executionCompiledIn"]:
        verdict.refuse("jump-off", "the Legacy Jump execution is not compiled in (Jump OFF is never a formal candidate)")
    if caps["buildRole"] != "Formal":
        verdict.refuse("build-role", "BuildRole=%r (formal needs 'Formal')" % caps["buildRole"])
    if caps["featureBits"] < int(contract.get("minFeatureBits", 1)):
        verdict.refuse("feature-bits", "featureBits=%d" % caps["featureBits"])
    if not caps["jumpCapabilityAdvertised"]:
        verdict.refuse("jump-not-advertised", "")
    for token in contract.get("requiredTokens", []):
        if token not in caps["tokens"]:
            verdict.refuse("token-missing", token)
    side = None
    if not os.path.isfile(sidecar):
        verdict.refuse("sidecar-absent", sidecar)
    else:
        try:
            side = read_json(sidecar)
        except Exception:
            verdict.refuse("sidecar-unreadable", sidecar)
    if side is not None:
        if side.get("schema") != SIDECAR_SCHEMA:
            verdict.refuse("sidecar-schema", str(side.get("schema")))
        if str(side.get("sha256", "")).upper() != str(cap.get("sha256", "")).upper():
            verdict.refuse("sidecar-sha-mismatch", "sidecar %s vs dll %s" % (str(side.get("sha256", ""))[:8], str(cap.get("sha256", ""))[:8]))
        if side.get("sizeBytes") != cap.get("sizeBytes"):
            verdict.refuse("sidecar-size-mismatch", "")
        if side.get("legacyJumpExec") is not True or side.get("executionCompiledIn") is not True:
            verdict.refuse("sidecar-capability", "legacyJumpExec / executionCompiledIn must be true")
        if side.get("buildRole") != "Formal" or side.get("formalCandidate") is not True:
            verdict.refuse("sidecar-not-formal", "buildRole=%r formalCandidate=%r" % (side.get("buildRole"), side.get("formalCandidate")))
        if side.get("featureBits") != caps["featureBits"]:
            verdict.refuse("sidecar-featurebits-mismatch", "")
        if side.get("jumpCapabilityAdvertised") is not True:
            verdict.refuse("sidecar-not-advertised", "")
        if not COMMIT_RE.match(str(side.get("sourceCommit", ""))):
            verdict.refuse("sidecar-source-commit", str(side.get("sourceCommit")))
        if side.get("rootsMatched") is not True:
            verdict.refuse("sidecar-roots", "the 2 clean roots did not match")
        if side.get("configuration") != "Release":
            verdict.refuse("sidecar-configuration", str(side.get("configuration")))
    return dict(caps, sha256=str(cap.get("sha256", "")).upper(), sizeBytes=cap.get("sizeBytes"), sourceCommit=(side or {}).get("sourceCommit"))


def entries(ledger, stage, sha):
    return [e for e in (ledger or {}).get("history", []) if e.get("stage") == stage and str(e.get("sha256", "")).upper() == sha]


def same_capabilities(a, b):
    return all(a.get(k) == b.get(k) for k in CAPABILITY_KEYS) and sorted(a.get("tokens") or []) == sorted(b.get("tokens") or [])


def require_previous(ledger, stage, rec, verdict):
    found = entries(ledger, stage, rec["sha256"])
    if not found:
        verdict.refuse("%s-entry-missing" % stage, "the ledger has no `%s` entry for SHA %s" % (stage, rec["sha256"][:8]))
        return
    for entry in found:
        if not same_capabilities(entry.get("capabilities", {}), rec):
            verdict.refuse("%s-capability-differs" % stage, "the `%s` entry of %s records other capabilities" % (stage, rec["sha256"][:8]))
            return


def baseline_loss(ledger, rec, verdict, approval):
    base = (ledger or {}).get("baseline", {})
    lost = lost_capabilities(base.get("capabilities", {}), rec)
    if lost and not approval:
        verdict.refuse("capability-regression", "lost vs the baseline %s: %s" % (str(base.get("sha256", ""))[:8], ", ".join(lost)))


def source_on_remote(commit, remote_ref):
    try:
        p = subprocess.run(["git", "-C", REPO, "merge-base", "--is-ancestor", commit, remote_ref], capture_output=True, text=True)
        return p.returncode == 0
    except Exception:
        return False


def check(stage, dll, sidecar=None, ledger_path=DEFAULT_LEDGER, deployed=None, remote_ref=None, owner_approval=None, rollback_dll=None, reader=read_dll_capability, git_check=source_on_remote):
    verdict = Verdict()
    if stage not in STAGES:
        verdict.refuse("usage", "unknown stage %r" % stage)
        return verdict, None
    ledger = None
    try:
        ledger = read_json(ledger_path)
        if ledger.get("schema") != LEDGER_SCHEMA:
            verdict.refuse("ledger-schema", str(ledger.get("schema")))
    except Exception:
        verdict.refuse("ledger-unreadable", ledger_path)
    sidecar = sidecar or sidecar_path(dll)
    if stage == "rollback":
        target = rollback_dll or dll
        cap = reader(target)
        if not cap.get("ok"):
            verdict.refuse("capability-unreadable", str(cap.get("error")))
            return verdict, None
        sha = str(cap.get("sha256", "")).upper()
        caps = capabilities_of(cap)
        rec = dict(caps, sha256=sha)
        assets = [a for a in (ledger or {}).get("rollbackAssets", []) if str(a.get("sha256", "")).upper() == sha]
        if not assets:
            verdict.refuse("rollback-asset-unregistered", "SHA %s is not a registered rollback asset" % sha[:8])
        else:
            if not same_capabilities(assets[0].get("capabilities", {}), caps):
                verdict.refuse("rollback-capability-differs", "")
            baseline_loss(ledger, rec, verdict, owner_approval)
        return verdict, rec
    rec = check_build(dll, sidecar, ledger, reader, verdict)
    if rec is None or stage == "build":
        return verdict, rec
    if stage == "accept":
        require_previous(ledger, "build", rec, verdict)
    elif stage == "deploy":
        require_previous(ledger, "build", rec, verdict)
        require_previous(ledger, "accept", rec, verdict)
        baseline_loss(ledger, rec, verdict, owner_approval)
    elif stage == "promote":
        for prev in ("build", "accept", "deploy"):
            require_previous(ledger, prev, rec, verdict)
        baseline_loss(ledger, rec, verdict, owner_approval)
        if not deployed:
            verdict.refuse("deployed-path-missing", "promote compares the DEPLOYED file: pass --deployed")
        else:
            dcap = reader(deployed)
            if not dcap.get("ok"):
                verdict.refuse("deployed-unreadable", str(dcap.get("error")))
            else:
                if str(dcap.get("sha256", "")).upper() != rec["sha256"]:
                    verdict.refuse("deployed-sha-differs", "deployed %s vs candidate %s" % (str(dcap.get("sha256", ""))[:8], rec["sha256"][:8]))
                if not same_capabilities(capabilities_of(dcap), rec):
                    verdict.refuse("deployed-capability-differs", "")
        if not remote_ref:
            verdict.refuse("remote-ref-missing", "promote needs --remote-ref (the source commit must be on the remote)")
        elif not git_check(rec.get("sourceCommit") or "", remote_ref):
            verdict.refuse("source-not-on-remote", "%s is not reachable from %s" % (str(rec.get("sourceCommit"))[:8], remote_ref))
    return verdict, rec


def record(stage, rec, ledger_path, evidence, owner_approval, at):
    ledger = read_json(ledger_path)
    entry = {"stage": stage, "sha256": rec["sha256"], "sourceCommit": rec.get("sourceCommit"),
             "capabilities": {k: rec.get(k) for k in CAPABILITY_KEYS + ("tokens",)}, "evidence": evidence, "at": at}
    if owner_approval:
        entry["ownerApproval"] = owner_approval
    ledger.setdefault("history", []).append(entry)
    if stage == "promote":                       # the baseline changes ONLY by a promote entry (build / accept / deploy never touch it)
        ledger["baseline"] = {"sha256": rec["sha256"], "sourceCommit": rec.get("sourceCommit"), "sizeBytes": rec.get("sizeBytes"),
                              "capabilities": {k: rec.get(k) for k in CAPABILITY_KEYS + ("tokens",)}, "promotedAt": at, "closeRef": evidence}
    write_json(ledger_path, ledger)
    return entry


def make_sidecar(dll, commit, msbuild_args, script_sha256, roots_matched, source_on_remote, formal=True, built_at="", reader=read_dll_capability):
    """Writes <dll>.capability.json FROM THE DLL (never from a declaration). Returns (path, dict). The sidecar of a diagnostic Jump OFF build says formalCandidate=false; accepted / deployed / promoted are NOT fields of the
    sidecar (they live in the ledger: the build never marks a stage that was not done)."""
    cap = reader(dll)
    if not cap.get("ok"):
        raise RuntimeError("capability-unreadable:%s" % cap.get("error"))
    caps = capabilities_of(cap)
    side = {
        "schema": SIDECAR_SCHEMA, "component": "TScoring.TelemetryA", "host": "Legacy",
        "sourceCommit": commit, "configuration": "Release", "msbuildArgs": msbuild_args, "buildScriptSha256": script_sha256,
        "buildRole": caps["buildRole"], "legacyJumpExec": caps["legacyJumpExec"], "executionCompiledIn": caps["executionCompiledIn"],
        "featureBits": caps["featureBits"], "jumpCapabilityAdvertised": caps["jumpCapabilityAdvertised"], "capabilityTokens": caps["tokens"],
        "sha256": str(cap["sha256"]).upper(), "sizeBytes": cap["sizeBytes"], "rootsMatched": bool(roots_matched), "sourceOnRemoteAtBuild": bool(source_on_remote),
        "formalCandidate": bool(formal) and caps["legacyJumpExec"] and caps["buildRole"] == "Formal", "builtAtUtc": built_at,
    }
    path = sidecar_path(dll)
    write_json(path, side)
    return path, side


def static_findings(repo=REPO):
    """The source-side contract of OD-X11 v2 (used by the tests and by `check-source`): csproj default Jump ON + guard, AssemblyMetadata, the formal build script, no `LegacyJumpExec` parameter."""
    problems = []
    proj = os.path.join(repo, "TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "TSScoringPlugin.AtsExLegacy.Telemetry.csproj")
    info = os.path.join(repo, "TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "src", "AssemblyInfo.cs")
    script = os.path.join(repo, "TsScoringPlugin", "Handshake", "Tools", "Build-Formal-TelemetryA.ps1")
    try:
        text = open(proj, encoding="utf-8").read()
        if not re.search(r"<LegacyJumpExec Condition=\"'\$\(LegacyJumpExec\)' == ''\">true</LegacyJumpExec>", text):
            problems.append("csproj-default-not-true")
        for code in ("TSCORING-JUMP-VALUE", "TSCORING-JUMPOFF-NOT-DIAGNOSTIC", "TSCORING-JUMPOFF-FORMAL-OUTPUT"):
            if code not in text:
                problems.append("csproj-guard-missing:" + code)
    except OSError:
        problems.append("csproj-absent")
    try:
        text = open(info, encoding="utf-8").read()
        for needle in ('AssemblyMetadata("TScoring.LegacyJumpExec", "true")', 'AssemblyMetadata("TScoring.BuildRole", "Formal")', 'AssemblyMetadata("TScoring.BuildRole", "DiagnosticJumpOff")'):
            if needle not in text:
                problems.append("assemblyinfo-missing:" + needle)
    except OSError:
        problems.append("assemblyinfo-absent")
    try:
        text = open(script, encoding="utf-8").read()
        if "/p:LegacyJumpExec=true" not in text:
            problems.append("build-script-property-missing")
        if re.search(r"param\s*\([^)]*LegacyJumpExec", text, re.S | re.I):
            problems.append("build-script-has-legacyjumpexec-parameter")
    except OSError:
        problems.append("build-script-absent")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check")
    c.add_argument("--stage", required=True, choices=STAGES)
    c.add_argument("--dll", required=True)
    c.add_argument("--sidecar")
    c.add_argument("--ledger", default=DEFAULT_LEDGER)
    c.add_argument("--deployed")
    c.add_argument("--remote-ref")
    c.add_argument("--owner-approval")
    c.add_argument("--rollback-dll")
    r = sub.add_parser("record")
    r.add_argument("--stage", required=True, choices=("build", "accept", "deploy", "promote", "rollback-asset"))
    r.add_argument("--dll", required=True)
    r.add_argument("--sidecar")
    r.add_argument("--ledger", default=DEFAULT_LEDGER)
    r.add_argument("--evidence", default="")
    r.add_argument("--owner-approval")
    r.add_argument("--at", default="")
    r.add_argument("--deployed")
    r.add_argument("--remote-ref")
    m = sub.add_parser("make-sidecar")
    m.add_argument("--dll", required=True)
    m.add_argument("--commit", required=True)
    m.add_argument("--msbuild-args", default="")
    m.add_argument("--script-sha256", default="")
    m.add_argument("--roots-matched", default="false")
    m.add_argument("--source-on-remote", default="false")
    m.add_argument("--diagnostic", action="store_true")
    m.add_argument("--built-at", default="")
    sub.add_parser("check-source")
    a = ap.parse_args(argv)
    if a.cmd == "check-source":
        problems = static_findings()
        print("RESULT: %s  stage=source findings=%d" % ("ACCEPT" if not problems else "REJECT", len(problems)))
        for p in problems:
            print("  finding: " + p)
        return 0 if not problems else 1
    if a.cmd == "make-sidecar":
        path, side = make_sidecar(a.dll, a.commit, a.msbuild_args, a.script_sha256, a.roots_matched.lower() == "true", a.source_on_remote.lower() == "true", formal=not a.diagnostic, built_at=a.built_at)
        print("SIDECAR %s sha=%s formalCandidate=%s" % (path, side["sha256"][:8], side["formalCandidate"]))
        return 0
    if a.cmd == "check":
        verdict, rec = check(a.stage, a.dll, a.sidecar, a.ledger, a.deployed, a.remote_ref, a.owner_approval, a.rollback_dll)
        print("RESULT: %s  stage=%s sha=%s findings=%d" % ("ACCEPT" if verdict.accepted else "REJECT", a.stage, (rec or {}).get("sha256", "")[:8], len(verdict.findings)))
        for line in verdict.lines():
            print(line)
        return 0 if verdict.accepted else 1
    if a.cmd == "record":
        stage = a.stage
        if stage == "rollback-asset":
            cap = read_dll_capability(a.dll)
            if not cap.get("ok"):
                print("RESULT: REJECT  record rollback-asset: capability-unreadable")
                return 1
            ledger = read_json(a.ledger)
            rec = dict(capabilities_of(cap), sha256=str(cap["sha256"]).upper())
            ledger.setdefault("rollbackAssets", []).append({"sha256": rec["sha256"], "capabilities": {k: rec.get(k) for k in CAPABILITY_KEYS + ("tokens",)}, "path": a.dll, "note": a.evidence})
            write_json(a.ledger, ledger)
            print("RECORDED rollback-asset %s" % rec["sha256"][:8])
            return 0
        verdict, rec = check(stage, a.dll, a.sidecar, a.ledger, a.deployed, a.remote_ref, a.owner_approval)
        if not verdict.accepted:
            print("RESULT: REJECT  record %s refused" % stage)
            for line in verdict.lines():
                print(line)
            return 1
        record(stage, rec, a.ledger, a.evidence, a.owner_approval, a.at)
        print("RECORDED %s %s" % (stage, rec["sha256"][:8]))
        return 0
    ap.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())
