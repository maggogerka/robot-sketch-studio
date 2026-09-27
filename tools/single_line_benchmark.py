from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from svg_quality_benchmark import SvgDrawing, _face_mask, _render_paths, load_svg, summarize

from robot_sketch_studio.event_single_line import SingleLineFeature, collapse_parallel_paths
from robot_sketch_studio.fidelity import _metrics
from robot_sketch_studio.models import (
    ExportProfile,
    FillStrategy,
    PaperPreset,
    ProcessingOptions,
    VectorizationMode,
)
from robot_sketch_studio.vectorization import (
    polyline_length,
    vectorize,
    write_svg,
    write_trajectory,
)


def scale_drawing(
    drawing: SvgDrawing,
    width_mm: float = 80.0,
    height_mm: float = 113.0,
    stroke_width_mm: float | None = None,
) -> SvgDrawing:
    scale_x = width_mm / drawing.width_mm
    scale_y = height_mm / drawing.height_mm
    paths = [[(x * scale_x, y * scale_y) for x, y in path] for path in drawing.paths]
    return SvgDrawing(
        paths,
        width_mm,
        height_mm,
        drawing.stroke_width_mm if stroke_width_mm is None else stroke_width_mm,
        drawing.command_count,
    )


def comparable_metrics(reference: np.ndarray, rendered: np.ndarray, scale: int) -> dict:
    metrics = _metrics(reference, rendered, 1.0 / scale)
    face = _face_mask(reference)
    face_recall = float((reference & rendered & face).sum()) / max(1, int((reference & face).sum()))
    silhouette = reference & ~face
    silhouette_recall = float((rendered & silhouette).sum()) / max(1, int(silhouette.sum()))
    return {
        **metrics,
        "face_weighted_recall": round(face_recall, 5),
        "silhouette_recall": round(silhouette_recall, 5),
    }


def redundancy_metrics(drawing: SvgDrawing, scale: int) -> dict[str, float | int]:
    rendered = _render_paths(drawing, scale)
    _, labels = cv2.connectedComponents(rendered.astype(np.uint8), 8)
    face = _face_mask(rendered)
    features: list[SingleLineFeature] = []
    for index, path in enumerate(drawing.paths):
        points = np.rint(np.asarray(path) * scale).astype(np.int32)
        points[:, 0] = np.clip(points[:, 0], 0, rendered.shape[1] - 1)
        points[:, 1] = np.clip(points[:, 1], 0, rendered.shape[0] - 1)
        component_values = labels[points[:, 1], points[:, 0]]
        nonzero = component_values[component_values > 0]
        component_id = int(np.bincount(nonzero).argmax()) if len(nonzero) else -(index + 1)
        length = polyline_length(path)
        face_weight = float(face[points[:, 1], points[:, 0]].mean())
        importance = min(1.0, math.log1p(length) / math.log(81.0))
        features.append(SingleLineFeature(path, component_id, importance, face_weight, 1.0))
    _, stats = collapse_parallel_paths(features, drawing.stroke_width_mm)
    return {
        "redundant_path_count": stats.removed_path_count,
        "parallel_overlap_ratio": stats.input_parallel_overlap_ratio,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark physical 80x113 Event Single-Line output"
    )
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--fidelity", type=Path)
    parser.add_argument("--output", type=Path, default=Path("storage/single-line-benchmark"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    original_event = load_svg(args.event)
    event = scale_drawing(original_event, stroke_width_mm=original_event.stroke_width_mm)
    fidelity = scale_drawing(load_svg(args.fidelity)) if args.fidelity else event
    raster_scale = 6
    event_render = _render_paths(event, raster_scale)
    fidelity_render = _render_paths(fidelity, raster_scale)
    options = ProcessingOptions(
        vectorization_mode=VectorizationMode.EVENT_SINGLE_LINE,
        export_profile=ExportProfile.ROTRICS_CENTERLINE,
        paper=PaperPreset.ROTRICS_80X113,
        margin_mm=0,
        pen_width_mm=event.stroke_width_mm,
        fill_strategy=FillStrategy.NONE,
        minimum_path_length_mm=0.2,
        minimum_feature_size_mm=0.08,
        curve_fit_tolerance_mm=0.2,
        join_distance_mm=0.5,
        maximum_join_angle_deg=20,
        drawing_speed_mm_s=35,
        travel_speed_mm_s=90,
        pen_lift_delay_s=0.35,
    )
    single = vectorize(event_render.astype(np.float32), options)
    write_svg(single, options, args.output / "drawing-single-line.svg")
    write_trajectory(single, options, args.output / "trajectory-single-line.json")
    Image.fromarray(np.where(event_render, 0, 255).astype(np.uint8)).save(
        args.output / "event-quality-physical.png"
    )
    Image.fromarray(single.vector_preview).save(args.output / "single-line-preview.png")
    Image.fromarray(single.difference_overlay).save(args.output / "single-line-difference.png")

    event_summary = summarize(event)
    fidelity_summary = summarize(fidelity)
    single_render = single.vector_preview == 0
    table = {
        "Fidelity": {
            **fidelity_summary,
            "redundant_path_count": None,
            "parallel_overlap_ratio": None,
            **comparable_metrics(fidelity_render, fidelity_render, raster_scale),
        },
        "Event Quality": {
            **event_summary,
            **redundancy_metrics(event, raster_scale),
            **comparable_metrics(fidelity_render, event_render, raster_scale),
        },
        "Event Single-Line": {
            **single.stats.model_dump(),
            **comparable_metrics(fidelity_render, single_render, raster_scale),
        },
    }
    report = {
        "input": {
            "path": str(args.event),
            "width_mm": original_event.width_mm,
            "height_mm": original_event.height_mm,
            "stroke_width_mm": original_event.stroke_width_mm,
            **summarize(original_event),
        },
        "physical_target_mm": [80, 113],
        "table": table,
        "single_line_reduction_percent": {
            "paths": round(
                100 * (1 - single.stats.stroke_count / max(1, int(event_summary["paths"]))),
                2,
            ),
            "pen_lifts": round(
                100 * (1 - single.stats.pen_lifts / max(1, int(event_summary["pen_lifts"]))),
                2,
            ),
            "time": round(
                100
                * (
                    1
                    - single.stats.estimated_time_seconds
                    / max(1e-9, float(event_summary["estimated_time_seconds"]))
                ),
                2,
            ),
        },
    }
    (args.output / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
