from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SketchEngineName(StrEnum):
    OPENCV_XDOG = "opencv_xdog"
    LINEART_AI = "lineart_ai"


class BackgroundMode(StrEnum):
    OFF = "off"
    AUTO = "auto"
    PERSON = "person"
    OBJECT = "object"


class PaperPreset(StrEnum):
    A4_PORTRAIT = "a4_portrait"
    A4_LANDSCAPE = "a4_landscape"
    CUSTOM = "custom"


class ProcessingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: SketchEngineName = SketchEngineName.OPENCV_XDOG
    background: BackgroundMode = BackgroundMode.OFF
    detail: int = Field(default=55, ge=0, le=100)
    threshold: int = Field(default=185, ge=1, le=254)
    min_line_length_mm: float = Field(default=1.5, ge=0, le=100)
    smoothing: float = Field(default=1.2, ge=0, le=10)
    paper: PaperPreset = PaperPreset.A4_PORTRAIT
    page_width_mm: float = Field(default=210.0, gt=20, le=2000)
    page_height_mm: float = Field(default=297.0, gt=20, le=2000)
    margin_mm: float = Field(default=10.0, ge=0, le=200)
    stroke_width_mm: float = Field(default=0.35, gt=0, le=10)
    drawing_speed_mm_s: float = Field(default=35.0, gt=0, le=1000)
    travel_speed_mm_s: float = Field(default=90.0, gt=0, le=2000)

    @model_validator(mode="after")
    def validate_page(self) -> ProcessingOptions:
        width, height = self.page_dimensions
        if self.margin_mm * 2 >= min(width, height):
            raise ValueError("Margins leave no drawable page area")
        return self

    @property
    def page_dimensions(self) -> tuple[float, float]:
        if self.paper == PaperPreset.A4_PORTRAIT:
            return 210.0, 297.0
        if self.paper == PaperPreset.A4_LANDSCAPE:
            return 297.0, 210.0
        return self.page_width_mm, self.page_height_mm


class DrawingStats(BaseModel):
    stroke_count: int
    drawing_length_mm: float
    travel_length_mm: float
    estimated_time_seconds: float


class JobState(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRecord(BaseModel):
    id: str
    state: JobState
    created_at: str
    updated_at: str
    original_filename: str
    options: ProcessingOptions
    progress: int = Field(default=0, ge=0, le=100)
    message: str = "Queued"
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    stats: DrawingStats | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)


class ArtifactInfo(BaseModel):
    name: str
    media_type: str
    size: int
    download_url: str


class ArtifactList(BaseModel):
    job_id: str
    artifacts: list[ArtifactInfo]


class Capabilities(BaseModel):
    version: str
    engines: dict[str, dict[str, Any]]
    background_removal: dict[str, Any]
    formats: list[str]
    paper_presets: list[str]
    host_mode: bool
    author: str = "maggogerka"
