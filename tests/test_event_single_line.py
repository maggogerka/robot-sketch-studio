from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections import Counter

import cv2
import numpy as np

from robot_sketch_studio.event_single_line import (
    SingleLineFeature,
    collapse_parallel_paths,
    write_rotrics_line_test_svg,
)
from robot_sketch_studio.models import (
    DrawingPreset,
    ExportProfile,
    FillStrategy,
    PaperPreset,
    ProcessingOptions,
    VectorizationMode,
)
from robot_sketch_studio.vectorization import (
    build_graph,
    trace_graph_edge_disjoint,
    vectorize,
    write_svg,
    write_trajectory,
)


def single_options(**overrides) -> ProcessingOptions:
    values = {
        "vectorization_mode": VectorizationMode.EVENT_SINGLE_LINE,
        "export_profile": ExportProfile.ROTRICS_CENTERLINE,
        "paper": PaperPreset.ROTRICS_80X113,
        "margin_mm": 5,
        "pen_width_mm": 0.8,
        "fill_strategy": FillStrategy.NONE,
        "minimum_path_length_mm": 0.2,
        "minimum_feature_size_mm": 0.05,
        "curve_fit_tolerance_mm": 0.2,
        "join_distance_mm": 0.5,
        "maximum_join_angle_deg": 20,
        "drawing_speed_mm_s": 40,
        "travel_speed_mm_s": 100,
        "pen_lift_delay_s": 0.4,
    }
    values.update(overrides)
    return ProcessingOptions(**values)


def curved_line_map() -> np.ndarray:
    image = np.zeros((180, 140), dtype=np.float32)
    points = np.asarray([(18, 145), (25, 105), (45, 65), (82, 35), (120, 22)])
    cv2.polylines(image, [points], False, 0.96, 11, cv2.LINE_AA)
    return image


def test_single_line_preset_uses_final_physical_rotrics_profile():
    options = ProcessingOptions(drawing_preset=DrawingPreset.EVENT_SINGLE_LINE)
    assert options.vectorization_mode == VectorizationMode.EVENT_SINGLE_LINE
    assert options.export_profile == ExportProfile.ROTRICS_CENTERLINE
    assert options.paper == PaperPreset.ROTRICS_80X113
    assert options.page_dimensions == (80.0, 113.0)
    assert options.fill_strategy == FillStrategy.NONE
    assert options.pen_width_mm == 0.8


def portrait_map() -> np.ndarray:
    image = np.zeros((180, 140), dtype=np.float32)
    cv2.ellipse(image, (70, 68), (38, 51), 0, 0, 360, 0.94, 9)
    cv2.ellipse(image, (55, 64), (7, 3), 0, 0, 360, 1.0, 2)
    cv2.ellipse(image, (85, 64), (7, 3), 0, 0, 360, 1.0, 2)
    cv2.line(image, (70, 68), (67, 85), 0.95, 3)
    cv2.ellipse(image, (70, 95), (14, 5), 0, 0, 180, 1.0, 2)
    cv2.line(image, (45, 112), (31, 166), 0.82, 12)
    cv2.line(image, (95, 112), (109, 166), 0.82, 12)
    return image


def edge(first, second):
    return tuple(sorted((first, second)))


def test_thick_curve_creates_one_centerline_not_center_plus_outline():
    result = vectorize(curved_line_map(), single_options(join_distance_mm=0))
    assert result.stats.stroke_count == 1
    assert result.stats.redundant_path_count == 0
    assert result.stats.unique_centerline_coverage > 0.95


def test_each_skeleton_edge_is_visited_once_with_minimum_trails():
    skeleton = np.zeros((9, 9), dtype=bool)
    skeleton[4, 1:8] = True
    skeleton[1:8, 4] = True
    graph = build_graph(skeleton)
    trails = trace_graph_edge_disjoint(graph)
    expected = Counter(
        edge(node, neighbor)
        for node, neighbors in graph.items()
        for neighbor in neighbors
        if node < neighbor
    )
    visited = Counter(
        edge(first, second)
        for trail in trails
        for first, second in zip(trail, trail[1:], strict=False)
    )
    assert visited == expected
    assert len(trails) == sum(len(neighbors) % 2 for neighbors in graph.values()) // 2


def feature(line, component=1, importance=0.8, face=0.0):
    return SingleLineFeature(line, component, importance, face, importance)


def test_parallel_duplicates_are_removed_but_close_face_details_survive():
    first = feature([(10.0, 10.0), (45.0, 10.0)], importance=0.95)
    duplicate = feature([(10.0, 10.25), (45.0, 10.25)], importance=0.70)
    collapsed, stats = collapse_parallel_paths([duplicate, first], 0.8)
    assert len(collapsed) == 1
    assert collapsed[0].importance == 0.95
    assert stats.removed_path_count == 1
    assert stats.redundant_path_count == 0
    assert stats.parallel_overlap_ratio == 0
    assert stats.input_parallel_overlap_ratio > 0.4

    eye_lid = feature([(10.0, 20.0), (25.0, 20.0)], face=1.0)
    eye_detail = feature([(10.0, 20.35), (25.0, 20.35)], importance=0.76, face=1.0)
    preserved, face_stats = collapse_parallel_paths([eye_lid, eye_detail], 0.8)
    assert len(preserved) == 2
    assert face_stats.removed_path_count == 0
    assert face_stats.redundant_path_count == 0


def test_single_line_reduces_real_lifts_and_time_against_event_quality():
    image = portrait_map()
    single = vectorize(image, single_options())
    quality = vectorize(
        image,
        single_options(
            vectorization_mode=VectorizationMode.EVENT_QUALITY,
            export_profile=ExportProfile.STANDARD,
            fill_strategy=FillStrategy.ADAPTIVE_SPARSE,
        ),
    )
    assert single.stats.stroke_count < quality.stats.stroke_count
    assert single.stats.pen_lifts < quality.stats.pen_lifts
    assert single.stats.estimated_time_seconds < quality.stats.estimated_time_seconds


def test_rotrics_svg_is_80_by_113_deterministic_and_dexarm_safe(tmp_path):
    options = single_options()
    first = vectorize(portrait_map(), options)
    second = vectorize(portrait_map(), options)
    assert first.lines == second.lines
    assert first.stats == second.stats

    svg = tmp_path / "drawing-speed.svg"
    trajectory = tmp_path / "trajectory-speed.json"
    write_svg(first, options, svg)
    write_trajectory(first, options, trajectory)
    root = ET.parse(svg).getroot()
    assert root.attrib["width"] == "80mm"
    assert root.attrib["height"] == "113mm"
    assert root.attrib["viewBox"] == "0 0 80 113"
    assert {element.tag.rsplit("}", 1)[-1] for element in root.iter()} == {"svg", "path"}
    assert len(root) == first.stats.stroke_count
    for path in root:
        assert path.attrib["fill"] == "none"
        assert path.attrib["stroke-width"] == "0.8"
        assert "transform" not in path.attrib
        assert "Z" not in path.attrib["d"].upper()
        assert path.attrib["d"].upper().count("M") == 1
        assert set(re.findall(r"[A-Za-z]", path.attrib["d"])) <= {"M", "L", "C"}
    for line, commands in zip(first.lines, first.commands or [], strict=True):
        points = list(line)
        for command in commands:
            points.append(command.end)
            if hasattr(command, "control1"):
                points.extend((command.control1, command.control2))
        assert all(math.isfinite(value) for point in points for value in point)
        assert all(0 <= point[0] <= 80 and 0 <= point[1] <= 113 for point in points)

    text = trajectory.read_text(encoding="utf-8")
    assert '"schema_version": "1.5"' in text
    assert '"export_profile": "rotrics_centerline"' in text
    assert '"fill_strategy": "none"' in text


def test_rotrics_diagnostic_uses_selected_physical_pen_width(tmp_path):
    destination = tmp_path / "rotrics-line-test.svg"
    write_rotrics_line_test_svg(single_options(pen_width_mm=0.7), destination)
    root = ET.parse(destination).getroot()
    assert root.attrib["width"] == "80mm"
    assert root.attrib["height"] == "113mm"
    assert len(root) == 1
    assert root[0].attrib["stroke-width"] == "0.7"
    assert root[0].attrib["d"].count("M") == 1


def test_non_final_size_reports_physical_scaling_warning():
    result = vectorize(
        curved_line_map(),
        single_options(
            export_profile=ExportProfile.STANDARD,
            paper=PaperPreset.CUSTOM,
            page_width_mm=210,
            page_height_mm=297,
        ),
    )
    assert any(
        warning == "Масштабирование изменит физический интервал между траекториями. "
        "Генерируйте SVG сразу в конечном размере."
        for warning in result.warnings
    )
