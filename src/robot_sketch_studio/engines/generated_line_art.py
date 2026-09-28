from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from skimage.filters import apply_hysteresis_threshold
from skimage.morphology import skeletonize

from robot_sketch_studio.engines.base import SketchEngine
from robot_sketch_studio.models import LineArtImportProfile, ProcessingOptions


@dataclass(frozen=True, slots=True)
class LineArtAnalysis:
    width_px: int
    height_px: int
    millimetres_per_pixel: float
    background_level: int
    line_level: int
    estimated_stroke_width_mm: float
    noise_ratio: float
    thin_lines: bool
    recommendations: dict[str, float | int]

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PreparedLineArt:
    confidence: np.ndarray
    cleaned_mask: np.ndarray
    analysis: LineArtAnalysis
    options: ProcessingOptions


def decode_line_art_image(source: Path | bytes | BinaryIO) -> np.ndarray:
    stream: Path | BytesIO | BinaryIO
    stream = BytesIO(source) if isinstance(source, bytes) else source
    try:
        with Image.open(stream) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
            if image.width < 2 or image.height < 2:
                raise ValueError("Image must be at least 2×2 pixels")
            if image.width * image.height > 50_000_000:
                raise ValueError("Decoded image is too large (maximum 50 megapixels)")
            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
            white = Image.new("RGBA", image.size, (255, 255, 255, 255))
            composited = Image.alpha_composite(white, image).convert("RGB")
            return np.asarray(composited, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The upload is not a valid JPG, PNG, or WebP image") from exc


def _millimetres_per_pixel(shape: tuple[int, int], options: ProcessingOptions) -> float:
    height, width = shape
    page_width, page_height = options.page_dimensions
    available_width = page_width - 2 * options.margin_mm
    available_height = page_height - 2 * options.margin_mm
    return min(
        available_width / max(width - 1, 1),
        available_height / max(height - 1, 1),
    )


def _normalized_ink(rgb: np.ndarray) -> tuple[np.ndarray, int, int]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    border = np.concatenate((gray[0], gray[-1], gray[:, 0], gray[:, -1]))
    background = float(max(np.median(border), np.percentile(gray, 85)))
    darker = gray[gray < background - 3.0]
    line = float(np.percentile(darker, 12)) if darker.size else max(0.0, background - 32.0)
    contrast = max(18.0, background - line)
    confidence = np.clip((background - gray) / contrast, 0.0, 1.0).astype(np.float32)
    return confidence, round(background), round(line)


def _analysis(rgb: np.ndarray, options: ProcessingOptions) -> LineArtAnalysis:
    confidence, background, line = _normalized_ink(rgb)
    scale = _millimetres_per_pixel(confidence.shape, options)
    values = np.rint(confidence * 255).astype(np.uint8)
    otsu, _ = cv2.threshold(values, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    high = float(np.clip(otsu / 255.0, 0.20, 0.58))
    rough = apply_hysteresis_threshold(confidence, high * 0.48, high)
    if rough.any():
        distance = cv2.distanceTransform(rough.astype(np.uint8), cv2.DIST_L2, 5)
        center = skeletonize(rough)
        widths = 2.0 * distance[center] * scale
        stroke_width = float(np.median(widths)) if widths.size else scale
    else:
        stroke_width = scale

    count, _, stats, _ = cv2.connectedComponentsWithStats(rough.astype(np.uint8), 8)
    total_ink = max(1, int(rough.sum()))
    noisy_area = sum(
        int(stats[index, cv2.CC_STAT_AREA])
        for index in range(1, count)
        if max(stats[index, cv2.CC_STAT_WIDTH], stats[index, cv2.CC_STAT_HEIGHT]) * scale < 0.18
    )
    noise_ratio = noisy_area / total_ink
    thin = stroke_width <= max(options.pen_width_mm * 1.2, scale * 2.5)
    optimized = options.line_art_import_profile == LineArtImportProfile.DEXARM_OPTIMIZED
    if optimized:
        noise = float(np.clip(max(0.12, stroke_width * 0.22), 0.12, 0.32))
        minimum_path = float(np.clip(max(0.24, stroke_width * 0.28), 0.24, 0.6))
        gap = float(np.clip(max(0.12, stroke_width * 0.16), 0.12, 0.28))
        smoothing = float(np.clip(max(0.12, stroke_width * 0.16), 0.12, 0.24))
        simplify = float(np.clip(max(0.10, stroke_width * 0.15), 0.10, 0.22))
        duplicate = float(np.clip(options.pen_width_mm * 0.52, 0.18, 0.6))
    else:
        noise = float(np.clip(max(0.05, stroke_width * 0.10), 0.05, 0.16))
        minimum_path = float(np.clip(max(0.08, stroke_width * 0.10), 0.08, 0.25))
        gap = float(np.clip(max(0.05, stroke_width * 0.08), 0.05, 0.16))
        smoothing = float(np.clip(max(0.05, stroke_width * 0.08), 0.05, 0.12))
        simplify = float(np.clip(max(0.04, stroke_width * 0.06), 0.04, 0.10))
        duplicate = float(np.clip(options.pen_width_mm * 0.42, 0.15, 0.48))
    recommendations: dict[str, float | int] = {
        "threshold": int(round((1.0 - high) * 255)),
        "line_art_noise_removal_mm": round(noise, 3),
        "minimum_path_length_mm": round(minimum_path, 3),
        "line_art_gap_closing_mm": round(gap, 3),
        "line_art_smoothing_mm": round(smoothing, 3),
        "line_art_simplify_tolerance_mm": round(simplify, 3),
        "line_art_duplicate_tolerance_mm": round(duplicate, 3),
    }
    return LineArtAnalysis(
        width_px=rgb.shape[1],
        height_px=rgb.shape[0],
        millimetres_per_pixel=round(scale, 5),
        background_level=background,
        line_level=line,
        estimated_stroke_width_mm=round(stroke_width, 3),
        noise_ratio=round(noise_ratio, 5),
        thin_lines=thin,
        recommendations=recommendations,
    )


def _effective_options(options: ProcessingOptions, analysis: LineArtAnalysis) -> ProcessingOptions:
    settings = (
        analysis.recommendations
        if options.line_art_auto
        else {
            "threshold": options.threshold,
            "line_art_noise_removal_mm": options.line_art_noise_removal_mm,
            "minimum_path_length_mm": options.minimum_path_length_mm,
            "line_art_gap_closing_mm": options.line_art_gap_closing_mm,
            "line_art_smoothing_mm": options.line_art_smoothing_mm,
            "line_art_simplify_tolerance_mm": options.line_art_simplify_tolerance_mm,
            "line_art_duplicate_tolerance_mm": options.line_art_duplicate_tolerance_mm,
        }
    )
    optimized = options.line_art_import_profile == LineArtImportProfile.DEXARM_OPTIMIZED
    return options.model_copy(
        update={
            **settings,
            "minimum_feature_size_mm": max(
                0.02, float(settings["line_art_noise_removal_mm"]) * 0.55
            ),
            "join_distance_mm": float(settings["line_art_gap_closing_mm"]),
            "maximum_join_angle_deg": 18.0 if optimized else 13.0,
            "curve_fit_tolerance_mm": float(settings["line_art_smoothing_mm"]),
        }
    )


def _remove_isolated_noise(
    confidence: np.ndarray,
    options: ProcessingOptions,
    scale: float,
) -> tuple[np.ndarray, np.ndarray]:
    high = float(np.clip(1.0 - options.threshold / 255.0, 0.08, 0.78))
    mask = apply_hysteresis_threshold(confidence, high * 0.46, high)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    accepted = np.zeros(count, dtype=bool)
    removal = options.line_art_noise_removal_mm
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        left = int(stats[component, cv2.CC_STAT_LEFT])
        top = int(stats[component, cv2.CC_STAT_TOP])
        width = int(stats[component, cv2.CC_STAT_WIDTH])
        height = int(stats[component, cv2.CC_STAT_HEIGHT])
        component_labels = labels[top : top + height, left : left + width]
        component_confidence = confidence[top : top + height, left : left + width]
        region = component_labels == component
        maximum = float(component_confidence[region].max(initial=0.0))
        span_mm = max(width, height) * scale
        area_mm = area * scale * scale
        obvious_noise = (
            removal > 0
            and span_mm < removal
            and area_mm < removal * removal * 0.55
            and maximum < 0.94
        )
        accepted[component] = not obvious_noise
    cleaned = accepted[labels]
    return np.where(cleaned, confidence, 0.0).astype(np.float32), cleaned


class GeneratedLineArtEngine(SketchEngine):
    name = "generated_line_art"

    def available(self) -> bool:
        return True

    def analyze(self, rgb: np.ndarray, options: ProcessingOptions) -> LineArtAnalysis:
        return _analysis(rgb, options)

    def prepare(self, rgb: np.ndarray, options: ProcessingOptions) -> PreparedLineArt:
        analysis = self.analyze(rgb, options)
        effective = _effective_options(options, analysis)
        confidence, _, _ = _normalized_ink(rgb)
        cleaned, mask = _remove_isolated_noise(
            confidence,
            effective,
            _millimetres_per_pixel(confidence.shape, effective),
        )
        return PreparedLineArt(cleaned, mask, analysis, effective)

    def render_confidence(self, rgb: np.ndarray, options: ProcessingOptions) -> np.ndarray:
        return self.prepare(rgb, options).confidence

    def render(self, rgb: np.ndarray, options: ProcessingOptions) -> np.ndarray:
        confidence = self.render_confidence(rgb, options)
        return np.rint((1.0 - confidence) * 255).astype(np.uint8)
