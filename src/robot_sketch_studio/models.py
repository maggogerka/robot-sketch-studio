from __future__ import annotations

from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SketchEngineName(StrEnum):
    CLEAN_AI = "clean_ai"
    ARTISTIC_REMOTE = "artistic_remote"
    OPENCV_XDOG = "opencv_xdog"
    # Compatibility alias for saved v0.2 jobs and API clients.
    LINEART_AI = "lineart_ai"


class BackgroundMode(StrEnum):
    OFF = "off"
    AUTO = "auto"
    PERSON = "person"
    OBJECT = "object"


class ImageProfile(StrEnum):
    AUTO = "auto"
    PHOTO = "photo"
    PORTRAIT = "portrait"
    OBJECT = "object"
    DOCUMENT = "document"
    LINE_DRAWING = "line_drawing"


class DrawingPreset(StrEnum):
    DEXARM_FIDELITY = "dexarm_fidelity"
    MINIMAL = "minimal"
    BALANCED = "balanced"
    DETAILED = "detailed"


class VectorizationMode(StrEnum):
    PLOTTER_FIDELITY = "plotter_fidelity"
    CENTERLINE = "centerline"
    MINIMAL = "minimal"


class FillStrategy(StrEnum):
    CONTOUR = "contour"
    PARALLEL = "parallel"
    NONE = "none"


class RemoteBackendName(StrEnum):
    OPENAI_IMAGES = "openai_images"
    COMFYUI = "comfyui"


class PaperPreset(StrEnum):
    A4_PORTRAIT = "a4_portrait"
    A4_LANDSCAPE = "a4_landscape"
    CUSTOM = "custom"


PRESET_DEFAULTS: dict[DrawingPreset, dict[str, float | int | bool | StrEnum]] = {
    DrawingPreset.DEXARM_FIDELITY: {
        "vectorization_mode": VectorizationMode.PLOTTER_FIDELITY,
        "pen_width_mm": 0.5,
        "ink_coverage_target": 0.97,
        "fill_strategy": FillStrategy.CONTOUR,
        "minimum_path_length_mm": 0.25,
        "minimum_feature_size_mm": 0.15,
        "curve_fit_tolerance_mm": 0.08,
        "join_distance_mm": 0.35,
        "maximum_join_angle_deg": 25.0,
        "maximum_plotter_paths": 3000,
        "preserve_short_details": True,
    },
    DrawingPreset.MINIMAL: {
        "vectorization_mode": VectorizationMode.MINIMAL,
        "target_paths": 16,
        "minimum_path_length_mm": 4.0,
        "join_distance_mm": 2.0,
        "maximum_join_angle_deg": 20.0,
        "minimum_feature_size_mm": 1.2,
        "curve_fit_tolerance_mm": 0.5,
    },
    DrawingPreset.BALANCED: {
        "vectorization_mode": VectorizationMode.CENTERLINE,
        "target_paths": 32,
        "minimum_path_length_mm": 2.5,
        "join_distance_mm": 1.5,
        "maximum_join_angle_deg": 25.0,
        "minimum_feature_size_mm": 0.8,
        "curve_fit_tolerance_mm": 0.3,
    },
    DrawingPreset.DETAILED: {
        "vectorization_mode": VectorizationMode.CENTERLINE,
        "target_paths": 64,
        "minimum_path_length_mm": 1.5,
        "join_distance_mm": 1.0,
        "maximum_join_angle_deg": 30.0,
        "minimum_feature_size_mm": 0.5,
        "curve_fit_tolerance_mm": 0.2,
    },
}


class ProcessingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: SketchEngineName = SketchEngineName.CLEAN_AI
    background: BackgroundMode = BackgroundMode.OFF
    profile: ImageProfile = ImageProfile.AUTO
    drawing_preset: DrawingPreset = DrawingPreset.DEXARM_FIDELITY
    vectorization_mode: VectorizationMode = VectorizationMode.PLOTTER_FIDELITY
    detail: int = Field(default=55, ge=0, le=100)
    threshold: int = Field(default=185, ge=1, le=254)
    target_paths: int = Field(default=32, ge=4, le=512)
    minimum_path_length_mm: float = Field(default=2.5, ge=0, le=100)
    join_distance_mm: float = Field(default=1.5, ge=0, le=20)
    maximum_join_angle_deg: float = Field(default=25.0, ge=0, le=90)
    minimum_feature_size_mm: float = Field(default=0.8, ge=0, le=20)
    curve_fit_tolerance_mm: float = Field(default=0.3, gt=0, le=10)
    # v0.2 request compatibility. New clients use the fields above.
    min_line_length_mm: float | None = Field(default=None, ge=0, le=100)
    smoothing: float | None = Field(default=None, ge=0, le=10)
    paper: PaperPreset = PaperPreset.A4_PORTRAIT
    page_width_mm: float = Field(default=210.0, gt=20, le=2000)
    page_height_mm: float = Field(default=297.0, gt=20, le=2000)
    margin_mm: float = Field(default=10.0, ge=0, le=200)
    stroke_width_mm: float = Field(default=0.35, gt=0, le=10)
    pen_width_mm: float = Field(default=0.5, ge=0.2, le=2.0)
    ink_coverage_target: float = Field(default=0.97, ge=0.80, le=0.995)
    fill_strategy: FillStrategy = FillStrategy.CONTOUR
    maximum_plotter_paths: int = Field(default=3000, ge=100, le=10000)
    preserve_short_details: bool = True
    generate_difference_preview: bool = True
    drawing_speed_mm_s: float = Field(default=35.0, gt=0, le=1000)
    travel_speed_mm_s: float = Field(default=90.0, gt=0, le=2000)
    remote_backend: RemoteBackendName = RemoteBackendName.OPENAI_IMAGES
    remote_url: str | None = None
    remote_model: str | None = None

    @field_validator("remote_url")
    @classmethod
    def validate_remote_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise ValueError("remote_url must be an http(s) URL")
        return value

    @model_validator(mode="after")
    def validate_page(self) -> ProcessingOptions:
        width, height = self.page_dimensions
        if self.margin_mm * 2 >= min(width, height):
            raise ValueError("Margins leave no drawable page area")
        if (
            self.engine == SketchEngineName.OPENCV_XDOG
            and "drawing_preset" not in self.model_fields_set
            and "vectorization_mode" not in self.model_fields_set
        ):
            object.__setattr__(self, "drawing_preset", DrawingPreset.BALANCED)
        defaults = PRESET_DEFAULTS[self.drawing_preset]
        for field_name, value in defaults.items():
            if field_name not in self.model_fields_set:
                object.__setattr__(self, field_name, value)
        if self.engine == SketchEngineName.ARTISTIC_REMOTE and not self.remote_url:
            raise ValueError("remote_url is required for artistic_remote")
        return self

    @property
    def page_dimensions(self) -> tuple[float, float]:
        if self.paper == PaperPreset.A4_PORTRAIT:
            return 210.0, 297.0
        if self.paper == PaperPreset.A4_LANDSCAPE:
            return 297.0, 210.0
        return self.page_width_mm, self.page_height_mm

    @property
    def effective_minimum_path_length_mm(self) -> float:
        if self.min_line_length_mm is not None:
            return self.min_line_length_mm
        return self.minimum_path_length_mm

    @property
    def effective_curve_tolerance_mm(self) -> float:
        return self.smoothing if self.smoothing is not None else self.curve_fit_tolerance_mm


class DrawingStats(BaseModel):
    stroke_count: int
    drawing_length_mm: float
    travel_length_mm: float
    estimated_time_seconds: float
    average_path_length_mm: float = 0.0
    curve_segment_count: int = 0
    pen_lifts: int = 0
    ink_recall: float = 0.0
    ink_precision: float = 0.0
    ink_iou: float = 0.0
    coverage_difference: float = 0.0
    mean_line_distance_mm: float = 0.0
    source_ink_area_px: int = 0
    rendered_ink_area_px: int = 0
    source_ink_area: int = 0
    rendered_ink_area: int = 0


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
    image_profiles: list[str]
    drawing_presets: list[str] = Field(default_factory=list)
    remote_backends: list[str] = Field(default_factory=list)
    vectorization_modes: list[str] = Field(default_factory=list)
    fill_strategies: list[str] = Field(default_factory=list)
    host_mode: bool
    author: str = "maggogerka"


class RemoteConnectionRequest(BaseModel):
    backend: RemoteBackendName
    url: str
    model: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise ValueError("url must be an http(s) URL")
        return value
