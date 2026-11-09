# Live saved-frame AI workflow check — 7 November 2026

The queued detection and assessment workflow passed using a real public wildlife photo and live Gemini 2.5 Flash calls in an isolated synthetic case. This is an integration check, not aerial performance, model accuracy, or clinical validation.

## Input and execution

Source: [iNaturalist observation 151797312](https://www.inaturalist.org/observations/151797312), photo 261969015. The live source API confirmed the photo association and CC0 license. Source reference taxon: Chelonia mydas. This photo already exists in our development manifest and is not an independent holdout.

The input was visually inspected: one turtle on sand. Preparation removed EXIF and converted to RGB JPEG; no source species label, location, or description was supplied to the model. No source GPS is retained in this report.

The request, evidence upload, detection enqueue, assessment enqueue, and result reads used the case API. Each model job ran in a separate invocation of the actual analysis worker. Temporary SQLite case data was cleaned after the run; results and provenance are preserved in the adjacent JSON record. No real incident or responder was used.

## Results

| Check | Result |
|---|---|
| Live detection | One turtle target; completed, one attempt |
| Live assessment | Completed, one attempt |
| Identification | Green Sea Turtle / Chelonia mydas; model confidence 0.95 |
| Model assessment | Monitor; severity confidence 0.55; advisory only |
| Worker elapsed time | Detection 5.035 s; assessment 18.433 s |
| Whole run | 24.687 s |
| Evidence integrity | Saved bytes matched recorded hash |
| Original intake and rescue phase | Unchanged |
| Camera capture time and animal GPS | Remained unknown |
| Notifications | None queued |
| Coordinator review | Required; no expert review performed |

## Model limitation found

The environmental rationale claimed the turtle was on the beach outside nesting season. Capture date, location, and nesting context were not supplied, so that inference is unsupported and must be rejected during review. The source species match does not validate the severity decision. Single-photo stillness cannot establish responsiveness or illness.

The workflow correctly retains the low-confidence result as a separate advisory assessment. It does not overwrite intake, confirm a rescue finding, or change dispatch. No threshold was calibrated from this example.

## Initial failure and fixes

The first attempt stayed queued with zero attempts and failed before model inference. Its worker only logged a generic cycle failure and returned success in once mode. The exact initial exception was not retained, so its root cause is not asserted.

The worker now exits nonzero after a failed once-mode cycle and logs only the exception class. Concurrent initial heartbeats use update/insert conflict recovery, and once mode avoids starting a redundant heartbeat thread. Detection limitations now describe an unverified viewpoint rather than assuming every still is aerial.

The original failed attempt remains separate from the successful rerun. Regression checks cover concurrent initial heartbeats and nonzero, redacted worker failure, alongside the existing follow-up tests.

## Remaining acceptance

Physical Mini 2 / teammate phone streaming and evidence transfer, representative aerial footage, independent expert annotations, and real configured reminder delivery remain unverified. No production feature activation, deployment, push, flight, or external notification was performed.

Machine-readable output: research/drone_validation/live_frame_ai_check_2026-11-07.json. Runtime and prompt hashes are included there; its git_commit identifies the base commit plus the recorded uncommitted runtime changes. Runner formatting was subsequently cleaned without another model call.

Verification: all 22 follow-up tests passed; Ruff passed for changed Python files.

Follow-up: the saved-frame context issue was addressed and revalidated in [the context grounding fix](drone_context_grounding_fix_2026-11-07.md). The original results above remain unchanged.
