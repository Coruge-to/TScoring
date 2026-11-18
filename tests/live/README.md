# tests/live: live tests that need BVE

Not part of the regression runs (they start BVE and send keys). Run by hand, with the PC left alone.

## F1 menu autonomous test (WP2 of the first completion)

    python tests\live\f1_autonomous.py --scenario "C:\Users\<you>\Documents\Bvets\Scenarios\iida_sanmpe.txt"

- Starts BVE 6 with the scenario, with the probe armed through the environment (`PYTHONPATH=tests\live\probe`, `TSPROBE_LOG=<file>`), waits for TScoring (the probe's `ARMED`),
  injects keys WITH SCAN CODES while BVE is in front (no on-screen keyboard needed), and runs the flow of `f1_flow.py`:
  open F1 -> the scoring settings pages 1/3 -> 2/3 -> 3/3 and back (the Backspace returns) -> the environment settings: switch a HUD item, the speed-limit / advance interlock
  (ENV-1), revert every switch -> close F1 -> reopen -> close.
- Verdict and exit code: `PASS` 0 / `FAIL` 1 (a check of the F1 contract did not hold: a product finding) / `INCONCLUSIVE` 2 (the setup did not hold: probe not armed, F1 never
  opened, a key never seen, BVE not in front: NOT a product finding) / 3 BVE did not start. `result.json`, `run.log`, `probe.log` are written to `%TEMP%\tscoring-live\<time>\`.
- F1 settings are NOT persisted (they are regenerated from the saved initial defaults at the next scenario load), so nothing is saved or restored on disk: the test checks the
  Overlay's state through the probe (`disp` = the 8 HUD switches, `hud_item_state` = what the HUD will draw) and that the end state equals the start state.
- It uses only the keyboard path a user has, one 0.15 s key press at a time, and refuses to send when BVE is not the foreground window or the left mouse button is down.

The same flow runs on the REAL Overlay without BVE in `tests/test_f1_flow_offscreen.py` (a Transport that calls the real key handlers, the same probe, the same log lines):
it passes on the real code, fails when the ENV-1 interlock is broken, and is INCONCLUSIVE when keys do not arrive. So the flow and its verdicts are in every regression run;
only the key injection into BVE needs the live run.

## The probe (`probe/sitecustomize.py`)

Observation only; the product is not changed. Python imports `sitecustomize` from every PYTHONPATH entry; the probe does nothing unless `TSPROBE_LOG` is set and the script is a
`main.py`. It also records the timing of the menu transitions (`ENTER ... dur`, `PAINT ... since_enter`, `STEP`, `STALL`), which is how the first paint of the scoring settings
page 3/3 was found to take 0.3-1.6 s (the bundled font has no subscript digits; see the FW-1 note in the handoff folder first-completion-v1-20261118).

## Official fullscreen

Not automated. Editing `BveTs6.Preferences.xml` (`Windowed=false`) does NOT reproduce BVE's official fullscreen (the BVE main window stays small, only the D3D proxy window is
full size: the HUD and the F1 menu are drawn in a stale box and look broken; this was a false alarm on 2026-11-17). Check it by hand: BVE settings -> window -> fullscreen, restart BVE.