from __future__ import annotations

import shutil
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from robot_sketch_studio.config import Settings
from robot_sketch_studio.models import JobRecord, JobState, ProcessingOptions
from robot_sketch_studio.pipeline import SketchPipeline


class QueueFullError(RuntimeError):
    pass


class JobNotFoundError(KeyError):
    pass


class JobBusyError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobManager:
    def __init__(self, settings: Settings, pipeline: SketchPipeline | None = None) -> None:
        self.settings = settings
        self.pipeline = pipeline or SketchPipeline(settings.device, settings.model_dir)
        self.jobs_dir = settings.data_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        settings.results_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: dict[str, JobRecord] = {}
        self._futures: dict[str, Future[None]] = {}
        self._capacity = threading.BoundedSemaphore(settings.max_workers + settings.queue_size)
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_workers, thread_name_prefix="sketch-job"
        )
        self._load_records()
        self.cleanup_expired()

    def _load_records(self) -> None:
        for metadata in self.jobs_dir.glob("*/metadata.json"):
            try:
                record = JobRecord.model_validate_json(metadata.read_text(encoding="utf-8"))
                if record.state in {JobState.QUEUED, JobState.PROCESSING}:
                    record.state = JobState.FAILED
                    record.error = "Processing was interrupted by a server restart"
                    record.message = "Interrupted"
                    record.updated_at = _now()
                    self._write(record)
                self._records[record.id] = record
            except (OSError, ValueError):
                continue

    def _normalize_id(self, job_id: str) -> str:
        try:
            return str(uuid.UUID(job_id))
        except ValueError as exc:
            raise JobNotFoundError(job_id) from exc

    def _job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / self._normalize_id(job_id)

    def _result_dir(self, job_id: str) -> Path:
        return self.settings.results_dir / self._normalize_id(job_id)

    def _write(self, record: JobRecord) -> None:
        directory = self.jobs_dir / record.id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "metadata.json"
        temporary = directory / "metadata.tmp"
        temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(target)

    def submit(
        self, data: bytes, original_filename: str, suffix: str, options: ProcessingOptions
    ) -> JobRecord:
        self.cleanup_expired()
        if not self._capacity.acquire(blocking=False):
            raise QueueFullError("The processing queue is full; retry after a job finishes")
        job_id = str(uuid.uuid4())
        timestamp = _now()
        record = JobRecord(
            id=job_id,
            state=JobState.QUEUED,
            created_at=timestamp,
            updated_at=timestamp,
            original_filename=Path(original_filename).name or f"upload{suffix}",
            options=options,
        )
        try:
            job_dir = self.jobs_dir / job_id
            job_dir.mkdir(parents=True)
            source = job_dir / f"input{suffix}"
            source.write_bytes(data)
            with self._lock:
                self._records[job_id] = record
                self._write(record)
                future = self._executor.submit(self._run, job_id, source)
                future.add_done_callback(lambda _: self._capacity.release())
                self._futures[job_id] = future
        except Exception:
            self._capacity.release()
            raise
        return record.model_copy(deep=True)

    def _run(self, job_id: str, source: Path) -> None:
        self._update(job_id, state=JobState.PROCESSING, progress=10, message="Creating sketch")
        try:
            record = self.get(job_id)
            result = self.pipeline.process(source, self._result_dir(job_id), record.options)
            artifacts = {name: name for name in result.artifacts}
            self._update(
                job_id,
                state=JobState.COMPLETED,
                progress=100,
                message="Completed",
                stats=result.vector.stats,
                warnings=result.warnings,
                artifacts=artifacts,
            )
        except Exception as exc:  # The API exposes a sanitized message, not a traceback.
            self._update(
                job_id,
                state=JobState.FAILED,
                progress=100,
                message="Processing failed",
                error=str(exc) or type(exc).__name__,
            )

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            record = self._records[job_id]
            updated = record.model_copy(update={**changes, "updated_at": _now()})
            self._records[job_id] = updated
            self._write(updated)

    def get(self, job_id: str) -> JobRecord:
        normalized = self._normalize_id(job_id)
        with self._lock:
            if normalized not in self._records:
                raise JobNotFoundError(job_id)
            return self._records[normalized].model_copy(deep=True)

    def artifact_path(self, job_id: str, name: str) -> Path:
        record = self.get(job_id)
        if name not in record.artifacts or name not in {
            "sketch.png",
            "drawing.svg",
            "trajectory.json",
        }:
            raise JobNotFoundError(name)
        path = self._result_dir(record.id) / name
        if not path.is_file():
            raise JobNotFoundError(name)
        return path

    def delete(self, job_id: str) -> None:
        normalized = self._normalize_id(job_id)
        with self._lock:
            if normalized not in self._records:
                raise JobNotFoundError(job_id)
            future = self._futures.get(normalized)
            if future and not future.done() and not future.cancel():
                raise JobBusyError("A running job cannot be deleted until it finishes")
            self._records.pop(normalized, None)
            self._futures.pop(normalized, None)
        shutil.rmtree(self.jobs_dir / normalized, ignore_errors=True)
        shutil.rmtree(self.settings.results_dir / normalized, ignore_errors=True)

    def cleanup_expired(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=self.settings.job_ttl_hours)
        for job_id, record in list(self._records.items()):
            try:
                created = datetime.fromisoformat(record.created_at)
                if created < cutoff and record.state not in {JobState.QUEUED, JobState.PROCESSING}:
                    self.delete(job_id)
            except (ValueError, JobBusyError):
                continue

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
