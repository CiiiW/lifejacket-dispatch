# Task: describe what one video frame shows, for choosing evidence frames

You are looking at a single frame from a video recorded by a drone (or a
camera) over an animal that may need help. A person will review a few frames
chosen from the whole video, so this step only **describes** the frame. You do
not choose frames, identify the species, judge how serious anything is, or
recommend a response.

The animal can be any kind: a marine mammal on a beach, a bird, a turtle, a
land animal, a young animal on its own, an animal on a cliff or in a road.
Do not assume a particular species or place.

Answer from what is visible in this frame only. If you cannot tell, say so
with the "unknown" or "none" value rather than guessing.

- `animal_visible`: true only if at least one animal can be clearly made out.
  Title cards, empty scenery, and frames where the animal is only a vague
  speck are false.
- `view`: what kind of shot this is.
  - `wide_context`: mostly surroundings; the animal is small but the setting
    (terrain, water, hazards, other animals or people) is clear.
  - `full_body`: the whole body of one animal is in view.
  - `head_face`: the head or face is the main subject.
  - `body_detail`: a close view of part of the body (limb, flank, wound area,
    anything attached to the animal).
  - `other`: anything else, including frames with no animal.
- `side`: which side of the animal faces the camera. One of `top_down`,
  `left`, `right`, `front`, `rear`, `unknown`. Use the animal's own left and
  right. Use `unknown` for groups, wide shots, or when unclear.
- `clarity`: integer 1-5. How sharp and well exposed the animal itself is
  (1 = blurred or hidden, 3 = usable, 5 = crisp detail).
- `animal_size`: integer 1-5. How much of the frame the animal fills
  (1 = tiny, 3 = about a quarter, 5 = most of the frame).
- `environment`: at most 8 words naming the setting ("rocky beach, rising
  surf", "cliff ledge, grass").
- `notable`: one short sentence, only if the frame shows something that
  would worry a rescuer, such as a possible wound or bleeding, something
  wrapped around or stuck to the animal, an unusual or abnormal posture, a
  young animal apparently alone, a hazard nearby, or a trapped or stranded
  position. Normal appearance is NOT notable: wet or sandy fur, resting,
  sleeping, huddling in a group, or ordinary behaviour. Most frames should
  have an empty `notable`. Describe only what you see and use words like
  "appears" or "possible". Use an empty string if nothing would worry a
  rescuer.
- `notable_clear`: true only if what you wrote in `notable` is shown clearly
  enough in this frame for a person to examine. False if `notable` is empty
  or the detail is too small or unclear.

Return JSON matching the schema.
