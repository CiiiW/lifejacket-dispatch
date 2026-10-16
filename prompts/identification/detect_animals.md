# Task: find every animal in the photo

You are looking at a photo a member of the public took of an animal (or
animals) they found. Do **not** identify the species. Only locate each animal
so the reporter can tap the one they mean.

Return one entry per distinct animal that is clearly visible, including
birds, partly submerged animals, and animals that are small or far away.
Do not include people, boats, debris, shadows, or reflections. If a group is
too dense to separate individuals, return one entry for the whole group and
say so in `description`.

For each animal:

- `box`: `[ymin, xmin, ymax, xmax]`, each an integer from 0 to 1000, relative
  to the full image (0,0 is the top-left corner). Fit the box tightly around
  the visible body.
- `description`: <=10 words a reporter would recognise, using position and
  colour ("dark animal in the water, left", "white bird, top right"). No
  species names.
- `kind`: `bird`, `mammal`, `reptile`, `fish`, or `other`.

If there are no animals, return an empty `animals` list.

Return JSON matching the schema.
