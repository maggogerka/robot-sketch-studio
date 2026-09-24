from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from robot_sketch_studio.engines import CleanAIEngine, OpenCVXDoGEngine
from robot_sketch_studio.models import BackgroundMode, ProcessingOptions, SketchEngineName
from robot_sketch_studio.providers import RembgProvider, create_image_edit_provider
from robot_sketch_studio.vectorization import VectorResult, vectorize, write_svg, write_trajectory


class InvalidImageError(ValueError):
    pass


@dataclass(slots=True)
class PipelineResult:
    vector: VectorResult
    artifacts: dict[str, str]
    warnings: list[str] = field(default_factory=list)


class SketchPipeline:
    def __init__(
        self,
        device: str = "auto",
        model_dir: Path | None = None,
        comfyui_workflow: Path | None = None,
    ) -> None:
        if model_dir is not None:
            cache_root = model_dir.expanduser().resolve()
            os.environ.setdefault("HF_HOME", str(cache_root / "huggingface"))
            os.environ.setdefault("TORCH_HOME", str(cache_root / "torch"))
        clean_ai = CleanAIEngine(device, model_dir)
        self.engines = {
            SketchEngineName.CLEAN_AI: clean_ai,
            SketchEngineName.LINEART_AI: clean_ai,
            SketchEngineName.OPENCV_XDOG: OpenCVXDoGEngine(),
        }
        self.background = RembgProvider(model_dir)
        self.comfyui_workflow = comfyui_workflow

    def capabilities(self) -> dict[str, object]:
        return {
            "engines": {
                SketchEngineName.CLEAN_AI.value: {
                    "available": self.engines[SketchEngineName.CLEAN_AI].available(),
                    "requires_weights": True,
                    "dependency_available": self.engines[
                        SketchEngineName.CLEAN_AI
                    ].dependency_available(),
                },
                SketchEngineName.ARTISTIC_REMOTE.value: {
                    "available": True,
                    "requires_weights": False,
                    "dependency_available": True,
                },
                SketchEngineName.OPENCV_XDOG.value: {
                    "available": True,
                    "requires_weights": False,
                    "dependency_available": True,
                    "fallback": True,
                },
            },
            "background_removal": {
                "available": self.background.available(),
                "modes": [mode.value for mode in BackgroundMode],
                "models": {
                    "u2net": self.background.weights_available("auto"),
                    "u2net_human_seg": self.background.weights_available("person"),
                },
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

    def process(
        self,
        source: Path,
        output_dir: Path,
        options: ProcessingOptions,
        remote_api_key: str = "",
    ) -> PipelineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        rgb = self.load_image(source)
        warnings: list[str] = []
        if options.background != BackgroundMode.OFF:
            if self.background.ready(options.background.value):
                rgb = self.background.remove(rgb, options.background.value)
            else:
                warnings.append(
                    "rembg background removal was skipped. Install the background extra and "
                    "download the matching U2-Net model from Models."
                )

        if options.engine == SketchEngineName.ARTISTIC_REMOTE:
            provider = create_image_edit_provider(
                options.remote_backend,
                options.remote_url or "",
                options.remote_model,
                remote_api_key,
                self.comfyui_workflow,
            )
            edited = provider.edit(rgb)
            gray = cv2.cvtColor(edited, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
            confidence = np.clip(1.0 - gray, 0.0, 1.0)
        else:
            confidence = self.engines[options.engine].render_confidence(rgb, options)
        vector = vectorize(confidence, options)
        confidence_path = output_dir / "confidence.png"
        sketch_path = output_dir / "sketch.png"
        vector_preview_path = output_dir / "vector-preview.png"
        difference_path = output_dir / "difference-overlay.png"
        svg_path = output_dir / "drawing.svg"
        trajectory_path = output_dir / "trajectory.json"
        confidence_image = np.rint((1.0 - confidence) * 255.0).astype(np.uint8)
        Image.fromarray(confidence_image, mode="L").save(
            confidence_path, format="PNG", optimize=True
        )
        Image.fromarray(vector.preview, mode="L").save(sketch_path, format="PNG", optimize=True)
        vector_preview = (
            vector.vector_preview if vector.vector_preview is not None else vector.preview
        )
        Image.fromarray(vector_preview, mode="L").save(
            vector_preview_path, format="PNG", optimize=True
        )
        if vector.difference_overlay is None:
            difference = np.full((*vector.preview.shape, 3), 255, dtype=np.uint8)
            difference[vector.preview == 0] = (36, 166, 76)
        else:
            difference = vector.difference_overlay
        Image.fromarray(difference, mode="RGB").save(difference_path, format="PNG", optimize=True)
        write_svg(vector, options, svg_path)
        write_trajectory(vector, options, trajectory_path)
        return PipelineResult(
            vector=vector,
            artifacts={
                "confidence.png": str(confidence_path),
                "sketch.png": str(sketch_path),
                "vector-preview.png": str(vector_preview_path),
                "difference-overlay.png": str(difference_path),
                "drawing.svg": str(svg_path),
                "trajectory.json": str(trajectory_path),
            },
            warnings=warnings + vector.warnings,
        )
