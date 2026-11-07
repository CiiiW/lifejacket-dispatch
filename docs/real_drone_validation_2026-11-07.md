# Real-photo retrospective validation — 2026-11-07

This analysis uses saved model outputs from real iNaturalist photos. It is a retrospective development-data analysis, not a fresh model run, independent hold-out, clinical validation or aerial-drone benchmark. The configured 90% threshold was not changed and remains provisional.

## Findings

- Animal-group agreement with the existing reference labels: **97/102 (95.1%)**. Reference species come from the existing iNaturalist manifest and its project group mapping; they have not been independently adjudicated for this study.
- At 90%, **100** photos meet the pooled group-confidence cutoff. **4** of those disagree with the reference group. A low-confidence trigger does not flag these confident disagreements.
- **1** photo has no usable pooled group-confidence score; this is an unscorable/abstaining result, not an extra confident misclassification.
- On the condition pilot, **24/38 (63.2%)** assessed photos trigger an additional-evidence suggestion at 90%. **6** also trigger the existing urgent parallel-review note. These are policy outputs, not confirmed clinical needs.
- The pilot has **40** photos, **38** assessed predictions and **2** cases requiring target selection. Target-selection cases are excluded from the assessed denominator and are not labeled healthy.
- The saved condition run has **0** review files. No expert condition or verification-needed labels are available for an accuracy/precision estimate.
- The two development samples overlap on **4** observation IDs. Their sample sizes must not be added as independent observations.

## Group-level reference agreement

Confidence is pooled across candidate species in the same routing group using the current drone-suggestion policy. A tied maximum is recorded as unresolved. Missing/invalid scores remain unknown.

| Reference group | Photos | Agreement |
|---|---:|---:|
| cetacean | 32 | 32 |
| domestic_animal | 3 | 3 |
| other_marine | 9 | 7 |
| pinniped | 29 | 27 |
| sea_turtle | 11 | 10 |
| seabird | 12 | 12 |
| terrestrial | 6 | 6 |

## Disagreement audit

The last column is a reference link retained by the source manifest, not a new expert review. Unknown confidence is not converted into a numeric score.

| Case | Reference group | Pooled model group | Pooled confidence | Source |
|---|---|---|---:|---|
| eumetopias_jubatus_02 | pinniped | terrestrial | 95% | [iNaturalist](https://www.inaturalist.org/observations/264136175) |
| odobenus_rosmarus_01 | pinniped | cetacean | 98% | [iNaturalist](https://www.inaturalist.org/observations/6659273) |
| lepidochelys_kempii_01 | sea_turtle | unresolved | unknown | [iNaturalist](https://www.inaturalist.org/observations/153735396) |
| enhydra_lutris_02 | other_marine | pinniped | 95% | [iNaturalist](https://www.inaturalist.org/observations/127403691) |
| trichechus_manatus_01 | other_marine | terrestrial | 98% | [iNaturalist](https://www.inaturalist.org/observations/37589411) |

## Condition-policy workload sweep

These counts replay the current suggestion policy on saved image-only predictions. The eligible workflow state is constructed for this analysis; no incident, request or flight is created. Signal counts can overlap within a suggestion.

| Cutoff | Assessed photos | Suggestions | Group-confidence signal | Condition-confidence signal | Urgent parallel-review note |
|---|---:|---:|---:|---:|---:|
| 50% | 38 | 5 | 0 | 5 | 0 |
| 60% | 38 | 8 | 1 | 8 | 0 |
| 70% | 38 | 11 | 1 | 11 | 1 |
| 80% | 38 | 17 | 1 | 17 | 4 |
| 85% | 38 | 24 | 1 | 24 | 6 |
| 90% | 38 | 24 | 1 | 24 | 6 |
| 95% | 38 | 33 | 6 | 31 | 10 |
| 99% | 38 | 35 | 21 | 32 | 12 |

## Provenance and limits

- Identification: saved original-image run `first_look_20261005_172608`, gemini-2.5-flash, begun 2026-10-05T17:26:08. Location context was included; the run metadata records uncommitted source changes.
- Condition: run `82cebed1b3e44e4c8b2352b22be595f9`, gemini-2.5-flash, begun 2026-10-23T04:56:11.128887+00:00. The saved run used image pixels without source labels or descriptions.
- Raw condition-confidence audit: `{}`. Missing raw scores are retained as unknown; old parser defaults are never used as model-provided confidence. An empty object means no missing/raw-vs-stored discrepancies were found.
- Input manifests, saved predictions, run metadata and the current policy source have SHA-256 fingerprints in the JSON report.
- No new model inference calls, model training, expert labels, operational rescue cases or aircraft commands were created.
- The sample is opportunistic, includes non-marine groups, and has development exposure. Marine groups are reported separately above; do not treat the aggregate as marine-only performance.
- Current model/prompt changes are not evaluated by replaying older predictions. Species/group agreement does not establish whether another observation would improve a rescue decision.

## Action from these results

1. Review the four high-confidence group conflicts and the unscorable result. Verify the images, reference labels and target selection, and assess image-quality and taxonomy checks alongside confidence.
2. Keep 90% provisional. Choosing a higher cutoff increases review workload in this sample, but cannot establish clinical benefit or precision without labels.
3. Use the prepared 40-case blind review template to label whether more observation would help, and record uncertainty. Source group hints and model findings are omitted. These remain development/validation cases.
4. Obtain a separate qualified-reviewer/NOAA sample with representative distant/aerial and clear/unclear views. Keep animal events separate and reserve independent cases for the held-out test cutoff evaluation.

## Reproduce

`python scripts/validate_real_drone_data.py --condition-run /home/jupyter/var/condition-baseline/pilot-v1-live`

The input prediction directory is local research data and is not committed with this change. The aggregate report excludes coordinates, reporter contacts and raw observation descriptions.
