from __future__ import annotations

import base64
import json
from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image

from robot_sketch_studio.engines.lineart_ai import _build_generator
from robot_sketch_studio.models import DrawingPreset, ProcessingOptions
from robot_sketch_studio.providers.image_edit import (
    ARTISTIC_PROMPT,
    ComfyUIImageEditProvider,
    OpenAIImageEditProvider,
)
from robot_sketch_studio.vectorization import vectorize


def test_presets_apply_physical_defaults_and_allow_overrides():
    minimal = ProcessingOptions(drawing_preset=DrawingPreset.MINIMAL)
    detailed = ProcessingOptions(drawing_preset=DrawingPreset.DETAILED)
    custom = ProcessingOptions(drawing_preset=DrawingPreset.MINIMAL, target_paths=23)
    assert minimal.target_paths == 16
    assert minimal.minimum_path_length_mm == 4.0
    assert detailed.target_paths == 64
    assert detailed.curve_fit_tolerance_mm == 0.2
    assert custom.target_paths == 23


def test_vectorizer_limits_paths_and_fits_cubic_curves():
    confidence = np.zeros((140, 180), dtype=np.float32)
    for row in range(15, 125, 11):
        cv2.line(confidence, (10, row), (170, row), 1.0, 2)
    result = vectorize(
        confidence,
        ProcessingOptions(
            target_paths=4,
            minimum_path_length_mm=0.1,
            minimum_feature_size_mm=0.1,
            join_distance_mm=0,
            curve_fit_tolerance_mm=0.2,
        ),
    )
    assert result.stats.stroke_count == 4
    assert result.stats.curve_segment_count >= 4
    assert all(path for path in result.curves)


def test_official_generator_matches_published_checkpoint_keys():
    pytest.importorskip("torch")
    keys = _build_generator().state_dict()
    assert "model0.1.weight" in keys
    assert "model2.0.conv_block.1.weight" in keys
    assert "model4.1.weight" in keys


class FakeResponse(BytesIO):
    headers: dict[str, str] = {}


def test_openai_image_edit_sends_fixed_prompt_and_decodes_image(monkeypatch):
    image = Image.new("RGB", (8, 6), "white")
    stream = BytesIO()
    image.save(stream, format="PNG")
    encoded = base64.b64encode(stream.getvalue()).decode()
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return FakeResponse(json.dumps({"data": [{"b64_json": encoded}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAIImageEditProvider("http://render-pc:9000/v1", "qwen-edit", "secret")
    result = provider.edit(np.zeros((6, 8, 3), dtype=np.uint8))
    request = captured["request"]
    assert result.shape == (6, 8, 3)
    assert request.full_url == "http://render-pc:9000/v1/images/edits"
    assert request.headers["Authorization"] == "Bearer secret"
    assert ARTISTIC_PROMPT.encode() in request.data
    assert b"qwen-edit" in request.data


def test_comfyui_replaces_image_and_prompt_placeholders():
    workflow = {
        "1": {"inputs": {"image": "{{IMAGE}}"}},
        "2": {"inputs": {"text": "{{PROMPT}}"}},
    }
    replaced = ComfyUIImageEditProvider._replace(workflow, "upload.png")
    assert replaced["1"]["inputs"]["image"] == "upload.png"
    assert replaced["2"]["inputs"]["text"] == ARTISTIC_PROMPT
