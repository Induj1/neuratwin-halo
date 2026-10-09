# Evaluation protocol and external recordings

This procedure separates three kinds of evidence:

1. **Known-corpus regression:** the existing 91001–91024 synthetic seeds, already inspected in earlier reviews. Changes in results test the revised implementation; this is not fresh validation.
2. **Fresh internal synthetic evaluation:** new randomly selected seeds, frozen source and methods before generation, one claimed run, with every result retained. These are still our internally generated plants and paired cases, not externally supplied recordings or independent field assets.
3. **Externally supplied recording:** an identified third-party oil-temperature trace processed by the same observation assessor. Its origin, units, calibration and settings must be supplied and reviewed. Uploading a file does not verify those claims. A recording known to its uploader is retrospective, not a prospective physical trial.

## What the report measures

The full pipeline, without-CUSUM ablation and true threshold-only comparator retain separate outcomes. Completing the predefined expected signal set is not the same as any warning, and neither proves a real fault's cause.

- **Critical-warning recall:** every synthetic critical crossing is retained, including missed warnings. An alert at the crossing is not an early warning.
- **Paired warning lead:** baseline first-warning time minus full-pipeline first-warning time for the same case. Positive means the full pipeline warned earlier. Cases with missing warning timestamps are counted separately, never silently converted to zero. Counts and distributions are shown overall, by family and by condition.
- **First-warning attribution:** the original warning categories accompany every pair. Earlier model disagreement must not be presented as a forecast-derived advantage. Simultaneous categories can overlap.
- **Alarm burden:** false-alarm minutes, episodes, affected cases, episode durations and episodes per 100 labelled inactive **case-hours**. The denominator includes healthy and pre-onset minutes; it is not a fleet field-hour estimate. Warning-kind minute counts can overlap.
- **Forecast evidence:** separate oil and reported hot-spot targets at 5, 15 and 30 minutes; all eligible/missing/withheld targets stay in the coverage denominator. Model/persistence errors compare the same scored targets. Signed error is prediction minus observation, so negative values indicate underprediction. Reports retain MAE, RMSE, median/P95/maximum error, underprediction tails, per-target paired wins/ties/losses and family/condition/time partitions.

The P95 calculation remains the historical sorted-array definition, index `min(n-1, floor(.95*n))`. These descriptive distributions are not calibrated prediction intervals. Paired seeds and overlapping origins are dependent; no independent-asset confidence interval or significance claim is made.

The independent plant evaluation ends at a 30-minute horizon. The scenario-informed planner's 240-minute parameter-corner study and its execution checks remain **internal consistency evidence**. The planner knows declared cooling/fault conditions; the observation assessor receives observed prefixes and no hidden cooling or fault labels. A matching simulated intervention cannot validate real maintenance benefit or long-horizon safety.

## Freeze and run fresh synthetic evaluation

Finish numerical code and development tests first. The freeze command must run before any generation or inspection of its chosen seeds:

```powershell
python scripts/prospective_evaluation.py freeze --protocol reports/pipeline-v5-fresh-protocol.json --seeds 24
python scripts/prospective_evaluation.py run --protocol reports/pipeline-v5-fresh-protocol.json
```

`freeze` records the pipeline version, source hashes, current starting settings, plant families, conditions, origins, horizons, comparator definitions, seed count and selected seeds. It excludes seeds found in existing JSON reports plus explicit development/historical ranges. Selection does not run the plant or assessor.

`run` refuses changed source or an altered protocol. Before evaluation it exclusively creates `pipeline-v5-fresh-protocol-claim.json`; a second invocation cannot reuse the claim. A completed run writes:

- `pipeline-v5-fresh-protocol-run/benchmark.json`
- `pipeline-v5-fresh-protocol-run/forecasts.csv`
- `pipeline-v5-fresh-protocol-run/decisions.csv`
- `pipeline-v5-fresh-protocol-run/manifest.json`, binding the protocol digest, run ID, source hashes and exact artifact bytes.

A failed/interrupted run leaves its claim consumed and, where possible, a `failed.json`. Preserve the failure. Do not delete the claim to obtain a preferred result. If another study is justified, document why and create a distinct protocol; the old result remains known evidence.

This is a **local source-bound protocol**, not external preregistration or tamper-proof custody. A user with filesystem access can replace files. Hashes detect changes against retained copies, not authorship. Share the protocol and claim before viewing results when independent custody is wanted. After results are seen, the seeds are no longer unseen and must not be tuned and re-presented as fresh.

The benchmark has no score-driven pass/fail threshold invented after inspection: report predictive errors, coverage, misses and alarm burden together. Zero forecast-validity overrides and simulator action consistency are correctness checks; passing them does not establish diagnostic accuracy.

## Evaluate an externally supplied CSV with the existing API

Use Evidence → import recording → bind source → freeze observation assessment → reveal later readings. Required channels are `elapsed_s, oil_c, ambient_c, load_percent, voltage_pu`; add `hotspot_c` only for a real reported hot-spot channel. Optional RMS phase channels use the observer's supported contract. A surface probe is not oil. The first 70 rows must be a reviewed healthy reference, with the required duration/excitation; the assessment origin follows that prefix.

For a reproducible CLI invocation, use the existing authenticated case endpoints. Prepare a metadata file locally; do not put credentials into it:

```json
{
  "asset_id": "SUPPLIER-ASSET-ID",
  "source_class": "unknown",
  "recording_started_at": null,
  "units_verified": false,
  "calibration_reference": null,
  "calibration_reviewed": false,
  "configuration_reference": null,
  "configuration_reviewed": false,
  "reviewer": "Named reviewer",
  "note": "Identify supplier, acquisition method, channel meanings and limitations."
}
```

Replace placeholders with real information. Use `recorded_oil_reference` only when that source classification is justified; review flags must reflect actual review. Missing metadata can remain unknown and must not be fabricated to unlock quantitative maintenance acceptance.

```powershell
$reviewBase = 'http://127.0.0.1:8765/api/halo/twin/challenges'
$reviewHeaders = @{ Authorization = 'Bearer ' + $env:HALO_OPERATOR_TOKEN }
$reviewMetadata = Get-Content -LiteralPath '.\recording-provenance.json' -Raw | ConvertFrom-Json
$reviewPayload = @{
  request_id = [guid]::NewGuid().ToString()
  name = 'Supplier recording — reviewed oil channel'
  temperature_mode = 'oil_only'
  csv_text = Get-Content -LiteralPath '.\recording.csv' -Raw
  origin_index = 90
  healthy_reference_reviewed = $true
  provenance = $reviewMetadata
} | ConvertTo-Json -Depth 12
# Retain this payload locally for an exact idempotent retry; do not publish private data.
$reviewCase = Invoke-RestMethod -Uri ($reviewBase + '/import') -Method Post -Headers $reviewHeaders -ContentType 'application/json' -Body $reviewPayload
$reviewUrl = $reviewBase + '/' + [uri]::EscapeDataString($reviewCase.id)
$reviewAssessment = Invoke-RestMethod -Uri ($reviewUrl + '/assess') -Method Post -Headers $reviewHeaders
Invoke-WebRequest -Uri $reviewUrl -Headers $reviewHeaders -OutFile '.\frozen-external-assessment.json'
# Only after the assessment is frozen:
$reviewRevealed = Invoke-RestMethod -Uri ($reviewUrl + '/reveal') -Method Post -Headers $reviewHeaders
Invoke-WebRequest -Uri $reviewUrl -Headers $reviewHeaders -OutFile '.\revealed-external-case.json'
```

Use a configured operator credential; the app does not accept an empty token for writes. For cloud sessions, use the signed-in application instead of copying HttpOnly cookies. CLI requests are explicit imports into the selected workspace, not offline analysis. They do not operate hardware.

The assessor's frozen record includes input/settings/result hashes and numerical source hashes. Retain the original CSV and its SHA-256, supplier/reference identity, protocol, calibration and exact exported bytes. Downloads must use raw response bytes: parsing and re-serializing JSON in JavaScript can convert `10.0` into `10` and invalidate existing nested digests.

The API holds future rows from the assessor until its immutable assessment is produced, then scores later observations. The uploader already knows a historical recording; call this **retrospective holdout evaluation**. No fault-detection recall is valid without independently supplied onset/ground-truth annotations. A single healthy commissioning trace does not establish generalization across assets.

The same case can enter the imported-recording maintenance workflow. Comparable later evidence can close a **reference review**, never automatically certify physical repair, causal benefit, recovered insulation life or a maintenance-cost saving.
