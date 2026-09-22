from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

from robot_sketch_studio.models import ProcessingOptions
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
        ProcessingOptions(min_line_length_mm=0.5, smoothing=0.8, detail=65),
    )
    assert result.vector.stats.stroke_count > 0
    sketch = Image.open(output / "sketch.png")
    assert sketch.getbbox() is not None
    assert (output / "sketch.png").stat().st_size > 100
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
        ProcessingOptions(background="auto", min_line_length_mm=0.5),
    )
    assert result.vector.stats.stroke_count > 0
    assert any("rembg" in warning for warning in result.warnings)
