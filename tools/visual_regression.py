from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from robot_sketch_studio.fidelity import _geometry, _metrics
from robot_sketch_studio.models import (
    FillStrategy,
    PaperPreset,
    ProcessingOptions,
    VectorizationMode,
)
from robot_sketch_studio.vectorization import vectorize, write_svg, write_trajectory


def synthetic_portrait() -> np.ndarray:
    image = np.zeros((601, 801), dtype=np.float32)
    cv2.ellipse(image, (400, 275), (155, 205), 0, 0, 360, 1.0, 7)
    cv2.ellipse(image, (400, 195), (145, 125), 0, 190, 350, 1.0, 34)
    cv2.ellipse(image, (345, 270), (28, 13), 0, 0, 360, 1.0, 6)
    cv2.ellipse(image, (455, 270), (28, 13), 0, 0, 360, 1.0, 6)
    cv2.circle(image, (345, 270), 5, 1.0, -1)
    cv2.circle(image, (455, 270), 5, 1.0, -1)
    cv2.line(image, (400, 282), (386, 342), 1.0, 4)
    cv2.line(image, (386, 342), (409, 342), 1.0, 4)
    cv2.ellipse(image, (400, 378), (48, 18), 0, 5, 175, 1.0, 5)
    cv2.line(image, (245, 480), (115, 585), 1.0, 11)
    cv2.line(image, (555, 480), (685, 585), 1.0, 11)
    return image


def render_centerline(
    lines: list[list[tuple[float, float]]],
    shape: tuple[int, int],
    settings: ProcessingOptions,
) -> np.ndarray:
    geometry = _geometry(shape, settings)
    rendered = np.zeros(shape, dtype=np.uint8)
    thickness = max(1, int(round(settings.stroke_width_mm / geometry.scale)))
    for line in lines:
        points = np.asarray(
            [
                (
                    round((x - geometry.offset_x) / geometry.scale),
                    round((y - geometry.offset_y) / geometry.scale),
                )
                for x, y in line
            ],
            dtype=np.int32,
        )
        cv2.polylines(rendered, [points], False, 1, thickness, cv2.LINE_8)
    return rendered.astype(bool)


def overlay(source: np.ndarray, rendered: np.ndarray) -> np.ndarray:
    result = np.full((*source.shape, 3), 255, dtype=np.uint8)
    result[source & rendered] = (36, 166, 76)
    result[source & ~rendered] = (220, 48, 48)
    result[~source & rendered] = (45, 92, 220)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic v0.3.1 previews")
    parser.add_argument("--output", type=Path, default=Path("storage/v031-regression"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = synthetic_portrait()
    common = {
        "paper": PaperPreset.CUSTOM,
        "page_width_mm": 100,
        "page_height_mm": 75,
        "margin_mm": 10,
        "minimum_path_length_mm": 0.25,
        "minimum_feature_size_mm": 0.15,
        "join_distance_mm": 0.35,
    }
    before_options = ProcessingOptions(
        **common,
        vectorization_mode=VectorizationMode.MINIMAL,
        target_paths=64,
        curve_fit_tolerance_mm=0.3,
        stroke_width_mm=0.35,
    )
    after_options = ProcessingOptions(
        **common,
        vectorization_mode=VectorizationMode.PLOTTER_FIDELITY,
        pen_width_mm=0.5,
        curve_fit_tolerance_mm=0.08,
        fill_strategy=FillStrategy.CONTOUR,
    )
    before = vectorize(source, before_options)
    after = vectorize(source, after_options)
    before_render = render_centerline(before.lines, source.shape, before_options)
    before_metrics = _metrics(
        source.astype(bool), before_render, _geometry(source.shape, before_options).scale
    )

    Image.fromarray(np.where(source > 0, 0, 255).astype(np.uint8)).save(
        args.output / "source-sketch.png"
    )
    Image.fromarray(np.where(before_render, 0, 255).astype(np.uint8)).save(
        args.output / "before-centerline.png"
    )
    Image.fromarray(overlay(source.astype(bool), before_render)).save(
        args.output / "before-difference.png"
    )
    Image.fromarray(after.vector_preview).save(args.output / "after-fidelity.png")
    Image.fromarray(after.difference_overlay).save(args.output / "after-difference.png")
    write_svg(before, before_options, args.output / "before.svg")
    write_svg(after, after_options, args.output / "after.svg")
    write_trajectory(after, after_options, args.output / "after-trajectory.json")
    report = {
        "before": {"paths": before.stats.stroke_count, **before_metrics},
        "after": {"paths": after.stats.stroke_count, **after.stats.model_dump()},
    }
    (args.output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
