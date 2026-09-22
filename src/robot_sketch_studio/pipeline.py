from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from robot_sketch_studio.engines import LineartAIEngine, OpenCVXDoGEngine
from robot_sketch_studio.models import BackgroundMode, ProcessingOptions, SketchEngineName
from robot_sketch_studio.providers import RembgProvider
from robot_sketch_studio.vectorization import VectorResult, vectorize, write_svg, write_trajectory


class InvalidImageError(ValueError):
    pass


@dataclass(slots=True)
class PipelineResult:
    vector: VectorResult
    artifacts: dict[str, str]
    warnings: list[str] = field(default_factory=list)


class SketchPipeline:
    def __init__(self, device: str = "auto", model_dir: Path | None = None) -> None:
        if model_dir is not None:
            cache_root = model_dir.expanduser().resolve()
            os.environ.setdefault("HF_HOME", str(cache_root / "huggingface"))
            os.environ.setdefault("TORCH_HOME", str(cache_root / "torch"))
        self.engines = {
            SketchEngineName.OPENCV_XDOG: OpenCVXDoGEngine(),
            SketchEngineName.LINEART_AI: LineartAIEngine(device),
        }
        self.background = RembgProvider(model_dir)

    def capabilities(self) -> dict[str, object]:
        return {
            "engines": {
                name.value: {
                    "available": engine.available(),
                    "requires_weights": name == SketchEngineName.LINEART_AI,
                }
                for name, engine in self.engines.items()
            },
            "background_removal": {
                "available": self.background.available(),
                "modes": [mode.value for mode in BackgroundMode],
            },
        }

    @staticmethod
    def load_image(source: Path) -> np.ndarray:
        try:
            with Image.open(source) as opened:
                opened.verify()
            with Image.open(source) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                if image.width < 2 or image.height < 2:
                    raise InvalidImageError("Image must be at least 2×2 pixels")
                if image.width * image.height > 50_000_000:
                    raise InvalidImageError("Decoded image is too large (maximum 50 megapixels)")
                image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                return np.asarray(image, dtype=np.uint8)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise InvalidImageError("The upload is not a valid JPG, PNG, or WebP image") from exc

    def process(self, source: Path, output_dir: Path, options: ProcessingOptions) -> PipelineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        rgb = self.load_image(source)
        warnings: list[str] = []
        if options.background != BackgroundMode.OFF:
            if self.background.available():
                rgb = self.background.remove(rgb, options.background.value)
            else:
                warnings.append("Background removal was skipped because rembg is not installed.")

        sketch = self.engines[options.engine].render(rgb, options)
        vector = vectorize(sketch, options)
        sketch_path = output_dir / "sketch.png"
        svg_path = output_dir / "drawing.svg"
        trajectory_path = output_dir / "trajectory.json"
        Image.fromarray(sketch, mode="L").save(sketch_path, format="PNG", optimize=True)
        write_svg(vector, options, svg_path)
        write_trajectory(vector, options, trajectory_path)
        return PipelineResult(
            vector=vector,
            artifacts={
                "sketch.png": str(sketch_path),
                "drawing.svg": str(svg_path),
                "trajectory.json": str(trajectory_path),
            },
            warnings=warnings,
        )
