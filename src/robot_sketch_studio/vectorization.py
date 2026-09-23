from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from skimage.filters import apply_hysteresis_threshold
from skimage.morphology import binary_closing, disk, skeletonize

from robot_sketch_studio import __version__
from robot_sketch_studio.models import DrawingStats, ProcessingOptions

Pixel = tuple[int, int]
Point = tuple[float, float]
Polyline = list[Point]
CubicBezier = tuple[Point, Point, Point, Point]

NEIGHBORS_8 = tuple((dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if not (dy == 0 and dx == 0))


def _edge(a: Pixel, b: Pixel) -> tuple[Pixel, Pixel]:
    return (a, b) if a <= b else (b, a)


def build_graph(skeleton: np.ndarray) -> dict[Pixel, list[Pixel]]:
    pixels = {tuple(point) for point in np.argwhere(skeleton).tolist()}
    graph: dict[Pixel, list[Pixel]] = {}
    for y, x in pixels:
        neighbors: list[Pixel] = []
        for dy, dx in NEIGHBORS_8:
            candidate = (y + dy, x + dx)
            if candidate not in pixels:
                continue
            # Do not add a diagonal shortcut alongside an orthogonal stroke.
            if dy and dx and ((y, x + dx) in pixels or (y + dy, x) in pixels):
                continue
            neighbors.append(candidate)
        graph[(y, x)] = neighbors
    return graph


def trace_graph(graph: dict[Pixel, list[Pixel]]) -> list[list[Pixel]]:
    """Trace edges into branches delimited by endpoints and junctions."""
    visited: set[tuple[Pixel, Pixel]] = set()
    paths: list[list[Pixel]] = []

    def walk(start: Pixel, first: Pixel) -> list[Pixel]:
        path = [start, first]
        visited.add(_edge(start, first))
        previous, current = start, first
        while len(graph[current]) == 2:
            candidates = [node for node in graph[current] if node != previous]
            if not candidates:
                break
            following = candidates[0]
            edge = _edge(current, following)
            if edge in visited:
                break
            visited.add(edge)
            path.append(following)
            previous, current = current, following
        return path

    for start in sorted(graph):
        if len(graph[start]) == 2:
            continue
        for neighbor in sorted(graph[start]):
            if _edge(start, neighbor) not in visited:
                paths.append(walk(start, neighbor))
    for start in sorted(graph):
        for neighbor in sorted(graph[start]):
            if _edge(start, neighbor) not in visited:
                paths.append(walk(start, neighbor))
    return paths


def trace_graph_continuous(graph: dict[Pixel, list[Pixel]]) -> list[list[Pixel]]:
    """Trace every undirected edge exactly once, continuing straight at junctions."""
    visited: set[tuple[Pixel, Pixel]] = set()
    paths: list[list[Pixel]] = []

    def turn_cost(previous: Pixel, current: Pixel, following: Pixel) -> float:
        incoming = (current[0] - previous[0], current[1] - previous[1])
        outgoing = (following[0] - current[0], following[1] - current[1])
        denominator = math.hypot(*incoming) * math.hypot(*outgoing)
        if denominator == 0:
            return math.pi
        cosine = max(-1.0, min(1.0, np.dot(incoming, outgoing) / denominator))
        return math.acos(float(cosine))

    def walk(start: Pixel, first: Pixel) -> list[Pixel]:
        path = [start, first]
        visited.add(_edge(start, first))
        previous, current = start, first
        while True:
            candidates = [
                node
                for node in graph[current]
                if node != previous and _edge(current, node) not in visited
            ]
            if not candidates:
                break
            following = min(
                candidates,
                key=lambda node: (turn_cost(previous, current, node), node),
            )
            visited.add(_edge(current, following))
            path.append(following)
            previous, current = current, following
        return path

    # Starting at real endpoints makes the dominant contours win at crossings.
    starts = sorted(graph, key=lambda point: (len(graph[point]) != 1, point))
    for start in starts:
        for neighbor in sorted(graph[start]):
            if _edge(start, neighbor) not in visited:
                paths.append(walk(start, neighbor))
    return paths


def polyline_length(points: list[tuple[float, float]] | list[Pixel]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def rdp(points: list[Point], epsilon: float) -> list[Point]:
    if len(points) < 3 or epsilon <= 0:
        return points[:]
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        first, last = pending.pop()
        start = np.asarray(points[first], dtype=float)
        end = np.asarray(points[last], dtype=float)
        segment = end - start
        denominator = float(np.dot(segment, segment))
        maximum, selected = -1.0, -1
        for position in range(first + 1, last):
            candidate = np.asarray(points[position], dtype=float)
            if denominator == 0:
                distance = float(np.linalg.norm(candidate - start))
            else:
                projection = np.clip(float(np.dot(candidate - start, segment)) / denominator, 0, 1)
                distance = float(np.linalg.norm(candidate - (start + projection * segment)))
            if distance > maximum:
                maximum, selected = distance, position
        if maximum > epsilon and selected > first:
            keep.add(selected)
            pending.append((first, selected))
            pending.append((selected, last))
    return [points[index] for index in sorted(keep)]


def optimize_stroke_order(lines: list[Polyline], origin: Point = (0.0, 0.0)) -> list[Polyline]:
    remaining = [line[:] for line in lines if len(line) >= 2]
    ordered: list[Polyline] = []
    cursor = origin
    while remaining:
        _, best_index, reverse = min(
            (
                (math.dist(cursor, line[0]), index, False)
                if math.dist(cursor, line[0]) <= math.dist(cursor, line[-1])
                else (math.dist(cursor, line[-1]), index, True)
            )
            for index, line in enumerate(remaining)
        )
        selected = remaining.pop(best_index)
        if reverse:
            selected.reverse()
        ordered.append(selected)
        cursor = selected[-1]
    return ordered


def _angle_degrees(first: tuple[float, float], second: tuple[float, float]) -> float:
    denominator = math.hypot(*first) * math.hypot(*second)
    if denominator <= 1e-9:
        return 180.0
    cosine = max(-1.0, min(1.0, float(np.dot(first, second)) / denominator))
    return math.degrees(math.acos(cosine))


def _gap_has_support(
    first: Pixel,
    second: Pixel,
    confidence: np.ndarray,
    low_threshold: float,
    free_gap_px: float,
) -> bool:
    distance = math.dist(first, second)
    if distance <= max(2.0, free_gap_px):
        return True
    samples = max(3, int(math.ceil(distance)) + 1)
    yy = np.rint(np.linspace(first[0], second[0], samples)).astype(int)
    xx = np.rint(np.linspace(first[1], second[1], samples)).astype(int)
    values = confidence[yy, xx]
    # Refuse a shortcut through a genuinely empty region, while allowing weak
    # model responses to bridge a broken semantic contour.
    return float(np.mean(values >= low_threshold * 0.35)) >= 0.25


def _can_join(
    first: list[Pixel],
    second: list[Pixel],
    confidence: np.ndarray,
    maximum_distance: float,
    maximum_angle: float,
    low_threshold: float,
    free_gap_px: float,
) -> tuple[bool, float]:
    distance = math.dist(first[-1], second[0])
    if distance <= 0 or distance > maximum_distance:
        return False, math.inf
    first_index = max(0, len(first) - 4)
    second_index = min(len(second) - 1, 3)
    incoming = (
        first[-1][0] - first[first_index][0],
        first[-1][1] - first[first_index][1],
    )
    outgoing = (
        second[second_index][0] - second[0][0],
        second[second_index][1] - second[0][1],
    )
    gap = (
        second[0][0] - first[-1][0],
        second[0][1] - first[-1][1],
    )
    turn = _angle_degrees(incoming, outgoing)
    if turn > maximum_angle:
        return False, math.inf
    if distance > 1.5 and (
        _angle_degrees(incoming, gap) > maximum_angle * 1.5
        or _angle_degrees(gap, outgoing) > maximum_angle * 1.5
    ):
        return False, math.inf
    if not _gap_has_support(first[-1], second[0], confidence, low_threshold, free_gap_px):
        return False, math.inf
    return True, distance + turn / max(maximum_angle, 1.0)


def merge_close_paths(
    paths: list[list[Pixel]],
    confidence: np.ndarray,
    maximum_distance: float,
    maximum_angle: float,
    low_threshold: float,
    free_gap_px: float,
) -> list[list[Pixel]]:
    if maximum_distance <= 0 or len(paths) < 2:
        return paths
    cell_size = max(1.0, maximum_distance)
    cells: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for index, path in enumerate(paths):
        if len(path) < 2:
            continue
        for end in (0, -1):
            y, x = path[end]
            cells[(int(y // cell_size), int(x // cell_size))].append((index, end))

    unused = set(range(len(paths)))
    merged: list[list[Pixel]] = []
    seeds = sorted(unused, key=lambda index: polyline_length(paths[index]), reverse=True)
    for seed in seeds:
        if seed not in unused:
            continue
        unused.remove(seed)
        current = paths[seed][:]
        while True:
            best: tuple[float, int, bool, bool] | None = None
            for reverse_current in (False, True):
                oriented = list(reversed(current)) if reverse_current else current
                y, x = oriented[-1]
                cy, cx = int(y // cell_size), int(x // cell_size)
                for cell_y in range(cy - 1, cy + 2):
                    for cell_x in range(cx - 1, cx + 2):
                        for candidate_index, candidate_end in cells.get((cell_y, cell_x), []):
                            if candidate_index not in unused:
                                continue
                            candidate = paths[candidate_index]
                            reverse_candidate = candidate_end == -1
                            target = list(reversed(candidate)) if reverse_candidate else candidate
                            allowed, score = _can_join(
                                oriented,
                                target,
                                confidence,
                                maximum_distance,
                                maximum_angle,
                                low_threshold,
                                free_gap_px,
                            )
                            if allowed and (best is None or score < best[0]):
                                best = (
                                    score,
                                    candidate_index,
                                    reverse_current,
                                    reverse_candidate,
                                )
            if best is None:
                break
            _, candidate_index, reverse_current, reverse_candidate = best
            if reverse_current:
                current.reverse()
            target = paths[candidate_index]
            if reverse_candidate:
                target = list(reversed(target))
            current.extend(target)
            unused.remove(candidate_index)
        merged.append(current)
    return merged


def fit_cubic_beziers(points: Polyline) -> list[CubicBezier]:
    """Interpolate a simplified path with smooth Catmull-Rom cubic segments."""
    if len(points) < 2:
        return []
    curves: list[CubicBezier] = []
    for index in range(len(points) - 1):
        previous = points[max(0, index - 1)]
        start = points[index]
        end = points[index + 1]
        following = points[min(len(points) - 1, index + 2)]
        control_1 = (
            start[0] + (end[0] - previous[0]) / 6.0,
            start[1] + (end[1] - previous[1]) / 6.0,
        )
        control_2 = (
            end[0] - (following[0] - start[0]) / 6.0,
            end[1] - (following[1] - start[1]) / 6.0,
        )
        curves.append((start, control_1, control_2, end))
    return curves


@dataclass(slots=True)
class VectorResult:
    lines: list[Polyline]
    curves: list[list[CubicBezier]]
    width_mm: float
    height_mm: float
    stats: DrawingStats
    preview: np.ndarray


def _as_confidence(sketch: np.ndarray) -> np.ndarray:
    if sketch.ndim != 2:
        raise ValueError("Vectorization expects a grayscale confidence map")
    if np.issubdtype(sketch.dtype, np.floating):
        array = sketch.astype(np.float32)
        if float(array.max(initial=0.0)) > 1.0:
            array /= 255.0
        return np.clip(array, 0.0, 1.0)
    return np.clip(1.0 - sketch.astype(np.float32) / 255.0, 0.0, 1.0)


def vectorize(sketch: np.ndarray, options: ProcessingOptions) -> VectorResult:
    confidence = _as_confidence(sketch)
    height_px, width_px = confidence.shape
    page_width, page_height = options.page_dimensions
    available_width = page_width - 2 * options.margin_mm
    available_height = page_height - 2 * options.margin_mm
    scale = min(
        available_width / max(width_px - 1, 1),
        available_height / max(height_px - 1, 1),
    )
    offset_x = options.margin_mm + (available_width - (width_px - 1) * scale) / 2
    offset_y = options.margin_mm + (available_height - (height_px - 1) * scale) / 2

    feature_px = options.minimum_feature_size_mm / max(scale, 1e-9)
    sigma = min(1.5, max(0.35, feature_px * 0.18))
    softened = cv2.GaussianBlur(confidence, (0, 0), sigmaX=sigma, sigmaY=sigma)
    high_threshold = float(np.clip(1.0 - options.threshold / 255.0, 0.12, 0.72))
    low_threshold = high_threshold * (0.46 + (100 - options.detail) * 0.0015)
    ink = apply_hysteresis_threshold(softened, low_threshold, high_threshold)
    minimum_pixels = max(2, int(math.ceil(feature_px)))
    component_count, labels, component_stats, _ = cv2.connectedComponentsWithStats(
        ink.astype(np.uint8), 8
    )
    clean = np.zeros_like(ink, dtype=bool)
    for component in range(1, component_count):
        if component_stats[component, cv2.CC_STAT_AREA] >= minimum_pixels:
            clean[labels == component] = True
    ink = clean
    close_radius = min(4, max(0, int(round(feature_px * 0.3))))
    if close_radius:
        ink = binary_closing(ink, disk(close_radius))
    skeleton = skeletonize(ink)

    pixel_paths = trace_graph_continuous(build_graph(skeleton))
    minimum_length_px = options.effective_minimum_path_length_mm / max(scale, 1e-9)
    pixel_paths = [path for path in pixel_paths if polyline_length(path) >= minimum_length_px]
    pixel_paths = merge_close_paths(
        pixel_paths,
        softened,
        options.join_distance_mm / max(scale, 1e-9),
        options.maximum_join_angle_deg,
        low_threshold,
        max(1.0, feature_px),
    )
    pixel_paths = [path for path in pixel_paths if polyline_length(path) >= minimum_length_px]

    def importance(path: list[Pixel]) -> float:
        values = [softened[y, x] for y, x in path]
        return polyline_length(path) * (0.5 + float(np.mean(values)))

    pixel_paths.sort(key=importance, reverse=True)
    pixel_paths = pixel_paths[: options.target_paths]

    lines: list[Polyline] = []
    for path in pixel_paths:
        raw = [(offset_x + x * scale, offset_y + y * scale) for y, x in path]
        simplified = rdp(raw, options.effective_curve_tolerance_mm)
        if len(simplified) >= 2:
            lines.append(simplified)
    lines = optimize_stroke_order(lines, (options.margin_mm, options.margin_mm))
    curves = [fit_cubic_beziers(line) for line in lines]

    drawing_length = sum(polyline_length(line) for line in lines)
    travel_length = 0.0
    cursor = (options.margin_mm, options.margin_mm)
    for line in lines:
        travel_length += math.dist(cursor, line[0])
        cursor = line[-1]
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
        curve_segment_count=sum(len(path) for path in curves),
    )
    preview = np.where(ink, 0, 255).astype(np.uint8)
    return VectorResult(lines, curves, page_width, page_height, stats, preview)


def _number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def write_svg(result: VectorResult, options: ProcessingOptions, destination: Path) -> None:
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
    ET.SubElement(root, "{http://www.w3.org/2000/svg}title").text = "Robot drawing trajectory"
    group = ET.SubElement(
        root,
        "{http://www.w3.org/2000/svg}g",
        {
            "fill": "none",
            "stroke": "#111111",
            "stroke-width": _number(options.stroke_width_mm),
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
        },
    )
    for index, path_curves in enumerate(result.curves):
        if not path_curves:
            continue
        commands = [f"M {_number(path_curves[0][0][0])} {_number(path_curves[0][0][1])}"]
        for _, control_1, control_2, end in path_curves:
            commands.append(
                "C "
                f"{_number(control_1[0])} {_number(control_1[1])} "
                f"{_number(control_2[0])} {_number(control_2[1])} "
                f"{_number(end[0])} {_number(end[1])}"
            )
        ET.SubElement(
            group,
            "{http://www.w3.org/2000/svg}path",
            {"id": f"stroke-{index + 1}", "d": " ".join(commands), "fill": "none"},
        )
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def write_trajectory(result: VectorResult, options: ProcessingOptions, destination: Path) -> None:
    strokes = []
    for index, (line, path_curves) in enumerate(zip(result.lines, result.curves, strict=True)):
        strokes.append(
            {
                "id": index + 1,
                "points": [{"x": round(x, 3), "y": round(y, 3)} for x, y in line],
                "beziers": [
                    {
                        "start": {"x": round(curve[0][0], 3), "y": round(curve[0][1], 3)},
                        "control1": {"x": round(curve[1][0], 3), "y": round(curve[1][1], 3)},
                        "control2": {"x": round(curve[2][0], 3), "y": round(curve[2][1], 3)},
                        "end": {"x": round(curve[3][0], 3), "y": round(curve[3][1], 3)},
                    }
                    for curve in path_curves
                ],
            }
        )
    payload = {
        "schema_version": "1.1",
        "generator": f"Robot Sketch Studio v{__version__}",
        "author": "maggogerka",
        "units": "mm",
        "page": {
            "width": result.width_mm,
            "height": result.height_mm,
            "margin": options.margin_mm,
        },
        "stats": result.stats.model_dump(),
        "strokes": strokes,
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
