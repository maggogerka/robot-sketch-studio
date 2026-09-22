from __future__ import annotations

import importlib.util

import numpy as np
from PIL import Image

from robot_sketch_studio.engines.base import EngineUnavailableError, SketchEngine
from robot_sketch_studio.models import ProcessingOptions


class LineartAIEngine(SketchEngine):
    name = "lineart_ai"

    def __init__(self, device: str = "auto") -> None:
        self.device = device
        self._detector = None

    def available(self) -> bool:
        return importlib.util.find_spec("controlnet_aux") is not None

    def _load(self):
        if not self.available():
            raise EngineUnavailableError(
                "lineart_ai is not installed. Install the 'ai' extra and its model weights, "
                "or select opencv_xdog."
            )
        if self._detector is None:
            from controlnet_aux import LineartDetector

            self._detector = LineartDetector.from_pretrained("lllyasviel/Annotators")
        return self._detector

    def render(self, rgb: np.ndarray, options: ProcessingOptions) -> np.ndarray:
        detector = self._load()
        result = detector(Image.fromarray(rgb), detect_resolution=max(rgb.shape[:2]))
        array = np.asarray(result.convert("L"), dtype=np.uint8)
        # Annotator versions differ in polarity; the whiter background wins.
        if float(array.mean()) < 127:
            array = 255 - array
        return np.where(array < options.threshold, 0, 255).astype(np.uint8)
