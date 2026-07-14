# FreeSkillz API

Small FastAPI service for YouTube transcripts, WebBrain-powered New York Times article fetching, and best-effort media download or metadata resolution through `yt-dlp`.

## Endpoints

- `GET /healthz`
- `POST /v1/youtube/transcript`
- `POST /v1/youtube/transcript/languages`
- `POST /nytimes/fetch`
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
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","lang":"en","timestamps":true,"text_limit":6000,"include_segments":false}'
```

Long transcripts can be read without a fixed cap by paging through `text` windows:
send `text_limit`, then repeat with `text_offset` set to the previous
`next_text_offset` while `has_more_text` is true. Omit `text_limit` for the
legacy full-response shape.

## Media download delivery

Media jobs require one direct public media permalink. Feed and profile URLs are
not enough to identify which visible post the caller means. Browser agents
should resolve the intended post/reel URL before creating a job.

For `kind: "video"`, FreeSkillz owns the complete delivery pipeline: yt-dlp
selects and merges the source streams, then FFmpeg normalizes the result to one
QuickTime-compatible H.264/AAC-LC MP4 with fast-start metadata. Corrupt source
packets are discarded during normalization, and the job fails rather than
returning a video-only file when the requested video has no audio track.

## New York Times article fetch

This route uses a persistent WebBrain Cloud browser through the bundled Python
client. Configure a newly generated WebBrain API key and a ready browser
session. The public endpoint does not require callers to authenticate:

```bash
WEBBRAIN_API_KEY=wbp_your_new_key
WEBBRAIN_BROWSER_SESSION_ID=bs_your_session
```

Optional settings are `WEBBRAIN_BASE_URL` and `WEBBRAIN_RUN_TIMEOUT_MS`.

```bash
curl -X POST http://localhost:8000/nytimes/fetch \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.nytimes.com/2026/07/12/us/politics/example.html"}'
```

Only HTTPS `nytimes.com` URLs are accepted. The response includes `article`,
`summary`, `final_url`, and the WebBrain `run_id`. If WebBrain initially returns
a running job, FreeSkillz polls it to a terminal result before responding.

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

## Proxy Configuration

YouTube often blocks cloud provider IPs, including DigitalOcean. For transcript reliability, use Webshare Residential rotating proxies:

```bash
WEBSHARE_PROXY_USERNAME=your-webshare-proxy-username
WEBSHARE_PROXY_PASSWORD=your-webshare-proxy-password
WEBSHARE_FILTER_IP_LOCATIONS=us,tr
WEBSHARE_RETRIES_WHEN_BLOCKED=10
```

`youtube-transcript-api` will use Webshare's rotating residential proxy config when both username and password are present.

Generic transcript proxy fallback:

```bash
TRANSCRIPT_PROXY_HTTP_URL=http://user:pass@proxy.example:8080
TRANSCRIPT_PROXY_HTTPS_URL=http://user:pass@proxy.example:8080
```

For media resolve/download through `yt-dlp`:

```bash
YTDLP_PROXY_URL=socks5://user:pass@proxy.example:1080
```

Proxy URLs and Webshare passwords are redacted from provider error messages.

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
- Video jobs return one finalized MP4; callers do not need to merge tracks locally.
- The service does not bypass DRM, paywalls, or private-content restrictions.
