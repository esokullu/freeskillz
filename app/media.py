from __future__ import annotations

import importlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from .config import Settings


class MediaServiceError(Exception):
    """Raised when yt-dlp cannot resolve or download media."""


ProgressCallback = Callable[[float, str | None], None]

_YTDLP_BROWSER_AUTH_GUIDANCE_RE = re.compile(
    r"(?:"
    r"check if\b[^.\n]{0,400}\b(?:browser|logged[- ]?in)\b|"
    r"sign in\b|log in\b|"
    r"--cookies(?:-from-browser)?\b|"
    r"cookies-from-browser\b|"
    r"how-do-i-pass-cookies\b"
    r")",
    re.IGNORECASE,
)
_REMOTE_MEDIA_AUTH_CONTEXT = (
    "FreeSkillz fetches media on its own server. Signing in to the caller's browser "
    "or retrying from a logged-in browser will not affect this request because browser "
    "cookies are not sent to FreeSkillz. Only authentication configured by the "
    "FreeSkillz server operator can affect server-side access. Try the exact public "
    "media permalink or retry later."
)


def _youtube_dl_class() -> Any:
    try:
        module = importlib.import_module("yt_dlp")
    except ImportError as exc:
        raise MediaServiceError("yt-dlp is not installed") from exc
    return module.YoutubeDL


def _sanitize_message(message: str, settings: Settings) -> str:
    if settings.ytdlp_cookies_dir:
        message = message.replace(str(settings.ytdlp_cookies_dir), "[cookies]")
    message = settings.redact(message).strip()
    auth_guidance = _YTDLP_BROWSER_AUTH_GUIDANCE_RE.search(message)
    if not auth_guidance:
        return message

    # yt-dlp's stock error text assumes it is running on the user's machine
    # and therefore recommends browser cookies. FreeSkillz runs remotely, so
    # that advice is both inapplicable and likely to make callers expose or
    # reason about credentials that the service never receives.
    provider_detail = message[: auth_guidance.start()].strip().rstrip(".:;,-")
    if len(provider_detail) < 20:
        provider_detail = "The upstream media extractor could not access this URL"
    return f"{provider_detail}. {_REMOTE_MEDIA_AUTH_CONTEXT}"


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
        f"bestvideo[ext=mp4][vcodec^=avc1]{height_clause}+bestaudio[ext=m4a][acodec^=mp4a]/"
        f"best[ext=mp4][vcodec^=avc1][acodec^=mp4a]{height_clause}/"
        f"bestvideo{height_clause}+bestaudio/"
        f"best{height_clause}/"
        "bestvideo+bestaudio/best"
    )


def _run_media_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise MediaServiceError(f"Required media tool is not installed: {Path(command[0]).name}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaServiceError(f"{Path(command[0]).name} timed out while preparing the media file") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown media-processing error").strip().splitlines()
        message = detail[-1][:500] if detail else "unknown media-processing error"
        raise MediaServiceError(f"{Path(command[0]).name} failed while preparing the media file: {message}")
    return result


def _probe_media(file_path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise MediaServiceError("Required media tool is not installed: ffprobe")
    result = _run_media_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(file_path),
        ],
        timeout=30,
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaServiceError("ffprobe returned invalid media metadata") from exc
    return payload if isinstance(payload, dict) else {}


def _first_stream(probe: dict[str, Any], codec_type: str) -> dict[str, Any] | None:
    for stream in probe.get("streams") or []:
        if isinstance(stream, dict) and stream.get("codec_type") == codec_type:
            return stream
    return None


def _normalize_video_for_delivery(file_path: Path, require_audio: bool) -> tuple[Path, dict[str, Any]]:
    """Produce one clean H.264/AAC MP4 instead of exposing yt-dlp's raw tracks."""
    source_probe = _probe_media(file_path)
    if not _first_stream(source_probe, "video"):
        raise MediaServiceError("Downloaded media did not include a video track")
    has_audio = _first_stream(source_probe, "audio") is not None
    if require_audio and not has_audio:
        raise MediaServiceError("Downloaded video did not include an audio track")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MediaServiceError("Required media tool is not installed: ffmpeg")
    target = file_path.with_suffix(".mp4")
    temporary = file_path.parent / f".{target.stem}.quicktime.tmp.mp4"
    temporary.unlink(missing_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+discardcorrupt",
        "-err_detect",
        "ignore_err",
        "-i",
        str(file_path),
        "-map",
        "0:v:0",
    ]
    if has_audio:
        command.extend(["-map", "0:a:0"])
    command.extend(
        [
            "-sn",
            "-dn",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-profile:v",
            "high",
            "-level:v",
            "4.1",
            "-pix_fmt",
            "yuv420p",
            "-tag:v",
            "avc1",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        ]
    )
    if has_audio:
        command.extend(
            [
                "-c:a",
                "aac",
                "-profile:a",
                "aac_low",
                "-b:a",
                "160k",
                "-af",
                "aresample=async=1:first_pts=0",
                "-shortest",
            ]
        )
    command.extend(["-max_muxing_queue_size", "2048", "-movflags", "+faststart", str(temporary)])

    try:
        _run_media_command(command, timeout=900)
        output_probe = _probe_media(temporary)
        video = _first_stream(output_probe, "video")
        audio = _first_stream(output_probe, "audio")
        if not video or video.get("codec_name") != "h264":
            raise MediaServiceError("Prepared video is not H.264")
        if require_audio and (not audio or audio.get("codec_name") != "aac"):
            raise MediaServiceError("Prepared video is missing its AAC audio track")

        if target == file_path:
            file_path.unlink(missing_ok=True)
        else:
            target.unlink(missing_ok=True)
            file_path.unlink(missing_ok=True)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    for sibling in target.parent.iterdir():
        if sibling.is_file() and sibling != target and not sibling.name.endswith(".part"):
            sibling.unlink(missing_ok=True)

    duration = (output_probe.get("format") or {}).get("duration")
    return target, {
        "single_file": True,
        "container": "mp4",
        "video_codec": "h264",
        "audio_codec": "aac" if audio else None,
        "audio_included": audio is not None,
        "quicktime_compatible": True,
        "duration": float(duration) if duration is not None else None,
    }


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
    metadata = public_metadata(info, include_formats=False)
    if kind == "video" or metadata.get("media_type") == "video":
        try:
            file_path, delivery = _normalize_video_for_delivery(file_path, require_audio=kind == "video")
        except MediaServiceError as exc:
            raise MediaServiceError(_sanitize_message(str(exc), settings)) from exc
        metadata["delivery"] = delivery
    if file_path.stat().st_size > settings.max_download_bytes:
        try:
            os.remove(file_path)
        finally:
            raise MediaServiceError("Downloaded file exceeded MAX_DOWNLOAD_MB")

    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return {
        "file_path": str(file_path),
        "filename": file_path.name,
        "content_type": media_type,
        "metadata": metadata,
    }
