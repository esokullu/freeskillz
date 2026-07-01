from __future__ import annotations

import re
import urllib.parse
from typing import Any, Iterable

from .config import Settings


class TranscriptServiceError(Exception):
    """Raised when transcript provider calls fail."""


def extract_video_id(url_or_id: str) -> str:
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", url_or_id):
        return url_or_id

    parsed = urllib.parse.urlparse(url_or_id)

    if parsed.netloc.endswith("youtu.be"):
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return vid

    qs = urllib.parse.parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0]

    match = re.search(r"/(?:shorts|embed|v)/([0-9A-Za-z_-]{11})", parsed.path)
    if match:
        return match.group(1)

    raise ValueError(f"Video id cikarilamadi: {url_or_id}")


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def preferred_language_order(available_codes: Iterable[str], requested: str | None) -> list[str]:
    codes = list(dict.fromkeys(available_codes))
    if not requested:
        return codes
    return [requested] + [code for code in codes if code != requested]


def build_transcript_proxy_config(settings: Settings | None) -> Any | None:
    if not settings or not settings.has_transcript_proxy:
        return None

    try:
        from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
    except ImportError as exc:
        raise TranscriptServiceError("youtube-transcript-api proxy support is not installed") from exc

    if settings.webshare_proxy_username and settings.webshare_proxy_password:
        return WebshareProxyConfig(
            proxy_username=settings.webshare_proxy_username,
            proxy_password=settings.webshare_proxy_password,
            filter_ip_locations=list(settings.webshare_filter_ip_locations),
            retries_when_blocked=settings.webshare_retries_when_blocked,
            domain_name=settings.webshare_domain_name,
            proxy_port=settings.webshare_proxy_port,
        )

    return GenericProxyConfig(
        http_url=settings.transcript_proxy_http_url,
        https_url=settings.transcript_proxy_https_url,
    )


def _new_api(settings: Settings | None = None) -> Any:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise TranscriptServiceError("youtube-transcript-api is not installed") from exc
    return YouTubeTranscriptApi(proxy_config=build_transcript_proxy_config(settings))


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _provider_error(exc: Exception, settings: Settings | None) -> TranscriptServiceError:
    message = str(exc)
    if settings:
        message = settings.redact(message)
    return TranscriptServiceError(message)


def list_youtube_transcript_languages(
    url_or_id: str,
    api: Any | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    video_id = extract_video_id(url_or_id)
    client = api or _new_api(settings)
    try:
        available = client.list(video_id)
        languages = [
            {
                "language_code": item.language_code,
                "language": item.language,
                "is_generated": bool(item.is_generated),
            }
            for item in available
        ]
    except Exception as exc:  # Provider exceptions are version-specific.
        raise _provider_error(exc, settings) from exc

    return {"video_id": video_id, "languages": languages}


def fetch_youtube_transcript(
    url_or_id: str,
    lang: str | None = None,
    timestamps: bool = False,
    text_offset: int = 0,
    text_limit: int | None = None,
    include_segments: bool = True,
    api: Any | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    video_id = extract_video_id(url_or_id)
    client = api or _new_api(settings)
    try:
        available = client.list(video_id)
        available_codes = [item.language_code for item in available]
        languages = preferred_language_order(available_codes, lang)
        transcript = client.fetch(video_id, languages=languages)
    except Exception as exc:  # Provider exceptions are version-specific.
        raise _provider_error(exc, settings) from exc

    segments = []
    for snippet in transcript:
        start = float(_field(snippet, "start", 0.0))
        text = str(_field(snippet, "text", ""))
        segment = {
            "text": text,
            "start": start,
            "duration": _field(snippet, "duration"),
            "timestamp": format_timestamp(start) if timestamps else None,
        }
        segments.append(segment)

    full_text = "\n".join(segment["text"] for segment in segments)
    safe_text_offset = max(0, int(text_offset or 0))
    text_length = len(full_text)
    text_start = min(safe_text_offset, text_length)
    if text_limit is None:
        text_end = text_length
        effective_text_limit = None
    else:
        effective_text_limit = max(1, int(text_limit))
        text_end = min(text_length, text_start + effective_text_limit)
    text = full_text[text_start:text_end]
    has_more_text = text_end < text_length

    selected_language = _field(transcript, "language_code") or (languages[0] if languages else None)
    return {
        "video_id": video_id,
        "selected_language": selected_language,
        "text": text,
        "text_length": text_length,
        "text_offset": text_start,
        "text_limit": effective_text_limit,
        "has_more_text": has_more_text,
        "next_text_offset": text_end if has_more_text else None,
        "segments": segments if include_segments else [],
        "total_segments": len(segments),
        "segments_included": bool(include_segments),
    }
