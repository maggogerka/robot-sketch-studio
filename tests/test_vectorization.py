from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from robot_sketch_studio.models import PaperPreset, ProcessingOptions
from robot_sketch_studio.vectorization import (
    _edge,
    build_graph,
    optimize_stroke_order,
    polyline_length,
    rdp,
    trace_graph,
    vectorize,
    write_svg,
    write_trajectory,
)


def graph_edges(graph):
    return {_edge(node, neighbor) for node, neighbors in graph.items() for neighbor in neighbors}


def path_edges(paths):
    return [_edge(a, b) for path in paths for a, b in zip(path, path[1:], strict=False)]


def assert_exact_edge_coverage(image: np.ndarray) -> list[list[tuple[int, int]]]:
    graph = build_graph(image)
    paths = trace_graph(graph)
    traced = path_edges(paths)
    assert set(traced) == graph_edges(graph)
    assert len(traced) == len(set(traced))
    return paths


def test_traces_straight_line_without_duplicate_edges():
    skeleton = np.zeros((9, 9), dtype=bool)
    skeleton[4, 1:8] = True
    paths = assert_exact_edge_coverage(skeleton)
    assert len(paths) == 1
    assert len(paths[0]) == 7


def test_traces_y_junction_without_duplicate_edges():
    skeleton = np.zeros((11, 11), dtype=bool)
    for index in range(4):
        skeleton[5 - index, 5 - index] = True
        skeleton[5 - index, 5 + index] = True
    skeleton[5:10, 5] = True
    paths = assert_exact_edge_coverage(skeleton)
    assert len(paths) >= 3


def test_traces_closed_loop_without_duplicate_edges():
    skeleton = np.zeros((11, 11), dtype=bool)
    ring = [
        (5, 2),
        (4, 3),
        (3, 4),
        (2, 5),
        (3, 6),
        (4, 7),
        (5, 8),
        (6, 7),
        (7, 6),
        (8, 5),
        (7, 4),
        (6, 3),
    ]
    for point in ring:
        skeleton[point] = True
    paths = assert_exact_edge_coverage(skeleton)
    assert any(path[0] == path[-1] for path in paths)


def test_rdp_simplifies_collinear_points():
    points = [(float(x), 5.0 + math.sin(x) * 0.01) for x in range(30)]
    simplified = rdp(points, 0.1)
    assert simplified == [points[0], points[-1]]


def test_vectorize_removes_short_component_and_keeps_coordinates_inside_page(tmp_path):
    sketch = np.full((100, 200), 255, dtype=np.uint8)
    sketch[50, 10:190] = 0
    sketch[5, 5:8] = 0
    options = ProcessingOptions(
        paper=PaperPreset.CUSTOM,
        page_width_mm=120,
        page_height_mm=100,
        margin_mm=10,
        min_line_length_mm=5,
        smoothing=0.2,
    )
    result = vectorize(sketch, options)
    assert result.stats.stroke_count == 1
    assert result.lines
    for line in result.lines:
        for x, y in line:
            assert 10 <= x <= 110
            assert 10 <= y <= 90

    svg_path = tmp_path / "drawing.svg"
    json_path = tmp_path / "trajectory.json"
    write_svg(result, options, svg_path)
    write_trajectory(result, options, json_path)
    root = ET.parse(svg_path).getroot()
    assert root.attrib["viewBox"] == "0 0 120 100"
    paths = [element for element in root.iter() if element.tag.endswith("}path")]
    assert paths and all(element.attrib.get("fill") == "none" for element in paths)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["units"] == "mm"
    assert len(payload["strokes"]) == result.stats.stroke_count


def test_vectorization_preserves_aspect_ratio():
    sketch = np.full((80, 160), 255, dtype=np.uint8)
    sketch[10, 20:141] = 0
    sketch[69, 20:141] = 0
    sketch[10:70, 20] = 0
    sketch[10:70, 140] = 0
    options = ProcessingOptions(min_line_length_mm=0, smoothing=0)
    result = vectorize(sketch, options)
    points = [point for line in result.lines for point in line]
    width = max(x for x, _ in points) - min(x for x, _ in points)
    height = max(y for _, y in points) - min(y for _, y in points)
    assert width / height == pytest.approx(120 / 59, rel=0.04)


def test_nearest_neighbor_optimization_reduces_travel():
    lines = [[(90.0, 0.0), (80.0, 0.0)], [(10.0, 0.0), (20.0, 0.0)], [(50.0, 0.0), (60.0, 0.0)]]

    def travel(sequence):
        cursor = (0.0, 0.0)
        total = 0.0
        for line in sequence:
            total += math.dist(cursor, line[0])
            cursor = line[-1]
        return total

    optimized = optimize_stroke_order(lines)
    assert travel(optimized) < travel(lines)
    assert sum(polyline_length(line) for line in optimized) == sum(
        polyline_length(line) for line in lines
    )
