from __future__ import annotations

import types
from pathlib import Path

import app.media as media_module
from app.config import Settings
from app.media import _format_selector, _normalize_video_for_delivery, _sanitize_message, cookie_file_for_url, download_media, resolve_media


class FakeYoutubeDL:
    last_opts = None

    def __init__(self, opts):
        self.opts = opts
        FakeYoutubeDL.last_opts = opts

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
    monkeypatch.setattr(
        media_module,
        "_normalize_video_for_delivery",
        lambda path, require_audio: (
            path,
            {
                "single_file": True,
                "container": "mp4",
                "video_codec": "h264",
                "audio_codec": "aac",
                "audio_included": True,
                "quicktime_compatible": True,
            },
        ),
    )

    result = download_media("https://example.com/video", settings(tmp_path), "job1", progress_callback=lambda *_: None)

    assert Path(result["file_path"]).read_bytes() == b"video"
    assert result["filename"] == "sample-abc.mp4"
    assert result["content_type"] == "video/mp4"
    assert result["metadata"]["delivery"]["quicktime_compatible"] is True


def test_video_format_selector_prefers_h264_and_aac() -> None:
    selector = _format_selector("video", 720)

    assert selector.startswith("bestvideo[ext=mp4][vcodec^=avc1][height<=720]+bestaudio[ext=m4a][acodec^=mp4a]/")
    assert "bestvideo[height<=720]+bestaudio" in selector


def test_video_normalization_transcodes_to_single_quicktime_file(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "sample.webm"
    source.write_bytes(b"source")
    probes = iter(
        [
            {
                "streams": [
                    {"codec_type": "video", "codec_name": "vp9"},
                    {"codec_type": "audio", "codec_name": "opus"},
                ],
                "format": {"duration": "12.5"},
            },
            {
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p"},
                    {"codec_type": "audio", "codec_name": "aac", "profile": "LC"},
                ],
                "format": {"duration": "12.4"},
            },
        ]
    )
    monkeypatch.setattr(media_module, "_probe_media", lambda _path: next(probes))
    monkeypatch.setattr(media_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    commands = []

    def fake_run(command, timeout):
        commands.append((command, timeout))
        Path(command[-1]).write_bytes(b"normalized")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(media_module, "_run_media_command", fake_run)

    output, delivery = _normalize_video_for_delivery(source, require_audio=True)

    assert output == tmp_path / "sample.mp4"
    assert output.read_bytes() == b"normalized"
    assert not source.exists()
    command = commands[0][0]
    assert ["-c:v", "libx264"] == command[command.index("-c:v"):command.index("-c:v") + 2]
    assert ["-profile:a", "aac_low"] == command[command.index("-profile:a"):command.index("-profile:a") + 2]
    assert "-shortest" in command
    assert delivery["single_file"] is True
    assert delivery["audio_included"] is True
    assert delivery["quicktime_compatible"] is True


def test_video_normalization_rejects_missing_audio(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        media_module,
        "_probe_media",
        lambda _path: {"streams": [{"codec_type": "video", "codec_name": "h264"}]},
    )

    try:
        _normalize_video_for_delivery(source, require_audio=True)
    except media_module.MediaServiceError as exc:
        assert "audio track" in str(exc)
    else:
        raise AssertionError("video downloads must not silently return a video-only file")


def test_ytdlp_proxy_url_is_passed_to_resolve(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    cfg = Settings(
        media_tmp_dir=tmp_path / "media",
        media_ttl_seconds=1800,
        max_concurrent_downloads=1,
        max_download_mb=10,
        default_max_height=720,
        ytdlp_proxy_url="socks5://user:pass@proxy.example:1080",
    )

    resolve_media("https://example.com/video", cfg)

    assert FakeYoutubeDL.last_opts["proxy"] == "socks5://user:pass@proxy.example:1080"


def test_proxy_secrets_are_redacted(tmp_path: Path) -> None:
    cfg = Settings(
        media_tmp_dir=tmp_path / "media",
        media_ttl_seconds=1800,
        max_concurrent_downloads=1,
        max_download_mb=10,
        default_max_height=720,
        webshare_proxy_password="super-secret",
        ytdlp_proxy_url="socks5://user:pass@proxy.example:1080",
    )

    redacted = cfg.redact("failed super-secret via socks5://user:pass@proxy.example:1080")

    assert "super-secret" not in redacted
    assert "socks5://user:pass@proxy.example:1080" not in redacted


def test_ytdlp_browser_cookie_advice_is_replaced_with_remote_service_context(tmp_path: Path) -> None:
    raw = (
        "ERROR: [Instagram] abc: Instagram sent an empty media response. "
        "Check if this post is accessible in your browser without being logged-in. "
        "If it is not, use --cookies-from-browser for authentication. "
        "See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp"
    )

    sanitized = _sanitize_message(raw, settings(tmp_path))

    assert "Instagram sent an empty media response" in sanitized
    assert "own server" in sanitized
    assert "will not affect this request" in sanitized
    assert "browser cookies are not sent to FreeSkillz" in sanitized
    assert "FreeSkillz server operator" in sanitized
    assert "Check if this post" not in sanitized
    assert "--cookies" not in sanitized
    assert "how-do-i-pass-cookies" not in sanitized


def test_media_errors_without_browser_auth_advice_keep_their_provider_detail(tmp_path: Path) -> None:
    raw = "ERROR: upstream extractor timed out while reading the public media URL"

    assert _sanitize_message(raw, settings(tmp_path)) == raw
