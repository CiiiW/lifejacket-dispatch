#!/usr/bin/env bash
# FALLBACK ONLY. You probably do not need this.
#
# The main path starts from DroneMegaDetector, which is already trained on
# person / animal / vehicle in drone imagery at 50-120 m AGL. These three
# datasets exist to train such a detector from scratch, which is the plan you
# fall back to only if notebook 1 shows DroneMegaDetector does not transfer
# to your footage.
#
#   bash research/aerial_detector/gcp/fetch_datasets.sh dmd        # the weights
#   bash research/aerial_detector/gcp/fetch_datasets.sh visdrone   # fallback
#   bash research/aerial_detector/gcp/fetch_datasets.sh mmla       # fallback
#   bash research/aerial_detector/gcp/fetch_datasets.sh waid       # fallback
#
# Each dataset lands in its own directory under $DATA_ROOT/raw. Nothing is
# extracted into a directory that holds scripts.
#
# Licences differ and none of them is "public means reusable". Record what you
# relied on before this ends up in a thesis:
#   WAID      github.com/xiaohuicui/WAID
#   MMLA      huggingface.co/datasets/imageomics/mmla_opc (and _mpala, _wilds)
#   VisDrone  github.com/VisDrone/VisDrone-Dataset

set -euo pipefail

DATA_ROOT="${DATA_ROOT:-${HOME}/aerial-data}"
RAW="${DATA_ROOT}/raw"
WHICH="${1:-}"

mkdir -p "${RAW}"

fetch_visdrone() {
  local dest="${RAW}/visdrone"
  mkdir -p "${dest}"
  cd "${dest}"
  # Ultralytics mirrors the official zips; 6,471 train / 548 val / 1,610 test-dev.
  for part in train val test-dev; do
    local zip="VisDrone2019-DET-${part}.zip"
    if [[ -d "VisDrone2019-DET-${part}" ]]; then
      echo "  ${part} already extracted, skipping"
      continue
    fi
    echo "  downloading ${zip}"
    curl -fL -o "${zip}" \
      "https://github.com/ultralytics/assets/releases/download/v0.0.0/${zip}"
    unzip -q "${zip}" && rm -f "${zip}"
  done
  echo "  visdrone -> ${dest}"
}

fetch_mmla() {
  local dest="${RAW}/mmla"
  mkdir -p "${dest}"
  command -v huggingface-cli >/dev/null 2>&1 || {
    echo "huggingface-cli not found. pip install huggingface-hub" >&2
    exit 1
  }
  # Three site repos. Start with one - opc alone is enough to prove the
  # pipeline, and all three together are a large download.
  for repo in mmla_opc mmla_mpala mmla_wilds; do
    echo "  downloading imageomics/${repo}"
    huggingface-cli download "imageomics/${repo}" \
      --repo-type dataset --local-dir "${dest}/${repo}"
  done
  echo "  mmla -> ${dest}"
}

fetch_waid() {
  local dest="${RAW}/waid"
  mkdir -p "${dest}"
  cat <<'MANUAL'
  WAID has no stable direct-download URL, so this step is manual.

    1. Open https://github.com/xiaohuicui/WAID
    2. Follow the download link in its README (Google Drive / Baidu).
    3. Extract into:  $DATA_ROOT/raw/waid

  Expected afterwards: a data.yaml with six names - sheep, cattle, seal,
  camelus, kiang, zebra - plus train/valid/test image and label directories.
  harmonize.py --inspect will tell you whether it found them.

  WAID matters more than its size suggests: it is the only one of the three
  that contains seals, and its habitats include sandy beaches.
MANUAL
}

fetch_dmd() {
  python - <<'FETCH'
import sys
from pathlib import Path

for candidate in (Path.cwd(), *Path.cwd().parents):
    module = candidate / "research" / "aerial_detector"
    if module.is_dir():
        sys.path.insert(0, str(module))
        break
import dmd

path = dmd.ensure_dmd_weights()
info = dmd.describe_checkpoint(path)
print(f"\n  {path}")
for key, value in info.items():
    print(f"    {key:14s} {value}")
FETCH
}

case "${WHICH}" in
  dmd) fetch_dmd ;;
  visdrone) fetch_visdrone ;;
  mmla) fetch_mmla ;;
  waid) fetch_waid ;;
  *)
    echo "usage: $0 {dmd|visdrone|mmla|waid}" >&2
    exit 1
    ;;
esac
