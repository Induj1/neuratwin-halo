# NeuraTwin Halo — software audit closure

Historical hardening snapshot. See [the current release record](RELEASE_READINESS_2026-10-09.md) for continuous recovery, v5 evaluation and latest verification.

This update addresses the concrete gaps from the CPRI-style audit. It does not establish a judging score, electrical commissioning, or field predictive accuracy.

## What changed

| Before | After | Why |
| --- | --- | --- |
| A changed temperature-calibration offset could appear to be maintenance improvement. | Physical comparisons require unchanged immutable calibration/configuration identities and consistent raw values in both windows. | A numerical conversion change is not evidence of repair. |
| Accepted sensor acquisition could survive a crash without completed analysis. | Acquisition and a pending-analysis job commit together. Startup can recover pending analysis with hardware commands disabled. | Preserve accepted evidence without unexpectedly operating relays. |
| Historical readings could inherit today's configuration. | Frames, models and decisions retain their acquisition configuration. Unbound legacy readings remain visible, with dependent interpretation withheld. | Later settings must not rewrite history. |
| The observer discarded available phase information. | Valid phase observations determine electrical severity and thermal loading; absent/partial phase data have explicit assumptions or holds. | Operations and observation review should assess the same evidence consistently. |
| The reported threshold baseline still contained model logic. | Separate genuine threshold-only, without-CUSUM, and full-pipeline comparisons. | Attribute any improvement to the correct method. |
| Imported recordings stopped at assessment. | Immutable source binding → frozen assessment → work order → inspection → action → comparable later recording → reference-review closure → export. | Keep the maintenance decision traceable to its source, not the currently selected simulation. |
| A held health assessment prominently displayed a substitute stress score. | The dial says Review/Tripped/Held when health is unavailable; operating stress is separately labelled. | Missing confidence must not look like a healthy asset. |
| Controls and explanatory copy pushed the main evidence down the screen. | Compact decision ribbon, load/imbalance controls, adjacent model/waveform/dial; advanced settings and exports in disclosures. | The first interaction should show a decision and its evidence. |
| Contribution clicks selected the whole model. | Thermal and electrical contributions highlight radiator/bushing geometry with an explicit explanatory label. | Explain the relevant component without claiming fault localization. |
| Browser JSON reserialization could invalidate evidence hashes. | Authenticated downloads preserve the exact server bytes across workflow, case, prototype and reference exports. | The downloaded artifact must verify, including integer-valued floats. |
| A failed recording-form response could duplicate a retry or restore a stale view. | Stable intent IDs, partial-import recovery, guarded callbacks and preserved disabled states. | Network interruptions and navigation must not corrupt the evidence workflow. |

## Validation

- Full Python suite: **292 passed**, recorded in `reports/halo-hardening-tests.xml`.
- JavaScript suites: **40 passed**, including the real waveform/health helpers and imported-workflow event handlers. See `reports/halo-hardening-js-tests.txt`.
- Isolated recording workflow: import, source binding, assessment, inspection, action, comparable follow-up, closure and hashed export. See `reports/observation-workflow-rehearsal.json`.
- Hardware provenance regressions: calibration-change rejection, immutable configuration and command-free startup recovery. See `reports/hardware-provenance-rehearsal.json`.
- Additive Supabase migration applied and its readiness RPC verified; hardware control remains disabled. See `reports/hardware-cloud-migration.json`.
- Current numerical benchmark reruns the existing 480 paired synthetic cases. It is a fixed-corpus regression, not a fresh held-out trial or 480 independent physical assets. Source hashes are retained.
- Browser and extracted-package results are recorded separately in `reports/halo-hardening-browser.json` and `reports/submission-package-smoke-current.json`. The latter identifies the exact tested ZIP and remains alongside it to avoid a self-referencing manifest.

## How to demonstrate the improvement

1. In Digital twin, change simulated load and imbalance. Show the immediate electrical response and delayed thermal response. Waveforms reconstructed from RMS remain explicitly illustrative.
2. Use the warning's comparison button. Inspect conditional no-action/reduced-load curves, then apply a simulated reduction. Advance five minutes while paused; the run returns to paused state.
3. Replay an alert. History inspection disables simulation mutations and keeps the model, readings, waveform envelope and health breakdown on the same observation.
4. In Evidence, import the labelled `synthetic-review-before.csv`, bind its declared source and freeze the assessment. Follow the documented reference-review sequence using `synthetic-review-after.csv`.
5. In Maintenance, choose **Imported recordings** to reopen the same case. Close only after comparable evidence passes. The result explicitly remains **reference review**, not verified physical repair.
6. Show the benchmark's three policies. All warned before the same 82 critical crossings; richer diagnostic coverage comes with two false-alarm episodes. Do not present this as proven superior critical-warning recall.

## What still requires actual evidence

The software cannot supply verified transformer/controller identity, safe mains wiring, reviewed sensor calibration, actual acquired hardware response, long-duration reliability or independent real-fault evaluation. No oil/hot-spot measurement is inferred from the surface probe as a measured channel. K4 remains locked. No equipment was operated during this update.

The physical recovery mechanism processes at most 100 pending jobs per startup, newest first; it is not a distributed continuous worker. Configuration matching is a firmware report, not proof of physical wiring. Imported source metadata is uploader-declared. Reference closure cannot establish causality or a repaired asset. These limits are retained in the relevant views and exports.

## Reproduce

```powershell
python -m pytest tests -q
node --test tests/test_command.mjs tests/test_waveform.mjs tests/test_evidence_workflow.mjs
python scripts/rehearse_observation_workflow.py
python scripts/benchmark_pipeline.py --split evaluation
python scripts/package_submission.py
python scripts/smoke_submission.py
```

For the installed Windows Python 3.14 environment's readline/pytest incompatibility, use:

```powershell
python -c "import sys; sys.modules['readline']=None; import pytest; raise SystemExit(pytest.main(['tests','-q']))"
```
