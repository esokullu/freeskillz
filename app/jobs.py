from __future__ import annotations

import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .media import download_media


Downloader = Callable[..., dict[str, Any]]


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass
class MediaJob:
    job_id: str
    url: str
    kind: str
    max_height: int | None
    status: str = "queued"
    progress: float = 0.0
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)
    expires_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    error: str | None = None
    file_path: str | None = None
    filename: str | None = None
    content_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "url": self.url,
            "kind": self.kind,
            "max_height": self.max_height,
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
            "error": self.error,
            "file_url": f"/v1/media/jobs/{self.job_id}/file" if self.status == "complete" else None,
        }


class JobManager:
    def __init__(self, settings: Settings, downloader: Downloader = download_media) -> None:
        self.settings = settings
        self.downloader = downloader
        self._jobs: dict[str, MediaJob] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=settings.max_concurrent_downloads)
        settings.media_tmp_dir.mkdir(parents=True, exist_ok=True)

    def create_job(self, url: str, kind: str, max_height: int | None) -> MediaJob:
        self.cleanup_expired()
        job = MediaJob(job_id=uuid.uuid4().hex, url=url, kind=kind, max_height=max_height)
        with self._lock:
            self._jobs[job.job_id] = job
        self._executor.submit(self._run_job, job.job_id)
        return job

    def get_job(self, job_id: str) -> MediaJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job:
            self._expire_if_needed(job)
        return job

    def get_file(self, job_id: str) -> tuple[MediaJob, Path] | tuple[None, None]:
        job = self.get_job(job_id)
        if not job or not job.file_path:
            return None, None
        return job, Path(job.file_path)

    def delete_job(self, job_id: str) -> MediaJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.status in {"queued", "running"}:
                return job
            self._jobs.pop(job_id, None)

        self._remove_job_files(job)
        return job

    def cleanup_expired(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            self._expire_if_needed(job)

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.updated_at = now_utc()

        def update_progress(percent: float, _status: str | None) -> None:
            with self._lock:
                job.progress = max(job.progress, percent)
                job.updated_at = now_utc()

        try:
            result = self.downloader(
                job.url,
                self.settings,
                job.job_id,
                kind=job.kind,
                max_height=job.max_height,
                progress_callback=update_progress,
            )
        except Exception as exc:
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.progress = 100.0
                job.updated_at = now_utc()
            return

        with self._lock:
            job.status = "complete"
            job.progress = 100.0
            job.updated_at = now_utc()
            job.expires_at = job.updated_at + timedelta(seconds=self.settings.media_ttl_seconds)
            job.metadata = result.get("metadata")
            job.file_path = result.get("file_path")
            job.filename = result.get("filename")
            job.content_type = result.get("content_type")

    def _expire_if_needed(self, job: MediaJob) -> None:
        if job.status != "complete" or not job.expires_at or job.expires_at > now_utc():
            return

        self._remove_job_files(job)
        with self._lock:
            job.status = "expired"
            job.file_path = None
            job.progress = 100.0
            job.updated_at = now_utc()

    def _remove_job_files(self, job: MediaJob) -> None:
        file_path = Path(job.file_path) if job.file_path else None
        job_dir = self.settings.media_tmp_dir / job.job_id
        if file_path and file_path.exists():
            file_path.unlink(missing_ok=True)
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
