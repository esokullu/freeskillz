from __future__ import annotations

import types
from pathlib import Path

from app.config import Settings
from app.media import cookie_file_for_url, download_media, resolve_media


class FakeYoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download):
        info = {
            "id": "abc",
            "title": "Sample",
            "extractor": "Generic",
            "webpage_url": url,
            "thumbnail": "https://example.com/thumb.jpg",
            "duration": 12.5,
            "ext": "mp4",
            "vcodec": "h264",
            "acodec": "aac",
            "formats": [{"format_id": "18", "ext": "mp4", "height": 360, "vcodec": "h264"}],
        }
        if download:
            outtmpl = Path(self.opts["outtmpl"])
            output = outtmpl.parent / "sample-abc.mp4"
            output.write_bytes(b"video")
            info["_filename"] = str(output)
        return info


def settings(tmp_path: Path) -> Settings:
    return Settings(
        media_tmp_dir=tmp_path / "media",
        media_ttl_seconds=1800,
        max_concurrent_downloads=1,
        max_download_mb=10,
        default_max_height=720,
        ytdlp_cookies_dir=tmp_path / "cookies",
    )


def test_cookie_file_for_url_prefers_global_cookie_file(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    cfg.ytdlp_cookies_dir.mkdir()
    cookie_file = cfg.ytdlp_cookies_dir / "cookies.txt"
    cookie_file.write_text("# netscape cookie file\n")

    assert cookie_file_for_url("https://www.instagram.com/p/example", cfg) == cookie_file


def test_resolve_media_uses_ytdlp_without_download(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    result = resolve_media("https://example.com/video", settings(tmp_path))

    assert result["title"] == "Sample"
    assert result["media_type"] == "video"
    assert result["formats"][0]["format_id"] == "18"


def test_download_media_returns_created_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    result = download_media("https://example.com/video", settings(tmp_path), "job1", progress_callback=lambda *_: None)

    assert Path(result["file_path"]).read_bytes() == b"video"
    assert result["filename"] == "sample-abc.mp4"
    assert result["content_type"] == "video/mp4"
