# LifeJacket Dispatch

A geo-aware, agentic AI system for stranded sea mammal rescue dispatch and response coordination.

## Status
In progress. See [PROJECT_NOTES.md](PROJECT_NOTES.md) for the current layout, decisions, change log, known issues and open work.

## How It Works

```
Reporter photo + location
        |
        v
Agent 1: Intake (Chatbox/ChatBox_V8.ipynb)
  Gemini CV -> fixed questions -> assessment -> follow-up loop (max 5)
  -> saves one row to Coordination_agent2/agent1_incident_database.csv
        |
        v
Agent 2: Triage & Coordination (Coordination_agent2/agent2.ipynb)
  species -> validation -> duplicates -> severity -> action -> dispatch
  -> alert card + guardrail -> end-of-day log -> prompt improvement
  A human coordinator approves every dispatch.
        |
        v
Demo app (Coordination_agent2/lifejacket_app.py, Streamlit on Cloud Run)
```

## Repository Layout

| Folder | Contents |
|---|---|
| `Chatbox/` | Agent 1 intake notebook (`ChatBox_V8.ipynb`) |
| `Coordination_agent2/` | Agent 2 notebook, prompt library, rescue center directory, incident database and schema, Streamlit app, Dockerfile, Cloud Run guide. See its README |
| `Coordination_agent2/dispatch_testing/` | 100-case benchmark: dispatch from the directory vs online search |
| `Gemini Confidence Testing/` | Vision research: species ID confidence across prompt strategies and image distortion |
| `archive/` | Superseded notebook versions, kept for reference. Nothing active reads from here |

## Running

Notebooks run in a GCP Vertex AI Workbench (JupyterLab) with access to Vertex AI in project `spring-2026-lifejacket`. Each notebook resolves paths relative to its own folder, so open and run it from where it lives. Agent 2 setup is in `Coordination_agent2/README.md`; Cloud Run deployment is in `Coordination_agent2/CLOUD_RUN_DEPLOYMENT.md`.

## Data Not In This Repo

Raw photos (about 1.1 GB) are excluded by `.gitignore`:
- `Gemini Confidence Testing/animal_dataset_images/`, `hurt_animal_dataset_images/`, `hurt_animal_dataset_images_filtered/`, `distortion_images/`
- species image folders under `archive/`

They were downloaded from public iNaturalist observations by the scraping cells in `Gemini Confidence Testing.ipynb`. The metadata CSVs in that folder (observation IDs, coordinates, observer descriptions) are included so the set can be rebuilt. iNaturalist content is licensed by its observers; check each observation's license before reusing images.

## Data Notes

- `agent1_incident_database.csv` is temporary prototype storage. See the Incident Database section of `Coordination_agent2/README.md`.
- Rescue center contacts come from the public 2026 West Coast Marine Mammal Stranding Network directory.
- Dispatch benchmark cases are synthetic.
