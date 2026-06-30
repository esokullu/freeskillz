from __future__ import annotations

import time
from pathlib import Path

from app.config import Settings
from app.jobs import JobManager, now_utc


def settings(tmp_path: Path) -> Settings:
    return Settings(
        media_tmp_dir=tmp_path / "media",
        media_ttl_seconds=1,
        max_concurrent_downloads=1,
        max_download_mb=10,
        default_max_height=720,
    )


def fake_downloader(url, cfg, job_id, kind="auto", max_height=None, progress_callback=None):
    output_dir = cfg.media_tmp_dir / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "sample.mp4"
    output.write_bytes(b"video")
    if progress_callback:
        progress_callback(50.0, "downloading")
    return {
        "file_path": str(output),
        "filename": output.name,
        "content_type": "video/mp4",
        "metadata": {"title": "Sample"},
    }


def wait_for_status(manager: JobManager, job_id: str, status: str):
    deadline = time.time() + 3
    while time.time() < deadline:
        job = manager.get_job(job_id)
        if job and job.status == status:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job did not reach {status}")


def test_job_lifecycle_completes(tmp_path: Path) -> None:
    manager = JobManager(settings(tmp_path), downloader=fake_downloader)

    job = manager.create_job("https://example.com/video", "auto", 720)
    completed = wait_for_status(manager, job.job_id, "complete")

    assert completed.progress == 100.0
    assert completed.metadata == {"title": "Sample"}
    assert Path(completed.file_path).exists()


def test_expired_job_removes_file(tmp_path: Path) -> None:
    manager = JobManager(settings(tmp_path), downloader=fake_downloader)
    job = manager.create_job("https://example.com/video", "auto", 720)
    completed = wait_for_status(manager, job.job_id, "complete")

    completed.expires_at = now_utc()
    expired = manager.get_job(job.job_id)

    assert expired.status == "expired"
    assert expired.file_path is None


def test_delete_completed_job_removes_file(tmp_path: Path) -> None:
    manager = JobManager(settings(tmp_path), downloader=fake_downloader)
    job = manager.create_job("https://example.com/video", "auto", 720)
    completed = wait_for_status(manager, job.job_id, "complete")
    file_path = Path(completed.file_path)

    deleted = manager.delete_job(job.job_id)

    assert deleted.job_id == job.job_id
    assert not file_path.exists()
    assert manager.get_job(job.job_id) is None
