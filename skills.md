# FreeSkillz Agent Usage Guide

FreeSkillz.xyz is a public REST API for agents that need YouTube transcripts, media metadata, or short-lived media downloads.

Base URL:

```text
https://freeskillz.xyz
```

Local development URL:

```text
http://127.0.0.1:8000
```

No API key is required.

## Agent Workflow

1. Call `GET /healthz` before a task if availability matters.
2. For YouTube text, call `POST /v1/youtube/transcript` first.
3. For unknown media URLs, call `POST /v1/media/resolve` before downloading.
4. For media files, create a job with `POST /v1/media/jobs`, poll `GET /v1/media/jobs/{job_id}`, fetch `GET /v1/media/jobs/{job_id}/file`, then call `DELETE /v1/media/jobs/{job_id}`.
5. Treat downloads as temporary. They expire automatically and can be deleted early.

## Endpoints

### Health

```http
GET /healthz
```

Expected response:

```json
{"status":"ok"}
```

### YouTube Transcript Languages

```http
POST /v1/youtube/transcript/languages
Content-Type: application/json

{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
```

Returns `video_id` and a `languages` array with `language_code`, `language`, and `is_generated`.

### YouTube Transcript

```http
POST /v1/youtube/transcript
Content-Type: application/json

{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","lang":"en","timestamps":true}
```

Returns:

- `video_id`
- `selected_language`
- `text`
- `segments`, including `text`, `start`, `duration`, and optional `timestamp`

### Media Resolve

```http
POST /v1/media/resolve
Content-Type: application/json

{"url":"https://www.youtube.com/watch?v=jNQXAC9IVRw"}
```

Use this before download when you need title, extractor, media type, thumbnail, duration, and available formats.

### Media Download Job

```http
POST /v1/media/jobs
Content-Type: application/json

{"url":"https://www.youtube.com/watch?v=jNQXAC9IVRw","kind":"video","max_height":360}
```

`kind` can be `auto`, `video`, `audio`, or `image`.

The response contains:

- `job_id`
- `status_url`
- `file_url`

Poll:

```http
GET /v1/media/jobs/{job_id}
```

When `status` is `complete`, fetch:

```http
GET /v1/media/jobs/{job_id}/file
```

Then cleanup:

```http
DELETE /v1/media/jobs/{job_id}
```

## Supported Media

The service uses `yt-dlp`, so support is best-effort across public URLs including:

- YouTube videos and Shorts
- TikTok videos
- Instagram public reels/posts
- X/Twitter public videos
- Reddit media
- Other public URLs supported by yt-dlp's generic extractor

Private accounts, DRM, paywalls, and login-only content are not bypassed.

## Failure Handling

- `400`: invalid request, invalid YouTube URL, or unsupported input shape.
- `404`: missing job.
- `409`: job is not ready or cannot be deleted while running.
- `410`: file expired or disappeared.
- `502`: upstream extractor/transcript provider failed.

Agents should surface the provider error briefly, then suggest trying another public URL or lowering `max_height`.

## Public-Service Etiquette

- Prefer transcripts and metadata over downloads when possible.
- Keep `max_height` modest, for example `360` or `720`.
- Always delete completed download jobs after fetching the file.
- Do not send private, paywalled, or sensitive URLs.
