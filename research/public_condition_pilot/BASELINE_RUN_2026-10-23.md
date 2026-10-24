# First live public-photo condition baseline

Run `82cebed1b3e44e4c8b2352b22be595f9` started 2026-10-23 at
04:56:11 UTC on the GCP notebook, using Vertex `gemini-2.5-flash`.
This is a development baseline; the sample has no expert injury ground truth.

| Initial image-only result | Photos |
| --- | ---: |
| Detection processed | 40 |
| Single detected target identified and assessed | 38 |
| Multiple detections, awaiting human target choice | 2 |
| No detection | 0 |
| Failed case | 0 |
| Human annotations | 0 |
| Expert-verified annotations | 0 |

Target selection is required for `inat_101291305_169148756` and
`inat_387081105_708774713`. A single detection is also unconfirmed until a
reviewer checks that box. Successful execution is not evidence of correct
localization, species or injury predictions.

| Predicted animal group among 38 assessed targets | Count |
| --- | ---: |
| Sea turtle | 6 |
| Wild land animal | 10 |
| Pinniped | 4 |
| Domestic animal | 6 |
| Cetacean | 5 |
| Seabird | 5 |
| Other marine | 2 |

These are model predictions, not validated group labels. The reviewer uses the
same eight-value animal-group enum as the chatbot, including unknown.

The latest saved attempts recorded 386,346 prompt tokens, 30,641 output tokens,
and 802.421 summed per-image wall seconds. The batch used at most three concurrent
images after a two-image smoke test. Summed image time is not elapsed batch time
or a complete billing ledger of retries. No clinical accuracy is reported.

The collection manifest SHA-256 is
`143b6b60d8ecb413db438145b3b81d2561863bb21d14737fcb32bc359dc34b12`.
Original-photo hashes were checked before analysis. EXIF is removed and
orientation normalized before detection; crops go to identification/assessment.
Source names, descriptions, group hints and coordinates are excluded from model
inputs. Run metadata retains inference-code and prompt hashes and settings.

The private review app is served at `/proxy/8813/` on the authenticated GCP
notebook. Saved outputs and histories are in
`var/condition-baseline/pilot-v1-live/`; use the page's export button for current
results and reviews. See [usage and annotation rules](README.md#image-only-baseline-and-private-review).

Validation: **361 backend tests passed** locally and on GCP. Changed Python files
passed Ruff; the review-page script passed Node syntax checking. Browser checks
covered the private page, original media, shared group choices, manual drawing,
multiple-detection controls and keep/discard navigation. Scripted tests verify
orchestration only. UI checks did not create human annotations.

Next: annotate visible signs with model/source suggestions hidden, check target
boxes and viewpoints, then compare the same target/version using provisional
annotations. Independent expert review and a held-out NOAA sample are still
needed to evaluate injury performance. Aerial patrol video needs its own
representative evaluation; these opportunistic photos do not establish that.
