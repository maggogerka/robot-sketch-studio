from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

from robot_sketch_studio.engines.opencv_xdog import OpenCVXDoGEngine
from robot_sketch_studio.models import (
    EventQualityLevel,
    ImageProfile,
    ProcessingOptions,
    SketchEngineName,
    VectorizationMode,
)
from robot_sketch_studio.pipeline import SketchPipeline


def make_test_image(path: Path) -> None:
    image = Image.new("RGB", (180, 120), "white")
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((25, 15, 150, 105), outline="black", width=5)
    drawing.line((30, 95, 150, 25), fill="black", width=4)
    drawing.line((20, 60, 160, 60), fill=(40, 40, 40), width=3)
    image.save(path)


def test_full_pipeline_creates_nonempty_artifacts(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "output"
    make_test_image(source)
    result = SketchPipeline().process(
        source,
        output,
        ProcessingOptions(
            engine=SketchEngineName.OPENCV_XDOG,
            minimum_path_length_mm=0.5,
            curve_fit_tolerance_mm=0.8,
            detail=65,
        ),
    )
    assert result.vector.stats.stroke_count > 0
    sketch = Image.open(output / "sketch.png")
    assert sketch.getbbox() is not None
    assert (output / "sketch.png").stat().st_size > 100
    assert (output / "confidence.png").stat().st_size > 100
    assert (output / "vector-preview.png").stat().st_size > 100
    assert (output / "difference-overlay.png").stat().st_size > 100
    root = ET.parse(output / "drawing.svg").getroot()
    assert root.tag.endswith("svg")
    assert list(root.iter("{http://www.w3.org/2000/svg}path"))
    payload = json.loads((output / "trajectory.json").read_text(encoding="utf-8"))
    assert payload["strokes"]
    assert payload["stats"]["stroke_count"] == len(payload["strokes"])


def test_missing_optional_background_provider_is_nonfatal(tmp_path):
    source = tmp_path / "source.png"
    make_test_image(source)
    pipeline = SketchPipeline()
    if pipeline.background.available():
        return
    result = pipeline.process(
        source,
        tmp_path / "output",
        ProcessingOptions(
            engine=SketchEngineName.OPENCV_XDOG,
            background="auto",
            minimum_path_length_mm=0.5,
        ),
    )
    assert result.vector.stats.stroke_count > 0
    assert any("rembg" in warning for warning in result.warnings)


def test_event_quality_pipeline_adds_named_artifacts_without_removing_standard_ones(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "speed-output"
    make_test_image(source)
    result = SketchPipeline().process(
        source,
        output,
        ProcessingOptions(
            engine=SketchEngineName.OPENCV_XDOG,
            vectorization_mode=VectorizationMode.EVENT_QUALITY,
            event_quality_level=EventQualityLevel.QUICK,
            minimum_path_length_mm=0.2,
            minimum_feature_size_mm=0.05,
        ),
    )
    assert set(result.artifacts) == {
        "confidence.png",
        "sketch.png",
        "vector-preview.png",
        "difference-overlay.png",
        "drawing.svg",
        "trajectory.json",
        "drawing-speed.svg",
        "trajectory-speed.json",
        "vector-speed-preview.png",
        "speed-difference-overlay.png",
    }
    for artifact in result.artifacts:
        assert (output / artifact).stat().st_size > 0
    assert (output / "drawing.svg").read_bytes() == (output / "drawing-speed.svg").read_bytes()
    payload = json.loads((output / "trajectory-speed.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "event_quality"
    assert payload["event_quality_level"] == "quick"
    assert payload["canonical_mode"] == "event_quality"


def test_line_drawing_profile_preserves_marks_without_filling_page(tmp_path):
    source = tmp_path / "source.png"
    make_test_image(source)
    rgb = SketchPipeline.load_image(source)
    sketch = OpenCVXDoGEngine().render(
        rgb, ProcessingOptions(profile=ImageProfile.LINE_DRAWING, detail=60)
    )
    ink_ratio = float((sketch == 0).mean())
    assert 0.005 < ink_ratio < 0.35
