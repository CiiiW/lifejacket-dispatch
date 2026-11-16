# Aerial detector: DroneMegaDetector, evaluated and fine-tuned

A three-class object detector for low-altitude drone imagery —
`person`, `animal`, `vehicle` — built on
[DroneMegaDetector](https://github.com/ConservationDronesAI/DroneMegaDetector),
plus the tooling to measure it on real NOAA footage and fine-tune it for
specific searches.

**No backend module imports anything in this directory**, and the training
dependencies live in a separate `requirements.txt`. The backend test suite
stays offline, fast and free of CUDA.

A trained checkpoint reaches the application the other way round: `publish.py`
uploads it to Hugging Face, and
[`backend/lifejacket/drones/detector.py`](../../backend/lifejacket/drones/detector.py)
downloads it by pinned commit SHA and verifies the hash. That loader is off by
default and returns a `FakeDetector` until configured.

## Why DroneMegaDetector rather than training our own

The earlier plan here was to pool WAID, MMLA and VisDrone and train a
three-class detector from COCO. DroneMegaDetector **is that model, already
trained**, on more data than we would have assembled, at our altitude, under
a permissive licence. Building it ourselves would have taken weeks to arrive
somewhere worse.

| | |
| --- | --- |
| Architecture | RF-DETR Medium, 35.3M parameters |
| Classes | `person` (0), `animal` (1), `vehicle` (2) |
| Altitude | predominantly 50–120 m AGL — the Mini 2's range |
| Licence | repo MIT, `rfdetr` Apache-2.0. **No AGPL network clause** |
| Paper | [Elchik et al. 2026](https://doi.org/10.64898/2026.10.12.758430) |

Two limitations, both stated by its authors:

- **`animal` is effectively `mammal`.** The paper is titled "Detecting Large
  Mammals" and the repo says behaviour on non-mammals is undefined. Seals are
  comfortably in scope; **birds are the known gap**, and the abstract reports
  weaker transfer to unseen avian imagery.
- **It has never seen your coastline.** Whatever it scores on your footage is
  a statement about transfer. That is what notebook 1 measures.

## The class order is the interface

```
0 person    1 animal    2 vehicle
```

Not alphabetical, not intuitive. Read out of the published checkpoint's own
`model_config` rather than copied from its README —
`dmd.describe_checkpoint()` reproduces it, and the repo's documentation
agrees. Every fine-tune inherits it, `backend/.../detector.py` matches it, and
`publish.py` refuses a checkpoint that disagrees.

A mismatch does not crash. It relabels every detection silently, which is
worse.

## Fine-tunes do not add classes

A seal model is **not** a model with a `seal` class. It is a model whose
`animal` class finds seals reliably. Likewise for birds.

Three reasons:

1. Every checkpoint stays interchangeable — one decode path, one
   `CLASS_NAMES`, and switching models in production is three environment
   variables.
2. Species naming is already another stage's job. The identification agent
   does it on a cropped frame via [`taxonomy.py`](../../backend/lifejacket/taxonomy.py),
   which pools probabilities up the taxonomic tree to whatever rank is
   actually confident.
3. It avoids RF-DETR's `num_classes` misconfiguration trap
   ([issue #878](https://github.com/roboflow/rf-detr/issues/878)).

Both fine-tune notebooks end with exactly what changing this would involve,
if you decide the scene summary genuinely needs it.

## Files

| | |
| --- | --- |
| [`dmd.py`](dmd.py) | Shared: weights, inference, COCO, scoring, plots. The scoring half imports no torch, so it is testable anywhere |
| [`detect_video.py`](detect_video.py) | **Point it at a clip and look.** Frames → detections → annotated video + scene summary. No labels needed |
| [`prepare_noaa.py`](prepare_noaa.py) | NOAA video → spaced frames → a labelling-ready COCO skeleton |
| [`dataset.py`](dataset.py) | A labelled COCO export → RF-DETR's `train/valid/test` layout, split by capture session |
| [`finetune.py`](finetune.py) | Fine-tune DMD, with replay against forgetting |
| [`evaluate.py`](evaluate.py) | Score any checkpoint; `--compare` flags regressions |
| [`publish.py`](publish.py) | Hash, model card, upload to Hugging Face |
| [`notebooks/`](notebooks/) | The four below |
| [`harmonize.py`](harmonize.py) | **Fallback only.** Pools WAID + MMLA + VisDrone to train from scratch, if DMD does not transfer |

### Notebooks

| | |
| --- | --- |
| [`00_try_a_video.ipynb`](notebooks/00_try_a_video.ipynb) | **Start here.** Any clip, no labels: scrub frames, slide the threshold, see the scene summary |
| [`01_evaluate_dmd_on_noaa.ipynb`](notebooks/01_evaluate_dmd_on_noaa.ipynb) | Stock DMD scored on **labelled** NOAA frames: pixels-on-target, confidence sweep, failure gallery |
| [`02_finetune_seals.ipynb`](notebooks/02_finetune_seals.ipynb) | Seals. Expect a modest gain on an already-decent baseline |
| [`03_finetune_birds.ipynb`](notebooks/03_finetune_birds.ipynb) | Birds. DMD's documented gap; expect to start near zero |
| [`04_compare_and_tune.ipynb`](notebooks/04_compare_and_tune.ipynb) | Compare checkpoints, slide the threshold, pick an operating point |

---

# Runbook

## 0. The machine

```bash
gcloud config set project YOUR_PROJECT
bash research/aerial_detector/gcp/create_vm.sh
```

One NVIDIA L4 on `g2-standard-8`, 500 GB data disk at `/home/jupyter`, idle
shutdown set to 24 hours. Check L4 quota in your region first — it is the
usual blocker and takes a day or two to grant.

```bash
gcloud compute ssh aerial-detector --zone us-central1-a
git clone YOUR_REPO && cd lifejacket-dispatch && git checkout yuta
bash research/aerial_detector/gcp/setup_vm.sh
source ~/.venvs/aerial/bin/activate
```

`setup_vm.sh` stops immediately if torch cannot see the GPU, and pre-fetches
the DroneMegaDetector weights so a later step does not stall on a 142 MB
download.

**Stop the instance when you are not training.** The cost leak is not the
training run; it is an L4 left running overnight.

> Workbench's idle shutdown counts **notebook kernel** activity, not shell
> activity. A terminal training run does not reset the timer, which is why
> `create_vm.sh` sets it to 24 hours rather than the 180-minute default.

## 1. Look at a clip first

Before any labelling, point the detector at a video and see what happens:

```bash
cd research/aerial_detector
python detect_video.py ~/clips/DJI_0001.MP4 --out ~/aerial-data/runs/clip1
```

Writes `annotated.mp4`, `detections.json`, and a `summary.json` of counts.
Or open [`notebooks/00_try_a_video.ipynb`](notebooks/00_try_a_video.ipynb)
for sliders over frame and threshold.

**This shows what the model sees; it does not measure accuracy.** Without
ground truth there is nothing to be right or wrong against, so no precision
or recall is reported. Looking at output and measuring accuracy are
different activities, and only the second belongs in the writeup. That is
what the next step is for.

## 2. Build the NOAA evaluation set

```bash
cd research/aerial_detector

python prepare_noaa.py --video NOAA_CLIP.mp4 --out ~/aerial-data/noaa_eval \
    --interval 5 --max-frames 50 \
    --source "NOAA Fisheries ..." --rights "NOAA Fisheries; ..."
```

This calls the repo's existing offline extractor
([`drones/video.py`](../../backend/lifejacket/drones/video.py)) — FFmpeg and
hashing, no cloud calls — and writes `images/` plus an empty-but-valid
`_annotations.coco.json`. Provenance travels with it: the source hash, the
rights note, and each frame's offset in the clip.

**`--interval 5` matters.** Fifty consecutive frames would be fifty pictures
of one moment: you would have labelled a single scene fifty times.

Now label those frames — Label Studio or CVAT — with the category names
exactly `person`, `animal`, `vehicle`, and export COCO over the skeleton.

Label **locally**, not on a hosted service. It keeps NOAA imagery off third
parties while the reuse question is open, the same caution
[`public_condition_pilot`](../public_condition_pilot/README.md) applies to its
sources. A source being hosted by NOAA is not by itself a reuse licence.

Fifty labelled frames for evaluation beats a thousand for training: two hours
instead of a week, and **once you train on them you can no longer honestly
evaluate on them.**

## 3. Measure DroneMegaDetector

Open [`notebooks/01_evaluate_dmd_on_noaa.ipynb`](notebooks/01_evaluate_dmd_on_noaa.ipynb),
or from the shell:

```bash
python evaluate.py --weights dmd \
    --data ~/aerial-data/noaa_eval/_annotations.coco.json --tag noaa-dmd
```

**This is the measurement that decides the rest of the project.** Read the
notebook's conclusions section; in short:

| Result | What to do |
| --- | --- |
| `animal` recall above ~0.6 | The pretraining transfers. Go straight to step 4 |
| Poor recall, boxes in sensible places | Normal domain gap. Fine-tuning is the fix |
| Finds nothing, and targets were under 32 px | A **resolution** problem. Fly lower or raise input size; weights will not help |
| Boxes systematically offset | Stop — find the preprocessing bug first |

Read `blind_images` before mAP: frames containing the target where nothing
at all was detected. That is the failure a coordinator would feel.

## 4. Fine-tune

```bash
python dataset.py --coco labelled/_annotations.coco.json \
    --images labelled/images --out ~/aerial-data/seals --inspect
python dataset.py --coco ... --out ~/aerial-data/seals --overwrite

tmux new -s seals
python finetune.py --data ~/aerial-data/seals --name seals-v1 \
    --replay ~/aerial-data/noaa_eval --replay-fraction 0.25
```

Three things this gets right that are easy to get wrong:

**Splits are by capture session, never random.** Consecutive frames of one
animal are near-identical; split randomly and the same animal lands in train
and test. `dataset.py` orders sessions by a hash of their name and cuts that
ordering at the requested image fractions — deterministic, and it cannot put
a session in two splits. It refuses to write if `train` or `valid` would be
empty rather than hand you a dataset that cannot train.

**Replay guards against forgetting.** Fine-tuning only on seals makes the
model better at seals and worse at `person` and `vehicle`, which every site
needs. `--replay` mixes general data into training. Validation stays purely
task-specific.

**The class order is checked before training starts**, not discovered in
epoch one.

Run it in `tmux`, not in a notebook cell. The notebooks print the exact
command to copy.

## 5. Check both directions

```bash
# did it get better at the job?
python evaluate.py --weights runs/seals-v1/checkpoint_best_total.pth \
    --data ~/aerial-data/seals/test/_annotations.coco.json \
    --tag seals-after --compare results/eval_seals-before.json

# did it get worse at everything else?
python evaluate.py --weights runs/seals-v1/checkpoint_best_total.pth \
    --data ~/aerial-data/noaa_eval/_annotations.coco.json \
    --tag seals-general --compare results/eval_noaa-dmd.json
```

**Do not skip the second one.** A seal model that stopped detecting people is
a worse product in the field than stock DroneMegaDetector, and without this
you would ship it not knowing. `--compare` flags any metric that fell by 0.05
or more and prints what to do about it.

## 6. Choose an operating point

[`notebooks/04_compare_and_tune.ipynb`](notebooks/04_compare_and_tune.ipynb).

The threshold is a decision, not a number that falls out of the data. **F1 is
the wrong objective here**: it weighs a miss and a false alarm equally, and
for dispatch they are not equal. A missed stranded animal is a welfare
failure; a false alarm costs a coordinator seconds, and a human reviews every
detection anyway. The notebook lets you set that ratio explicitly and picks
the threshold that minimises real cost — usually lower than best-F1, which is
correct.

## 7. Publish

```bash
huggingface-cli login
python publish.py --weights runs/seals-v1/checkpoint_best_total.pth \
    --repo YOUR_USERNAME/lifejacket-seals \
    --purpose "finding hauled-out seals" --private --dry-run
```

`--dry-run` stages the checkpoint and the generated model card locally and
uploads nothing. Read the card, then drop the flag.

It prints a `DRONE_DETECTOR_*` block for `.env`. The revision is a **commit
SHA**, and the loader rejects a branch name as "a moving target" — a Hugging
Face repo can serve different bytes tomorrow under the same id. The SHA-256
is verified on every load.

```bash
pip install -r ../../backend/requirements-detector.txt
```

Weights never go in git: `.gitignore` excludes `runs/**/weights/` and `*.pth`.
The training curves and `results/*.json` beside them are small and stay
committable — they are the evidence for the writeup.

## Honest limits

- **Scoring is greedy IoU matching at 0.5, not COCO mAP**, on small
  hand-labelled sets. A go/no-go measurement, deliberately simple enough to
  read in one sitting. Do not report it as a benchmark.
- **Nothing here is wired into the application.** `detector.py` exists and
  loads published weights, but no route, service or script calls it, and
  nothing analyses the live RTMP stream. `detect_video.py` is a research
  tool you run by hand on a recorded clip.
- **Nothing here has been run on real data yet.** `dmd.py`'s scoring,
  `dataset.py`'s split assignment, `prepare_noaa.py`'s COCO output and
  `detector.py`'s decoding are all exercised against fixtures, and the
  DroneMegaDetector checkpoint was downloaded and introspected for real. The
  `rfdetr` training and inference calls have not been executed — torch is not
  installed outside the GPU environment. Use `--dry-run` on `finetune.py` and
  a short run first. `detect_video.py`'s FFmpeg calls are likewise untested
  locally -- ffmpeg is not installed here -- though the failure path gives a
  clean message rather than a traceback.
- **The app-side loader cannot read what `publish.py` uploads.**
  `publish.py` publishes the RF-DETR `.pth`; `OnnxDetector` reads ONNX.
  Exporting RF-DETR to ONNX and checking `decode_detr` against a real export
  is unfinished, so `DRONE_DETECTOR_ENABLED` stays off and `load_detector()`
  returns a `FakeDetector`. The decoding is unit-tested against synthetic
  tensors in both layouts, but the first real export is where a transposed
  axis or an unexpected letterbox would surface. Draw the first detections on
  a frame and look at them before trusting it.
  Research-side use is unaffected: `detect_video.py`, `evaluate.py` and the
  notebooks load the `.pth` through `rfdetr` directly.
- **The live path is worse than anything measured here.** 4K sensor →
  720p/1080p OcuSync → 1–2 Mbps RTMP on iOS → 640 px decode leaves a 2 m
  animal at 50 m about 15 px across. Recorded-footage scores are an upper
  bound.
- **Spatial claims need telemetry this model does not produce.** Distances
  and headings come from the GPS and altitude DJI writes to the `.SRT`
  sidecar on the memory card; the RTMP live path carries none of it.
- **DroneMegaDetector's training data is not published.** Not in the README,
  the model card or the abstract. Its author maintains
  [a catalogue of drone wildlife datasets](https://github.com/agentmorris/drone-wildlife-datasets)
  described as "en route to a harmonized dataset", which is the best
  available proxy — but coverage of your domain cannot be reasoned about from
  documentation. That is why step 2 exists.

## Known gaps, and what would close them

| Gap | Option |
| --- | --- |
| Birds | Notebook 3, or [`weecology/deepforest-bird`](https://huggingface.co/weecology/deepforest-bird) — 250K+ annotations, 13 projects. Benchmark against your fine-tune |
| Animals in water (cetaceans, turtles) | [`deepforest-marine-biodiversity`](https://huggingface.co/weecology/deepforest-marine-biodiversity), but read the numbers: 57.9% box recall, and sand and foam cause false positives. Out of scope for now |
| Dense flocks | Tiled inference — DMD's own batch script slices 1280×1280 with 100 px overlap. Note the 300-query cap is a hard ceiling on detections per frame |

## Licence note

`rfdetr` is Apache-2.0 and the DroneMegaDetector repository is MIT, so none of
this carries the AGPL network clause an Ultralytics-based detector would have
imposed on a hosted API.

Two things to resolve before this ships anywhere: the DroneMegaDetector
**weights** have no separately stated licence (the repo is MIT, the preprint
is CC BY-NC-ND — three different objects), and dataset licences are separate
again. Email the authors; they are actively soliciting imagery from
underrepresented habitats, and Californian beach strandings are exactly that.

## Upload and test your own video

Open [notebook 20](notebooks/20_practical_options_report.ipynb), select the aerial GPU kernel, and Run All once. Upload one short video (under 100 MB), then click **Run this video**. Start with the default six-second, 1-FPS preview. The panel runs DMD full-frame plus overlapping tiles, YOLO-World context proposals, and bounded Gemini advice, then displays review cards and an H.264 MP4. Nothing runs merely from opening the upload panel.

Confirm the animal in the exact reviewed frame before any supported person/vehicle regions are shown; approval never carries to another timestamp. Open original full-resolution frames for small targets, then refresh the annotated video after reviewing. The advanced path input supports recordings already on the notebook server.

Prerequisites: cached DMD and YOLO-World weights, the research detector environments, FFmpeg, ipywidgets, and configured Vertex access for Gemini. Existing Workbench environment markers are detected automatically; other installations can set the environment paths in the setup cell. Detector-only mode works without Gemini advice and leaves context unverified. The original recording stays on the server; selected review images are sent to configured Gemini when enabled.

This is a sampled recorded-video research interface, not live DJI integration, field validation, an injury assessment or automatic dispatch. The ground-level seal/people/truck example is a proxy. Failed paid requests are retained rather than silently retried; other unreviewed windows remain visible.

Offline policy/upload regression checks: python -m unittest discover -s research/aerial_detector -p test_video_review_workflow.py
