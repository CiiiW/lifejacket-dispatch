#!/usr/bin/env bash
# Create the GPU machine for steps 1-3. Run this on your laptop, once.
#
#   bash research/aerial_detector/gcp/create_vm.sh
#
# Defaults to a Vertex AI Workbench instance with one NVIDIA L4. Workbench is
# the right choice here for three reasons: it installs the GPU driver for you,
# it gives you JupyterLab for the error analysis, and it is a real VM you can
# SSH into - so long training runs go in tmux over SSH, not in a notebook cell
# that dies when the browser proxy drops.
#
# An L4 is the sweet spot for fine-tuning YOLO11m: 24 GB, roughly $0.70/hour
# on demand, much less on Spot. An A100 is overkill and harder to get quota
# for. A T4 works and is cheaper, but is roughly three times slower.

set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-us-central1-a}"
NAME="${NAME:-aerial-detector}"
MACHINE="${MACHINE:-g2-standard-8}"   # G2 is the only family that carries L4
BOOT_GB="${BOOT_GB:-150}"
DATA_GB="${DATA_GB:-500}"             # MMLA is the one that needs the room
# Workbench enables idle shutdown by default at 180 minutes, and it measures
# NOTEBOOK KERNEL activity - a training run in a terminal does not count. That
# default will kill a long run mid-epoch. 24 hours is long enough for any run
# here while still stopping an instance you walked away from.
IDLE_TIMEOUT="${IDLE_TIMEOUT:-86400}"

if [[ -z "${PROJECT}" ]]; then
  echo "No project set. Run: gcloud config set project YOUR_PROJECT" >&2
  exit 1
fi

cat <<INFO
  project   ${PROJECT}
  zone      ${ZONE}
  name      ${NAME}
  machine   ${MACHINE} (1x NVIDIA L4)
  boot      ${BOOT_GB} GB
  data      ${DATA_GB} GB  (mounted at /home/jupyter, survives stop/start)
  idle      shuts down after ${IDLE_TIMEOUT}s idle (default would be 180 min)

Check L4 availability in this zone first:
  gcloud compute accelerator-types list --filter="name=nvidia-l4" --format="value(zone)"

And check you have quota - "NVIDIA L4 GPUs" in the region, not just "GPUs (all regions)":
  gcloud compute regions describe "${ZONE%-*}" --format="table(quotas.metric,quotas.limit,quotas.usage)" | grep -i l4

INFO

read -r -p "Create the instance? [y/N] " reply
[[ "${reply}" == "y" || "${reply}" == "Y" ]] || { echo "aborted"; exit 0; }

gcloud workbench instances create "${NAME}" \
  --project="${PROJECT}" \
  --location="${ZONE}" \
  --machine-type="${MACHINE}" \
  --accelerator-type=NVIDIA_L4 \
  --accelerator-core-count=1 \
  --install-gpu-driver \
  --boot-disk-size="${BOOT_GB}" \
  --data-disk-size="${DATA_GB}" \
  --data-disk-type=PD_BALANCED \
  --metadata=idle-timeout-seconds="${IDLE_TIMEOUT}"

cat <<NEXT

Created. Now:

  # SSH in (this is where the training runs - not the notebook)
  gcloud compute ssh "${NAME}" --project "${PROJECT}" --zone "${ZONE}"

  # on the VM
  bash setup_vm.sh        # after copying it over, or clone the repo first

  # JupyterLab, for the error analysis only
  gcloud workbench instances describe "${NAME}" --location "${ZONE}" \\
    --format="value(gceSetup.metadata.proxy-url)"

STOP IT WHEN YOU ARE NOT TRAINING. An idle L4 overnight costs more than the
whole harmonisation step:

  gcloud workbench instances stop "${NAME}" --location "${ZONE}"
  gcloud workbench instances start "${NAME}" --location "${ZONE}"

NEXT
