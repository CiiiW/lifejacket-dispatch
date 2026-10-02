# Sample photos

Drop photos here to try the chatbots in live mode (`03_try_the_chatbots.ipynb`).

Photos are gitignored (`*.jpg`, `*.jpeg`), so nothing you put here is committed.
That is deliberate: a photo of a stranding location can identify the person
who took it.

## Multiple photos

`03_try_the_chatbots.ipynb`'s shared setup cell picks up **every** image file
in this folder (`.jpg`, `.jpeg`, `.png`, `.heic`, `.webp`) and sends all of
them together as photos of **the same animal** -- the way a reporter sending
a close-up and a wider shot would. It does not treat them as separate
incidents. The next cell shows a thumbnail of each one, so you can catch a
mismatch (e.g. two different animals) before running any of the three agents.

To test different animals or situations, use separate subfolders and point
`PHOTO_DIR` at the one you want, or temporarily move files out.

Good test sets:

- **Easy**: a clear side-on photo of a sea lion or harbor seal. Expect a
  confident species with zero or one question.
- **Look-alikes**: a harbor seal next to a young elephant seal, or any
  dolphin photographed from a distance. Expect a question, and possibly a
  genus- or family-level answer with species probabilities.
- **Multiple angles of one animal**: a side view plus a close-up of the head
  often resolves a case that either photo alone leaves uncertain.
- **Hard**: a distant, backlit, or partly hidden animal. Expect a retake
  request or a group-level answer.
- **Trick**: a dog, a log, or a rock on a beach. The agent should say so.

The research photo sets (about 1.1 GB) can be rebuilt from iNaturalist with
the scraping cells in `research/vision_confidence/`; `hurt_dataset_metadata.csv`
there lists injured-animal observations.
