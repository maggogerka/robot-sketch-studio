from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load a small, dependency-free subset of dotenv syntax."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _default_runtime_dir() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "RobotSketchStudio"
    return Path.home() / ".local" / "share" / "robot-sketch-studio"


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    api_token: str | None = None
    device: str = "auto"
    model_dir: Path = field(default_factory=lambda: _default_runtime_dir() / "models")
    data_dir: Path = field(default_factory=lambda: _default_runtime_dir() / "data")
    results_dir: Path = field(default_factory=lambda: _default_runtime_dir() / "results")
    max_upload_mb: int = 20
    job_ttl_hours: int = 24
    cors_origins: list[str] = field(default_factory=list)
    max_workers: int = 2
    queue_size: int = 4
    comfyui_workflow: Path | None = None
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = ""
    ollama_api_key: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv()
        runtime = _default_runtime_dir()
        return cls(
            host=os.getenv("SKETCHARM_HOST", "127.0.0.1"),
            port=int(os.getenv("SKETCHARM_PORT", "8000")),
            api_token=os.getenv("SKETCHARM_API_TOKEN") or None,
            device=os.getenv("SKETCHARM_DEVICE", "auto"),
            model_dir=Path(os.getenv("SKETCHARM_MODEL_DIR", runtime / "models")),
            data_dir=Path(os.getenv("SKETCHARM_DATA_DIR", runtime / "data")),
            results_dir=Path(os.getenv("SKETCHARM_RESULTS_DIR", runtime / "results")),
            max_upload_mb=int(os.getenv("SKETCHARM_MAX_UPLOAD_MB", "20")),
            job_ttl_hours=int(os.getenv("SKETCHARM_JOB_TTL_HOURS", "24")),
            cors_origins=_split_csv(os.getenv("SKETCHARM_CORS_ORIGINS", "")),
            max_workers=max(1, int(os.getenv("SKETCHARM_MAX_WORKERS", "2"))),
            queue_size=max(0, int(os.getenv("SKETCHARM_QUEUE_SIZE", "4"))),
            comfyui_workflow=(
                Path(os.environ["SKETCHARM_COMFYUI_WORKFLOW"])
                if os.getenv("SKETCHARM_COMFYUI_WORKFLOW")
                else None
            ),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
            ollama_model=os.getenv("OLLAMA_MODEL", ""),
            ollama_api_key=os.getenv("OLLAMA_API_KEY", ""),
        )

    @property
    def host_mode(self) -> bool:
        return self.host not in {"127.0.0.1", "localhost", "::1"}

    def prepare(self) -> None:
        if self.host_mode and not self.api_token:
            raise ValueError("SKETCHARM_API_TOKEN is required when host mode is enabled")
        for path in (self.model_dir, self.data_dir, self.results_dir):
            path.expanduser().resolve().mkdir(parents=True, exist_ok=True)
