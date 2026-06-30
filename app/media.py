from __future__ import annotations

import importlib
import mimetypes
import os
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from .config import Settings


class MediaServiceError(Exception):
    """Raised when yt-dlp cannot resolve or download media."""


ProgressCallback = Callable[[float, str | None], None]


def _youtube_dl_class() -> Any:
    try:
        module = importlib.import_module("yt_dlp")
    except ImportError as exc:
        raise MediaServiceError("yt-dlp is not installed") from exc
    return module.YoutubeDL


def _sanitize_message(message: str, settings: Settings) -> str:
    if settings.ytdlp_cookies_dir:
        message = message.replace(str(settings.ytdlp_cookies_dir), "[cookies]")
    return settings.redact(message)


def _hostname(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.lower().split("@")[-1].split(":")[0]


def cookie_file_for_url(url: str, settings: Settings) -> Path | None:
    cookies_dir = settings.ytdlp_cookies_dir
    if not cookies_dir:
        return None

    host = _hostname(url)
    short_host = host.removeprefix("www.")
    platform_names = {
        "youtu.be": "youtube",
        "youtube.com": "youtube",
        "m.youtube.com": "youtube",
        "instagram.com": "instagram",
        "x.com": "twitter",
        "twitter.com": "twitter",
        "tiktok.com": "tiktok",
        "reddit.com": "reddit",
    }

    candidates = [
        cookies_dir / "cookies.txt",
        cookies_dir / f"{short_host}.txt",
    ]
    platform = platform_names.get(short_host)
    if platform:
        candidates.append(cookies_dir / f"{platform}.txt")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _base_opts(url: str, settings: Settings) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 2,
        "fragment_retries": 2,
        "max_filesize": settings.max_download_bytes,
    }
    cookie_file = cookie_file_for_url(url, settings)
    if cookie_file:
        opts["cookiefile"] = str(cookie_file)
    if settings.ytdlp_proxy_url:
        opts["proxy"] = settings.ytdlp_proxy_url
    return opts


def _format_selector(kind: str, max_height: int) -> str:
    if kind == "audio":
        return "bestaudio/best"
    if kind == "image":
        return "best"
    height_clause = f"[height<={max_height}]"
    return (
        f"bestvideo{height_clause}+bestaudio/"
        f"best{height_clause}/"
        "bestvideo+bestaudio/best"
    )


def _media_type(info: dict[str, Any]) -> str:
    if info.get("_type") == "playlist":
        return "playlist"
    ext = (info.get("ext") or "").lower()
    vcodec = info.get("vcodec")
    acodec = info.get("acodec")
    if ext in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "image"
    if vcodec and vcodec != "none":
        return "video"
    if acodec and acodec != "none":
        return "audio"
    if info.get("duration") is not None:
        return "video"
    return "unknown"


def _public_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [
        "format_id",
        "ext",
        "resolution",
        "width",
        "height",
        "fps",
        "vcodec",
        "acodec",
        "filesize",
        "filesize_approx",
        "format_note",
    ]
    formats = []
    for item in info.get("formats") or []:
        formats.append({key: item.get(key) for key in keys if item.get(key) is not None})
    return formats[:80]


def public_metadata(info: dict[str, Any], include_formats: bool = True) -> dict[str, Any]:
    raw = {
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
    }
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "extractor": info.get("extractor") or info.get("extractor_key"),
        "webpage_url": info.get("webpage_url"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "media_type": _media_type(info),
        "ext": info.get("ext"),
        "formats": _public_formats(info) if include_formats else [],
        "raw": {key: value for key, value in raw.items() if value is not None},
    }


def resolve_media(url: str, settings: Settings) -> dict[str, Any]:
    YoutubeDL = _youtube_dl_class()
    opts = _base_opts(url, settings)
    opts["skip_download"] = True

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise MediaServiceError(_sanitize_message(str(exc), settings)) from exc

    return public_metadata(info)


def _find_downloaded_file(job_dir: Path, info: dict[str, Any]) -> Path:
    filename = info.get("_filename") or info.get("filepath")
    if filename and Path(filename).is_file():
        return Path(filename)

    files = [path for path in job_dir.iterdir() if path.is_file() and not path.name.endswith(".part")]
    if not files:
        raise MediaServiceError("Download completed but no media file was found")
    return max(files, key=lambda path: path.stat().st_mtime)


def download_media(
    url: str,
    settings: Settings,
    job_id: str,
    kind: str = "auto",
    max_height: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    YoutubeDL = _youtube_dl_class()
    height = max_height or settings.default_max_height
    job_dir = settings.media_tmp_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def hook(payload: dict[str, Any]) -> None:
        if not progress_callback:
            return
        status = payload.get("status")
        percent = 0.0
        total = payload.get("total_bytes") or payload.get("total_bytes_estimate")
        downloaded = payload.get("downloaded_bytes")
        if total and downloaded:
            percent = min(99.0, max(0.0, downloaded / total * 100))
        elif status == "finished":
            percent = 99.0
        progress_callback(percent, status)

    opts = _base_opts(url, settings)
    opts.update(
        {
            "format": _format_selector(kind, height),
            "merge_output_format": "mp4",
            "outtmpl": str(job_dir / "%(title).120B-%(id)s.%(ext)s"),
            "progress_hooks": [hook],
        }
    )

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise MediaServiceError(_sanitize_message(str(exc), settings)) from exc

    file_path = _find_downloaded_file(job_dir, info)
    if file_path.stat().st_size > settings.max_download_bytes:
        try:
            os.remove(file_path)
        finally:
            raise MediaServiceError("Downloaded file exceeded MAX_DOWNLOAD_MB")

    metadata = public_metadata(info, include_formats=False)
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return {
        "file_path": str(file_path),
        "filename": file_path.name,
        "content_type": media_type,
        "metadata": metadata,
    }
