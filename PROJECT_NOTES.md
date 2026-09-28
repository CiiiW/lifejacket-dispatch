# LifeJacket Project Notes

Running log of structure, decisions, known issues, and open work. Newest entries at the top of each section.

## Current Layout

| Folder | What it is | Main file |
|---|---|---|
| `Chatbox/` | Agent 1: intake chatbot (photo, CV, questions, assessment, follow-up loop, save) | `ChatBox_V8.ipynb` |
| `Coordination_agent2/` | Agent 2: triage and coordination prompt chain, shared data, Streamlit app, Cloud Run files | `agent2.ipynb`, `lifejacket_app.py` |
| `Coordination_agent2/dispatch_testing/` | 100-case dispatch benchmark: directory vs online search | `agent2_dispatch_online_vs_directory_100.ipynb` |
| `Gemini Confidence Testing/` | Vision research: species ID confidence across prompt strategies and distortion levels | `Gemini Confidence Testing.ipynb` |
| `archive/` | Superseded versions and exact duplicates. Nothing active reads from here | |

Shared data lives once, in `Coordination_agent2/`: `agent2_prompt_library.json`, `agent2_rescue_center_directory.csv`, `agent1_incident_database.csv`, `agent1_incident_schema.json`, `agent2_config.json`.

## Decisions

- **2026-09-28** Code, notebooks, prompts, CSV results and charts go to GitHub; raw photos stay out of the repo.
- **2026-09-28** Incident storage stays a CSV for now (`agent1_incident_database.csv`). Temporary only; see limits under Known Issues. Replace with SQLite locally, then Firestore or Cloud SQL, keeping the same column names.
- **2026-09-28** Keep the CDRL prompt in V8's CV module. On the research data it had the highest top-1 accuracy (53.9%) and the lowest confidence when wrong (35.8), ahead of the `_best` folder's prompt (51.7%, 39.3). Differences are small and based on only 5 photos.
- **2026-09-28** The column contract between Agent 1 and Agent 2 is `Coordination_agent2/agent1_incident_schema.json` (v1, 45 columns). Add columns only at the end and bump the version.
- **Pending** Whether V8 logic moves into a `lifejacket_intake.py` module (proposed: module holds logic, notebook becomes the walkthrough).

## Change Log

### 2026-09-28
- Put the project under git and connected it to https://github.com/CiiiW/lifejacket-dispatch (public, branch `main`). The repo root is the JupyterLab home folder; `.gitignore` allows only the project folders, and excludes raw photos (about 1.1 GB, rebuildable from iNaturalist), `archive/_duplicates/`, checkpoints and hidden files. Root `README.md` expanded from the original one-line version.
- Reorganized files. Old ChatBox versions (Demo_v1, v2 to V7), `agent2_reference.ipynb`, `_old cv testing`, `!round1 testing` and the notebook template moved to `archive/`. Exact duplicates moved to `archive/_duplicates/` (safe to delete).
- Dispatch notebook now reads the directory and prompt library from `Coordination_agent2/` instead of local copies.
- V8 image folder path fixed to `../Gemini Confidence Testing/hurt_animal_dataset_images` so it runs from `Chatbox/`.
- README: `agent2_prompt_first.ipynb` references corrected to `agent2.ipynb`; added Incident Database section.
- V8: added Save To Incident Database section. Each completed conversation appends one row to `agent1_incident_database.csv`, validated against the schema file. `SAVE_TO_DATABASE = False` disables writing during tests.
- V8 assessment prompt: added 10 injury and distress flags Agent 2 uses for triage (`llm_injury_present`, `llm_injury_confidence`, wound, bleeding, entanglement, swelling, abnormal posture, respiratory distress, unresponsive, `llm_mobility_concern`). Verified with a live Gemini call.
- V8 assessment prompt: added `llm_likely_animal_group` (pinniped, cetacean, sea_turtle, other, unknown). Stored in `final_llm_output_json`, not its own column yet.
- V8 cell 1 now imports `vertexai`, so the notebook runs top to bottom in a fresh kernel.

## Known Issues

- **Python 3.10 kernel.** Google's Vertex AI library (`google-cloud-aiplatform`) stops releasing updates for Python 3.10 after 2026-10-04. Current code keeps working, but new library versions will not install. Accepted for now; move to a Python 3.11+ kernel when convenient. Also check the Cloud Run `Dockerfile` (uses `python:3.12-slim`, so it is not affected).
- **CSV storage limits.** No locking (do not save from two sessions at once), append-only, and not durable on Cloud Run (resets on every deploy).
- **Columns with no V8 source.** `reported_color`, `reported_bleeding` and `cv_top3_*` are saved empty. V8 asks body covering instead of color, and bleeding arrives in free-text `reported_extra_condition`. Raw answers are in `incident_package_json`.
- **Two model setups.** Agent 1 calls `gemini-2.5-flash` through the `vertexai` SDK directly; Agent 2 uses the Google Gen AI SDK on Vertex AI with the model from config (default `gemini-3.5-flash`).
- **Vision research is small.** Strategy comparison used 5 photos (one a dog control). All strategies miss the same 2: common dolphin read as harbour porpoise, loggerhead read as green sea turtle. Both misses stay within the correct animal group.
- **High-confidence mistakes.** With CDRL, 50 of 485 answers at 90%+ confidence were wrong in the research data. V8 stops follow-ups at 0.90 (after follow-ups, not raw CV), so this threshold should be tested.
- **Injury detection untested.** V8's wound, blood and image-clarity checks and the new injury flags have not been evaluated on a dataset.
- **Minor prompt typo.** In V8's assessment prompt, the line "Do not ask a generic animal question if a more species-specific trait question is available." is repeated three times with a missing line break.

## Open Work (in suggested order)

1. Agent 2 side schema check: have `agent2.ipynb` and `lifejacket_app.py` validate the CSV against `agent1_incident_schema.json`.
2. Decide on the `lifejacket_intake.py` module, then build the real Agent 1 tab in the Streamlit app (photo upload, location, follow-up loop, send to Agent 2) and update the Dockerfile.
3. Route Agent 1 through the same Vertex client and config as Agent 2 (one model setting).
4. Consider a `llm_likely_animal_group` column in schema v2 so Agent 2 can route by group directly.
5. Evaluation on the 400-image hurt-animal dataset: animal-group accuracy and injury flag accuracy, plus a check of the 0.90 stop threshold.
6. End-to-end test: batch of images through Agent 1, database, Agent 2, dispatch recommendation. Keep as the regression test.
