from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from io import BytesIO

import cv2
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from robot_sketch_studio.app import create_app
from robot_sketch_studio.config import Settings
from robot_sketch_studio.engines.generated_line_art import (
    GeneratedLineArtEngine,
    decode_line_art_image,
)
from robot_sketch_studio.models import (
    DrawingPreset,
    ExportProfile,
    FillStrategy,
    LineArtImportProfile,
    PaperPreset,
    ProcessingOptions,
    SketchEngineName,
    VectorizationMode,
)
from robot_sketch_studio.pipeline import SketchPipeline
from robot_sketch_studio.vectorization import vectorize, write_svg


def options(**overrides) -> ProcessingOptions:
    values = {
        "engine": SketchEngineName.GENERATED_LINE_ART,
        "drawing_preset": DrawingPreset.GENERATED_LINE_ART,
        "line_art_import_profile": LineArtImportProfile.PRESERVE_QUALITY,
        "paper": PaperPreset.ROTRICS_80X113,
        "export_profile": ExportProfile.ROTRICS_CENTERLINE,
        "vectorization_mode": VectorizationMode.EVENT_SINGLE_LINE,
        "fill_strategy": FillStrategy.NONE,
        "margin_mm": 5,
        "pen_width_mm": 0.8,
    }
    values.update(overrides)
    return ProcessingOptions(**values)


def png_bytes(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def line_art(width: int = 160, height: int = 200) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((35, 18, 125, 145), outline="black", width=7)
    drawing.arc((51, 60, 70, 72), 180, 360, fill="black", width=2)
    drawing.arc((90, 60, 109, 72), 180, 360, fill="black", width=2)
    drawing.line((80, 70, 77, 94), fill="black", width=2)
    drawing.arc((63, 95, 98, 116), 0, 180, fill="black", width=2)
    drawing.line((48, 142, 27, 194), fill="black", width=5)
    drawing.line((112, 142, 133, 194), fill="black", width=5)
    return image


def detailed_portrait_fixture() -> Image.Image:
    image = line_art()
    drawing = ImageDraw.Draw(image)
    drawing.arc((32, 12, 128, 92), 190, 350, fill="black", width=8)  # hair
    drawing.ellipse((45, 57, 73, 78), outline="black", width=1)  # glasses
    drawing.ellipse((87, 57, 115, 78), outline="black", width=1)
    drawing.line((73, 67, 87, 67), fill="black", width=1)
    drawing.line((50, 155, 80, 185), fill="black", width=3)  # clothing
    drawing.line((110, 155, 80, 185), fill="black", width=3)
    return image


def prepare(image: Image.Image, settings: ProcessingOptions | None = None):
    rgb = decode_line_art_image(png_bytes(image))
    return GeneratedLineArtEngine().prepare(rgb, settings or options())


def test_generated_import_defaults_to_offline_single_line_profile():
    settings = ProcessingOptions(engine=SketchEngineName.GENERATED_LINE_ART)
    assert settings.drawing_preset == DrawingPreset.GENERATED_LINE_ART
    assert settings.vectorization_mode == VectorizationMode.EVENT_SINGLE_LINE
    assert settings.fill_strategy == FillStrategy.NONE
    assert settings.paper == PaperPreset.ROTRICS_80X113
    assert settings.page_dimensions == (80.0, 113.0)
    assert settings.margin_mm == 5


def test_transparent_background_is_composited_to_white():
    image = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    ImageDraw.Draw(image).line((10, 40, 90, 40), fill=(0, 0, 0, 255), width=5)
    rgb = decode_line_art_image(png_bytes(image))
    assert tuple(rgb[0, 0]) == (255, 255, 255)
    prepared = GeneratedLineArtEngine().prepare(rgb, options())
    assert prepared.confidence[0, 0] == 0
    assert prepared.confidence[40, 50] > 0.95


def test_thick_stroke_becomes_one_centerline_and_thin_stroke_survives():
    thick = Image.new("RGB", (120, 160), "white")
    ImageDraw.Draw(thick).line((25, 135, 90, 20), fill="black", width=15)
    thick_result = vectorize(prepare(thick).confidence, prepare(thick).options)
    assert thick_result.stats.stroke_count == 1
    assert thick_result.stats.unique_centerline_coverage > 0.92

    thin = Image.new("RGB", (120, 160), "white")
    ImageDraw.Draw(thin).arc((20, 20, 100, 140), 80, 280, fill="black", width=1)
    prepared = prepare(thin)
    thin_result = vectorize(prepared.confidence, prepared.options)
    assert thin_result.stats.stroke_count >= 1
    assert thin_result.stats.drawing_length_mm > 20


def test_separate_face_details_are_not_joined_across_white_space():
    image = Image.new("RGB", (160, 200), "white")
    drawing = ImageDraw.Draw(image)
    drawing.line((42, 76, 65, 76), fill="black", width=3)
    drawing.line((95, 76, 118, 76), fill="black", width=3)
    drawing.arc((62, 105, 98, 122), 0, 180, fill="black", width=3)
    prepared = prepare(image, options(line_art_gap_closing_mm=0.12, line_art_auto=False))
    result = vectorize(prepared.confidence, prepared.options)
    assert result.stats.stroke_count == 3
    for line in result.lines:
        x_values = [point[0] for point in line]
        assert max(x_values) - min(x_values) < 18


def test_generated_svg_is_black_physical_deterministic_and_dexarm_safe(tmp_path):
    prepared = prepare(line_art())
    first = vectorize(prepared.confidence, prepared.options)
    second = vectorize(prepared.confidence, prepared.options)
    assert first.lines == second.lines
    assert first.stats == second.stats
    assert first.stats.node_count >= first.stats.stroke_count * 2
    assert first.stats.mean_line_distance_mm <= prepared.options.pen_width_mm
    canonical = {min(tuple(line), tuple(reversed(line))) for line in first.lines}
    assert len(canonical) == len(first.lines)
    for line, commands in zip(first.lines, first.commands or [], strict=True):
        lower = np.min(np.asarray(line), axis=0) - prepared.options.line_art_smoothing_mm
        upper = np.max(np.asarray(line), axis=0) + prepared.options.line_art_smoothing_mm
        cursor = line[0]
        for command in commands:
            assert math.dist(cursor, command.end) > 1e-8
            controls = [command.end]
            if hasattr(command, "control1"):
                controls.extend((command.control1, command.control2))
            assert np.all(np.asarray(controls) >= lower - 1e-8)
            assert np.all(np.asarray(controls) <= upper + 1e-8)
            cursor = command.end

    destination = tmp_path / "drawing.svg"
    write_svg(first, prepared.options, destination)
    root = ET.parse(destination).getroot()
    assert root.attrib["width"] == "80mm"
    assert root.attrib["height"] == "113mm"
    assert root.attrib["viewBox"] == "0 0 80 113"
    assert len(root) == first.stats.stroke_count
    for path in root:
        assert path.tag.rsplit("}", 1)[-1] == "path"
        assert path.attrib["fill"] == "none"
        assert path.attrib["stroke"] == "#000000"
        assert path.attrib["stroke-linecap"] == "round"
        assert path.attrib["stroke-linejoin"] == "round"
        assert path.attrib["d"].upper().count("M") == 1
        assert "Z" not in path.attrib["d"].upper()
        assert not any(token in path.attrib for token in ("transform", "mask", "filter"))
    assert all(
        math.isfinite(coordinate) for line in first.lines for point in line for coordinate in point
    )


def test_optimized_profile_does_not_add_paths_or_lose_face_details():
    image = line_art()
    preserve = prepare(image, options())
    optimized = prepare(
        image,
        options(line_art_import_profile=LineArtImportProfile.DEXARM_OPTIMIZED),
    )
    preserve_result = vectorize(preserve.confidence, preserve.options)
    optimized_result = vectorize(optimized.confidence, optimized.options)
    assert optimized_result.stats.stroke_count <= preserve_result.stats.stroke_count
    assert optimized_result.stats.pen_lifts <= preserve_result.stats.pen_lifts
    assert optimized_result.stats.face_weighted_recall >= 0.8


def test_hair_glasses_clothing_and_mixed_width_fixture_is_preserved():
    prepared = prepare(detailed_portrait_fixture())
    result = vectorize(prepared.confidence, prepared.options)
    assert result.stats.stroke_count >= 8
    assert result.stats.unique_centerline_coverage > 0.9
    assert result.stats.face_weighted_recall > 0.85
    assert prepared.analysis.thin_lines is False


def test_pipeline_emits_centerline_artifact_and_auto_analysis_api(tmp_path):
    source = tmp_path / "portrait.png"
    line_art().save(source)
    output = tmp_path / "result"
    result = SketchPipeline(model_dir=tmp_path / "models").process(source, output, options())
    assert "centerline-overlay.png" in result.artifacts
    assert "drawing-speed.svg" in result.artifacts
    assert result.vector.stats.stroke_count > 0
    trajectory = json.loads((output / "trajectory-speed.json").read_text(encoding="utf-8"))
    assert trajectory["engine"] == "generated_line_art"
    assert trajectory["line_art_import_profile"] == "preserve_quality"
    assert trajectory["metrics"]["node_count"] == result.vector.stats.node_count

    settings = Settings(
        data_dir=tmp_path / "data",
        results_dir=tmp_path / "api-results",
        model_dir=tmp_path / "api-models",
    )
    with TestClient(create_app(settings)) as client:
        capabilities = client.get("/api/v1/capabilities").json()
        assert capabilities["engines"]["generated_line_art"]["offline"] is True
        assert capabilities["line_art_import_profiles"] == [
            "preserve_quality",
            "dexarm_optimized",
        ]
        response = client.post(
            "/api/v1/line-art/analyze",
            files={"image": ("portrait.png", png_bytes(line_art()), "image/png")},
            data={"options": json.dumps(options().model_dump(mode="json"))},
        )
        assert response.status_code == 200
        analysis = response.json()
        assert analysis["width_px"] == 160
        assert analysis["height_px"] == 200
        assert analysis["millimetres_per_pixel"] > 0
        assert analysis["estimated_stroke_width_mm"] > 0
        assert 0 <= analysis["noise_ratio"] <= 1
        assert "line_art_smoothing_mm" in analysis["recommendations"]


def test_noise_removal_only_removes_small_isolated_marks():
    image = Image.new("RGB", (160, 200), "white")
    drawing = ImageDraw.Draw(image)
    drawing.line((20, 100, 140, 100), fill="black", width=2)
    drawing.point((5, 5), fill=(90, 90, 90))
    prepared = prepare(
        image,
        options(line_art_auto=False, line_art_noise_removal_mm=1.0, threshold=180),
    )
    count, _, _, _ = cv2.connectedComponentsWithStats((prepared.confidence > 0).astype(np.uint8), 8)
    assert count == 2
