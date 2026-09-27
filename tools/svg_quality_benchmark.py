from __future__ import annotations

import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from robot_sketch_studio.bezier_fit import CubicCommand, sample_commands
from robot_sketch_studio.event_speed import _safe_commands, optimize_event_order
from robot_sketch_studio.fidelity import (
    Geometry,
    _metrics,
    _preview_images,
    _render,
    write_fidelity_svg,
)
from robot_sketch_studio.models import DrawingStats, PaperPreset, ProcessingOptions
from robot_sketch_studio.vectorization import VectorResult, polyline_length, rdp

TOKEN = re.compile(r"[MLC]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


@dataclass(frozen=True, slots=True)
class SvgDrawing:
    paths: list[list[tuple[float, float]]]
    width_mm: float
    height_mm: float
    stroke_width_mm: float
    command_count: int


def _parse_path(data: str) -> tuple[list[tuple[float, float]], int]:
    tokens = TOKEN.findall(data)
    points: list[tuple[float, float]] = []
    index = 0
    command = ""
    cursor = np.zeros(2, dtype=np.float64)
    command_count = 0
    while index < len(tokens):
        if tokens[index] in {"M", "L", "C"}:
            command = tokens[index]
            command_count += 1
            index += 1
        if command in {"M", "L"}:
            cursor = np.asarray([float(tokens[index]), float(tokens[index + 1])])
            points.append((float(cursor[0]), float(cursor[1])))
            index += 2
            if command == "M":
                command = "L"
        elif command == "C":
            control1 = np.asarray([float(tokens[index]), float(tokens[index + 1])])
            control2 = np.asarray([float(tokens[index + 2]), float(tokens[index + 3])])
            end = np.asarray([float(tokens[index + 4]), float(tokens[index + 5])])
            index += 6
            polygon = (
                np.linalg.norm(control1 - cursor)
                + np.linalg.norm(control2 - control1)
                + np.linalg.norm(end - control2)
            )
            steps = max(4, min(300, int(math.ceil(polygon / 0.22))))
            for position in np.linspace(1.0 / steps, 1.0, steps):
                point = (
                    (1 - position) ** 3 * cursor
                    + 3 * (1 - position) ** 2 * position * control1
                    + 3 * (1 - position) * position**2 * control2
                    + position**3 * end
                )
                points.append((float(point[0]), float(point[1])))
            cursor = end
        else:
            raise ValueError(f"Unsupported SVG command in: {data[:80]}")
    return points, command_count


def load_svg(path: Path) -> SvgDrawing:
    root = ET.parse(path).getroot()
    view_box = [float(value) for value in root.attrib["viewBox"].split()]
    paths: list[list[tuple[float, float]]] = []
    command_count = 0
    stroke_width = 0.5
    for element in root:
        if not element.tag.endswith("path"):
            raise ValueError("Benchmark SVG must contain direct path children only")
        if re.search(r"[^MLC\d\s.,+\-eE]", element.attrib.get("d", "")):
            raise ValueError("Benchmark supports only absolute M/L/C commands")
        points, commands = _parse_path(element.attrib["d"])
        if len(points) >= 2:
            paths.append(points)
            command_count += commands
        stroke_width = float(element.attrib.get("stroke-width", stroke_width))
    return SvgDrawing(paths, view_box[2], view_box[3], stroke_width, command_count)


def _render_paths(drawing: SvgDrawing, scale: int = 4) -> np.ndarray:
    image = np.zeros(
        (round(drawing.height_mm * scale) + 1, round(drawing.width_mm * scale) + 1),
        dtype=np.uint8,
    )
    thickness = max(1, round(drawing.stroke_width_mm * scale))
    for path in drawing.paths:
        points = np.rint(np.asarray(path) * scale).astype(np.int32)
        cv2.polylines(image, [points], False, 1, thickness, cv2.LINE_8)
    return image.astype(bool)


def _lengths(paths: list[list[tuple[float, float]]]) -> tuple[float, float]:
    drawing = sum(polyline_length(path) for path in paths)
    travel = sum(math.dist(paths[index - 1][-1], paths[index][0]) for index in range(1, len(paths)))
    return drawing, travel


def _face_mask(source: np.ndarray) -> np.ndarray:
    ys, xs = np.where(source)
    mask = np.zeros_like(source, dtype=bool)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    width, height = x1 - x0, y1 - y0
    mask[y0 : round(y0 + height * 0.50), round(x0 + width * 0.20) : round(x1 - width * 0.20)] = True
    return mask


def _coverage(path: list[tuple[float, float]], source: np.ndarray, scale: int, width: float):
    points = np.rint(np.asarray(path) * scale).astype(np.int32)
    padding = max(3, round(width * scale) + 2)
    x0 = max(0, int(points[:, 0].min()) - padding)
    x1 = min(source.shape[1], int(points[:, 0].max()) + padding + 1)
    y0 = max(0, int(points[:, 1].min()) - padding)
    y1 = min(source.shape[0], int(points[:, 1].max()) + padding + 1)
    local = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    shifted = points - np.asarray([x0, y0])
    cv2.polylines(local, [shifted], False, 1, max(1, round(width * scale)), cv2.LINE_8)
    ys, xs = np.where(local.astype(bool) & source[y0:y1, x0:x1])
    return np.unique((ys + y0) * source.shape[1] + xs + x0)


def select_hybrid(
    fidelity: SvgDrawing,
    event: SvgDrawing,
    source: np.ndarray,
    face: np.ndarray,
    *,
    scale: int = 4,
) -> list[list[tuple[float, float]]]:
    selected = [path[:] for path in event.paths]
    covered = _render_paths(event, scale).ravel()
    source_flat = source.ravel()
    face_flat = (source & face).ravel()
    weights = np.ones(source.size, dtype=np.float32)
    weights[face_flat] = 6.0
    entries = [
        (path, _coverage(path, source, scale, fidelity.stroke_width_mm), polyline_length(path))
        for path in fidelity.paths
    ]
    drawing_length = sum(polyline_length(path) for path in selected)
    cursor = selected[-1][-1]
    minimum, maximum = 450, 650
    while entries and len(selected) < maximum:
        recall = int(covered[source_flat].sum()) / max(1, int(source_flat.sum()))
        face_recall = int(covered[face_flat].sum()) / max(1, int(face_flat.sum()))
        if (
            len(selected) >= minimum
            and recall >= 0.72
            and face_recall >= 0.86
            and drawing_length >= 4000
        ):
            break
        best_index = -1
        best_key: tuple[float, float, tuple] | None = None
        for index, (path, indices, length) in enumerate(entries):
            unseen = ~covered[indices]
            if not unseen.any():
                continue
            if drawing_length + length > 5500:
                continue
            reserved_slots = max(0, minimum - len(selected))
            if reserved_slots:
                average_budget = (5500 - drawing_length) / reserved_slots
                if length > average_budget * 2.0:
                    continue
            gain = float(weights[indices[unseen]].sum())
            face_gain = int(face_flat[indices[unseen]].sum())
            if face_recall < 0.86:
                gain += face_gain * 18.0
            added_time = length / 35.0 + math.dist(cursor, path[0]) / 90.0 + 0.35
            score = gain * (1.15 if drawing_length < 4000 and length >= 8 else 1.0) / added_time
            key = (score, length, path[0])
            if best_key is None or key > best_key:
                best_key = key
                best_index = index
        if best_index < 0:
            break
        path, indices, length = entries.pop(best_index)
        covered[indices] = True
        selected.append(path)
        drawing_length += length
        cursor = path[-1]
    return selected


def build_result(
    paths: list[list[tuple[float, float]]], reference: SvgDrawing, source: np.ndarray
) -> VectorResult:
    options = ProcessingOptions(
        paper=PaperPreset.CUSTOM,
        page_width_mm=reference.width_mm,
        page_height_mm=reference.height_mm,
        margin_mm=0,
        pen_width_mm=reference.stroke_width_mm,
        curve_fit_tolerance_mm=0.16,
    )
    lines = [rdp(path, 0.08) for path in paths]
    lines = optimize_event_order(lines, two_opt_window=22, maximum_passes=3)
    geometry = Geometry(0.25, 0.0, 0.0, reference.width_mm, reference.height_mm)
    commands, curves = _safe_commands(lines, options, geometry, 0.16)
    rendered = _render(lines, commands, source.shape, geometry, reference.stroke_width_mm)
    metrics = _metrics(source, rendered, geometry.scale)
    face = _face_mask(source)
    face_recall = float((rendered & source & face).sum()) / max(1, int((source & face).sum()))
    drawing_length = 0.0
    travel_length = 0.0
    cursor = (0.0, 0.0)
    for line, path_commands in zip(lines, commands, strict=True):
        sampled = sample_commands(line[0], path_commands, 0.08)
        drawing_length += polyline_length(sampled)
        travel_length += math.dist(cursor, line[0])
        cursor = path_commands[-1].end if path_commands else line[-1]
    pen_lifts = max(0, len(lines) - 1)
    estimated = drawing_length / 35.0 + travel_length / 90.0 + pen_lifts * 0.35
    quality_score = (
        0.25 * float(metrics["ink_recall"])
        + 0.30 * float(metrics["ink_precision"])
        + 0.25 * float(metrics["ink_iou"])
        + 0.20 * face_recall
    )
    stats = DrawingStats(
        stroke_count=len(lines),
        drawing_length_mm=round(drawing_length, 3),
        travel_length_mm=round(travel_length, 3),
        estimated_time_seconds=round(estimated, 2),
        average_path_length_mm=round(drawing_length / len(lines), 3),
        curve_segment_count=sum(
            isinstance(command, CubicCommand) for path in commands for command in path
        ),
        pen_lifts=pen_lifts,
        svg_command_count=sum(1 + len(path) for path in commands),
        face_weighted_recall=round(face_recall, 5),
        quality_score=round(quality_score, 5),
        **metrics,
    )
    preview, vector_preview, difference = _preview_images(source, rendered)
    return VectorResult(
        lines=lines,
        curves=curves,
        width_mm=reference.width_mm,
        height_mm=reference.height_mm,
        stats=stats,
        preview=preview,
        commands=commands,
        pen_width_mm=reference.stroke_width_mm,
        vector_preview=vector_preview,
        difference_overlay=difference,
    )


def summarize(drawing: SvgDrawing) -> dict[str, float | int]:
    drawing_length, travel_length = _lengths(drawing.paths)
    pen_lifts = max(0, len(drawing.paths) - 1)
    return {
        "paths": len(drawing.paths),
        "svg_commands": drawing.command_count,
        "drawing_length_mm": round(drawing_length, 1),
        "travel_length_mm": round(travel_length, 1),
        "pen_lifts": pen_lifts,
        "estimated_time_seconds": round(
            drawing_length / 35.0 + travel_length / 90.0 + pen_lifts * 0.35, 2
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Event Quality using real SVG candidates"
    )
    parser.add_argument("--fidelity", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("storage/svg-quality-benchmark"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fidelity = load_svg(args.fidelity)
    event = load_svg(args.event)
    if (fidelity.width_mm, fidelity.height_mm) != (event.width_mm, event.height_mm):
        raise ValueError("Benchmark SVG page sizes differ")
    source = _render_paths(fidelity)
    event_rendered = _render_paths(event)
    face = _face_mask(source)
    event_metrics = _metrics(source, event_rendered, 0.25)
    event_face_recall = float((event_rendered & source & face).sum()) / max(
        1, int((source & face).sum())
    )
    hybrid_paths = select_hybrid(fidelity, event, source, face)
    hybrid = build_result(hybrid_paths, fidelity, source)
    write_fidelity_svg(hybrid, args.output / "drawing-event-quality.svg")
    _, event_preview, event_difference = _preview_images(source, event_rendered)
    Image.fromarray(np.where(source, 0, 255).astype(np.uint8)).save(
        args.output / "fidelity-reference.png"
    )
    Image.fromarray(event_preview).save(args.output / "event-speed-preview.png")
    Image.fromarray(event_difference).save(args.output / "event-speed-difference.png")
    Image.fromarray(hybrid.vector_preview).save(args.output / "event-quality-preview.png")
    Image.fromarray(hybrid.difference_overlay).save(args.output / "event-quality-difference.png")
    fidelity_summary = summarize(fidelity)
    event_summary = summarize(event)
    fidelity_time = float(fidelity_summary["estimated_time_seconds"])
    report = {
        "fidelity": fidelity_summary,
        "old_event": {
            **event_summary,
            **event_metrics,
            "face_weighted_recall": round(event_face_recall, 5),
        },
        "event_quality_replay": hybrid.stats.model_dump(),
        "speedup_vs_fidelity": round(
            fidelity_time / max(hybrid.stats.estimated_time_seconds, 1e-9), 3
        ),
        "note": (
            "Replay selects real paths from the provided Fidelity SVG because the original "
            "photo/confidence map was not provided. Production Event Quality selects the "
            "equivalent annotated candidates before SVG export."
        ),
    }
    (args.output / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
