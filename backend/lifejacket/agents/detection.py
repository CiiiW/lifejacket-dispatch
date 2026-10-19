"""Detection: find each animal in the photo so the reporter can pick one.

Runs before identification. When a photo holds several animals (a seal and a
gull, a flock of pelicans), identification would otherwise be asked about
"the animal" with no way to know which one. This step only *locates* animals;
it never names a species -- that stays identification's job, on the crop of
whichever animal the reporter chose.

Why Gemini and not a YOLO model: the COCO classes YOLO ships with contain no
seals, sea lions, dolphins or turtles, so it would miss the animals this
system exists for.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageOps

from lifejacket.agents.base import Agent
from lifejacket.llm.client import ImageInput
from lifejacket.llm.schema import STRING, array_of, enum_of, object_schema
from lifejacket.models.schemas import AnimalDetection, DetectionResult

DETECTION_SCHEMA = object_schema(
    {
        "animals": array_of(
            object_schema(
                {
                    # Four integers; constrained in size, validated on parse.
                    "box": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "description": STRING,
                    "kind": enum_of("bird", "mammal", "reptile", "fish", "other"),
                }
            )
        ),
    }
)

#: Padding added around a box when cropping, as a fraction of its size. The
#: model's boxes are tight and occasionally clip a flipper or tail.
CROP_MARGIN = 0.10


class DetectionAgent(Agent[DetectionResult]):
    """Finds every distinct animal in a photo and boxes it."""

    name = "detection"
    prompt_path = "identification/detect_animals.md"
    result_type = DetectionResult
    # Low temperature: the same photo should give the same boxes, or the
    # numbers shown to the reporter would change between turns.
    temperature = 0.1

    @property
    def output_schema(self) -> dict[str, Any]:
        return DETECTION_SCHEMA

    def build_prompt_values(self, **kwargs: Any) -> dict[str, Any]:
        return {}


def crop_to_detection(
    image: ImageInput, detection: AnimalDetection, margin: float = CROP_MARGIN
) -> ImageInput:
    """Crop `image` to the detection's box, plus a little margin, as a JPEG."""
    pil = ImageOps.exif_transpose(Image.open(io.BytesIO(image.data))).convert("RGB")
    width, height = pil.size
    ymin, xmin, ymax, xmax = detection.box
    top, bottom = sorted((ymin / 1000 * height, ymax / 1000 * height))
    left, right = sorted((xmin / 1000 * width, xmax / 1000 * width))
    pad_y, pad_x = (bottom - top) * margin, (right - left) * margin
    box = (
        max(0, round(left - pad_x)),
        max(0, round(top - pad_y)),
        min(width, round(right + pad_x)),
        min(height, round(bottom + pad_y)),
    )
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        return image  # degenerate box: better the whole photo than an empty crop

    buffer = io.BytesIO()
    pil.crop(box).save(buffer, format="JPEG", quality=92)
    return ImageInput(data=buffer.getvalue(), mime_type="image/jpeg", photo_id=image.photo_id)
