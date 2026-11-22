# Verification and remaining device checks — 22 November 2026

## Source preservation

The original public head was `711fa37a542bc292c766dbe3a42093cf5a9e6557`, with tree `ac5edf0d9df2efc2274a1aeed13a5ded2daba066`. The retrieved source files and five existing local photos reproduce that tree exactly. The GitHub-signed commit and its original parent history were preserved locally, with branch `backup/before-pi-integration-20261122` and an original-history Git bundle. No existing local CAN project folder was modified.

## SSH synchronization runner update

The follow-up adds `run_pi.cmd`, `scripts/sync_pi.py` and a standard-library Pi receiver. It directly mirrors saved source to an adaptable `can_ids` folder without requiring GitHub publication. The PowerShell deployment wrapper now delegates to that runner.

The complete suite now contains **39 tests** (21 controller checks, 11 snapshot/synchronization checks and 7 setup/commit/control workflow checks). The added tests execute real snapshot packaging, content verification, backups, additions/modifications/deletions, renames, file-to-directory changes and the actual encoded receiver bootstrap in a subprocess with an archive on stdin. They also verify first-time adoption, protected configuration/runtime files, invalid archive/symlink/traversal rejection, and inclusion of uncommitted/new/deleted Git working-tree files. All filesystem mutations occur in disposable test folders.

`run_pi.cmd --help` and `run.cmd --help` ran successfully on Windows, and the PowerShell wrapper parsed successfully. The new workflow checks use real local and simulated-Pi folders with real Git commits and actual receiver subprocesses: prerequisite/folder preflight precedes laptop commits; a failed preflight prevents commits; multiple add/edit/rename/delete transfers create both histories and retain secrets/backups. They also check staged-secret rejection and app/terminal dispatch, including avoiding a second controller over a running service. The simulated transport replaces SSH network calls only; its Pi prerequisite apt/sudo branch and real service processes are not executed. No actual SSH transfer, Pi dependency install or service restart was possible without a Pi connection. The direct receiver test exercises the transfer payload/receiver without opening a network connection. Watch mode requires SSH keys/agent for later noninteractive transfers; password-only users can run a one-shot sync after each group of edits.

## Original controller checks

| Check | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 21 tests passed on Windows, Python 3.11.9 |
| Flask dashboard and API | Rendered through Flask's in-process HTTP test client; live state schema verified |
| CAN commands/telemetry | Real `python-can` in-process virtual buses; motor command bytes and ToF decode checked |
| IDS behavior | Network countdown → block → rearm; HTTP 403 containment and global CAN-control refusal checked |
| Control loss | Stale browser input sends STOP; a refreshed held command remains active |
| Model handling | Missing/incompatible bundle rejected without disabling rule mode; compatible joblib roundtrip and live score checked |
| Configuration | `.env` located from another working directory; external environment wins; quoted spaces/`#` preserved |
| Wi-Fi helper | Input validation and generated NetworkManager commands tested with mocked subprocesses; management adapter not selected for AP changes |
| USB helper | Serial-matched generated rule/unit and identity rejection checked; no physical USB payload executed |
| Python source | Compilation passed for controller, trainer, scripts, USB and offline modules |
| Dashboard JavaScript | `node --check` passed |
| PowerShell deployment helper | Parsed successfully with the PowerShell language parser; SSH deployment was not executed |
| Git | `git diff --check`, complete object/history integrity and original bundle verification checked locally |
| Root trainer | Actual default two-hour **synthetic** baseline completed: 3,600 windows × 8 features; generated a compatible model |

The synthetic sanity checks flagged 0/60 generated normal validation windows and all three illustrative generated attack windows. These are smoke-test outputs, not physical CAN attack accuracy, recall, precision or latency measurements. The generated model is ignored by Git and not committed.

Dependency installation was blocked by this execution environment's network restrictions. Tests used existing Python packages (Flask 3.1.3, NumPy 2.4.6, scikit-learn 1.9.1, python-dotenv 1.2.3, joblib 1.6.0) and unmodified official `hardbyte/python-can` v4.6.1 source in a separate temporary test dependency directory. No global or other-project dependency files were changed. This does not verify a fresh Pi installation.

A standalone controller process started and opened its virtual CAN backend, but the environment denied even loopback client sockets with Windows error 10013. Therefore a socket-based browser/HTTP end-to-end check was **not completed**; the passing Flask checks use its in-process test client. GitHub DNS was unavailable from the terminal. The connected GitHub integration allowed reads but returned HTTP 403 (`Resource not accessible by integration`) when asked to create the backup branch. Publication is separate from local verification and must not be inferred from a local commit.

## Run on the actual Pi

No Pi address/session or connected physical testbed was available. These checks remain required:

1. Run `scripts/setup.sh` with the Pi's Python and confirm its dependencies install cleanly.
2. Confirm SSH/PuTTY and Raspberry Pi Connect access; check VS Code Remote SSH save/commit behavior.
3. Configure real home Wi-Fi credentials, country and an AP-capable second adapter; check DHCP, client IPv4/MAC and reconnect after unplug/reboot.
4. Configure the Pi MCP2515 overlay from the actual crystal/INT wiring, flash the three ESP32 sketches, and verify frames/heartbeats on the physical 500 kbit/s bus.
5. With wheels raised, check joystick hold/release, close the browser, and verify physical motor stop. Check lock state independently.
6. Register the exact USB serial, install its generated rule/service, then verify insertion, maintained state, containment and removal/rearm.
7. Run a deliberate lab-only CAN anomaly with the appropriate model; verify sustained anomaly → motor stop → control refusal → clear/rearm.
8. Install the user service, enable lingering, reboot, inspect logs and confirm CAN setup and app availability. Bring CAN up via an OS service if automatic CAN configuration is needed.
9. From the local checkout, run `run_pi.cmd` against the real Pi, then save/add/rename/delete a test source file and verify the matching changes, protected runtime files and backups in the chosen target. Check watch-mode SSH authentication and the running service's post-restart health check.

If install/tests fail during update, the helper stops before restarting the running service; the checkout may already contain the fetched update. Inspect the error and backup branch before retrying. It does not roll dependencies/source back automatically.

The Ubuntu CI workflow will run software tests, Python compilation and Bash syntax checks after publication. Its presence is not evidence of a completed CI run.
