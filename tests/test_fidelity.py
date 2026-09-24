from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET

import cv2
import numpy as np

from robot_sketch_studio.fidelity import _metrics
from robot_sketch_studio.models import (
    DrawingPreset,
    FillStrategy,
    PaperPreset,
    ProcessingOptions,
    VectorizationMode,
)
from robot_sketch_studio.vectorization import vectorize, write_svg, write_trajectory


def options(**overrides) -> ProcessingOptions:
    values = {
        "paper": PaperPreset.CUSTOM,
        "page_width_mm": 50,
        "page_height_mm": 40,
        "margin_mm": 5,
        "vectorization_mode": VectorizationMode.PLOTTER_FIDELITY,
        "pen_width_mm": 0.5,
        "minimum_path_length_mm": 0.05,
        "minimum_feature_size_mm": 0.05,
        "curve_fit_tolerance_mm": 0.08,
        "join_distance_mm": 0,
        "fill_strategy": FillStrategy.CONTOUR,
    }
    values.update(overrides)
    return ProcessingOptions(**values)


def golden_marks() -> np.ndarray:
    image = np.zeros((241, 321), dtype=np.float32)
    cv2.line(image, (25, 35), (290, 35), 1.0, 3)
    cv2.line(image, (25, 95), (290, 95), 1.0, 24)
    cv2.circle(image, (160, 175), 28, 1.0, -1)
    cv2.line(image, (115, 150), (123, 150), 1.0, 2)
    cv2.line(image, (197, 150), (205, 150), 1.0, 2)
    return image


def test_dexarm_fidelity_preset_has_physical_defaults():
    value = ProcessingOptions(drawing_preset=DrawingPreset.DEXARM_FIDELITY)
    assert value.vectorization_mode == VectorizationMode.PLOTTER_FIDELITY
    assert value.pen_width_mm == 0.5
    assert value.ink_coverage_target == 0.97
    assert value.fill_strategy == FillStrategy.CONTOUR
    assert value.minimum_path_length_mm == 0.25
    assert value.curve_fit_tolerance_mm == 0.08
    assert value.maximum_plotter_paths == 3000


def test_thin_line_is_one_path_and_thick_marks_get_multiple_passes():
    thin = np.zeros((241, 321), dtype=np.float32)
    cv2.line(thin, (25, 100), (290, 100), 1.0, 3)
    thin_result = vectorize(thin, options(fill_strategy=FillStrategy.NONE))
    assert thin_result.stats.stroke_count == 1

    thick = np.zeros_like(thin)
    cv2.line(thick, (25, 100), (290, 100), 1.0, 24)
    thick_result = vectorize(thick, options(target_paths=4))
    assert thick_result.stats.stroke_count > 4
    assert thick_result.stats.ink_recall >= 0.95


def test_black_circle_uses_concentric_closed_trajectories():
    image = np.zeros((241, 321), dtype=np.float32)
    cv2.circle(image, (160, 120), 45, 1.0, -1)
    result = vectorize(image, options())
    closed = [line for line in result.lines if math.dist(line[0], line[-1]) < 0.2]
    assert len(closed) >= 3
    assert result.stats.ink_iou >= 0.80


def test_short_details_survive_and_blank_gap_is_not_joined():
    image = np.zeros((241, 321), dtype=np.float32)
    cv2.line(image, (40, 100), (115, 100), 1.0, 2)
    cv2.line(image, (205, 100), (280, 100), 1.0, 2)
    cv2.line(image, (145, 130), (151, 130), 1.0, 2)
    cv2.line(image, (169, 130), (175, 130), 1.0, 2)
    result = vectorize(
        image,
        options(
            fill_strategy=FillStrategy.NONE,
            join_distance_mm=15,
            minimum_path_length_mm=5,
            preserve_short_details=True,
        ),
    )
    assert result.stats.stroke_count == 4


def test_fidelity_ignores_target_paths_but_minimal_honours_it():
    image = golden_marks()
    first = vectorize(image, options(target_paths=4))
    second = vectorize(image, options(target_paths=64))
    assert first.stats.stroke_count == second.stats.stroke_count
    assert first.stats.stroke_count > 4

    many = np.zeros((160, 220), dtype=np.float32)
    for y in range(15, 145, 12):
        cv2.line(many, (10, y), (210, y), 1.0, 1)
    minimal = vectorize(
        many,
        ProcessingOptions(
            vectorization_mode=VectorizationMode.MINIMAL,
            target_paths=4,
            minimum_path_length_mm=0,
            minimum_feature_size_mm=0,
            join_distance_mm=0,
        ),
    )
    assert minimal.stats.stroke_count == 4


def test_pen_width_changes_pass_count_and_metrics_are_consistent():
    image = golden_marks()
    fine = vectorize(image, options(pen_width_mm=0.3))
    broad = vectorize(image, options(pen_width_mm=1.0))
    assert fine.stats.stroke_count > broad.stats.stroke_count
    assert fine.stats.source_ink_area_px > 0
    assert 0 <= fine.stats.ink_recall <= 1
    assert 0 <= fine.stats.ink_precision <= 1
    mask = np.zeros((20, 20), dtype=bool)
    mask[5:15, 6:14] = True
    assert _metrics(mask, mask, 0.1)["ink_iou"] == 1.0


def test_fidelity_svg_is_safe_bounded_and_deterministic(tmp_path):
    image = golden_marks()
    settings = options()
    first = vectorize(image, settings)
    second = vectorize(image, settings)
    first_svg = tmp_path / "first.svg"
    second_svg = tmp_path / "second.svg"
    trajectory = tmp_path / "trajectory.json"
    write_svg(first, settings, first_svg)
    write_svg(second, settings, second_svg)
    write_trajectory(first, settings, trajectory)
    assert first_svg.read_bytes() == second_svg.read_bytes()
    assert b"nan" not in first_svg.read_bytes().lower()
    assert b"inf" not in first_svg.read_bytes().lower()

    root = ET.parse(first_svg).getroot()
    assert {element.tag.rsplit("}", 1)[-1] for element in root.iter()} == {"svg", "path"}
    paths = list(root)
    assert paths
    assert any("C" in path.attrib["d"] for path in paths)
    for path in paths:
        assert path.attrib["fill"] == "none"
        assert path.attrib["stroke-width"] == "0.5"
        assert "Z" not in path.attrib["d"].upper()
        assert set(re.findall(r"[A-Za-z]", path.attrib["d"])) <= {"M", "L", "C"}
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path.attrib["d"])]
        coordinates = list(zip(numbers[::2], numbers[1::2], strict=True))
        assert all(5 <= x <= 45 and 5 <= y <= 35 for x, y in coordinates)

    payload = json.loads(trajectory.read_text(encoding="utf-8"))
    assert payload["mode"] == "plotter_fidelity"
    assert payload["vectorization_mode"] == "plotter_fidelity"
    assert payload["path_count"] == first.stats.stroke_count
    assert payload["metrics"]["ink_recall"] == first.stats.ink_recall
