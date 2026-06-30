from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import MediaJob
from app.main import create_app
from app.transcripts import TranscriptServiceError


def settings(tmp_path: Path) -> Settings:
    return Settings(
        media_tmp_dir=tmp_path / "media",
        media_ttl_seconds=1800,
        max_concurrent_downloads=1,
        max_download_mb=10,
        default_max_height=720,
    )


class FakeJobManager:
    def __init__(self, file_path: Path | None = None, status: str = "complete") -> None:
        self.file_path = file_path
        self.status = status
        self.created = None

    def create_job(self, url: str, kind: str, max_height: int | None):
        self.created = (url, kind, max_height)
        return MediaJob(job_id="job1", url=url, kind=kind, max_height=max_height)

    def get_job(self, job_id: str):
        if job_id == "missing":
            return None
        job = MediaJob(job_id=job_id, url="https://example.com/video", kind="auto", max_height=720)
        job.status = self.status
        job.file_path = str(self.file_path) if self.file_path else None
        job.filename = self.file_path.name if self.file_path else None
        job.content_type = "video/mp4"
        return job

    def get_file(self, job_id: str):
        job = self.get_job(job_id)
        if not job:
            return None, None
        return job, self.file_path

    def delete_job(self, job_id: str):
        return self.get_job(job_id)


def client(tmp_path: Path, job_manager=None) -> TestClient:
    return TestClient(create_app(settings(tmp_path), job_manager=job_manager or FakeJobManager()))


def test_healthz_is_public(tmp_path: Path) -> None:
    response = client(tmp_path).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_is_public(tmp_path: Path) -> None:
    response = client(tmp_path).get("/")
    assert response.status_code == 200
    assert "FreeSkillz.xyz API" in response.text


def test_skills_markdown_is_public(tmp_path: Path) -> None:
    response = client(tmp_path).get("/skills.md")
    assert response.status_code == 200
    assert "FreeSkillz Agent Usage Guide" in response.text


def test_transcript_endpoint_success(monkeypatch, tmp_path: Path) -> None:
    def fake_fetch(url, lang=None, timestamps=False, settings=None):
        return {
            "video_id": "dQw4w9WgXcQ",
            "selected_language": lang,
            "text": "hello",
            "segments": [{"text": "hello", "start": 0.0, "duration": 1.0, "timestamp": "0:00"}],
        }

    monkeypatch.setattr("app.main.fetch_youtube_transcript", fake_fetch)
    response = client(tmp_path).post(
        "/v1/youtube/transcript",
        json={"url": "dQw4w9WgXcQ", "lang": "en", "timestamps": True},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "hello"


def test_transcript_errors_are_mapped(monkeypatch, tmp_path: Path) -> None:
    def fake_fetch(*_args, **_kwargs):
        raise TranscriptServiceError("provider failed")

    monkeypatch.setattr("app.main.fetch_youtube_transcript", fake_fetch)
    response = client(tmp_path).post(
        "/v1/youtube/transcript",
        json={"url": "dQw4w9WgXcQ"},
    )

    assert response.status_code == 502


def test_media_job_create_and_status(tmp_path: Path) -> None:
    manager = FakeJobManager()
    app_client = client(tmp_path, manager)

    response = app_client.post(
        "/v1/media/jobs",
        json={"url": "https://example.com/video", "kind": "video", "max_height": 360},
    )
    assert response.status_code == 200
    assert response.json()["job_id"] == "job1"
    assert manager.created == ("https://example.com/video", "video", 360)

    status = app_client.get("/v1/media/jobs/job1")
    assert status.status_code == 200
    assert status.json()["status"] == "complete"


def test_expired_file_returns_410(tmp_path: Path) -> None:
    manager = FakeJobManager(status="expired")
    response = client(tmp_path, manager).get("/v1/media/jobs/job1/file")
    assert response.status_code == 410


def test_delete_completed_job(tmp_path: Path) -> None:
    manager = FakeJobManager(status="complete")
    response = client(tmp_path, manager).delete("/v1/media/jobs/job1")
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "job_id": "job1"}


def test_delete_running_job_is_rejected(tmp_path: Path) -> None:
    manager = FakeJobManager(status="running")
    response = client(tmp_path, manager).delete("/v1/media/jobs/job1")
    assert response.status_code == 409
