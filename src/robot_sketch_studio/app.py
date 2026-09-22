from __future__ import annotations

import hmac
import json
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from robot_sketch_studio import __version__
from robot_sketch_studio.config import Settings
from robot_sketch_studio.jobs import JobBusyError, JobManager, JobNotFoundError, QueueFullError
from robot_sketch_studio.models import ArtifactInfo, ArtifactList, Capabilities, ProcessingOptions

STATIC_DIR = Path(__file__).with_name("static")
FORMAT_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MEDIA_TYPES = {
    "sketch.png": "image/png",
    "drawing.svg": "image/svg+xml",
    "trajectory.json": "application/json",
}


def _detect_image(data: bytes) -> str:
    try:
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 50_000_000:
                raise HTTPException(status_code=413, detail="Decoded image exceeds 50 megapixels")
            image.verify()
            image_format = image.format or ""
        if image_format not in FORMAT_SUFFIXES:
            raise HTTPException(status_code=415, detail="Only JPG, PNG, and WebP are supported")
        return FORMAT_SUFFIXES[image_format]
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(
            status_code=400, detail="The uploaded file is not a valid image"
        ) from exc


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    config.prepare()
    manager = JobManager(config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        manager.close()

    app = FastAPI(
        title="Robot Sketch Studio",
        description="Photo-to-vector sketch pipeline. Developed by maggogerka.",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = config
    app.state.jobs = manager
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def bearer_auth(request: Request, call_next):
        if config.host_mode and request.url.path.startswith("/api/"):
            header = request.headers.get("authorization", "")
            expected = f"Bearer {config.api_token}"
            if not hmac.compare_digest(header, expected):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "A valid Bearer API token is required"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/v1/capabilities", response_model=Capabilities)
    def capabilities() -> Capabilities:
        available = manager.pipeline.capabilities()
        return Capabilities(
            version=__version__,
            engines=available["engines"],
            background_removal=available["background_removal"],
            formats=["jpg", "png", "webp"],
            paper_presets=["a4_portrait", "a4_landscape", "custom"],
            host_mode=config.host_mode,
        )

    @app.post("/api/v1/jobs", status_code=202)
    async def create_job(image: UploadFile = File(...), options: str = Form(default="{}")):
        content_length = image.headers.get("content-length")
        limit = config.max_upload_mb * 1024 * 1024
        if content_length and int(content_length) > limit:
            raise HTTPException(
                status_code=413, detail=f"Maximum upload size is {config.max_upload_mb} MB"
            )
        data = await image.read(limit + 1)
        await image.close()
        if len(data) > limit:
            raise HTTPException(
                status_code=413, detail=f"Maximum upload size is {config.max_upload_mb} MB"
            )
        suffix = _detect_image(data)
        try:
            parsed_options = ProcessingOptions.model_validate(json.loads(options))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid processing options: {exc}"
            ) from exc
        try:
            return manager.submit(data, image.filename or f"upload{suffix}", suffix, parsed_options)
        except QueueFullError as exc:
            raise HTTPException(
                status_code=429, detail=str(exc), headers={"Retry-After": "2"}
            ) from exc

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return manager.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/api/v1/jobs/{job_id}/artifacts", response_model=ArtifactList)
    def get_artifacts(job_id: str) -> ArtifactList:
        try:
            record = manager.get(job_id)
            artifacts = [
                ArtifactInfo(
                    name=name,
                    media_type=MEDIA_TYPES[name],
                    size=manager.artifact_path(job_id, name).stat().st_size,
                    download_url=f"/api/v1/jobs/{job_id}/artifacts/{name}",
                )
                for name in record.artifacts
            ]
            return ArtifactList(job_id=job_id, artifacts=artifacts)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job or artifact not found") from exc

    @app.get("/api/v1/jobs/{job_id}/artifacts/{name}")
    def download_artifact(job_id: str, name: str) -> FileResponse:
        try:
            return FileResponse(
                manager.artifact_path(job_id, name),
                media_type=MEDIA_TYPES[name],
                filename=name,
            )
        except (JobNotFoundError, KeyError) as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc

    @app.delete("/api/v1/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str) -> None:
        try:
            manager.delete(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except JobBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
