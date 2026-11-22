# CAN IDS code-review follow-up

Date: 22 November 2026. Reviewed baseline: `b52e9d4`.

Workspace: `D:\My Projects\embed_proj`.
Git project: `D:\My Projects\embed_proj\Can_ids-update-20261122`.

The supplied second-pass review was checked against the local repository. Changes
below are local source edits, not a claim of Pi deployment or GitHub publication.

## Points that need correction or qualification

| Review point | Finding and reason | Resolution |
|---|---|---|
| 1: motor race is only a missed/duplicate STOP | Too narrow. Atomic reference reads do not keep command, client and timestamps consistent. A keep-alive/request can also race containment and send movement after STOP. Merely copying two globals under a lock does not order the later send. | Motor operations, attribution, keep-alives and containment now share a reentrant command lock; state reads/writes also use `state_lock`. Control routes recheck containment after acquiring the command lock. |
| 2: solenoid validation | Correct, but validation must reject truthy strings/numbers as well as non-object JSON. `"false"` previously requested ON. | Requires an object with a genuine boolean `on`; invalid or malformed requests return 400 and emit no CAN frame. |
| 3: nested snapshot and serialization | The mixed snapshot risk is real. The suggestion to serialize under the lock is unnecessary after making an independent deep copy. The same shallow-copy issue also affects `state.nodes`, which the review's code did not fix. | Both nested state trees are copied under their owning locks; serialization happens afterward. These are independent snapshots, not one globally atomic state/security transaction. |
| 4: bus race | A local `b = bus` does not prevent `shutdown()` overlapping `send()`. | A bus lifecycle/send lock covers construction, send and close; stale receive failures cannot close a replacement bus. Receive is not held under the send lock for its one-second timeout. |
| 7: population variance | Correctly identified as not a bug. These features summarize the complete window, and training/inference must agree. | Retained and documented. |
| 8: absolute model path | Absolute-path joining was already valid. The actual defect was missing `expanduser()` and duplicated path policy. | Controller/trainer now import the same `project_config.project_path`; relative, absolute and home-relative paths are covered. |
| 9: proposed Origin suffix expression | The second-pass explanation is wrong: for `origin="http://10.50.0.1:5000"`, `origin.endswith((":5000", "localhost", AP_IP))` is true because it ends with `:5000`. The expression would accept any host ending in that port; it is not a valid origin allowlist. | No suffix check added. Documented lack of authentication/origin policy, all-interface binding and isolated-network requirements. JSON endpoints now consistently require a JSON content type, which is not an authentication substitute. |
| 10 / priority-1 throttle snippet | A blanket early return inside 50 ms can discard release STOP; updating only the label after the throttle also lags feedback. | UI updates immediately; movement coalesces at 20 Hz. STOP bypasses the movement delay. Only one request is in flight so queued movement cannot finish after a later STOP; pending commands are cleared on block. |
| 11: atexit alone is graceful shutdown | Incomplete for a service: ordinary SIGTERM does not normally invoke Python atexit handlers. No cleanup can handle power loss/SIGKILL. | Added SIGTERM-to-normal-exit handling, a `finally` cleanup, an idempotent bus close and a stop event. ECU failsafe remains necessary. |
| 12: unused pandas | Confirmed; no imports found. | Removed from runtime requirements. `psutil` remains because offline telemetry uses it. |
| 14: MPU6050 | Confirmed: it was initialized but never read or transmitted. | Removed its object, initialization and direct includes; retained existing sensor CAN IDs. No untested IMU feature added. |
| 16: CAN setup usage | Confirmed low-cost improvement. | Help/usage and argument-error messages added before any network command executes. |
| 18: CI had no linting | The existing compilation, tests and Bash parsing were real checks, though not a linter. | Added Ruff syntax/undefined-name checks and executable Node dashboard tests to CI; local execution limits are below. |
| Unused `ids/` / duplicate feature pipeline | The running app does not use its models/policy engine, but the README already described that separation. Deleting the offline work or integrating an incompatible model format is not necessary. | Explicitly marked experimental. Its feature API now delegates arithmetic to `can_features.py`; offline rate overrides stay separate. Bundle formats and runtime policy remain separate. |
| ML evidence / accuracy | Correct. Synthetic training, held-out synthetic windows and illustrative attack cases do not establish physical-bus performance. A single asserted anomaly is only a regression smoke check. | Added that regression using the actual root trainer and live scoring path; no real precision/recall/F1/latency claims added. |
| Scores, 20-minute estimate and proposed 8–8.5 rating | Subjective estimates, not reproducible acceptance criteria. Locks, STOP ordering and environment/hardware checks require more validation than the snippets suggest. | Use behavioral tests and stated evidence limits; no new numeric project rating. |
| Resume state machine / MQTT | Correct: the live phases are NORMAL, COUNTDOWN, BLOCKED. No implemented MQTT was found. | README already states this. No resume file was edited as part of this code task. |

## Additional defects fixed

1. A blocked client could call `/api/ml/toggle`, change the detection mode and clear
   containment. The toggle now participates in containment checks and command
   serialization. CAN containment refuses mode changes until rearm as well.
2. CAN-window expiration happened only when a new frame arrived. A silent bus could
   therefore keep scoring old attack data forever. Scoring now expires old frames
   even without new traffic. Silence may still be anomalous; clearing stale frames
   does not promise that a silent bus will be classified normal.
3. The feature docstring claimed empty windows were seen in training. The current
   normal-traffic simulator does not provide them; the claim was removed.

## Implemented scope

All priority-1 fixes are implemented, with the concurrency/STOP refinements above.
Priority-2 items are implemented: bus synchronization/cleanup, common paths,
pandas removal, experimental offline classification/shared feature arithmetic,
and explicit trust-model documentation.

Priority-3 source changes are implemented: MPU cleanup, CAN setup usage, initial
Ruff CI configuration and an optional single-process threaded Waitress mode. Set
`APP_SERVER=waitress` after installing `requirements-server.txt`, then launch
`app.py` through the existing runner/service. A bare WSGI import does not start
the CAN/IDS workers; do not use multiple controller workers. Flask remains the
default lab server. See the README for the full server/access model.

## Verification performed

| Check | Result and boundary |
|---|---|
| Original Python suite | 43/43 passed before new regression cases were added. The reported missing-SSH test failure did not reproduce here. |
| Expanded Python suite | 54/54 passed, including actual virtual-CAN commands, malformed solenoid bodies, nested snapshot isolation, an already-validated request racing containment, shutdown versus send, blocked ML toggle, common paths and shared offline features. |
| Dashboard behavior | 4/4 Node tests passed: request ordering/release STOP, 1,000 pointer updates capped to 20 movement sends per second, blocked queue cleanup and held-position refresh. These execute the actual inline dashboard JavaScript with mocked DOM/fetch/timers, not a physical browser or motor. |
| Root trainer | Default two-hour simulation completed: 3,600 windows, eight features. Normal synthetic validation flagged 0/60; all three illustrative attack windows flagged anomalous. Model output stayed in ignored `.venv/review-model.joblib`. This is not physical-bus accuracy. |
| Python compilation / Git whitespace | Passed for controller, common features/config, trainer, scripts, USB, offline modules and tests; `git diff --check` passed. |
| Secondary static/feature checks | Official Pyflakes 3.4.0 source checked syntax/undefined-name categories across all 28 Python files with no findings; this is not a Ruff run. Empty, sparse and mixed feature vectors also matched the baseline offline algorithm before deduplication. |
| Fresh dependency installation | Blocked by package-host DNS failure. A project venv was created; tests used existing Python 3.11-compatible local packages and unmodified official python-can v4.6.1 source in ignored `.venv/test-deps`. No global or other-project packages were installed, changed or removed. |
| Ruff / Waitress runtime | Ruff and Waitress could not be installed locally due to that DNS failure. The new lint job and optional server therefore remain unexecuted locally. Configuring CI is not evidence of a passing CI run. |
| Bash / firmware | Local Bash invocation failed with access denied; shell parsing/help execution remain unverified here. Arduino CLI/toolchain and connected ESP32 hardware were unavailable, so firmware cleanup was inspected but not compiled/flashed. |

## Still requires the physical testbed

Record normal traffic and labelled flood, spoof and replay runs from the actual
Pi/ESP32 bus. Split recordings by run/session before fitting or tuning. Evaluate
the compatible live feature/model pipeline on held-out sessions and report class
counts, confusion matrix, precision, recall, F1 and false-positive rate. The
synthetic attack helpers replace normal traffic with isolated illustrative
patterns; those checks alone do not prove realistic mixed-traffic attack detection.

Measure attack-start-to-BLOCKED over repeated runs using a defined clock/event
source. Report the run count, mean and spread, together with `BLOCK_DELAY`, scoring
window and polling interval. Configured countdown is not measured detector latency.

Verify physical motor release/browser disconnect/containment, CAN reconnect,
service SIGTERM/restart, USB insertion/removal and the revised Sensor ECU on the
real hardware. Application containment cannot stop a malicious CAN transmitter
from injecting frames directly onto the wire, including subsequent motor commands.
Authentication and stronger network isolation remain prerequisites for a deployment
outside the intentionally trusted laboratory network.

## Final software pass

- Mode changes increment a generation counter. The monitor drops old results and serializes its final transitions with control/mode changes, so an OFF/ON toggle during scoring cannot revive an obsolete countdown.
- Model output directories are created as needed. A completed temporary model replaces the destination atomically; failures preserve the previous model and remove the temporary file. A regression covers an interrupted write and successful replacement.
- Boolean joystick coordinates are rejected. The browser handles ML-toggle refusals consistently with other controls.
- Sensor firmware guards ToF reads after failed initialization and reports unknown distance for invalid ranges. This firmware change still needs compilation/flashing and physical checks.
- Final results: 54 Python tests and four Node dashboard tests passed. Fresh dependency installation was retried and failed; Git Bash also failed during sandbox process initialization. No GitHub push or physical deployment was performed.
