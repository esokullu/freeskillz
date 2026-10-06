from __future__ import annotations

import json
import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from yt_dlp.networking.common import Response
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import DownloadError

import app.media as media
from app.config import Settings
from app.jobs import JobManager
from app.main import create_app


def settings(tmp_path: Path) -> Settings:
    return Settings(
        media_tmp_dir=tmp_path / "media",
        media_ttl_seconds=1800,
        max_concurrent_downloads=1,
        max_download_mb=10,
        default_max_height=720,
        ytdlp_cookies_dir=tmp_path / "cookies",
        ytdlp_proxy_url="socks5://user:secret@proxy.example:1080",
    )


def fail_extraction(monkeypatch, error: Exception) -> None:
    class FailingYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, download):
            raise error

    monkeypatch.setattr(media, "_youtube_dl_class", lambda: FailingYoutubeDL)


def bluesky_error(payload: bytes) -> DownloadError:
    response = Response(
        BytesIO(payload),
        "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread",
        {"Content-Type": "application/json"},
        status=400,
    )
    upstream = HTTPError(response)
    return DownloadError(
        "ERROR: [Bluesky] abc: Unable to download JSON metadata: HTTP Error 400: Bad Request",
        exc_info=(type(upstream), upstream, None),
    )


@pytest.mark.parametrize("operation", ["resolve", "download"])
@pytest.mark.parametrize(
    "url,message,code,status,fragment",
    [
        (
            "https://www.facebook.com/reel/123",
            "ERROR: [facebook] 123: Cannot parse data; please report this issue",
            "extractor_error", 502, "does not confirm an expired server session",
        ),
        (
            "https://x.com/example/status/123",
            "ERROR: [twitter] 123: Could not authenticate you via socks5://user:secret@proxy.example:1080",
            "authentication_required", 403, "FreeSkillz server operator",
        ),
        (
            "https://www.youtube.com/watch?v=deleted",
            "ERROR: This video has been removed. Use --cookies-from-browser for authentication.",
            "media_unavailable", 404, "deleted or removed post",
        ),
        (
            "https://www.youtube.com/watch?v=agegate",
            "ERROR: This video is unavailable. Sign in to confirm your age. Use --cookies-from-browser for authentication.",
            "authentication_required", 403, "FreeSkillz server operator",
        ),
        (
            "https://example.com/video",
            "ERROR: This video is available but no downloadable formats were returned",
            "extractor_error", 502, "no downloadable formats",
        ),
        (
            "https://example.com/video",
            "ERROR: Request timed out via socks5://user:secret@proxy.example:1080",
            "extractor_error", 502, "Request timed out",
        ),
    ],
)
def test_extractor_failure_classification(monkeypatch, tmp_path, operation, url, message, code, status, fragment):
    fail_extraction(monkeypatch, RuntimeError(message))
    cfg = settings(tmp_path)
    with pytest.raises(media.MediaServiceError) as raised:
        if operation == "resolve":
            media.resolve_media(url, cfg)
        else:
            media.download_media(url, cfg, "failed-job", kind="video")
    assert raised.value.code == code
    assert raised.value.status_code == status
    assert fragment in str(raised.value)
    assert "user:secret" not in str(raised.value)
    assert "--cookies" not in str(raised.value)


@pytest.mark.parametrize(
    "payload,code,status",
    [
        (json.dumps({"error": "NotFound", "message": "Post not found: at://example/post/123"}).encode(), "media_unavailable", 404),
        (json.dumps({"error": "InvalidRequest", "message": "Invalid URI"}).encode(), "extractor_error", 502),
        (b"not JSON", "extractor_error", 502),
    ],
)
def test_bluesky_requires_confirmed_not_found(monkeypatch, tmp_path, payload, code, status):
    fail_extraction(monkeypatch, bluesky_error(payload))
    with pytest.raises(media.MediaServiceError) as raised:
        media.resolve_media("https://bsky.app/profile/example/post/123", settings(tmp_path))
    assert raised.value.code == code
    assert raised.value.status_code == status


@pytest.mark.parametrize(
    "url,error,code,status",
    [
        ("https://bsky.app/profile/example/post/123", "Post not found: at://example/post/123", "media_unavailable", 404),
        ("https://x.com/example/status/123", "Could not authenticate you", "authentication_required", 403),
        ("https://facebook.com/reel/123", "Cannot parse data", "extractor_error", 502),
    ],
)
def test_resolve_api_preserves_detail_and_adds_error_code(monkeypatch, tmp_path, url, error, code, status):
    fail_extraction(monkeypatch, RuntimeError(error))
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/v1/media/resolve", json={"url": url})
    assert response.status_code == status
    assert response.json()["error_code"] == code
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]


def test_failed_download_job_exposes_unavailable_code(monkeypatch, tmp_path):
    fail_extraction(monkeypatch, bluesky_error(b'{"error":"NotFound","message":"Post not found: at://example/post/123"}'))
    cfg = settings(tmp_path)
    manager = JobManager(cfg)
    try:
        with TestClient(create_app(cfg, job_manager=manager)) as client:
            created = client.post("/v1/media/jobs", json={"url": "https://bsky.app/profile/example/post/123", "kind": "video"})
            job_id = created.json()["job_id"]
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                result = client.get(f"/v1/media/jobs/{job_id}").json()
                if result["status"] == "failed":
                    break
                time.sleep(0.02)
            assert result["status"] == "failed"
            assert result["error_code"] == "media_unavailable"
            assert "upstream post or media is unavailable" in result["error"]
            assert "HTTP Error 400" not in result["error"]
            assert client.delete(f"/v1/media/jobs/{job_id}").json()["deleted"] is True
    finally:
        manager._executor.shutdown(wait=True)
