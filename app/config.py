from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    media_tmp_dir: Path
    media_ttl_seconds: int
    max_concurrent_downloads: int
    max_download_mb: int
    default_max_height: int
    ytdlp_cookies_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        cookies_dir = os.getenv("YTDLP_COOKIES_DIR")
        return cls(
            media_tmp_dir=Path(os.getenv("MEDIA_TMP_DIR", "/tmp/webbrain-webtools")),
            media_ttl_seconds=_int_env("MEDIA_TTL_SECONDS", 1800),
            max_concurrent_downloads=max(1, _int_env("MAX_CONCURRENT_DOWNLOADS", 2)),
            max_download_mb=max(1, _int_env("MAX_DOWNLOAD_MB", 512)),
            default_max_height=max(144, _int_env("DEFAULT_MAX_HEIGHT", 720)),
            ytdlp_cookies_dir=Path(cookies_dir) if cookies_dir else None,
        )

    @property
    def max_download_bytes(self) -> int:
        return self.max_download_mb * 1024 * 1024
