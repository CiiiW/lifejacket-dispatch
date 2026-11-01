#!/usr/bin/env bash
# Run only as an authorized project IAM administrator.
# Stop if the role already exists: review it before granting any existing role.
set -euo pipefail

ROLE_DEFINITION_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

gcloud iam roles create lifejacketTokenVerifier \
  --project=spring-2026-lifejacket \
  --file="${ROLE_DEFINITION_DIR}/network-token-verifier-role.yaml"

gcloud projects add-iam-policy-binding spring-2026-lifejacket \
  --member='serviceAccount:workbench-sa@spring-2026-lifejacket.iam.gserviceaccount.com' \
  --role='projects/spring-2026-lifejacket/roles/lifejacketTokenVerifier' \
  --condition=None \
  --format='value(etag)'
