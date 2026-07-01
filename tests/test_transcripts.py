from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import Settings
from app.transcripts import (
    build_transcript_proxy_config,
    extract_video_id,
    fetch_youtube_transcript,
    format_timestamp,
    preferred_language_order,
)


@dataclass
class Language:
    language_code: str
    language: str
    is_generated: bool = False


class FakeApi:
    def __init__(self) -> None:
        self.fetch_languages = None

    def list(self, video_id: str):
        assert video_id == "dQw4w9WgXcQ"
        return [Language("en", "English"), Language("tr", "Turkish", True)]

    def fetch(self, video_id: str, languages: list[str]):
        assert video_id == "dQw4w9WgXcQ"
        self.fetch_languages = languages
        return [
            {"text": "hello", "start": 1.2, "duration": 2.0},
            {"text": "world", "start": 61.0, "duration": 1.5},
        ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_extract_video_id(value: str, expected: str) -> None:
    assert extract_video_id(value) == expected


def test_extract_video_id_rejects_invalid_input() -> None:
    with pytest.raises(ValueError):
        extract_video_id("https://example.com/nope")


def test_format_timestamp() -> None:
    assert format_timestamp(61.5) == "1:01"
    assert format_timestamp(3661) == "1:01:01"


def test_preferred_language_order_moves_requested_language_first() -> None:
    assert preferred_language_order(["en", "tr", "en"], "tr") == ["tr", "en"]


def test_fetch_transcript_returns_text_segments_and_language_priority() -> None:
    api = FakeApi()
    result = fetch_youtube_transcript("dQw4w9WgXcQ", lang="tr", timestamps=True, api=api)

    assert api.fetch_languages == ["tr", "en"]
    assert result["video_id"] == "dQw4w9WgXcQ"
    assert result["text"] == "hello\nworld"
    assert result["text_length"] == len("hello\nworld")
    assert result["has_more_text"] is False
    assert result["next_text_offset"] is None
    assert result["total_segments"] == 2
    assert result["segments_included"] is True
    assert result["segments"][0]["timestamp"] == "0:01"


def test_fetch_transcript_can_page_text_without_segments() -> None:
    api = FakeApi()
    result = fetch_youtube_transcript(
        "dQw4w9WgXcQ",
        text_offset=0,
        text_limit=7,
        include_segments=False,
        api=api,
    )

    assert result["text"] == "hello\nw"
    assert result["text_length"] == len("hello\nworld")
    assert result["text_offset"] == 0
    assert result["text_limit"] == 7
    assert result["has_more_text"] is True
    assert result["next_text_offset"] == 7
    assert result["segments"] == []
    assert result["total_segments"] == 2
    assert result["segments_included"] is False


def test_fetch_transcript_continues_from_text_offset() -> None:
    api = FakeApi()
    result = fetch_youtube_transcript(
        "dQw4w9WgXcQ",
        text_offset=7,
        text_limit=20,
        include_segments=False,
        api=api,
    )

    assert result["text"] == "orld"
    assert result["has_more_text"] is False
    assert result["next_text_offset"] is None


def test_builds_webshare_proxy_config(tmp_path) -> None:
    cfg = Settings(
        media_tmp_dir=tmp_path / "media",
        media_ttl_seconds=1800,
        max_concurrent_downloads=1,
        max_download_mb=10,
        default_max_height=720,
        webshare_proxy_username="user",
        webshare_proxy_password="pass",
        webshare_filter_ip_locations=("us", "tr"),
        webshare_retries_when_blocked=3,
    )

    proxy_config = build_transcript_proxy_config(cfg)

    assert proxy_config.http_url == "http://user-US-TR-rotate:pass@p.webshare.io:80/"
    assert proxy_config.https_url == "http://user-US-TR-rotate:pass@p.webshare.io:80/"
    assert proxy_config.retries_when_blocked == 3


def test_builds_generic_transcript_proxy_config(tmp_path) -> None:
    cfg = Settings(
        media_tmp_dir=tmp_path / "media",
        media_ttl_seconds=1800,
        max_concurrent_downloads=1,
        max_download_mb=10,
        default_max_height=720,
        transcript_proxy_https_url="http://user:pass@proxy.example:8080",
    )

    proxy_config = build_transcript_proxy_config(cfg)

    assert proxy_config.to_requests_dict() == {
        "http": "http://user:pass@proxy.example:8080",
        "https": "http://user:pass@proxy.example:8080",
    }
