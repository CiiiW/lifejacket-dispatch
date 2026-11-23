"""Pinned, opt-in YOLOX-S scoring for staged plush footage."""

import hashlib

MODEL_HASH = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"
SIZE = 640
TEDDY_BEAR = 77


def crop_origins(length):
    edge = max(0, length - SIZE)
    return sorted({*range(0, edge + 1, 320), edge})


class DemoPlushDetector:
    def __init__(self, weights):
        import cv2
        import numpy as np
        import onnxruntime as ort

        with weights.open("rb") as model:
            if hashlib.file_digest(model, "sha256").hexdigest() != MODEL_HASH:
                raise ValueError("Expected the pinned official YOLOX-S ONNX checkpoint")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(
            str(weights), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.cv, self.np = cv2, np

    def score_image(self, image):
        height, width = image.shape[:2]
        ratio = SIZE / max(height, width)
        w, h = max(1, int(width * ratio)), max(1, int(height * ratio))
        padded = self.np.full((SIZE, SIZE, 3), 114, dtype=self.np.uint8)
        padded[:h, :w] = self.cv.resize(image, (w, h))
        tensor = self.np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype="float32")
        predictions = self.session.run(None, {self.input_name: tensor})[0][0]
        teddy = predictions[predictions[:, 5:].argmax(axis=1) == TEDDY_BEAR]
        return float((teddy[:, 4] * teddy[:, 5 + TEDDY_BEAR]).max(initial=0))

    def score(self, jpeg):
        image = self.cv.imdecode(self.np.frombuffer(jpeg, dtype="uint8"), self.cv.IMREAD_COLOR)
        if image is None:
            raise ValueError("Cannot decode observation frame")
        h, w = image.shape[:2]
        scores = [self.score_image(image)]
        if max(h, w) > SIZE:
            scores.extend(
                self.score_image(image[y : y + SIZE, x : x + SIZE])
                for y in crop_origins(h)
                for x in crop_origins(w)
            )
        best = max(scores)
        return round(best, 4) if 0.30 <= best <= 1 else None
