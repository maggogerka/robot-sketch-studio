from __future__ import annotations

import hashlib
import importlib.util
import threading
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from robot_sketch_studio import __version__


@dataclass(frozen=True, slots=True)
class ModelFile:
    path: str
    url: str
    checksum: str
    algorithm: str = "sha256"
    size: int | None = None


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    name: str
    provider: str
    description: str
    dependency: str
    install_extra: str
    license: str
    files: tuple[ModelFile, ...]


MODEL_SPECS = (
    ModelSpec(
        id="rembg-u2net",
        name="U2-Net background removal",
        provider="rembg",
        description="General object and automatic background removal.",
        dependency="rembg",
        install_extra="background",
        license="Apache-2.0 model / MIT integration",
        files=(
            ModelFile(
                path="rembg/models/u2net/u2net.onnx",
                url="https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
                checksum="60024c5c889badc19c04ad937298a77b",
                algorithm="md5",
                size=175_997_641,
            ),
        ),
    ),
    ModelSpec(
        id="rembg-u2net-human",
        name="U2-Net human segmentation",
        provider="rembg",
        description="Portrait background removal tuned for people.",
        dependency="rembg",
        install_extra="background",
        license="Apache-2.0 model / MIT integration",
        files=(
            ModelFile(
                path="rembg/models/u2net_human_seg/u2net_human_seg.onnx",
                url=(
                    "https://github.com/danielgatis/rembg/releases/download/"
                    "v0.0.0/u2net_human_seg.onnx"
                ),
                checksum="c09ddc2e0104f800e3e1bb4652583d1f",
                algorithm="md5",
                size=175_997_641,
            ),
        ),
    ),
    ModelSpec(
        id="lineart-realistic",
        name="ControlNet Lineart",
        provider="controlnet_aux",
        description="Neural line extraction for photographs and detailed objects.",
        dependency="controlnet_aux",
        install_extra="ai",
        license="See lllyasviel/Annotators model card",
        files=(
            ModelFile(
                path="lineart/sk_model.pth",
                url="https://huggingface.co/lllyasviel/Annotators/resolve/main/sk_model.pth",
                checksum="c686ced2a666b4850b4bb6ccf0748031c3eda9f822de73a34b8979970d90f0c6",
                size=17_173_511,
            ),
            ModelFile(
                path="lineart/sk_model2.pth",
                url="https://huggingface.co/lllyasviel/Annotators/resolve/main/sk_model2.pth",
                checksum="30a534781061f34e83bb9406b4335da4ff2616c95d22a585c1245aa8363e74e0",
                size=17_173_511,
            ),
        ),
    ),
)


class UnknownModelError(KeyError):
    pass


class ModelManager:
    """Download a fixed model registry with checksums and atomic file replacement."""

    def __init__(
        self,
        model_dir: Path,
        specs: tuple[ModelSpec, ...] = MODEL_SPECS,
        opener: Callable[..., object] = urllib.request.urlopen,
    ) -> None:
        self.model_dir = model_dir.expanduser().resolve()
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._specs = {spec.id: spec for spec in specs}
        self._opener = opener
        self._lock = threading.RLock()
        self._state: dict[str, dict[str, object]] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-download")

    def _spec(self, model_id: str) -> ModelSpec:
        try:
            return self._specs[model_id]
        except KeyError as exc:
            raise UnknownModelError(model_id) from exc

    def _installed(self, spec: ModelSpec) -> bool:
        return all(
            (self.model_dir / item.path).is_file()
            and (item.size is None or (self.model_dir / item.path).stat().st_size == item.size)
            for item in spec.files
        )

    def describe(self, model_id: str) -> dict[str, object]:
        spec = self._spec(model_id)
        with self._lock:
            state = self._state.get(model_id, {}).copy()
        installed = self._installed(spec)
        state_status = str(state.get("status", "not_installed"))
        status = (
            "installed"
            if installed
            else ("not_installed" if state_status == "installed" else state_status)
        )
        return {
            "id": spec.id,
            "name": spec.name,
            "provider": spec.provider,
            "description": spec.description,
            "status": status,
            "progress": 100 if installed else int(state.get("progress", 0)),
            "downloaded_bytes": int(state.get("downloaded_bytes", 0)),
            "total_bytes": state.get("total_bytes"),
            "error": state.get("error"),
            "dependency_available": importlib.util.find_spec(spec.dependency) is not None,
            "install_hint": f'python -m pip install -e ".[{spec.install_extra}]"',
            "license": spec.license,
            "files": [item.path for item in spec.files],
            "model_dir": str(self.model_dir),
        }

    def list(self) -> list[dict[str, object]]:
        return [self.describe(model_id) for model_id in self._specs]

    def download(self, model_id: str) -> dict[str, object]:
        spec = self._spec(model_id)
        with self._lock:
            state = self._state.get(model_id, {})
            if self._installed(spec) or state.get("status") == "downloading":
                return self.describe(model_id)
            self._state[model_id] = {
                "status": "downloading",
                "progress": 0,
                "downloaded_bytes": 0,
                "total_bytes": sum(item.size or 0 for item in spec.files) or None,
                "error": None,
            }
            self._executor.submit(self._download, spec)
        return self.describe(model_id)

    def _update(self, model_id: str, **changes: object) -> None:
        with self._lock:
            self._state.setdefault(model_id, {}).update(changes)

    @staticmethod
    def _hasher(algorithm: str):
        if algorithm == "md5":
            return hashlib.md5(usedforsecurity=False)
        return hashlib.new(algorithm)

    def _download(self, spec: ModelSpec) -> None:
        downloaded = 0
        total = sum(item.size or 0 for item in spec.files)
        try:
            for item in spec.files:
                target = self.model_dir / item.path
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".part")
                request = urllib.request.Request(
                    item.url, headers={"User-Agent": f"RobotSketchStudio/{__version__}"}
                )
                digest = self._hasher(item.algorithm)
                file_downloaded = 0
                try:
                    with self._opener(request, timeout=60) as response:
                        response_size = int(response.headers.get("Content-Length", 0))
                        if not item.size and response_size:
                            total += response_size
                            self._update(spec.id, total_bytes=total)
                        with temporary.open("wb") as output:
                            while True:
                                chunk = response.read(1024 * 1024)
                                if not chunk:
                                    break
                                output.write(chunk)
                                digest.update(chunk)
                                file_downloaded += len(chunk)
                                current = downloaded + file_downloaded
                                progress = int(current * 100 / total) if total else 0
                                self._update(
                                    spec.id,
                                    downloaded_bytes=current,
                                    progress=min(progress, 99),
                                )
                    if digest.hexdigest().lower() != item.checksum.lower():
                        raise ValueError(f"Checksum verification failed for {item.path}")
                    temporary.replace(target)
                except Exception:
                    temporary.unlink(missing_ok=True)
                    raise
                downloaded += file_downloaded
            self._update(
                spec.id,
                status="installed",
                progress=100,
                downloaded_bytes=downloaded,
                total_bytes=total or downloaded,
                error=None,
            )
        except Exception as exc:
            self._update(spec.id, status="failed", error=str(exc), progress=0)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
