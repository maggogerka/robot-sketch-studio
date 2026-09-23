from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image

from robot_sketch_studio.engines.base import EngineUnavailableError, SketchEngine
from robot_sketch_studio.models import ProcessingOptions


class LineartAIEngine(SketchEngine):
    name = "lineart_ai"

    def __init__(self, device: str = "auto", model_dir: Path | None = None) -> None:
        self.device = device
        self.model_dir = model_dir.expanduser().resolve() / "lineart" if model_dir else None
        self._detector = None

    def dependency_available(self) -> bool:
        return importlib.util.find_spec("controlnet_aux") is not None

    def weights_available(self) -> bool:
        return bool(
            self.model_dir
            and (self.model_dir / "sk_model.pth").is_file()
            and (self.model_dir / "sk_model2.pth").is_file()
        )

    def available(self) -> bool:
        return self.dependency_available() and self.weights_available()

    def _load(self):
        if not self.dependency_available():
            raise EngineUnavailableError(
                "lineart_ai is not installed. Install the 'ai' extra or select opencv_xdog."
            )
        if not self.weights_available():
            raise EngineUnavailableError(
                "Lineart model weights are missing. Download 'lineart-realistic' "
                "from Models or with the models CLI."
            )
        if self._detector is None:
            from controlnet_aux import LineartDetector

            self._detector = LineartDetector.from_pretrained(
                str(self.model_dir), local_files_only=True
            )
            import torch

            device = self.device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            self._detector.to(device)
        return self._detector

    def render(self, rgb: np.ndarray, options: ProcessingOptions) -> np.ndarray:
        detector = self._load()
        resolution = max(64, min(2048, round(max(rgb.shape[:2]) / 64) * 64))
        result = detector(Image.fromarray(rgb), detect_resolution=resolution)
        array = np.asarray(result.convert("L"), dtype=np.uint8)
        # Annotator versions differ in polarity; the whiter background wins.
        if float(array.mean()) < 127:
            array = 255 - array
        return np.where(array < options.threshold, 0, 255).astype(np.uint8)
