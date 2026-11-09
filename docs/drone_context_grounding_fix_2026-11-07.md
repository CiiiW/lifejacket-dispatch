# Saved-frame context grounding fix — 7 November 2026

The saved-frame workflow now withholds unsupported environmental rationale and deadlines. The model prompt explicitly prohibits inferring season, local nesting context, capture date, or geography from a species, a beach photo, or processing time.

## Changes

- The current still-photo adapter has no verified weather, tide, daylight, or local nesting-data input. Its accepted environmental rationale is therefore an application-written statement of those unknowns. Its time_sensitivity_hours is null.
- Model environmental prose and timing are retained under context_validation.withheld_model_fields for audit. They are explicitly not accepted evidence.
- One still cannot establish movement or responsiveness: mobility remains unknown; unresponsive=false means not observed, not confirmed responsive. Injury-present is recomputed from the remaining visible injury/distress flags, so a model's stillness inference alone cannot create injury.
- The photo-only path does not send follow-up questions to a nonexistent live reporter. The assessment remains uncertain and requires coordinator review.
- Visible wound, bleeding, entanglement and other injury/distress flags still feed the existing deterministic severity calculation. This does not confirm those model findings as clinically correct.

## Verification

All 45 tests across context grounding, queued follow-up, and drone intake passed. Ruff passed for the changed Python files.

Regression tests inject a false nesting-season claim, an invented two-hour deadline and unsupported immobility/unresponsiveness. Environmental context is withheld both with and without a supplied date/location; visible wound and bleeding findings survive the checks. A separate test confirms that stillness alone is not accepted as injury.

The same CC0 turtle photo was run through separate real worker processes for detection and assessment using live Gemini 2.5 Flash. The final run passed all original isolation/provenance checks plus five grounding checks: no environmental deadline, unknown movement, no inferred unresponsiveness, no unanswerable reporter question, and preserved audit fields. Intake and rescue phase stayed unchanged, and no notifications were queued.

An earlier post-prompt run stopped claiming nesting season but still generated six hours despite saying environmental timing was unavailable. It also marked the turtle immobile. These observations motivated the application checks; prompt changes alone are not treated as sufficient.

## Limits

This corrects the saved-frame output handling for the observed failure class. Other model prose, injury flags and recommendations still require expert review. It does not establish aerial performance, clinical accuracy, threshold calibration, or Mini 2 hardware integration. Existing saved assessments are historical records and are not rewritten.

The live record is research/drone_validation/live_frame_context_fix_2026-11-07.json. It includes the input provenance, runtime/prompt hashes, results and all checks. The previous validation remains preserved for comparison.
