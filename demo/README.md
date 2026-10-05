# Demo incidents

Drop animal photos in this folder, describe them in `incidents.csv`, and run:

```bash
make run                                    # backend, in another terminal
make demo ARGS="--dry-run"                  # validate without spending calls
make demo ARGS="--limit 2"                  # try two rows
make demo                                   # all of them
```

Each row goes through the **real** intake API, so the incidents that come out
have genuine agent identifications, severity scores, reports, and guardrail
verdicts. Nothing is written straight to the database -- a hand-faked report is
the one thing a demo must not show.

Photos are gitignored (`*.jpg`, `*.jpeg`), so nothing you put here is
committed. `incidents.csv` is small and *is* committed, so keep personal
details out of it.

## incidents.csv

```csv
photo,latitude,longitude,condition,species,outcome,reporter_phone
harbor_seal_pup.jpg,36.6177,-121.9166,"Small pup alone on the sand, very thin, crusty eyes",Harbor seal,rescued,+15035550142
entangled_sea_lion.jpg,37.1200,-122.2800,"Deep gash on the shoulder, tangled in green netting, breathing fast",California sea lion,released,
```

| Column | Required | What it does |
|---|---|---|
| `photo` | yes | Filename in this folder. What the identification agent actually sees. |
| `latitude`, `longitude` | yes | Drives tide/weather lookup, species plausibility, and which centres are near. |
| `condition` | no, but | One sentence on what the reporter sees. This is what the assessment agent's questions get answered with. |
| `species` | no | **Ground truth, not an override.** Scores the agent; used to close a few incidents. |
| `outcome` | no | `rescued`, `released`, `deceased`, `not_found`, `no_action_needed`. Default `rescued`. Only used on logged rows. |
| `reporter_phone` | no | Makes the console's "Call reporter" button appear. |

## Three things that will bite you

**Keep rows more than 1 km apart.** Reports within 1 km and 24 hours are
treated as duplicate sightings of the same animal, marked `cancelled`, and
hidden from the console. `--dry-run` refuses to proceed if any two rows are
too close, and tells you which.

**`condition` matters more than it looks.** Without it, every assessment
question gets answered "Not sure", which flattens severity and makes all the
reports read alike. One specific sentence per row is the difference between a
demo that looks real and five copies of the same incident.

**`species` cannot force the identification.** The agent identifies from the
photo. The column is ground truth: the script prints an agent-vs-truth
comparison at the end, which is the same accuracy signal the responder app's
"Log outcome" screen exists to collect.

## Open vs closed incidents

By default the first two completed incidents are closed with a responder log
entry carrying the true species, so the console shows both states. A closed
incident leaves the open list -- use the **Show closed** toggle in the triage
panel to see it. Change the count with `--log-ground-truth N`, or `0` to keep
everything open.

## Cost

Roughly 6-12 live Gemini calls and a minute or two per row, on the GCP project
in `.env`. Use `--limit` before running twenty rows.
