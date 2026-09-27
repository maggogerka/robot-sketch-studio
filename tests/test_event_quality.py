from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pytest

from robot_sketch_studio.event_quality import detect_face_mask
from robot_sketch_studio.event_speed import vectorize_event_speed_legacy
from robot_sketch_studio.fidelity import (
    _confidence,
    _plotting_resolution,
    _prepare_ink,
    build_fidelity_candidate_set,
)
from robot_sketch_studio.models import (
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


def quality_options(**overrides) -> ProcessingOptions:
    values = {
        "paper": PaperPreset.CUSTOM,
        "page_width_mm": 94,
        "page_height_mm": 94,
        "margin_mm": 5,
        "vectorization_mode": VectorizationMode.EVENT_QUALITY,
        "event_quality_level": EventQualityLevel.BALANCED,
        "pen_width_mm": 0.8,
        "minimum_path_length_mm": 0.25,
        "minimum_feature_size_mm": 0.05,
        "curve_fit_tolerance_mm": 0.24,
        "join_distance_mm": 0.5,
        "maximum_join_angle_deg": 22,
        "fill_strategy": FillStrategy.ADAPTIVE_SPARSE,
        "drawing_speed_mm_s": 40,
        "travel_speed_mm_s": 100,
        "pen_lift_delay_s": 0.4,
        "detail": 55,
    }
    values.update(overrides)
    return ProcessingOptions(**values)


def dense_marks() -> np.ndarray:
    image = np.zeros((420, 420), dtype=np.float32)
    for row in range(20):
        for column in range(30):
            x = 3 + column * 14
            y = 7 + row * 20
            cv2.line(image, (x, y), (x + 6, y + (row + column) % 2), 0.88, 1)
    return image


def portrait_map() -> np.ndarray:
    image = np.zeros((180, 150), dtype=np.float32)
    cv2.ellipse(image, (75, 68), (39, 50), 0, 0, 360, 0.92, 8)
    cv2.ellipse(image, (75, 45), (38, 28), 0, 180, 360, 0.82, 14)
    cv2.ellipse(image, (60, 64), (7, 3), 0, 0, 360, 1.0, 2)
    cv2.ellipse(image, (90, 64), (7, 3), 0, 0, 360, 1.0, 2)
    cv2.line(image, (75, 68), (72, 85), 0.95, 2)
    cv2.ellipse(image, (75, 94), (14, 5), 0, 0, 180, 1.0, 2)
    cv2.line(image, (52, 108), (38, 157), 0.78, 14)
    cv2.line(image, (98, 108), (112, 157), 0.78, 14)
    cv2.rectangle(image, (42, 118), (108, 168), 0.68, -1)
    return image


def test_quality_levels_are_goals_and_respect_upper_limits():
    image = dense_marks()
    quick = vectorize(image, quality_options(event_quality_level=EventQualityLevel.QUICK))
    balanced = vectorize(image, quality_options(event_quality_level=EventQualityLevel.BALANCED))
    detailed = vectorize(image, quality_options(event_quality_level=EventQualityLevel.DETAILED))
    assert 300 <= quick.stats.stroke_count <= 450
    assert 450 <= balanced.stats.stroke_count <= 650
    assert balanced.stats.stroke_count <= detailed.stats.stroke_count <= 850
    fidelity = vectorize(
        image,
        quality_options(
            vectorization_mode=VectorizationMode.PLOTTER_FIDELITY,
            fill_strategy=FillStrategy.CONTOUR,
            maximum_plotter_paths=3000,
        ),
    )
    golden = json.loads(
        (Path(__file__).with_name("fixtures") / "event_quality_golden.json").read_text(
            encoding="utf-8"
        )
    )
    for name, result in {
        "quick": quick,
        "balanced": balanced,
        "detailed": detailed,
        "fidelity": fidelity,
    }.items():
        expected = golden[name]
        assert result.stats.stroke_count == expected["stroke_count"]
        assert result.stats.drawing_length_mm == pytest.approx(
            expected["drawing_length_mm"], abs=0.005
        )
        assert result.stats.travel_length_mm == pytest.approx(
            expected["travel_length_mm"], abs=0.005
        )
        assert result.stats.ink_recall == pytest.approx(expected["ink_recall"], abs=0.00001)
        assert result.stats.svg_command_count == expected["svg_command_count"]


def test_hybrid_improves_old_event_quality_and_is_faster_than_fidelity():
    image = portrait_map()
    base = {
        "paper": PaperPreset.CUSTOM,
        "page_width_mm": 90,
        "page_height_mm": 75,
        "margin_mm": 4,
        "pen_width_mm": 0.8,
        "minimum_path_length_mm": 0.25,
        "minimum_feature_size_mm": 0.05,
        "curve_fit_tolerance_mm": 0.22,
        "join_distance_mm": 0.6,
        "drawing_speed_mm_s": 40,
        "travel_speed_mm_s": 100,
        "pen_lift_delay_s": 0.4,
    }
    legacy_options = ProcessingOptions(
        **base,
        vectorization_mode=VectorizationMode.EVENT_SPEED,
        event_speed_level=EventSpeedLevel.EVENT,
        fill_strategy=FillStrategy.NONE,
    )
    quality = vectorize(
        image,
        ProcessingOptions(
            **base,
            vectorization_mode=VectorizationMode.EVENT_QUALITY,
            event_quality_level=EventQualityLevel.BALANCED,
            fill_strategy=FillStrategy.ADAPTIVE_SPARSE,
        ),
    )
    legacy = vectorize_event_speed_legacy(image, legacy_options)
    fidelity = vectorize(
        image,
        ProcessingOptions(
            **base,
            vectorization_mode=VectorizationMode.PLOTTER_FIDELITY,
            fill_strategy=FillStrategy.CONTOUR,
            maximum_plotter_paths=3000,
        ),
    )
    assert quality.stats.ink_recall >= legacy.stats.ink_recall + 0.25
    assert quality.stats.ink_iou >= legacy.stats.ink_iou + 0.20
    assert quality.stats.ink_precision >= 0.85
    assert fidelity.stats.estimated_time_seconds / quality.stats.estimated_time_seconds >= 1.7


def test_high_confidence_short_face_detail_is_protected():
    image = dense_marks()
    cv2.line(image, (207, 205), (211, 205), 1.0, 1)
    result = vectorize(
        image,
        quality_options(
            event_quality_level=EventQualityLevel.QUICK,
            minimum_path_length_mm=4.0,
            join_distance_mm=0,
        ),
    )
    details = [
        line
        for line in result.lines
        if polyline_length(line) < 4.0 and any(44 <= x <= 49 and 44 <= y <= 49 for x, y in line)
    ]
    assert details


def test_low_value_surface_does_not_create_excess_fill():
    image = np.zeros((220, 220), dtype=np.float32)
    cv2.rectangle(image, (15, 145), (205, 205), 0.31, -1)
    cv2.ellipse(image, (110, 75), (45, 58), 0, 0, 360, 0.95, 9)
    options = quality_options(page_width_mm=54, page_height_mm=54)
    confidence, geometry = _plotting_resolution(_confidence(image), options)
    source, softened, low = _prepare_ink(confidence, options, geometry, component_factor=0.55)
    face_mask, _ = detect_face_mask(softened, source)
    candidates = build_fidelity_candidate_set(source, softened, low, options, geometry, face_mask)
    fill_counts = Counter(
        candidate.component_id for candidate in candidates if candidate.path_type != "centerline"
    )
    low_surface_components = {
        candidate.component_id for candidate in candidates if candidate.mean_confidence < 0.4
    }
    assert fill_counts
    assert max(fill_counts.values()) <= 4
    assert all(fill_counts[component] <= 1 for component in low_surface_components)


def test_event_quality_is_deterministic_and_legacy_alias_matches():
    image = portrait_map()
    current = quality_options(
        page_width_mm=94,
        page_height_mm=94,
        event_quality_level=EventQualityLevel.BALANCED,
    )
    legacy = quality_options(
        vectorization_mode=VectorizationMode.EVENT_SPEED,
        event_speed_level=EventSpeedLevel.EVENT,
        fill_strategy=FillStrategy.NONE,
    )
    first = vectorize(image, current)
    second = vectorize(image, current)
    migrated = vectorize(image, legacy)
    assert first.lines == second.lines
    assert first.stats == second.stats
    assert first.lines == migrated.lines


def test_event_quality_svg_and_trajectory_are_dexarm_safe(tmp_path):
    options = quality_options(event_quality_level=EventQualityLevel.QUICK)
    result = vectorize(portrait_map(), options)
    svg = tmp_path / "drawing-speed.svg"
    trajectory = tmp_path / "trajectory-speed.json"
    write_svg(result, options, svg)
    write_trajectory(result, options, trajectory)

    root = ET.parse(svg).getroot()
    assert root.attrib["width"] == "94mm"
    assert root.attrib["height"] == "94mm"
    assert root.attrib["viewBox"] == "0 0 94 94"
    assert {element.tag.rsplit("}", 1)[-1] for element in root.iter()} == {"svg", "path"}
    assert len(root) == result.stats.stroke_count
    for path in root:
        assert path.attrib["fill"] == "none"
        assert path.attrib["stroke-width"] == "0.8"
        assert "transform" not in path.attrib
        assert "Z" not in path.attrib["d"].upper()
        assert set(re.findall(r"[A-Za-z]", path.attrib["d"])) <= {"M", "L", "C"}
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path.attrib["d"])]
        assert all(math.isfinite(value) for value in numbers)
        assert all(5 <= value <= 89 for value in numbers)

    payload = json.loads(trajectory.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.4"
    assert payload["mode"] == "event_quality"
    assert payload["event_quality_level"] == "quick"
    assert payload["fill_strategy"] == "adaptive_sparse"
    assert payload["path_count"] == result.stats.stroke_count
    assert payload["metrics"]["quality_score"] == result.stats.quality_score


@pytest.mark.parametrize(
    "relative_path", ["build_portable.ps1", ".github/workflows/windows-portable.yml"]
)
def test_windows_portable_metadata_uses_release_version(relative_path):
    content = Path(relative_path).read_text(encoding="utf-8")
    assert "0.4.0" not in content
    assert "0.4.1" in content
