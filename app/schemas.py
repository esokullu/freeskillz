from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TranscriptRequest(BaseModel):
    url: str = Field(..., min_length=1)
    lang: str | None = Field(default=None, min_length=2, max_length=12)
    timestamps: bool = False


class TranscriptLanguagesRequest(BaseModel):
    url: str = Field(..., min_length=1)


class TranscriptLanguage(BaseModel):
    language_code: str
    language: str
    is_generated: bool


class TranscriptSegment(BaseModel):
    text: str
    start: float
    duration: float | None = None
    timestamp: str | None = None


class TranscriptResponse(BaseModel):
    video_id: str
    selected_language: str | None
    text: str
    segments: list[TranscriptSegment]


class MediaResolveRequest(BaseModel):
    url: str = Field(..., min_length=1)


class MediaFormat(BaseModel):
    format_id: str | None = None
    ext: str | None = None
    resolution: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    filesize: int | None = None
    filesize_approx: int | None = None
    format_note: str | None = None


class MediaResolveResponse(BaseModel):
    id: str | None = None
    title: str | None = None
    extractor: str | None = None
    webpage_url: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    media_type: str
    ext: str | None = None
    formats: list[MediaFormat] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class MediaJobRequest(BaseModel):
    url: str = Field(..., min_length=1)
    kind: Literal["auto", "video", "audio", "image"] = "auto"
    max_height: int | None = Field(default=None, ge=144, le=4320)


class MediaJobCreateResponse(BaseModel):
    job_id: str
    status_url: str
    file_url: str


class MediaJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "complete", "failed", "expired"]
    url: str
    kind: str
    max_height: int | None
    progress: float
    created_at: str
    updated_at: str
    expires_at: str | None = None
    metadata: dict[str, Any] | None = None
    error: str | None = None
    file_url: str | None = None
