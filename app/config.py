from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _str_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _csv_env(name: str) -> tuple[str, ...]:
    value = os.getenv(name)
    if not value:
        return ()
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    media_tmp_dir: Path
    media_ttl_seconds: int
    max_concurrent_downloads: int
    max_download_mb: int
    default_max_height: int
    ytdlp_cookies_dir: Path | None = None
    webshare_proxy_username: str | None = None
    webshare_proxy_password: str | None = None
    webshare_filter_ip_locations: tuple[str, ...] = ()
    webshare_retries_when_blocked: int = 10
    webshare_domain_name: str = "p.webshare.io"
    webshare_proxy_port: int = 80
    transcript_proxy_http_url: str | None = None
    transcript_proxy_https_url: str | None = None
    ytdlp_proxy_url: str | None = None
    webbrain_api_key: str | None = None
    webbrain_browser_session_id: str | None = None
    webbrain_base_url: str = "https://webbrain.cloud"
    webbrain_run_timeout_ms: int = 240_000

    @classmethod
    def from_env(cls) -> "Settings":
        cookies_dir = os.getenv("YTDLP_COOKIES_DIR")
        webshare_username = _str_env("WEBSHARE_PROXY_USERNAME")
        webshare_password = _str_env("WEBSHARE_PROXY_PASSWORD")
        if bool(webshare_username) != bool(webshare_password):
            raise ValueError("WEBSHARE_PROXY_USERNAME and WEBSHARE_PROXY_PASSWORD must be set together")

        return cls(
            media_tmp_dir=Path(os.getenv("MEDIA_TMP_DIR", "/tmp/webbrain-webtools")),
            media_ttl_seconds=_int_env("MEDIA_TTL_SECONDS", 1800),
            max_concurrent_downloads=max(1, _int_env("MAX_CONCURRENT_DOWNLOADS", 2)),
            max_download_mb=max(1, _int_env("MAX_DOWNLOAD_MB", 512)),
            default_max_height=max(144, _int_env("DEFAULT_MAX_HEIGHT", 720)),
            ytdlp_cookies_dir=Path(cookies_dir) if cookies_dir else None,
            webshare_proxy_username=webshare_username,
            webshare_proxy_password=webshare_password,
            webshare_filter_ip_locations=_csv_env("WEBSHARE_FILTER_IP_LOCATIONS"),
            webshare_retries_when_blocked=max(1, _int_env("WEBSHARE_RETRIES_WHEN_BLOCKED", 10)),
            webshare_domain_name=_str_env("WEBSHARE_DOMAIN_NAME") or "p.webshare.io",
            webshare_proxy_port=max(1, _int_env("WEBSHARE_PROXY_PORT", 80)),
            transcript_proxy_http_url=_str_env("TRANSCRIPT_PROXY_HTTP_URL"),
            transcript_proxy_https_url=_str_env("TRANSCRIPT_PROXY_HTTPS_URL"),
            ytdlp_proxy_url=_str_env("YTDLP_PROXY_URL"),
            webbrain_api_key=_str_env("WEBBRAIN_API_KEY"),
            webbrain_browser_session_id=_str_env("WEBBRAIN_BROWSER_SESSION_ID"),
            webbrain_base_url=_str_env("WEBBRAIN_BASE_URL") or "https://webbrain.cloud",
            webbrain_run_timeout_ms=max(1_000, _int_env("WEBBRAIN_RUN_TIMEOUT_MS", 240_000)),
        )

    @property
    def max_download_bytes(self) -> int:
        return self.max_download_mb * 1024 * 1024

    @property
    def has_transcript_proxy(self) -> bool:
        return bool(
            (self.webshare_proxy_username and self.webshare_proxy_password)
            or self.transcript_proxy_http_url
            or self.transcript_proxy_https_url
        )

    def redact(self, message: str) -> str:
        redacted = message
        for secret in (
            self.webshare_proxy_password,
            self.transcript_proxy_http_url,
            self.transcript_proxy_https_url,
            self.ytdlp_proxy_url,
            self.webbrain_api_key,
        ):
            if secret:
                redacted = redacted.replace(secret, "[redacted]")
        return redacted
