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

The YouTube, New York Times, and media routes require no client API key.

## Agent Workflow

1. Call `GET /healthz` before a task if availability matters.
2. For YouTube text, call `POST /v1/youtube/transcript` first. For long videos, request bounded `text_limit` windows and continue with `text_offset` set to `next_text_offset` while `has_more_text` is true.
3. For a New York Times article, call `POST /nytimes/fetch`.
4. For unknown media URLs, call `POST /v1/media/resolve` before downloading.
5. For media files, create a job with `POST /v1/media/jobs`, poll `GET /v1/media/jobs/{job_id}`, fetch `GET /v1/media/jobs/{job_id}/file`, then call `DELETE /v1/media/jobs/{job_id}`.
6. Treat downloads as temporary. They expire automatically and can be deleted early.

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

{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","lang":"en","timestamps":true,"text_limit":6000,"include_segments":false}
```

Returns:

- `video_id`
- `selected_language`
- `text`, containing the requested transcript window
- `text_length`, `text_offset`, `text_limit`, `has_more_text`, and `next_text_offset`
- `segments`, including `text`, `start`, `duration`, and optional `timestamp`
- `total_segments` and `segments_included`

If `text_limit` is omitted, the API remains backward compatible and returns the full joined transcript text. Agents that need unlimited access should prefer paged windows, then keep fetching until `has_more_text` is false or the task has enough evidence. Set `include_segments` to `false` for compact text-only windows, or `true` when timestamped segment boundaries are needed.

### New York Times Article Fetch

```http
POST /nytimes/fetch
Content-Type: application/json

{"url":"https://www.nytimes.com/2026/07/12/us/politics/example.html"}
```

The service asks its configured WebBrain Cloud browser to fetch the article and
waits for the run to finish. The response contains `article`, `summary`,
`final_url`, `run_id`, and `status`. Only HTTPS URLs on `nytimes.com` are
accepted. A `409` means the configured browser tab already has an active run.

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

## Proxy Behavior

The deployed service may use Webshare Residential rotating proxies for YouTube transcript requests when these environment variables are configured:

- `WEBSHARE_PROXY_USERNAME`
- `WEBSHARE_PROXY_PASSWORD`
- `WEBSHARE_FILTER_IP_LOCATIONS`
- `WEBSHARE_RETRIES_WHEN_BLOCKED`

Agents do not need to pass proxy details in API requests. If a transcript request returns a cloud-IP block message, tell the operator to configure Webshare Residential credentials on the server.

Media resolve and download requests can use `YTDLP_PROXY_URL` server-side. Agents should still avoid private, paywalled, DRM, or login-only URLs.

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
