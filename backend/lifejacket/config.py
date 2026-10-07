"""Central configuration for the LifeJacket backend.

Everything tunable lives here or in the JSON files under `config/`. Nothing
else in the codebase should read `os.environ` directly -- import `settings`
instead, so there is exactly one place to look when something is misconfigured.

Two kinds of configuration are deliberately kept apart:

- **Secrets and deployment details** (API keys, database URL, model name) come
  from environment variables / `.env`. They change per developer and per
  deployment, so they never get committed.
- **Domain tuning** (severity weights, dispatch scoring, species groups) lives
  in `config/scoring.json`. These are modelling decisions the team argues about
  and version-controls, so they belong in the repo where a diff is reviewable.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the repository root by walking up from this file:
# config.py -> lifejacket/ -> backend/ -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
PROMPTS_DIR = REPO_ROOT / "prompts"


class Settings(BaseSettings):
    """Environment-driven settings, read once at import time.

    Field names map to upper-case environment variables, so `llm_model` is set
    by `LLM_MODEL`. See `.env.example` for the full list with explanations.
    """

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM / Vertex AI -------------------------------------------------
    # The team's GCP project hosts the Gemini models used by all three agents.
    gcp_project: str = Field(default="spring-2026-lifejacket")
    gcp_location: str = Field(default="us-central1")
    llm_model: str = Field(default="gemini-2.5-flash")

    # Vision calls are the expensive part of intake. A lower temperature keeps
    # species identification reproducible, which matters for evaluation runs.
    llm_temperature: float = Field(default=0.2)

    # gemini-2.5-flash spends part of max_output_tokens on its own internal
    # "thinking" before it writes the actual JSON reply, and that thinking
    # length varies call to call. Left uncapped, a long thinking pass can eat
    # most of a small budget and truncate the JSON mid-string -- this is what
    # "Unterminated string" / "Expecting value" JSON errors on retry are, not
    # a flaky model. llm_thinking_budget caps that so there is always real
    # room left for the answer.
    #
    # Measured against the real model across all four agents' prompts
    # (2024-10, gemini-2.5-flash, 24 live calls, vision + text):
    #   thinking   ~700-950 tokens  (never exceeded the 1024 budget below)
    #   JSON output ~80-600 tokens  (report/identification highest, guardrail lowest)
    #   combined worst case observed: 1429 tokens
    # thinking_budget has a small margin over the observed max; max_output_tokens
    # has a much larger one, since a higher ceiling costs nothing -- billing is
    # by tokens actually produced, not by the cap. Re-measure with
    # notebooks/sample_photos/*.ipynb-style raw calls (see PROJECT_NOTES.md) if
    # you change a prompt enough to move the typical output size.
    llm_thinking_budget: int = Field(default=1280)
    llm_max_output_tokens: int = Field(default=6144)
    llm_max_retries: int = Field(default=3)

    # Coordination chooses read-only tools; bounds apply to each request.
    coordination_max_rounds: int = Field(default=6, ge=4, le=12)
    coordination_max_evidence_chars: int = Field(default=60000, ge=1000, le=200000)

    # --- Storage ---------------------------------------------------------
    # SQLite by default so the repo runs with no setup. Point this at Postgres
    # or Cloud SQL in deployment; the ORM models do not change.
    database_url: str = Field(default=f"sqlite:///{REPO_ROOT / 'lifejacket.db'}")

    # Uploaded photos are kept outside the repo (they are large and often
    # contain personal context). Overridden with a bucket path in deployment.
    photo_storage_dir: Path = Field(default=REPO_ROOT / "var" / "photos")

    # --- External context APIs -------------------------------------------
    # Open-Meteo and NOAA CO-OPS are both free and keyless, which is why they
    # are the defaults -- a new team member can run the pipeline immediately.
    weather_api_url: str = Field(default="https://api.open-meteo.com/v1/forecast")
    marine_api_url: str = Field(default="https://marine-api.open-meteo.com/v1/marine")
    noaa_tides_api_url: str = Field(
        default="https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    )
    noaa_stations_api_url: str = Field(
        default="https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
    )
    nominatim_api_url: str = Field(default="https://nominatim.openstreetmap.org/reverse")
    nominatim_search_url: str = Field(default="https://nominatim.openstreetmap.org/search")

    # Nominatim's usage policy requires a contact in the User-Agent header.
    http_user_agent: str = Field(default="LifeJacketDispatch/1.0 (capstone project)")
    http_timeout_seconds: float = Field(default=10.0)

    # Google Maps powers turn-by-turn navigation in the responder app. Without
    # a key the app still renders the map, it just cannot compute driving ETAs.
    google_maps_api_key: str = Field(default="")

    # OpenRouteService draws the driving route from a rescue centre to an
    # incident. The key is read here, server-side, and the console asks the
    # backend for routes -- deliberately, so the key never ships in the web
    # bundle where anyone could lift it. Free keys: openrouteservice.org/dev.
    # Without one, routing degrades to the straight-line estimate and the
    # console simply draws no road route.
    ors_api_key: str = Field(default="")
    ors_api_url: str = Field(
        default="https://api.openrouteservice.org/v2/directions/driving-car/geojson"
    )

    # --- Conversation limits ---------------------------------------------
    # Hard product requirement: the identification agent may ask at most five
    # questions before it has to commit to an answer.
    max_identification_questions: int = Field(default=5)
    max_assessment_questions: int = Field(default=5)

    # Pooled probability at which a taxon counts as identified. Applied at
    # every rank by `taxonomy.resolve_taxon`: 0.90 for one species, or 0.90
    # summed across the species in a genus or family.
    # UNVALIDATED -- see the Known Limitations in the README.
    identification_confidence_threshold: float = Field(default=0.90)

    # Below this, the agent is not allowed to settle just because it claims no
    # question would discriminate its top candidates -- that claim is only
    # trustworthy near the confidence bar above. Below it, a vague three-way
    # split (see Decisions, PROJECT_NOTES.md, 2026-10-01) must keep asking,
    # using a generic fallback clue if the agent itself offers no question,
    # until confidence clears this bar or the question budget runs out.
    identification_min_confidence_to_settle: float = Field(default=0.80)

    # Ranks at which the chatbot may stop asking questions early.
    #
    # Species and genus: stop as soon as either is confident.
    # Family is deliberately NOT here by default. "True seals" pools harbor and
    # elephant seals, which one question about size usually separates -- so
    # stopping there would waste an easy win. Family-level answers ("oceanic
    # dolphins") are still accepted, but only once the agent says no question
    # can separate the species from a safe distance, or the 5 questions run out.
    #
    # Add "family" here to stop sooner. Set in .env as a JSON list:
    #   CONFIDENT_TAXON_RANKS='["species","genus","family"]'
    confident_taxon_ranks: list[str] = Field(default=["species", "genus"])

    # --- API server -------------------------------------------------------
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    cors_allow_origins: list[str] = Field(default=["*"])


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()


settings = get_settings()


@lru_cache
def load_scoring_config() -> dict[str, Any]:
    """Load `config/scoring.json`: severity weights, dispatch weights, species groups.

    Cached because it is read on every incident and never changes at runtime.
    Restart the server after editing the file.
    """
    with open(CONFIG_DIR / "scoring.json", encoding="utf-8") as fh:
        return json.load(fh)
