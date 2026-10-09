# Imported observation maintenance workflow

Implemented for NeuraTwin Halo on 8 October 2026. This workflow belongs to an imported observation case, not to whichever industrial simulation is currently selected.

## Meaning and boundary

An imported recording is a retrospective reference. Its uploader may already know every future sample. Saving an assessment before the application reveals the holdout supports reproducible retrospective evaluation; it does not turn that recording into a prospective trial.

A closed workflow has status **closed_reference_review**. It means later, comparable reference evidence met the review criteria declared when the work order was opened. Every response and export retains **physical_repair_verified: false** and **causal_benefit_established: false**. It does not certify a repair, prove that an action caused a temperature change, or operate hardware.

Physical bench inspection and repair verification continue through their separate measured-evidence workflow. Surface-probe data must not be imported as oil or hotspot.

## End-to-end sequence

1. Import a CSV, declare its asset and source, and retain its file hash and parsed observations.
2. Review and freeze the observation-only assessment. The assessment stores hashes of the data prefix, settings, output and model source files.
3. Open a work order from that exact case and assessment.
4. Record an inspection and then an action. Times can be retrospective but must include a timezone and follow the originating observation.
5. Import and assess a separate later recording from the same declared asset and source class.
6. Link that follow-up to the original work order. The application compares the stable observation windows and reports explicit holds.
7. Close the reference review only when the declared acceptance criteria and evidence requirements pass.
8. Reveal both cases and export the complete immutable chain with a bundle hash.

## API

All writes require the existing operator authentication. Cloud reads also require team membership through the existing global middleware.

| Operation | Method / path | Request |
|---|---|---|
| List candidate cases | GET /api/halo/twin/challenges | Returns identifiers, names, source classes, asset IDs and assessed/revealed flags; no hidden future samples |
| Import | POST /api/halo/twin/challenges/import | Existing CSV import fields plus optional provenance |
| Bind an older imported case | POST /api/halo/twin/challenges/{case}/binding | request_id, provenance; binding can be created once, never silently replaced |
| Read maintenance context | GET /api/halo/twin/challenges/{case}/workflow | Origin binding and work orders with current verification |
| Create work | POST /api/halo/twin/challenges/{case}/work | request_id, title, owner, priority, acceptance_note, optional acceptance_rules |
| Inspection/action | POST /api/halo/twin/challenges/{case}/work/{work}/observations | request_id, revision, kind, observed_at, note |
| Link follow-up | POST /api/halo/twin/challenges/{case}/work/{work}/followup | request_id, revision, case_id, note |
| Close reference review | POST /api/halo/twin/challenges/{case}/work/{work}/close | request_id, revision, note |
| Export full chain | GET /api/halo/twin/challenges/{case}/workflow/export | Requires origin and linked follow-ups to have been revealed |

The source-class values are **synthetic**, **recorded_oil_reference**, and **unknown**. There is deliberately no field that labels an imported CSV as a verified live device or a verified physical repair.

## Immutable provenance

Provenance contains:

- asset_id and source_class;
- recording_started_at: explicit timezone-aware timestamp corresponding to elapsed_s = 0;
- units_verified: reviewer asserts the canonical units are seconds, Celsius, loading percent and per-unit voltage;
- calibration_reference and calibration_reviewed;
- configuration_reference and configuration_reviewed;
- reviewer and note.

These are uploader-declared references. Entering a reference does not automatically verify its contents. Synthetic recordings can reference their documented generator scale and assumed configuration; they must remain synthetic.

The binding additionally saves the recording, settings and original source-file hashes, temperature capability, author and timestamp. Corrections require a new imported case. The original samples, assessment and binding are retained. Work orders and follow-ups save the exact origin/assessment/binding/model hashes, rather than consulting the selected industrial simulation.

Older cases without provenance remain readable. They require a separate immutable binding before creating a work order. Existing idempotent import requests without a provenance field remain compatible.

## Acceptance rules

Defaults below are operator-review heuristics, **not transformer datasheet limits or safety requirements**. They are frozen at work-order creation.

| Rule | Default |
|---|---:|
| Stable comparison window | 10 minutes |
| Largest permitted sample gap | 120 seconds |
| Follow-up maximum load | 99% |
| Follow-up maximum oil temperature | 90°C |
| Required mean oil reduction | 0°C, meaning no increase |
| Maximum mean loading difference | 5 percentage points |
| Maximum mean ambient difference | 3°C |
| Maximum mean voltage difference | 0.02 pu |

Each window needs at least six valid observations spanning its declared duration. Oil, ambient, loading and voltage must be finite and within the observer's supported domain. Additional stability limits prevent averages from hiding large input changes: within-window load span at most 10 percentage points, ambient span at most 3°C and voltage span at most 0.04 pu.

Both recordings must have the same asset, source class, temperature capability, reviewed calibration reference and reviewed configuration reference. Unknown units, missing reviewed references, an unknown absolute recording time, inadequate coverage, active follow-up warnings or withheld follow-up validity block quantitative acceptance.

Every sample in the follow-up window is checked for an observed threshold breach; a normal final sample cannot erase an earlier breach in that window. The entire follow-up window must occur after the recorded action. A different calibration, lower load or cooler ambient can explain a temperature change and therefore cannot silently count as proof of maintenance benefit.

Even a passing result only establishes that these reference-review criteria were met. The output explicitly declines a causal or physical-repair conclusion.

## Ordering, persistence and retries

- A work order references a frozen assessment. An inspection precedes an action; an action precedes a follow-up link.
- Request IDs detect conflicting reuse. Identical retries do not duplicate observations or links.
- Mutations require the current work revision. Stale revisions return 409.
- The existing storage transaction now covers work records and their audit events atomically in SQLite and through cloud optimistic transactions.
- A closed review cannot be edited. A new investigation requires a new review.
- Binding, recording or assessment hash mismatches fail explicitly instead of presenting altered evidence as original.
- A failed or unavailable backend does not fall back to another evidence store.

## Verification

Tests in [test_observation_workflow.py](../tests/test_observation_workflow.py) cover the complete import-to-export chain, explicit reference closure, provenance immutability, old import request compatibility, source/asset isolation, chronology, missing calibration/units, operating-context changes, missing follow-up data, stale/idempotent requests, integrity tampering, atomic rollback and cloud access protection.

The app lifespan also invokes pending acquisition-analysis recovery once. That recovery is analysis-only: it does not open a serial port or issue hardware controls. Backend unavailability is retained as a startup recovery diagnostic and does not conceal the existing readiness endpoint's failure.

## Reproducible synthetic browser rehearsal

Run **python scripts/rehearse_observation_workflow.py** from the project root. It creates the two clearly synthetic CSVs below, uses the real API against a disposable SQLite database, completes the whole reference-review chain and exports the result. It never reads a private environment file or writes to the running application's database. Its report is [observation-workflow-rehearsal.json](../reports/observation-workflow-rehearsal.json).

The before file includes a deliberately injected +6°C oil indication after sample 75. This is an illustrative discrepancy, not a validated model of a particular failure. The after file omits that offset. Both retain an excited healthy commissioning prefix and then the same declared load, ambient and voltage. The resulting review can establish that the numerical acceptance rules pass; it cannot establish a real repair or causal effect.

| Browser form field | Origin recording | Follow-up recording |
|---|---|---|
| File | [synthetic-review-before.csv](../web/synthetic-review-before.csv) | [synthetic-review-after.csv](../web/synthetic-review-after.csv) |
| Name | SYNTHETIC reference review before | SYNTHETIC reference review after |
| Asset | SYNTHETIC-REVIEW-001 | SYNTHETIC-REVIEW-001 |
| Source class | synthetic | synthetic |
| Temperature mode | oil_only | oil_only |
| Origin row index | 90 | 90 |
| Recording start at elapsed zero | 2026-01-01T00:00:00Z | 2026-01-02T00:00:00Z |
| Units reviewed | true | true |
| Calibration reference | Synthetic generator scale v1; no physical sensor | Same text |
| Calibration reviewed | true | true |
| Configuration reference | Synthetic reference model 55C-rise/100min v1 | Same text |
| Configuration reviewed | true | true |
| Reviewer | Synthetic rehearsal reviewer | Synthetic rehearsal reviewer |

Use the note **Generated reference demonstration only; no field measurement or physical repair.** Review the first 70 rows as the known synthetic healthy prefix. Freeze each assessment. The original work order's inspection time is **2026-01-01T01:31:00Z** and action time is **2026-01-01T01:32:00Z**. If the browser uses local date/time controls, enter the equivalent local time, not the unchanged UTC clock digits; IST equivalents are **07:01** and **07:02** on 1 January. Recording starts are **05:30 IST** on 1 and 2 January respectively.

After linking, the expected comparison is 11 stable observations at 70% load, 30°C ambient and 1 pu voltage; mean oil falls by 6°C. Close **reference review**, reveal both cases and export. The application must retain the synthetic source label and false physical/causal verification flags throughout.
