# Baselines of the deployed TScoring artifacts

`package/artifact-baselines.json` is the single source of truth for the baseline (SHA-256, source commit, every deploy location, pair, rollback entries, evidence) of the five deployed artifacts:
TelemetryB + BridgeB (BveEx 2.0 Extensions, pair "Current"), TelemetryA + BridgeA (BveEx Legacy Extensions, pair "Legacy"), InputDevice / the Caller (BVE6 and BVE5 Input Devices, two locations).
TelemetryA is also governed by `package/artifact_guard.py` (capability ledger `package/capabilities/TScoring.TelemetryA.json`); `tests/test_baseline_check.py` keeps the two in step.

## Raising a baseline (the only supported way)
1. Build deterministically from a commit that is on the remote (2 clean roots, SHA match). TelemetryA: `Handshake/Tools/Build-Formal-TelemetryA.ps1`.
2. Deploy pair by pair with a backup (never one member of a pair alone), run the live acceptance, keep the evidence in a handoff folder.
3. `python package/baseline_check.py plan --candidate NAME=PATH ... --unchanged NAME ... --live-evidence "<reference>" --remote-ref origin/<branch>`
   - every artifact must be a candidate OR declared `--unchanged` (otherwise OMISSION),
   - a pair is raised together (otherwise PARTIAL PAIR; an Owner approval id is the only exception),
   - the candidate must contain every name / string literal of the baseline (DEGRADATION), unless `package/baselines/allowed-removals.json` lists the removal with a reason and an Owner reference,
   - a candidate much smaller than the baseline, or without live evidence, is refused; the TelemetryA candidate also goes through `artifact_guard.py check --stage promote`.
4. `python package/baseline_check.py promote ... --source-commit <sha> --at <date>` rewrites the manifest (the old baseline becomes a rollback entry) and writes the fingerprint file of every raised artifact. Commit the result (the promote commit).
5. `python package/baseline_check.py verify` must report ACCEPT on the machine (every deploy location holds the baseline SHA, no unlisted `TScoring.*.dll` in a deploy folder, pairs consistent).

The fingerprint (the .NET names and string literals of a DLL) is a tripwire for LOST features, not a proof: it cannot see a change of behaviour. The live acceptance and the deterministic tests stay the evidence.
