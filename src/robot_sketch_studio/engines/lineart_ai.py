from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

import cv2
import numpy as np

from robot_sketch_studio.engines.base import EngineUnavailableError, SketchEngine
from robot_sketch_studio.models import ProcessingOptions


def _build_generator():
    """Build the architecture published with Informative Drawings (CVPR 2022)."""
    import torch.nn as nn

    class ResidualBlock(nn.Module):
        def __init__(self, features: int) -> None:
            super().__init__()
            self.conv_block = nn.Sequential(
                nn.ReflectionPad2d(1),
                nn.Conv2d(features, features, 3),
                nn.InstanceNorm2d(features),
                nn.ReLU(inplace=True),
                nn.ReflectionPad2d(1),
                nn.Conv2d(features, features, 3),
                nn.InstanceNorm2d(features),
            )

        def forward(self, value):
            return value + self.conv_block(value)

    class Generator(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.model0 = nn.Sequential(
                nn.ReflectionPad2d(3),
                nn.Conv2d(3, 64, 7),
                nn.InstanceNorm2d(64),
                nn.ReLU(inplace=True),
            )
            downsample: list[nn.Module] = []
            current = 64
            for _ in range(2):
                following = current * 2
                downsample.extend(
                    [
                        nn.Conv2d(current, following, 3, stride=2, padding=1),
                        nn.InstanceNorm2d(following),
                        nn.ReLU(inplace=True),
                    ]
                )
                current = following
            self.model1 = nn.Sequential(*downsample)
            self.model2 = nn.Sequential(*(ResidualBlock(current) for _ in range(3)))
            upsample: list[nn.Module] = []
            for _ in range(2):
                following = current // 2
                upsample.extend(
                    [
                        nn.ConvTranspose2d(
                            current,
                            following,
                            3,
                            stride=2,
                            padding=1,
                            output_padding=1,
                        ),
                        nn.InstanceNorm2d(following),
                        nn.ReLU(inplace=True),
                    ]
                )
                current = following
            self.model3 = nn.Sequential(*upsample)
            self.model4 = nn.Sequential(
                nn.ReflectionPad2d(3),
                nn.Conv2d(64, 1, 7),
                nn.Sigmoid(),
            )

        def forward(self, value):
            value = self.model0(value)
            value = self.model1(value)
            value = self.model2(value)
            value = self.model3(value)
            return self.model4(value)

    return Generator()


class CleanAIEngine(SketchEngine):
    name = "clean_ai"

    def __init__(self, device: str = "auto", model_dir: Path | None = None) -> None:
        self.device = device
        self.model_dir = model_dir.expanduser().resolve() / "lineart" if model_dir else None
        self._model = None
        self._resolved_device = "cpu"
        self._load_lock = threading.Lock()

    def dependency_available(self) -> bool:
        return importlib.util.find_spec("torch") is not None

    def weights_available(self) -> bool:
        return bool(self.model_dir and (self.model_dir / "sk_model.pth").is_file())

    def available(self) -> bool:
        return self.dependency_available() and self.weights_available()

    def _load(self):
        if not self.dependency_available():
            raise EngineUnavailableError(
                "Clean AI Sketch needs PyTorch. Run setup_models_windows.bat "
                "or install the 'ai' extra."
            )
        if not self.weights_available():
            raise EngineUnavailableError(
                "Informative Drawings weights are missing. Download the model in the Models panel."
            )
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    import torch

                    requested = self.device.lower()
                    if requested == "auto":
                        requested = "cuda" if torch.cuda.is_available() else "cpu"
                    if requested == "cuda" and not torch.cuda.is_available():
                        raise EngineUnavailableError("CUDA was requested but is not available")
                    model = _build_generator()
                    weight_path = self.model_dir / "sk_model.pth"
                    try:
                        state = torch.load(weight_path, map_location="cpu", weights_only=True)
                    except TypeError:
                        state = torch.load(weight_path, map_location="cpu")
                    if isinstance(state, dict) and "state_dict" in state:
                        state = state["state_dict"]
                    state = {
                        str(key).removeprefix("module."): value for key, value in state.items()
                    }
                    model.load_state_dict(state, strict=True)
                    model.eval().to(requested)
                    self._model = model
                    self._resolved_device = requested
        return self._model

    def render_confidence(self, rgb: np.ndarray, options: ProcessingOptions) -> np.ndarray:
        model = self._load()
        import torch

        source_height, source_width = rgb.shape[:2]
        maximum_side = 1024.0 if self._resolved_device == "cuda" else 512.0
        scale = min(1.0, maximum_side / max(source_height, source_width))
        width = max(32, int(round(source_width * scale / 4)) * 4)
        height = max(32, int(round(source_height * scale / 4)) * 4)
        resized = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA)
        tensor = (
            torch.from_numpy(np.ascontiguousarray(resized.transpose(2, 0, 1)))
            .float()
            .div_(255.0)
            .unsqueeze(0)
            .to(self._resolved_device)
        )
        with torch.inference_mode():
            generated = model(tensor)[0, 0].detach().float().cpu().numpy()
        # The published model outputs black strokes on a white background.
        confidence = np.clip(1.0 - generated, 0.0, 1.0)
        if (height, width) != (source_height, source_width):
            confidence = cv2.resize(
                confidence,
                (source_width, source_height),
                interpolation=cv2.INTER_CUBIC,
            )
        return np.clip(confidence, 0.0, 1.0).astype(np.float32)

    def render(self, rgb: np.ndarray, options: ProcessingOptions) -> np.ndarray:
        confidence = self.render_confidence(rgb, options)
        return np.rint((1.0 - confidence) * 255.0).astype(np.uint8)


# Public compatibility name retained for integrations written against v0.2.
LineartAIEngine = CleanAIEngine
