from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from robot_sketch_studio.models import (
    EventQualityLevel,
    FillStrategy,
    PaperPreset,
    ProcessingOptions,
    VectorizationMode,
)
from robot_sketch_studio.vectorization import vectorize, write_svg, write_trajectory


def dense_portrait() -> np.ndarray:
    image = np.zeros((601, 801), dtype=np.float32)
    cv2.ellipse(image, (400, 275), (155, 205), 0, 0, 360, 1.0, 5)
    cv2.ellipse(image, (400, 195), (145, 125), 0, 190, 350, 0.92, 9)
    cv2.ellipse(image, (345, 270), (28, 13), 0, 0, 360, 1.0, 4)
    cv2.ellipse(image, (455, 270), (28, 13), 0, 0, 360, 1.0, 4)
    cv2.circle(image, (345, 270), 4, 1.0, -1)
    cv2.circle(image, (455, 270), 4, 1.0, -1)
    cv2.line(image, (400, 282), (386, 342), 0.94, 3)
    cv2.line(image, (386, 342), (409, 342), 0.94, 3)
    cv2.ellipse(image, (400, 378), (48, 18), 0, 5, 175, 1.0, 4)
    cv2.line(image, (245, 480), (115, 585), 0.9, 7)
    cv2.line(image, (555, 480), (685, 585), 0.9, 7)
    rng = np.random.default_rng(4031)
    for _ in range(520):
        side = -1 if rng.integers(0, 2) == 0 else 1
        x = int(400 + side * rng.integers(120, 280))
        y = int(rng.integers(75, 555))
        length = int(rng.integers(4, 15))
        slope = int(rng.integers(-4, 5))
        confidence = float(rng.uniform(0.48, 0.88))
        cv2.line(image, (x, y), (x + side * length, y + slope), confidence, 1)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Event Quality against dense centerlines"
    )
    parser.add_argument("--output", type=Path, default=Path("storage/event-speed-benchmark"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    confidence = dense_portrait()
    common = {
        "paper": PaperPreset.A4_PORTRAIT,
        "margin_mm": 10,
        "pen_width_mm": 0.5,
        "stroke_width_mm": 0.5,
        "minimum_feature_size_mm": 0.05,
        "join_distance_mm": 0.65,
        "maximum_join_angle_deg": 22,
        "curve_fit_tolerance_mm": 0.25,
        "drawing_speed_mm_s": 35,
        "travel_speed_mm_s": 90,
        "pen_lift_delay_s": 0.35,
    }
    quality_options = ProcessingOptions(
        **common,
        vectorization_mode=VectorizationMode.CENTERLINE,
        minimum_path_length_mm=0,
    )
    speed_options = ProcessingOptions(
        **common,
        vectorization_mode=VectorizationMode.EVENT_QUALITY,
        event_quality_level=EventQualityLevel.BALANCED,
        fill_strategy=FillStrategy.ADAPTIVE_SPARSE,
        minimum_path_length_mm=0.8,
    )
    quality = vectorize(confidence, quality_options)
    speed = vectorize(confidence, speed_options)
    quality_time = (
        quality.stats.drawing_length_mm / quality_options.drawing_speed_mm_s
        + quality.stats.travel_length_mm / quality_options.travel_speed_mm_s
        + quality.stats.pen_lifts * quality_options.pen_lift_delay_s
    )
    Image.fromarray(np.where(confidence > 0, 0, 255).astype(np.uint8)).save(
        args.output / "source.png"
    )
    Image.fromarray(quality.vector_preview).save(args.output / "quality-preview.png")
    Image.fromarray(speed.vector_preview).save(args.output / "speed-preview.png")
    Image.fromarray(speed.difference_overlay).save(args.output / "speed-difference-overlay.png")
    write_svg(quality, quality_options, args.output / "quality.svg")
    write_svg(speed, speed_options, args.output / "drawing-speed.svg")
    write_trajectory(speed, speed_options, args.output / "trajectory-speed.json")
    report = {
        "provided_drawing_5_baseline": {
            "available": True,
            "paths": 1000,
            "svg_commands": 13201,
            "drawing_length_mm": 8988.8,
            "travel_length_mm": 5728.3,
            "note": "Verified from drawing (5).svg; use svg_quality_benchmark.py to replay it.",
        },
        "synthetic_quality": {
            **quality.stats.model_dump(),
            "normalized_estimated_time_seconds": round(quality_time, 2),
        },
        "synthetic_event_quality": speed.stats.model_dump(),
        "reduction": {
            "paths_percent": round(
                100 * (1 - speed.stats.stroke_count / max(quality.stats.stroke_count, 1)), 2
            ),
            "travel_percent": round(
                100
                * (1 - speed.stats.travel_length_mm / max(quality.stats.travel_length_mm, 1e-9)),
                2,
            ),
            "time_percent": round(
                100 * (1 - speed.stats.estimated_time_seconds / max(quality_time, 1e-9)), 2
            ),
        },
    }
    (args.output / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
