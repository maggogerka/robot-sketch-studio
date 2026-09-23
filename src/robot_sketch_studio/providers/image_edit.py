from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from robot_sketch_studio.models import RemoteBackendName
from robot_sketch_studio.providers.base import ImageEditProvider

ARTISTIC_PROMPT = """Transform the input photograph into a clean minimalist pen-and-ink
single-line drawing. Preserve identity, pose, proportions, silhouette
and recognizable features. Use a pure white background and uniform
black lines. Use a small number of long, smooth, continuous strokes.
Remove shadows, textures, photographic noise, skin and fabric texture,
hatching, cross-hatching, dots and tiny disconnected details.
Do not add objects or change the composition. The result must be
suitable for drawing by a pen plotter."""


class RemoteImageEditError(RuntimeError):
    pass


def _multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, str]:
    boundary = f"RobotSketchStudio-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, (filename, payload, media_type) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {media_type}\r\n\r\n".encode(),
                payload,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _png_bytes(rgb: np.ndarray) -> bytes:
    stream = BytesIO()
    Image.fromarray(rgb.astype(np.uint8), mode="RGB").save(stream, format="PNG")
    return stream.getvalue()


def _decode_image(payload: bytes) -> np.ndarray:
    try:
        with Image.open(BytesIO(payload)) as image:
            return np.asarray(image.convert("RGB"), dtype=np.uint8)
    except Exception as exc:
        raise RemoteImageEditError("Remote server returned an invalid image") from exc


class _HTTPProvider(ImageEditProvider):
    def __init__(self, url: str, api_key: str = "", timeout: float = 180.0) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "RobotSketchStudio/0.3"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(self, request: urllib.request.Request, timeout: float | None = None) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                maximum = 64 * 1024 * 1024
                declared = int(response.headers.get("Content-Length", 0))
                if declared > maximum:
                    raise RemoteImageEditError("Remote response exceeds 64 MB")
                payload = response.read(maximum + 1)
                if len(payload) > maximum:
                    raise RemoteImageEditError("Remote response exceeds 64 MB")
                return payload
        except urllib.error.HTTPError as exc:
            detail = exc.read(512).decode("utf-8", errors="replace")
            raise RemoteImageEditError(f"Remote server returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RemoteImageEditError(f"Cannot reach remote server: {exc}") from exc


class OpenAIImageEditProvider(_HTTPProvider):
    """OpenAI-compatible image edit API, usable by Qwen/FLUX gateways."""

    def __init__(self, url: str, model: str | None, api_key: str = "") -> None:
        super().__init__(url, api_key)
        self.model = model or "image-edit"

    @property
    def edit_url(self) -> str:
        if self.url.endswith("/images/edits"):
            return self.url
        return f"{self.url}/images/edits"

    def test_connection(self) -> dict[str, Any]:
        base = self.url.removesuffix("/images/edits").rstrip("/")
        models_url = f"{base}/models"
        request = urllib.request.Request(models_url, headers=self._headers(), method="GET")
        self._request(request, timeout=15)
        return {"ok": True, "backend": RemoteBackendName.OPENAI_IMAGES}

    def edit(self, rgb: np.ndarray) -> np.ndarray:
        body, content_type = _multipart(
            {"model": self.model, "prompt": ARTISTIC_PROMPT, "response_format": "b64_json"},
            {"image": ("input.png", _png_bytes(rgb), "image/png")},
        )
        request = urllib.request.Request(
            self.edit_url,
            data=body,
            headers=self._headers(content_type),
            method="POST",
        )
        try:
            response = json.loads(self._request(request))
            result = response["data"][0]
            if result.get("b64_json"):
                return _decode_image(base64.b64decode(result["b64_json"], validate=True))
            if result.get("url"):
                result_url = str(result["url"])
                source = urllib.parse.urlparse(self.url)
                destination = urllib.parse.urlparse(result_url)
                same_origin = (
                    source.scheme == destination.scheme and source.netloc == destination.netloc
                )
                headers = (
                    self._headers()
                    if same_origin
                    else {
                        "Accept": "image/*",
                        "User-Agent": "RobotSketchStudio/0.3",
                    }
                )
                image_request = urllib.request.Request(result_url, headers=headers)
                return _decode_image(self._request(image_request))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RemoteImageEditError("Remote image API returned an unsupported response") from exc
        raise RemoteImageEditError("Remote image API returned no image")


class ComfyUIImageEditProvider(_HTTPProvider):
    def __init__(
        self,
        url: str,
        workflow_path: Path | None,
        api_key: str = "",
        timeout: float = 300.0,
    ) -> None:
        super().__init__(url, api_key, timeout)
        self.workflow_path = workflow_path

    def test_connection(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.url}/system_stats", headers=self._headers(), method="GET"
        )
        self._request(request, timeout=15)
        return {"ok": True, "backend": RemoteBackendName.COMFYUI}

    @staticmethod
    def _replace(value: Any, image_name: str) -> Any:
        if isinstance(value, str):
            return value.replace("{{IMAGE}}", image_name).replace("{{PROMPT}}", ARTISTIC_PROMPT)
        if isinstance(value, list):
            return [ComfyUIImageEditProvider._replace(item, image_name) for item in value]
        if isinstance(value, dict):
            return {
                key: ComfyUIImageEditProvider._replace(item, image_name)
                for key, item in value.items()
            }
        return value

    def _workflow(self, image_name: str) -> dict[str, Any]:
        if not self.workflow_path or not self.workflow_path.is_file():
            raise RemoteImageEditError(
                "Set SKETCHARM_COMFYUI_WORKFLOW to a ComfyUI API workflow JSON file"
            )
        try:
            loaded = json.loads(self.workflow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RemoteImageEditError("Cannot read the ComfyUI workflow JSON") from exc
        workflow = loaded.get("prompt", loaded)
        if not isinstance(workflow, dict):
            raise RemoteImageEditError("ComfyUI workflow must contain an API-format object")
        return self._replace(workflow, image_name)

    def edit(self, rgb: np.ndarray) -> np.ndarray:
        image_name = f"robot-sketch-{uuid.uuid4().hex}.png"
        body, content_type = _multipart(
            {"overwrite": "true"},
            {"image": (image_name, _png_bytes(rgb), "image/png")},
        )
        upload = urllib.request.Request(
            f"{self.url}/upload/image",
            data=body,
            headers=self._headers(content_type),
            method="POST",
        )
        self._request(upload)
        workflow = self._workflow(image_name)
        prompt_body = json.dumps(
            {"prompt": workflow, "client_id": f"robot-sketch-{uuid.uuid4().hex}"}
        ).encode()
        prompt_request = urllib.request.Request(
            f"{self.url}/prompt",
            data=prompt_body,
            headers=self._headers("application/json"),
            method="POST",
        )
        try:
            prompt_id = json.loads(self._request(prompt_request))["prompt_id"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RemoteImageEditError("ComfyUI did not return a prompt id") from exc

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            history_request = urllib.request.Request(
                f"{self.url}/history/{urllib.parse.quote(str(prompt_id))}",
                headers=self._headers(),
                method="GET",
            )
            history = json.loads(self._request(history_request, timeout=15))
            entry = history.get(str(prompt_id))
            if entry:
                for output in entry.get("outputs", {}).values():
                    images = output.get("images", [])
                    if images:
                        info = images[0]
                        query = urllib.parse.urlencode(
                            {
                                "filename": info["filename"],
                                "subfolder": info.get("subfolder", ""),
                                "type": info.get("type", "output"),
                            }
                        )
                        view = urllib.request.Request(
                            f"{self.url}/view?{query}", headers=self._headers(), method="GET"
                        )
                        return _decode_image(self._request(view))
                raise RemoteImageEditError("ComfyUI workflow completed without an image")
            time.sleep(1)
        raise RemoteImageEditError("ComfyUI image edit timed out")


def create_image_edit_provider(
    backend: RemoteBackendName,
    url: str,
    model: str | None = None,
    api_key: str = "",
    workflow_path: Path | None = None,
) -> ImageEditProvider:
    if backend == RemoteBackendName.COMFYUI:
        return ComfyUIImageEditProvider(url, workflow_path, api_key)
    return OpenAIImageEditProvider(url, model, api_key)
