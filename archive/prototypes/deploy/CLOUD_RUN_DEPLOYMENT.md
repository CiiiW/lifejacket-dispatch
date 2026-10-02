# Deploy LifeJacket Agent 2 To Cloud Run

Cloud Run hosts the Streamlit interface as an actual web application and allows it to call Vertex AI Gemini using a service account.

## Files To Upload

Upload these files into one JupyterLab folder:

```text
Dockerfile
.dockerignore
.gcloudignore
lifejacket_app.py
lifejacket_vertex.py
agent2_prompt_library.json
agent1_incident_database.csv
agent2_rescue_center_directory.csv
requirements-lifejacket-ui.txt
```

## Deploy Commands

Run in the terminal from that folder:

```bash
gcloud config set project spring-2026-lifejacket

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com

gcloud iam service-accounts create lifejacket-streamlit \
  --display-name="LifeJacket Streamlit Vertex AI"

gcloud projects add-iam-policy-binding spring-2026-lifejacket \
  --member="serviceAccount:lifejacket-streamlit@spring-2026-lifejacket.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

gcloud run deploy lifejacket-agent2 \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --service-account="lifejacket-streamlit@spring-2026-lifejacket.iam.gserviceaccount.com" \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=spring-2026-lifejacket,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=True,VERTEX_GEMINI_MODEL=publishers/google/models/gemini-3.5-flash" \
  --memory=1Gi \
  --timeout=3600 \
  --max-instances=1 \
  --session-affinity
```

If `lifejacket-streamlit` already exists, skip the service-account creation command and continue.

At the end of deployment, Cloud Run prints a `Service URL`. Open that URL for the live Streamlit demo.

## Demo Safety Note

The command above creates a public demonstration URL. Anyone with the link can open the app and initiate Vertex AI Gemini calls. For a classroom demonstration, avoid sharing it broadly and delete the service after presenting:

```bash
gcloud run services delete lifejacket-agent2 --region us-central1
```

## Demo Flow

1. In **Agent 1 Input**, show that reports are awaiting Gemini analysis.
2. In **Run Agent 2**, run the selected featured case `INC_80ca122f`.
3. In **Decision Output**, show severity, dispatch, guarded alert-card output, and audit JSON.
4. In **Documentation**, show automatic case documentation.
