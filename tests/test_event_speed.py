from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pytest

from robot_sketch_studio.event_speed import optimize_event_order
from robot_sketch_studio.models import (
    DrawingPreset,
    EventQualityLevel,
    EventSpeedLevel,
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


def speed_options(**overrides) -> ProcessingOptions:
    values = {
        "paper": PaperPreset.CUSTOM,
        "page_width_mm": 120,
        "page_height_mm": 100,
        "margin_mm": 5,
        "vectorization_mode": VectorizationMode.EVENT_SPEED,
        "event_speed_level": EventSpeedLevel.EVENT,
        "pen_width_mm": 0.5,
        "minimum_path_length_mm": 0.35,
        "minimum_feature_size_mm": 0.05,
        "curve_fit_tolerance_mm": 0.25,
        "join_distance_mm": 0.65,
        "maximum_join_angle_deg": 22,
        "drawing_speed_mm_s": 40,
        "travel_speed_mm_s": 100,
        "pen_lift_delay_s": 0.4,
    }
    values.update(overrides)
    return ProcessingOptions(**values)


def many_marks() -> np.ndarray:
    image = np.zeros((420, 420), dtype=np.float32)
    for row in range(20):
        for column in range(20):
            x = 7 + column * 20
            y = 8 + row * 20
            cv2.line(image, (x, y), (x + 8, y + (row + column) % 2), 0.72, 1)
    return image


def travel(lines, origin=(0.0, 0.0)) -> float:
    cursor = origin
    total = 0.0
    for line in lines:
        total += math.dist(cursor, line[0])
        cursor = line[-1]
    return total


def test_fast_portrait_legacy_defaults_and_level_migration():
    preset = ProcessingOptions(drawing_preset=DrawingPreset.FAST_PORTRAIT)
    assert preset.vectorization_mode == VectorizationMode.EVENT_SPEED
    assert preset.event_speed_level == EventSpeedLevel.EVENT
    assert preset.fill_strategy == FillStrategy.NONE
    assert preset.effective_event_quality_level == EventQualityLevel.BALANCED
    assert (
        speed_options(event_speed_level=EventSpeedLevel.EXPRESS).effective_event_quality_level
        == EventQualityLevel.QUICK
    )
    assert (
        speed_options(event_speed_level=EventSpeedLevel.FAST_DETAILED).effective_event_quality_level
        == EventQualityLevel.DETAILED
    )

    current = ProcessingOptions(drawing_preset=DrawingPreset.EVENT_QUALITY)
    assert current.vectorization_mode == VectorizationMode.EVENT_QUALITY
    assert current.event_quality_level == EventQualityLevel.BALANCED
    assert current.fill_strategy == FillStrategy.ADAPTIVE_SPARSE
    assert current.pen_width_mm == 0.8


def test_high_confidence_short_detail_survives_importance_selection():
    image = np.zeros((420, 420), dtype=np.float32)
    for row in range(20):
        for column in range(10):
            x = 6 + column * 13 if column < 5 else 285 + (column - 5) * 13
            y = 8 + row * 20
            cv2.line(image, (x, y), (x + 7, y), 0.66, 1)
    cv2.line(image, (207, 205), (213, 205), 1.0, 1)
    result = vectorize(
        image,
        speed_options(
            event_speed_level=EventSpeedLevel.EXPRESS,
            minimum_path_length_mm=4.0,
            join_distance_mm=0,
        ),
    )
    central_short = [
        line
        for line in result.lines
        if polyline_length(line) < 4.0 and any(52 <= x <= 68 and 42 <= y <= 58 for x, y in line)
    ]
    assert central_short


def test_event_order_is_deterministic_and_reduces_pen_up_travel():
    lines = [
        [(90.0, 70.0), (82.0, 70.0)],
        [(8.0, 12.0), (18.0, 12.0)],
        [(75.0, 15.0), (67.0, 18.0)],
        [(22.0, 75.0), (12.0, 78.0)],
        [(48.0, 42.0), (58.0, 42.0)],
    ]
    first = optimize_event_order(lines, maximum_passes=4)
    second = optimize_event_order(lines, maximum_passes=4)
    assert first == second
    assert travel(first) < travel(lines)
    assert sum(polyline_length(line) for line in first) == pytest.approx(
        sum(polyline_length(line) for line in lines)
    )


def test_event_budget_reduces_lifts_and_travel_without_joining_blank_gap():
    image = many_marks()
    quality = vectorize(
        image,
        speed_options(
            vectorization_mode=VectorizationMode.CENTERLINE,
            minimum_path_length_mm=0,
            minimum_feature_size_mm=0,
            join_distance_mm=0,
        ),
    )
    event = vectorize(image, speed_options(event_speed_level=EventSpeedLevel.EXPRESS))
    assert event.stats.pen_lifts < quality.stats.pen_lifts
    assert event.stats.travel_length_mm < quality.stats.travel_length_mm

    separated = np.zeros((120, 240), dtype=np.float32)
    cv2.line(separated, (20, 60), (90, 60), 1.0, 1)
    cv2.line(separated, (150, 60), (220, 60), 1.0, 1)
    result = vectorize(
        separated,
        speed_options(
            minimum_path_length_mm=0,
            join_distance_mm=20,
            event_speed_level=EventSpeedLevel.EXPRESS,
        ),
    )
    assert result.stats.stroke_count == 2


def test_event_svg_is_bounded_safe_and_deterministic(tmp_path):
    image = many_marks()
    options = speed_options(event_speed_level=EventSpeedLevel.EXPRESS)
    first = vectorize(image, options)
    second = vectorize(image, options)
    first_svg = tmp_path / "first.svg"
    second_svg = tmp_path / "second.svg"
    trajectory = tmp_path / "trajectory-speed.json"
    write_svg(first, options, first_svg)
    write_svg(second, options, second_svg)
    write_trajectory(first, options, trajectory)
    assert first_svg.read_bytes() == second_svg.read_bytes()

    root = ET.parse(first_svg).getroot()
    assert root.attrib["width"] == "120mm"
    assert root.attrib["height"] == "100mm"
    assert root.attrib["viewBox"] == "0 0 120 100"
    assert {element.tag.rsplit("}", 1)[-1] for element in root.iter()} == {"svg", "path"}
    paths = list(root)
    assert len(paths) == first.stats.stroke_count
    for path in paths:
        assert path.attrib["fill"] == "none"
        assert path.attrib["stroke-width"] == "0.5"
        assert "transform" not in path.attrib
        assert "Z" not in path.attrib["d"].upper()
        assert set(re.findall(r"[A-Za-z]", path.attrib["d"])) <= {"M", "L", "C"}
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path.attrib["d"])]
        assert all(math.isfinite(value) for value in numbers)
        coordinates = list(zip(numbers[::2], numbers[1::2], strict=True))
        assert all(5 <= x <= 115 and 5 <= y <= 95 for x, y in coordinates)

    payload = json.loads(trajectory.read_text(encoding="utf-8"))
    assert payload["mode"] == "event_speed"
    assert payload["event_speed_level"] == "express"
    assert payload["fill_strategy"] == "none"
    assert payload["path_count"] == first.stats.stroke_count
    assert first.stats.svg_command_count == sum(
        1 + len(path["commands"]) for path in payload["strokes"]
    )
    expected_time = (
        first.stats.drawing_length_mm / options.drawing_speed_mm_s
        + first.stats.travel_length_mm / options.travel_speed_mm_s
        + first.stats.pen_lifts * options.pen_lift_delay_s
    )
    assert first.stats.estimated_time_seconds == pytest.approx(expected_time, abs=0.02)


def test_existing_fidelity_regression_is_unchanged():
    image = np.zeros((241, 321), dtype=np.float32)
    cv2.line(image, (25, 35), (290, 35), 1.0, 3)
    cv2.line(image, (25, 95), (290, 95), 1.0, 24)
    cv2.circle(image, (160, 175), 28, 1.0, -1)
    cv2.line(image, (115, 150), (123, 150), 1.0, 2)
    cv2.line(image, (197, 150), (205, 150), 1.0, 2)
    options = ProcessingOptions(
        paper=PaperPreset.CUSTOM,
        page_width_mm=50,
        page_height_mm=40,
        margin_mm=5,
        vectorization_mode=VectorizationMode.PLOTTER_FIDELITY,
        pen_width_mm=0.5,
        minimum_path_length_mm=0.05,
        minimum_feature_size_mm=0.05,
        curve_fit_tolerance_mm=0.08,
        join_distance_mm=0,
        fill_strategy=FillStrategy.CONTOUR,
    )
    result = vectorize(image, options)
    assert result.stats.stroke_count == 21
    assert result.stats.drawing_length_mm == pytest.approx(519.313, abs=0.001)
    assert result.stats.travel_length_mm == pytest.approx(43.894, abs=0.001)
    assert result.stats.ink_iou == pytest.approx(0.89858, abs=0.00001)
    assert result.stats.pen_lifts == 20
