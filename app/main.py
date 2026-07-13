from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from .config import Settings
from .jobs import JobManager
from .media import MediaServiceError, resolve_media
from .nytimes import NyTimesFetchError, fetch_nytimes_article
from .schemas import (
    MediaJobCreateResponse,
    MediaJobRequest,
    MediaJobResponse,
    MediaResolveRequest,
    MediaResolveResponse,
    NyTimesFetchRequest,
    NyTimesFetchResponse,
    TranscriptLanguagesRequest,
    TranscriptLanguage,
    TranscriptRequest,
    TranscriptResponse,
)
from .transcripts import (
    TranscriptServiceError,
    fetch_youtube_transcript,
    list_youtube_transcript_languages,
)


def create_app(settings: Settings | None = None, job_manager: JobManager | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    jobs = job_manager or JobManager(settings)

    api = FastAPI(title="Webbrain Web Tools API", version="0.1.0")
    static_dir = Path(__file__).resolve().parent.parent / "static"
    index_file = static_dir / "index.html"
    skills_file = Path(__file__).resolve().parent.parent / "skills.md"

    @api.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        if not index_file.exists():
            raise HTTPException(status_code=404, detail="index.html not found")
        return FileResponse(index_file, media_type="text/html")

    @api.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/skills.md")
    def skills_markdown() -> FileResponse:
        if not skills_file.exists():
            raise HTTPException(status_code=404, detail="skills.md not found")
        return FileResponse(skills_file, media_type="text/markdown")

    @api.post(
        "/v1/youtube/transcript",
        response_model=TranscriptResponse,
    )
    def youtube_transcript(payload: TranscriptRequest) -> dict:
        try:
            return fetch_youtube_transcript(
                payload.url,
                lang=payload.lang,
                timestamps=payload.timestamps,
                text_offset=payload.text_offset,
                text_limit=payload.text_limit,
                include_segments=payload.include_segments,
                settings=settings,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except TranscriptServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @api.post(
        "/v1/youtube/transcript/languages",
    )
    def youtube_transcript_languages(payload: TranscriptLanguagesRequest) -> dict[str, list[TranscriptLanguage] | str]:
        try:
            return list_youtube_transcript_languages(payload.url, settings=settings)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except TranscriptServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @api.post(
        "/nytimes/fetch",
        response_model=NyTimesFetchResponse,
    )
    def nytimes_fetch(payload: NyTimesFetchRequest) -> dict:
        try:
            return fetch_nytimes_article(payload.url, settings)
        except NyTimesFetchError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @api.post(
        "/v1/media/resolve",
        response_model=MediaResolveResponse,
    )
    def media_resolve(payload: MediaResolveRequest) -> dict:
        try:
            return resolve_media(payload.url, settings)
        except MediaServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @api.post(
        "/v1/media/jobs",
        response_model=MediaJobCreateResponse,
    )
    def create_media_job(payload: MediaJobRequest) -> dict[str, str]:
        job = jobs.create_job(
            url=payload.url,
            kind=payload.kind,
            max_height=payload.max_height or settings.default_max_height,
        )
        return {
            "job_id": job.job_id,
            "status_url": f"/v1/media/jobs/{job.job_id}",
            "file_url": f"/v1/media/jobs/{job.job_id}/file",
        }

    @api.get(
        "/v1/media/jobs/{job_id}",
        response_model=MediaJobResponse,
    )
    def get_media_job(job_id: str) -> dict:
        job = jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job.to_dict()

    @api.delete(
        "/v1/media/jobs/{job_id}",
    )
    def delete_media_job(job_id: str) -> dict[str, bool | str]:
        job = jobs.delete_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status in {"queued", "running"}:
            raise HTTPException(status_code=409, detail=f"Job is {job.status}")
        return {"deleted": True, "job_id": job_id}

    @api.get(
        "/v1/media/jobs/{job_id}/file",
    )
    def get_media_job_file(job_id: str) -> FileResponse:
        job, file_path = jobs.get_file(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status == "expired":
            raise HTTPException(status_code=410, detail="Job expired")
        if job.status != "complete" or not file_path:
            raise HTTPException(status_code=409, detail=f"Job is {job.status}")
        if not file_path.exists():
            raise HTTPException(status_code=410, detail="File is no longer available")
        return FileResponse(
            file_path,
            media_type=job.content_type or "application/octet-stream",
            filename=job.filename or file_path.name,
        )

    return api


app = create_app()
