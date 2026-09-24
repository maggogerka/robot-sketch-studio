from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from skimage.filters import apply_hysteresis_threshold
from skimage.morphology import skeletonize

from robot_sketch_studio import __version__
from robot_sketch_studio.bezier_fit import (
    CubicCommand,
    LineCommand,
    PathCommand,
    fit_path,
    sample_commands,
)
from robot_sketch_studio.models import DrawingStats, FillStrategy, ProcessingOptions
from robot_sketch_studio.vectorization import (
    Pixel,
    Polyline,
    VectorResult,
    build_graph,
    merge_close_paths,
    optimize_stroke_order,
    polyline_length,
    rdp,
    trace_graph_continuous,
)


@dataclass(frozen=True, slots=True)
class Geometry:
    scale: float
    offset_x: float
    offset_y: float
    page_width: float
    page_height: float


def _confidence(sketch: np.ndarray) -> np.ndarray:
    if sketch.ndim != 2 or min(sketch.shape) < 2 or max(sketch.shape) > 2400:
        raise ValueError("Vectorization requires a grayscale image between 2 and 2400 pixels")
    if not np.isfinite(sketch).all():
        raise ValueError("Confidence map contains NaN or infinite values")
    if np.issubdtype(sketch.dtype, np.floating):
        result = sketch.astype(np.float32)
        if float(result.max(initial=0.0)) > 1.0:
            result /= 255.0
        return np.clip(result, 0.0, 1.0)
    return np.clip(1.0 - sketch.astype(np.float32) / 255.0, 0.0, 1.0)


def _geometry(shape: tuple[int, int], options: ProcessingOptions) -> Geometry:
    height, width = shape
    page_width, page_height = options.page_dimensions
    available_width = page_width - 2 * options.margin_mm
    available_height = page_height - 2 * options.margin_mm
    scale = min(
        available_width / max(width - 1, 1),
        available_height / max(height - 1, 1),
    )
    return Geometry(
        scale,
        options.margin_mm + (available_width - (width - 1) * scale) / 2,
        options.margin_mm + (available_height - (height - 1) * scale) / 2,
        page_width,
        page_height,
    )


def _plotting_resolution(
    confidence: np.ndarray, options: ProcessingOptions
) -> tuple[np.ndarray, Geometry]:
    geometry = _geometry(confidence.shape, options)
    desired_scale = options.pen_width_mm / 4.0
    factor = geometry.scale / desired_scale
    if 0.8 <= factor <= 1.2:
        return confidence, geometry
    factor = min(factor, 4.0, 1600 / max(confidence.shape))
    size = (
        max(2, int(round(confidence.shape[1] * factor))),
        max(2, int(round(confidence.shape[0] * factor))),
    )
    binary = float(((confidence > 0.04) & (confidence < 0.96)).mean()) < 0.025
    resized = cv2.resize(
        confidence, size, interpolation=cv2.INTER_NEAREST if binary else cv2.INTER_LINEAR
    )
    return resized, _geometry(resized.shape, options)


def _prepare_ink(
    confidence: np.ndarray,
    options: ProcessingOptions,
    geometry: Geometry,
    component_factor: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, float]:
    feature_px = options.minimum_feature_size_mm / max(geometry.scale, 1e-9)
    near_binary = float(((confidence > 0.04) & (confidence < 0.96)).mean()) < 0.025
    if near_binary:
        softened = confidence
    else:
        sigma = min(0.85, max(0.25, feature_px * 0.12))
        softened = cv2.GaussianBlur(confidence, (0, 0), sigmaX=sigma, sigmaY=sigma)
    high = float(np.clip(1.0 - options.threshold / 255.0, 0.12, 0.72))
    low = high * (0.46 + (100 - options.detail) * 0.0015)
    ink = apply_hysteresis_threshold(softened, low, high)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    minimum_area = max(2, int(math.ceil(feature_px * feature_px * 0.2 * component_factor)))
    accepted = np.zeros(count, dtype=bool)
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        x, y, width, height = stats[component, :4]
        region = labels[y : y + height, x : x + width] == component
        values = softened[y : y + height, x : x + width][region]
        strong_detail = (
            options.preserve_short_details and area >= 2 and float(values.max(initial=0.0)) >= 0.82
        )
        if area >= minimum_area or strong_detail:
            accepted[component] = True
    # Avoid closing that fuses independent facial marks. Supported endpoint
    # joining repairs weak breaks without introducing a line across white space.
    clean = accepted[labels]
    return clean, softened, low


def _path_confidence(path: list[Pixel], confidence: np.ndarray) -> float:
    return float(np.mean([confidence[int(y), int(x)] for y, x in path])) if path else 0.0


def _centerlines(
    ink: np.ndarray,
    confidence: np.ndarray,
    low_threshold: float,
    options: ProcessingOptions,
    geometry: Geometry,
    minimum_factor: float,
) -> list[list[Pixel]]:
    graph = build_graph(skeletonize(ink))
    paths = trace_graph_continuous(graph)
    for (y, x), neighbors in sorted(graph.items()):
        if not neighbors:
            direction = 0.2 if x < ink.shape[1] - 1 else -0.2
            paths.append([(y, x), (y, x + direction)])
    minimum_px = (
        options.effective_minimum_path_length_mm * minimum_factor / max(geometry.scale, 1e-9)
    )

    def keep(path: list[Pixel]) -> bool:
        length = polyline_length(path)
        return length >= minimum_px or (
            options.preserve_short_details
            and length > 0
            and _path_confidence(path, confidence) >= max(0.68, low_threshold)
        )

    paths = [path for path in paths if keep(path)]
    paths = merge_close_paths(
        paths,
        confidence,
        options.join_distance_mm / max(geometry.scale, 1e-9),
        options.maximum_join_angle_deg,
        low_threshold,
        max(1.0, options.minimum_feature_size_mm / max(geometry.scale, 1e-9)),
    )
    return [path for path in paths if keep(path)]


def _contour_fill(
    distance: np.ndarray,
    options: ProcessingOptions,
    geometry: Geometry,
    spacing_factor: float,
    budget: int,
    offset: tuple[int, int],
) -> list[list[Pixel]]:
    radius = options.pen_width_mm * 0.5 / max(geometry.scale, 1e-9)
    spacing = max(1.0, options.pen_width_mm * spacing_factor / geometry.scale)
    maximum = float(distance.max(initial=0.0))
    level = max(0.55, radius)
    paths: list[list[Pixel]] = []
    seen: set[tuple[int, int, int, int, int]] = set()
    while level <= maximum + 0.25 and len(paths) < budget:
        inset = (distance >= level).astype(np.uint8)
        contours, _ = cv2.findContours(inset, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        contours = sorted(contours, key=lambda contour: tuple(cv2.boundingRect(contour)))
        for contour in contours:
            if len(contour) < 2 or len(paths) >= budget:
                continue
            x, y, width, height = cv2.boundingRect(contour)
            signature = (x, y, width, height, len(contour))
            if signature in seen:
                continue
            seen.add(signature)
            path = [
                (
                    int(point[0][1]) + offset[0],
                    int(point[0][0]) + offset[1],
                )
                for point in contour
            ]
            if path[0] != path[-1]:
                path.append(path[0])
            if polyline_length(path) * geometry.scale >= 0.06:
                paths.append(path)
        level += spacing
    return paths


def _parallel_fill(
    distance: np.ndarray,
    options: ProcessingOptions,
    geometry: Geometry,
    spacing_factor: float,
    budget: int,
    offset: tuple[int, int],
) -> list[list[Pixel]]:
    radius = options.pen_width_mm * 0.5 / max(geometry.scale, 1e-9)
    spacing = max(1, int(round(options.pen_width_mm * spacing_factor / geometry.scale)))
    safe = distance >= max(0.55, radius)
    paths: list[list[Pixel]] = []
    reverse = False
    for y in range(0, safe.shape[0], spacing):
        changes = np.flatnonzero(np.diff(np.pad(safe[y].astype(np.int8), (1, 1))))
        for start, stop in changes.reshape(-1, 2):
            if stop <= start:
                continue
            path = [
                (y + offset[0], int(start) + offset[1]),
                (y + offset[0], int(stop - 1) + offset[1]),
            ]
            if reverse:
                path.reverse()
            paths.append(path)
            reverse = not reverse
            if len(paths) >= budget:
                return paths
    return paths


def _fill(
    ink: np.ndarray,
    options: ProcessingOptions,
    geometry: Geometry,
    spacing_factor: float,
    budget: int,
) -> list[list[Pixel]]:
    if budget <= 0 or options.fill_strategy == FillStrategy.NONE:
        return []
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    paths: list[list[Pixel]] = []
    components = sorted(
        range(1, count),
        key=lambda index: (
            int(stats[index, cv2.CC_STAT_TOP]),
            int(stats[index, cv2.CC_STAT_LEFT]),
        ),
    )
    for component in components:
        if len(paths) >= budget:
            break
        x, y, width, height = (int(value) for value in stats[component, :4])
        region = labels[y : y + height, x : x + width] == component
        padded = np.pad(region.astype(np.uint8), 1)
        distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)
        remaining = budget - len(paths)
        offset = (y - 1, x - 1)
        if options.fill_strategy == FillStrategy.PARALLEL:
            paths.extend(
                _parallel_fill(distance, options, geometry, spacing_factor, remaining, offset)
            )
        else:
            paths.extend(
                _contour_fill(distance, options, geometry, spacing_factor, remaining, offset)
            )
    return paths


def _path_geometry(
    pixel_paths: list[list[Pixel]],
    options: ProcessingOptions,
    geometry: Geometry,
    tolerance_factor: float,
) -> tuple[list[Polyline], list[list[PathCommand]], list[list[tuple]]]:
    lines: list[Polyline] = []
    simplify_tolerance = max(0.008, options.effective_curve_tolerance_mm * 0.35 * tolerance_factor)
    for path in pixel_paths:
        raw = [
            (geometry.offset_x + x * geometry.scale, geometry.offset_y + y * geometry.scale)
            for y, x in path
        ]
        simplified = rdp(raw, simplify_tolerance)
        if len(simplified) >= 2:
            lines.append(simplified)
    lines = optimize_stroke_order(lines, (options.margin_mm, options.margin_mm))
    all_commands: list[list[PathCommand]] = []
    all_curves: list[list[tuple]] = []
    tolerance = options.effective_curve_tolerance_mm * tolerance_factor
    bounds = (
        options.margin_mm,
        options.margin_mm,
        geometry.page_width - options.margin_mm,
        geometry.page_height - options.margin_mm,
    )
    for line in lines:
        commands: list[PathCommand] = []
        curves: list[tuple] = []
        cursor = line[0]
        # Pixel stair-steps commonly turn by 45°. Treat only stronger turns as
        # semantic corners, while the bounded fit still enforces the mm error.
        for command in fit_path(line, tolerance, corner_angle_deg=65.0):
            end = (
                float(np.clip(command.end[0], bounds[0], bounds[2])),
                float(np.clip(command.end[1], bounds[1], bounds[3])),
            )
            if isinstance(command, CubicCommand):
                control1 = (
                    float(np.clip(command.control1[0], bounds[0], bounds[2])),
                    float(np.clip(command.control1[1], bounds[1], bounds[3])),
                )
                control2 = (
                    float(np.clip(command.control2[0], bounds[0], bounds[2])),
                    float(np.clip(command.control2[1], bounds[1], bounds[3])),
                )
                safe: PathCommand = CubicCommand(control1, control2, end)
                curves.append((cursor, control1, control2, end))
            else:
                safe = LineCommand(end)
            commands.append(safe)
            cursor = end
        all_commands.append(commands)
        all_curves.append(curves)
    return lines, all_commands, all_curves


def _render(
    lines: list[Polyline],
    commands: list[list[PathCommand]],
    shape: tuple[int, int],
    geometry: Geometry,
    pen_width_mm: float,
) -> np.ndarray:
    rendered = np.zeros(shape, dtype=np.uint8)
    thickness = max(1, int(round(pen_width_mm / max(geometry.scale, 1e-9))))
    radius = max(0, thickness // 2)
    step = max(0.02, min(geometry.scale * 0.45, pen_width_mm * 0.2))
    for line, path_commands in zip(lines, commands, strict=True):
        sampled = sample_commands(line[0], path_commands, step)
        pixels = np.asarray(
            [
                (
                    int(round((x - geometry.offset_x) / geometry.scale)),
                    int(round((y - geometry.offset_y) / geometry.scale)),
                )
                for x, y in sampled
            ],
            dtype=np.int32,
        )
        if len(pixels) < 2:
            continue
        pixels[:, 0] = np.clip(pixels[:, 0], 0, shape[1] - 1)
        pixels[:, 1] = np.clip(pixels[:, 1], 0, shape[0] - 1)
        cv2.polylines(rendered, [pixels], False, 1, thickness, cv2.LINE_8)
        if radius:
            cv2.circle(rendered, tuple(pixels[0]), radius, 1, -1)
            cv2.circle(rendered, tuple(pixels[-1]), radius, 1, -1)
    return rendered.astype(bool)


def _metrics(source: np.ndarray, rendered: np.ndarray, scale: float) -> dict[str, float | int]:
    source_area = int(source.sum())
    rendered_area = int(rendered.sum())
    intersection = int(np.logical_and(source, rendered).sum())
    union = int(np.logical_or(source, rendered).sum())
    recall = intersection / source_area if source_area else 1.0
    precision = intersection / rendered_area if rendered_area else (1.0 if not source_area else 0.0)
    iou = intersection / union if union else 1.0
    if source_area and rendered_area:
        to_source = cv2.distanceTransform((~source).astype(np.uint8), cv2.DIST_L2, 3)
        to_rendered = cv2.distanceTransform((~rendered).astype(np.uint8), cv2.DIST_L2, 3)
        distance = (
            (float(to_source[rendered].mean()) + float(to_rendered[source].mean())) * 0.5 * scale
        )
    else:
        distance = 0.0
    return {
        "ink_recall": round(recall, 5),
        "ink_precision": round(precision, 5),
        "ink_iou": round(iou, 5),
        "coverage_difference": round((rendered_area - source_area) / max(source_area, 1), 5),
        "mean_line_distance_mm": round(distance, 5),
        "source_ink_area_px": source_area,
        "rendered_ink_area_px": rendered_area,
        "source_ink_area": source_area,
        "rendered_ink_area": rendered_area,
    }


def _preview_images(
    source: np.ndarray, rendered: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sketch = np.where(source, 0, 255).astype(np.uint8)
    vector = np.where(rendered, 0, 255).astype(np.uint8)
    overlay = np.full((*source.shape, 3), 255, dtype=np.uint8)
    overlay[np.logical_and(source, rendered)] = (36, 166, 76)
    overlay[np.logical_and(source, ~rendered)] = (220, 48, 48)
    overlay[np.logical_and(~source, rendered)] = (45, 92, 220)
    return sketch, vector, overlay


def _candidate(
    paths: list[list[Pixel]],
    source: np.ndarray,
    options: ProcessingOptions,
    geometry: Geometry,
    tolerance_factor: float,
) -> VectorResult:
    lines, commands, curves = _path_geometry(paths, options, geometry, tolerance_factor)
    rendered = _render(lines, commands, source.shape, geometry, options.pen_width_mm)
    metrics = _metrics(source, rendered, geometry.scale)
    drawing_length = 0.0
    travel_length = 0.0
    cursor = (options.margin_mm, options.margin_mm)
    for line, path_commands in zip(lines, commands, strict=True):
        sampled = sample_commands(line[0], path_commands, max(0.04, options.pen_width_mm * 0.15))
        drawing_length += polyline_length(sampled)
        travel_length += math.dist(cursor, line[0])
        cursor = path_commands[-1].end if path_commands else line[-1]
    estimated = (
        drawing_length / options.drawing_speed_mm_s
        + travel_length / options.travel_speed_mm_s
        + len(lines) * 0.12
    )
    stats = DrawingStats(
        stroke_count=len(lines),
        drawing_length_mm=round(drawing_length, 3),
        travel_length_mm=round(travel_length, 3),
        estimated_time_seconds=round(estimated, 2),
        average_path_length_mm=round(drawing_length / len(lines), 3) if lines else 0.0,
        curve_segment_count=sum(
            isinstance(command, CubicCommand) for path in commands for command in path
        ),
        pen_lifts=max(0, len(lines) - 1),
        **metrics,
    )
    preview, vector_preview, difference = _preview_images(source, rendered)
    return VectorResult(
        lines=lines,
        curves=curves,
        width_mm=geometry.page_width,
        height_mm=geometry.page_height,
        stats=stats,
        preview=preview,
        commands=commands,
        pen_width_mm=options.pen_width_mm,
        vector_preview=vector_preview,
        difference_overlay=difference,
    )


def vectorize_fidelity(sketch: np.ndarray, options: ProcessingOptions) -> VectorResult:
    confidence, geometry = _plotting_resolution(_confidence(sketch), options)
    source, softened, low_threshold = _prepare_ink(confidence, options, geometry)
    if not source.any():
        raise ValueError("No drawable ink remained after confidence-map cleanup")
    best: VectorResult | None = None
    protection_hit = False
    attempts = (
        (0.75, 1.0, 1.0, 1.0),
        (0.55, 0.65, 0.75, 0.5),
        (0.40, 0.35, 0.55, 0.2),
    )
    if options.fill_strategy == FillStrategy.NONE:
        attempts = attempts[:1]
    for spacing_factor, minimum_factor, tolerance_factor, component_factor in attempts:
        candidate_source = source
        candidate_confidence = softened
        candidate_low = low_threshold
        if component_factor < 1.0:
            candidate_source, candidate_confidence, candidate_low = _prepare_ink(
                confidence, options, geometry, component_factor
            )
        centerlines = _centerlines(
            candidate_source,
            candidate_confidence,
            candidate_low,
            options,
            geometry,
            minimum_factor,
        )
        if len(centerlines) > options.maximum_plotter_paths:
            centerlines = centerlines[: options.maximum_plotter_paths]
            protection_hit = True
        budget = options.maximum_plotter_paths - len(centerlines)
        fills = _fill(candidate_source, options, geometry, spacing_factor, budget)
        paths = centerlines + fills
        if len(paths) >= options.maximum_plotter_paths:
            protection_hit = True
        candidate = _candidate(paths, candidate_source, options, geometry, tolerance_factor)
        if best is None or (
            candidate.stats.ink_iou,
            candidate.stats.ink_recall,
            candidate.stats.ink_precision,
        ) > (
            best.stats.ink_iou,
            best.stats.ink_recall,
            best.stats.ink_precision,
        ):
            best = candidate
        if (
            candidate.stats.ink_recall >= options.ink_coverage_target
            and candidate.stats.ink_precision >= 0.85
            and candidate.stats.ink_iou >= 0.80
        ):
            best = candidate
            break
    if best is None:
        raise RuntimeError("Vectorization produced no candidate")
    if protection_hit:
        best.warnings.append(
            "maximum_plotter_paths protection limit was reached; some fill/detail "
            "trajectories could not be exported."
        )
    if (
        best.stats.ink_recall < options.ink_coverage_target
        or best.stats.ink_precision < 0.85
        or best.stats.ink_iou < 0.80
    ):
        best.warnings.append(
            "Requested raster fidelity was not fully reached after bounded refinement "
            f"(recall={best.stats.ink_recall:.3f}, precision="
            f"{best.stats.ink_precision:.3f}, IoU={best.stats.ink_iou:.3f})."
        )
    return best


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("SVG contains a non-finite coordinate")
    return f"{value:.3f}".rstrip("0").rstrip(".")


def write_fidelity_svg(result: VectorResult, destination: Path) -> None:
    if result.commands is None or result.pen_width_mm is None:
        raise ValueError("Fidelity SVG requires exact path commands and pen width")
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    root = ET.Element(
        "{http://www.w3.org/2000/svg}svg",
        {
            "width": f"{_number(result.width_mm)}mm",
            "height": f"{_number(result.height_mm)}mm",
            "viewBox": f"0 0 {_number(result.width_mm)} {_number(result.height_mm)}",
            "data-generator": f"Robot Sketch Studio v{__version__}",
            "data-author": "maggogerka",
        },
    )
    for index, (line, commands) in enumerate(zip(result.lines, result.commands, strict=True)):
        data = [f"M {_number(line[0][0])} {_number(line[0][1])}"]
        for command in commands:
            if isinstance(command, LineCommand):
                data.append(f"L {_number(command.end[0])} {_number(command.end[1])}")
            else:
                data.append(
                    "C "
                    f"{_number(command.control1[0])} {_number(command.control1[1])} "
                    f"{_number(command.control2[0])} {_number(command.control2[1])} "
                    f"{_number(command.end[0])} {_number(command.end[1])}"
                )
        ET.SubElement(
            root,
            "{http://www.w3.org/2000/svg}path",
            {
                "id": f"stroke-{index + 1}",
                "d": " ".join(data),
                "fill": "none",
                "stroke": "#111111",
                "stroke-width": _number(result.pen_width_mm),
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
            },
        )
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def _command_payload(command: PathCommand) -> dict[str, object]:
    if isinstance(command, LineCommand):
        return {
            "type": "L",
            "end": {"x": round(command.end[0], 3), "y": round(command.end[1], 3)},
        }
    return {
        "type": "C",
        "control1": {
            "x": round(command.control1[0], 3),
            "y": round(command.control1[1], 3),
        },
        "control2": {
            "x": round(command.control2[0], 3),
            "y": round(command.control2[1], 3),
        },
        "end": {"x": round(command.end[0], 3), "y": round(command.end[1], 3)},
    }


def write_fidelity_trajectory(
    result: VectorResult, options: ProcessingOptions, destination: Path
) -> None:
    if result.commands is None or result.pen_width_mm is None:
        raise ValueError("Fidelity trajectory requires exact path commands")
    strokes = [
        {
            "id": index + 1,
            "start": {"x": round(line[0][0], 3), "y": round(line[0][1], 3)},
            "commands": [_command_payload(command) for command in commands],
            "points": [{"x": round(x, 3), "y": round(y, 3)} for x, y in line],
        }
        for index, (line, commands) in enumerate(zip(result.lines, result.commands, strict=True))
    ]
    payload = {
        "schema_version": "1.2",
        "generator": f"Robot Sketch Studio v{__version__}",
        "author": "maggogerka",
        "units": "mm",
        "mode": options.vectorization_mode.value,
        "vectorization_mode": options.vectorization_mode.value,
        "pen_width_mm": result.pen_width_mm,
        "fill_strategy": options.fill_strategy.value,
        "path_count": len(strokes),
        "warnings": result.warnings,
        "metrics": {
            "ink_recall": result.stats.ink_recall,
            "ink_precision": result.stats.ink_precision,
            "ink_iou": result.stats.ink_iou,
            "coverage_difference": result.stats.coverage_difference,
            "mean_line_distance_mm": result.stats.mean_line_distance_mm,
            "source_ink_area_px": result.stats.source_ink_area_px,
            "rendered_ink_area_px": result.stats.rendered_ink_area_px,
            "source_ink_area": result.stats.source_ink_area,
            "rendered_ink_area": result.stats.rendered_ink_area,
        },
        "page": {
            "width": result.width_mm,
            "height": result.height_mm,
            "margin": options.margin_mm,
        },
        "stats": result.stats.model_dump(),
        "strokes": strokes,
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
