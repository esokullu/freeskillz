# Webbrain Web Tools API

Small FastAPI service for YouTube transcripts and best-effort media download or metadata resolution through `yt-dlp`.

## Endpoints

- `GET /healthz`
- `POST /v1/youtube/transcript`
- `POST /v1/youtube/transcript/languages`
- `POST /v1/media/resolve`
- `POST /v1/media/jobs`
- `GET /v1/media/jobs/{job_id}`
- `GET /v1/media/jobs/{job_id}/file`
- `DELETE /v1/media/jobs/{job_id}`

The public index page is served at `/`.
Agent-facing usage notes are served at `/skills.md` and stored in `skills.md`.

## Local Docker Run

```bash
cp .env.example .env
docker compose up --build
```

```bash
curl http://localhost:8000/healthz
curl -X POST http://localhost:8000/v1/youtube/transcript \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","lang":"en","timestamps":true}'
```

## Live API Smoke Tests

The mocked unit tests run without external services:

```bash
.venv/bin/pytest -q
```

The live smoke suite sends real REST calls to a running API and can email failures through SMTP:

```bash
LIVE_API_BASE_URL=http://127.0.0.1:8000 \
.venv/bin/python tests/live_api_smoke.py
```

Useful live-test overrides:

- `LIVE_TRANSCRIPT_URL`: YouTube URL used for transcript checks.
- `LIVE_MEDIA_URL`: URL used for metadata resolve checks.
- `LIVE_DOWNLOAD_URL`: URL used for download job checks.
- `LIVE_RUN_DOWNLOAD=0`: skip the download job.
- `LIVE_TIMEOUT_SECONDS=240`: increase polling timeout for slow networks.

Optional SMTP failure notification:

```bash
SMTP_HOST=smtp.example.com \
SMTP_PORT=587 \
SMTP_USERNAME=user \
SMTP_PASSWORD=secret \
SMTP_FROM=alerts@freeskillz.xyz \
SMTP_TO=you@example.com \
.venv/bin/python tests/live_api_smoke.py
```

Set `SMTP_SSL=1` for SSL-on-connect servers or `SMTP_STARTTLS=0` for a plain local relay.
The live runner deletes completed download jobs with `DELETE /v1/media/jobs/{job_id}` after it verifies the file response.

## Cookie Files

For platforms that need logged-in cookies, mount Netscape-format cookie files into `YTDLP_COOKIES_DIR`.

Supported lookup names:

- `cookies.txt`
- `{hostname}.txt`, for example `instagram.com.txt`
- platform aliases such as `youtube.txt`, `instagram.txt`, `twitter.txt`, `tiktok.txt`, `reddit.txt`

Cookie contents are never logged by the app.

## DigitalOcean Droplet Deploy

1. Create a small Ubuntu Droplet.
2. Point `freeskillz.xyz` and `www.freeskillz.xyz` DNS A records to the Droplet IP.
3. Use `deploy/cloud-init.yaml` as user data, or SSH in and run:

```bash
curl -fsSL https://raw.githubusercontent.com/esokullu/freeskillz/main/deploy/bootstrap.sh | sudo bash
```

The production compose file runs the API plus Caddy for HTTPS:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Keep one app process for the v1 in-memory job store; horizontal scaling needs a shared queue/object store.

## Notes

- Media jobs are ephemeral and stored under `MEDIA_TMP_DIR`.
- Completed files expire after `MEDIA_TTL_SECONDS`.
- The service does not bypass DRM, paywalls, or private-content restrictions.
