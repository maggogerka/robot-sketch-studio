from __future__ import annotations

import hashlib
import time
from io import BytesIO

from robot_sketch_studio.model_manager import ModelFile, ModelManager, ModelSpec


class FakeResponse(BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}


def wait_for_model(manager: ModelManager, model_id: str) -> dict[str, object]:
    for _ in range(100):
        item = manager.describe(model_id)
        if item["status"] in {"installed", "failed"}:
            return item
        time.sleep(0.01)
    raise AssertionError("model download did not finish")


def spec(payload: bytes, checksum: str | None = None) -> ModelSpec:
    return ModelSpec(
        id="test-model",
        name="Test model",
        provider="test",
        description="Fixture",
        dependency="json",
        install_extra="dev",
        license="test",
        files=(
            ModelFile(
                path="safe/model.bin",
                url="https://example.invalid/model.bin",
                checksum=checksum or hashlib.sha256(payload).hexdigest(),
                size=len(payload),
            ),
        ),
    )


def test_download_verifies_checksum_and_replaces_atomically(tmp_path):
    payload = b"verified model bytes"
    manager = ModelManager(
        tmp_path,
        specs=(spec(payload),),
        opener=lambda request, timeout: FakeResponse(payload),
    )
    try:
        assert manager.describe("test-model")["status"] == "not_installed"
        manager.download("test-model")
        result = wait_for_model(manager, "test-model")
        assert result["status"] == "installed"
        assert result["progress"] == 100
        assert (tmp_path / "safe" / "model.bin").read_bytes() == payload
        assert not (tmp_path / "safe" / "model.bin.part").exists()
    finally:
        manager.close()


def test_download_rejects_bad_checksum(tmp_path):
    payload = b"corrupt"
    manager = ModelManager(
        tmp_path,
        specs=(spec(payload, checksum="0" * 64),),
        opener=lambda request, timeout: FakeResponse(payload),
    )
    try:
        manager.download("test-model")
        result = wait_for_model(manager, "test-model")
        assert result["status"] == "failed"
        assert "Checksum" in str(result["error"])
        assert not (tmp_path / "safe" / "model.bin").exists()
        assert not (tmp_path / "safe" / "model.bin.part").exists()
    finally:
        manager.close()
