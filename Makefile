# Common commands. Run `make` with no target to see this list.
#
# The virtualenv lives OUTSIDE this repo by default (~/.venvs/lifejacket-dispatch),
# not in a `.venv/` folder here. If this repo sits in an iCloud-synced folder
# (e.g. under ~/Desktop or ~/Documents), a venv inside it adds ~20k small files
# that iCloud tries to sync and that make `git status` slow to the point of
# hanging. Override with `make setup VENV=.venv` if your checkout is not
# iCloud-synced and you prefer it local.

VENV ?= $(HOME)/.venvs/lifejacket-dispatch
PYTHON ?= python3.13
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.DEFAULT_GOAL := help
.PHONY: help setup kernel run test lint notebooks seed demo clean

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the virtualenv (outside the repo) and install dependencies
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r backend/requirements.txt pytest ruff
	@echo "Done. Venv at $(VENV)."
	@echo "Next:"
	@echo "  1. 'gcloud auth application-default login'  (for the LLM agents)"
	@echo "  2. 'make kernel'                             (to use notebooks/ in Jupyter or VS Code)"

kernel:  ## Register this venv as a Jupyter/VS Code kernel named "lifejacket"
	$(PY) -m ipykernel install --user --name lifejacket --display-name "LifeJacket"
	@echo "In VS Code: open a notebook, click the kernel picker (top right), select 'LifeJacket'."
	@echo "In JupyterLab: Kernel menu -> Change Kernel... -> 'LifeJacket'."

run:  ## Start the API with auto-reload on http://localhost:8000
	# Binds 0.0.0.0, not uvicorn's default 127.0.0.1, so a phone running the
	# reporter app over Expo Go can reach it. That does expose the API to
	# your local network while it runs.
	$(VENV)/bin/uvicorn lifejacket.api.main:app --reload --app-dir backend --host 0.0.0.0

test:  ## Run the test suite (no API key or network needed)
	$(PY) -m pytest

lint:  ## Check formatting and lint rules
	$(VENV)/bin/ruff check backend
	$(VENV)/bin/ruff format --check backend

notebooks:  ## Open JupyterLab in the notebooks directory
	$(VENV)/bin/jupyter lab notebooks/

seed:  ## Load the 33 real rescue centres into the database
	curl -fsS -X POST localhost:8000/responders/seed && echo

demo:  ## Create demo incidents from demo/incidents.csv (needs 'make run' and ADC)
	$(PY) scripts/seed_demo_incidents.py $(ARGS)

clean:  ## Remove the local database, uploaded photos, and caches
	rm -rf lifejacket.db var/ .pytest_cache .ruff_cache
	find backend -name __pycache__ -type d -exec rm -rf {} +
