from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from robot_sketch_studio.app import create_app
from robot_sketch_studio.config import Settings


def image_bytes() -> bytes:
    image = Image.new("RGB", (140, 100), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((15, 15, 125, 85), outline="black", width=4)
    drawing.line((20, 80, 120, 20), fill="black", width=3)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def settings(tmp_path, **overrides) -> Settings:
    values = {
        "data_dir": tmp_path / "data",
        "results_dir": tmp_path / "results",
        "model_dir": tmp_path / "models",
        "max_workers": 1,
        "queue_size": 2,
    }
    values.update(overrides)
    return Settings(**values)


def wait_for_job(client: TestClient, job_id: str, headers=None):
    for _ in range(100):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers or {})
        assert response.status_code == 200
        job = response.json()
        if job["state"] in {"completed", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("Job did not finish")


def test_health_and_complete_api_pipeline(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["version"] == "0.1.0"
        response = client.post(
            "/api/v1/jobs",
            files={"image": ("test.png", image_bytes(), "image/png")},
            data={"options": json.dumps({"min_line_length_mm": 0.5, "smoothing": 0.5})},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        job = wait_for_job(client, job_id)
        assert job["state"] == "completed", job.get("error")
        assert job["stats"]["stroke_count"] > 0

        artifacts = client.get(f"/api/v1/jobs/{job_id}/artifacts")
        assert artifacts.status_code == 200
        assert {item["name"] for item in artifacts.json()["artifacts"]} == {
            "sketch.png",
            "drawing.svg",
            "trajectory.json",
        }
        png = client.get(f"/api/v1/jobs/{job_id}/artifacts/sketch.png")
        Image.open(BytesIO(png.content)).verify()
        svg = client.get(f"/api/v1/jobs/{job_id}/artifacts/drawing.svg")
        ET.fromstring(svg.content)
        trajectory = client.get(f"/api/v1/jobs/{job_id}/artifacts/trajectory.json").json()
        assert trajectory["strokes"]

        deleted = client.delete(f"/api/v1/jobs/{job_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/jobs/{job_id}").status_code == 404


def test_rejects_corrupt_and_oversized_uploads(tmp_path):
    with TestClient(create_app(settings(tmp_path, max_upload_mb=1))) as client:
        corrupt = client.post(
            "/api/v1/jobs",
            files={"image": ("bad.png", b"not an image", "image/png")},
        )
        assert corrupt.status_code == 400
        oversized = client.post(
            "/api/v1/jobs",
            files={"image": ("huge.png", b"x" * (1024 * 1024 + 1), "image/png")},
        )
        assert oversized.status_code == 413


def test_host_mode_requires_bearer_token(tmp_path):
    config = settings(tmp_path, host="0.0.0.0", api_token="correct-horse")
    with TestClient(create_app(config)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/capabilities").status_code == 401
        headers = {"Authorization": "Bearer correct-horse"}
        capabilities = client.get("/api/v1/capabilities", headers=headers)
        assert capabilities.status_code == 200
        assert capabilities.json()["host_mode"] is True


def test_host_mode_refuses_to_start_without_token(tmp_path):
    config = settings(tmp_path, host="0.0.0.0", api_token=None)
    try:
        create_app(config)
    except ValueError as exc:
        assert "API_TOKEN" in str(exc)
    else:
        raise AssertionError("Host mode started without a token")
