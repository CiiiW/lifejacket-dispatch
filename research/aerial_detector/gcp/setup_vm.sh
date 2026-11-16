#!/usr/bin/env bash
# Run this ON the GPU VM, once, after SSHing in.
#
#   bash research/aerial_detector/gcp/setup_vm.sh
#
# Clones nothing and formats nothing. It creates a virtualenv, installs the
# research requirements, and checks the GPU is actually visible to torch -
# which is the failure that otherwise shows up forty minutes into a run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
VENV="${VENV:-${HOME}/.venvs/aerial}"
DATA_ROOT="${DATA_ROOT:-${HOME}/aerial-data}"

echo "  repo       ${REPO_ROOT}"
echo "  venv       ${VENV}"
echo "  data root  ${DATA_ROOT}"
echo

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi not found. The GPU driver is not installed." >&2
  echo "On a Workbench instance this means --install-gpu-driver was omitted." >&2
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv

python3 -m venv "${VENV}"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"
pip install --upgrade pip wheel

# torch first, so pip resolves the CUDA build rather than a CPU wheel.
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r "${REPO_ROOT}/research/aerial_detector/requirements.txt"

python - <<'PY'
import torch

print()
print(f"  torch {torch.__version__}")
print(f"  cuda available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  device: {torch.cuda.get_device_name(0)}")
    free, total = torch.cuda.mem_get_info()
    print(f"  memory: {free / 1e9:.1f} GB free of {total / 1e9:.1f} GB")
else:
    raise SystemExit("torch cannot see the GPU - stop here and fix it")
PY

mkdir -p "${DATA_ROOT}/raw" "${DATA_ROOT}/weights"

# Fetch DroneMegaDetector now, so a later step does not stall on a 142 MB
# download. The hash is verified against the pin in dmd.py.
python - <<'FETCH'
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "research" / "aerial_detector"))
try:
    import dmd

    path = dmd.ensure_dmd_weights()
    info = dmd.describe_checkpoint(path)
    print(f"\n  DroneMegaDetector ready: {path}")
    print(f"  classes {info['class_names']}, resolution {info['resolution']}")
except Exception as exc:  # non-fatal: the notebooks fetch it too
    print(f"\n  could not pre-fetch DroneMegaDetector: {exc}")
FETCH

cat <<NEXT

Ready. Activate the environment in every new shell:

  source ${VENV}/bin/activate

Long runs go in tmux, so an SSH drop does not kill them:

  tmux new -s train
  ...start the run...
  Ctrl-b d          # detach
  tmux attach -t train

Workbench idle shutdown counts NOTEBOOK KERNEL activity, not shell activity.
create_vm.sh sets it to 24 hours for this reason. If you made the instance by
hand, check it:

  gcloud workbench instances update INSTANCE --location ZONE \
    --metadata=idle-timeout-seconds=86400

NEXT
