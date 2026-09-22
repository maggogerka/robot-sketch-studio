from __future__ import annotations

import inspect
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from skimage.morphology import remove_small_objects, skeletonize

from robot_sketch_studio.models import DrawingStats, ProcessingOptions

Pixel = tuple[int, int]
Point = tuple[float, float]
Polyline = list[Point]

NEIGHBORS_8 = tuple((dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if not (dy == 0 and dx == 0))


def _edge(a: Pixel, b: Pixel) -> tuple[Pixel, Pixel]:
    return (a, b) if a <= b else (b, a)


def build_graph(skeleton: np.ndarray) -> dict[Pixel, list[Pixel]]:
    pixels = {tuple(point) for point in np.argwhere(skeleton).tolist()}
    graph: dict[Pixel, list[Pixel]] = {}
    for y, x in pixels:
        graph[(y, x)] = [(y + dy, x + dx) for dy, dx in NEIGHBORS_8 if (y + dy, x + dx) in pixels]
    return graph


def trace_graph(graph: dict[Pixel, list[Pixel]]) -> list[list[Pixel]]:
    """Trace every undirected skeleton edge exactly once into maximal polylines."""
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

    # Endpoints and junctions delimit open branches.
    for start in sorted(graph):
        if len(graph[start]) == 2:
            continue
        for neighbor in sorted(graph[start]):
            if _edge(start, neighbor) not in visited:
                paths.append(walk(start, neighbor))

    # Every remaining edge belongs to a closed loop (or a dense 8-neighbor pocket).
    for start in sorted(graph):
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


@dataclass(slots=True)
class VectorResult:
    lines: list[Polyline]
    width_mm: float
    height_mm: float
    stats: DrawingStats


def vectorize(sketch: np.ndarray, options: ProcessingOptions) -> VectorResult:
    if sketch.ndim != 2:
        raise ValueError("Vectorization expects a grayscale sketch")
    height_px, width_px = sketch.shape
    page_width, page_height = options.page_dimensions
    available_width = page_width - 2 * options.margin_mm
    available_height = page_height - 2 * options.margin_mm
    scale = min(available_width / max(width_px - 1, 1), available_height / max(height_px - 1, 1))
    offset_x = options.margin_mm + (available_width - (width_px - 1) * scale) / 2
    offset_y = options.margin_mm + (available_height - (height_px - 1) * scale) / 2

    ink = sketch < 128
    minimum_pixels = max(2, int((options.min_line_length_mm / max(scale, 1e-9)) ** 2 / 5))
    if "max_size" in inspect.signature(remove_small_objects).parameters:
        cleaned = remove_small_objects(ink, max_size=minimum_pixels - 1)
    else:  # scikit-image 0.24/0.25 compatibility
        cleaned = remove_small_objects(ink, min_size=minimum_pixels)
    skeleton = skeletonize(cleaned)
    pixel_paths = trace_graph(build_graph(skeleton))
    min_length_px = options.min_line_length_mm / max(scale, 1e-9)
    pixel_paths = [path for path in pixel_paths if polyline_length(path) >= min_length_px]

    lines: list[Polyline] = []
    for path in pixel_paths:
        # Pixel tuples are y/x; output coordinates are x/y in millimetres.
        raw = [(offset_x + x * scale, offset_y + y * scale) for y, x in path]
        simplified = rdp(raw, options.smoothing)
        if len(simplified) >= 2:
            lines.append(simplified)
    lines = optimize_stroke_order(lines, (options.margin_mm, options.margin_mm))

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
    )
    return VectorResult(lines, page_width, page_height, stats)


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
            "data-generator": "Robot Sketch Studio v0.1.0",
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
    for index, line in enumerate(result.lines):
        commands = [f"M {_number(line[0][0])} {_number(line[0][1])}"]
        commands.extend(f"L {_number(x)} {_number(y)}" for x, y in line[1:])
        ET.SubElement(
            group,
            "{http://www.w3.org/2000/svg}path",
            {"id": f"stroke-{index + 1}", "d": " ".join(commands), "fill": "none"},
        )
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def write_trajectory(result: VectorResult, options: ProcessingOptions, destination: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "generator": "Robot Sketch Studio v0.1.0",
        "author": "maggogerka",
        "units": "mm",
        "page": {
            "width": result.width_mm,
            "height": result.height_mm,
            "margin": options.margin_mm,
        },
        "stats": result.stats.model_dump(),
        "strokes": [
            {
                "id": index + 1,
                "points": [{"x": round(x, 3), "y": round(y, 3)} for x, y in line],
            }
            for index, line in enumerate(result.lines)
        ],
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
