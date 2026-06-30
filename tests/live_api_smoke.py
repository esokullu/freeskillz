#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any


@dataclass
class SmokeConfig:
    base_url: str
    transcript_url: str
    media_url: str
    download_url: str
    run_download: bool
    timeout_seconds: int
    poll_seconds: float


class SmokeFailure(Exception):
    pass


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def load_config() -> SmokeConfig:
    return SmokeConfig(
        base_url=os.getenv("LIVE_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        transcript_url=os.getenv("LIVE_TRANSCRIPT_URL", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        media_url=os.getenv("LIVE_MEDIA_URL", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
        download_url=os.getenv("LIVE_DOWNLOAD_URL", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
        run_download=env_bool("LIVE_RUN_DOWNLOAD", True),
        timeout_seconds=int(os.getenv("LIVE_TIMEOUT_SECONDS", "180")),
        poll_seconds=float(os.getenv("LIVE_POLL_SECONDS", "2")),
    )


def request_json(
    config: SmokeConfig,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        f"{config.base_url}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        status = exc.code

    if status != expected_status:
        raise SmokeFailure(f"{method} {path} returned {status}, expected {expected_status}: {body[:500]}")
    if not body:
        return {}
    return json.loads(body)


def request_bytes(config: SmokeConfig, method: str, path: str, expected_status: int = 200) -> bytes:
    req = urllib.request.Request(
        f"{config.base_url}{path}",
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code

    if status != expected_status:
        preview = body[:500].decode("utf-8", errors="replace")
        raise SmokeFailure(f"{method} {path} returned {status}, expected {expected_status}: {preview}")
    return body


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def wait_for_job(config: SmokeConfig, job_id: str) -> dict[str, Any]:
    deadline = time.time() + config.timeout_seconds
    last_status = "unknown"
    while time.time() < deadline:
        job = request_json(config, "GET", f"/v1/media/jobs/{job_id}")
        last_status = job.get("status", "unknown")
        if last_status in {"complete", "failed", "expired"}:
            return job
        time.sleep(config.poll_seconds)
    raise SmokeFailure(f"job {job_id} did not finish before timeout; last status={last_status}")


def cleanup_job(config: SmokeConfig, job_id: str) -> None:
    try:
        request_json(config, "DELETE", f"/v1/media/jobs/{job_id}")
    except Exception as exc:
        print(f"cleanup warning for job {job_id}: {exc}", file=sys.stderr)


def run_smoke(config: SmokeConfig) -> list[str]:
    notes: list[str] = []

    health = request_json(config, "GET", "/healthz")
    require(health.get("status") == "ok", "healthz did not return ok")
    notes.append("healthz ok")

    languages = request_json(config, "POST", "/v1/youtube/transcript/languages", {"url": config.transcript_url})
    require(isinstance(languages.get("languages"), list), "languages response missing languages list")
    notes.append(f"transcript languages ok ({len(languages['languages'])})")

    transcript = request_json(
        config,
        "POST",
        "/v1/youtube/transcript",
        {"url": config.transcript_url, "lang": "en", "timestamps": True},
    )
    require(transcript.get("video_id"), "transcript response missing video_id")
    require(transcript.get("text"), "transcript response missing text")
    require(isinstance(transcript.get("segments"), list) and transcript["segments"], "transcript response missing segments")
    notes.append(f"transcript ok ({len(transcript['segments'])} segments)")

    resolved = request_json(config, "POST", "/v1/media/resolve", {"url": config.media_url})
    require(resolved.get("title") or resolved.get("id"), "resolve response missing title/id")
    require(resolved.get("media_type") in {"video", "audio", "image", "unknown"}, "resolve response has invalid media_type")
    notes.append(f"media resolve ok ({resolved.get('media_type')})")

    if config.run_download:
        job_id: str | None = None
        try:
            created = request_json(
                config,
                "POST",
                "/v1/media/jobs",
                {"url": config.download_url, "kind": "video", "max_height": 360},
            )
            job_id = created.get("job_id")
            require(bool(job_id), "download job response missing job_id")
            job = wait_for_job(config, job_id)
            require(job.get("status") == "complete", f"download job failed: {job.get('error')}")
            content = request_bytes(config, "GET", f"/v1/media/jobs/{job_id}/file")
            require(len(content) > 1024, "downloaded media response is unexpectedly small")
            notes.append(f"download job ok ({len(content)} bytes)")
        finally:
            if job_id:
                cleanup_job(config, job_id)
                notes.append("download cleanup attempted")
    else:
        notes.append("download job skipped by LIVE_RUN_DOWNLOAD=0")

    return notes


def send_failure_email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    recipient = os.getenv("SMTP_TO")
    if not host or not sender or not recipient:
        return

    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    use_ssl = env_bool("SMTP_SSL", False)
    use_starttls = env_bool("SMTP_STARTTLS", True)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_starttls:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)


def main() -> int:
    config = load_config()
    try:
        notes = run_smoke(config)
    except Exception as exc:
        body = (
            "FreeSkillz.xyz API smoke test failed.\n\n"
            f"Base URL: {config.base_url}\n"
            f"Error: {type(exc).__name__}: {exc}\n"
        )
        try:
            send_failure_email("FreeSkillz.xyz API smoke test failed", body)
        except Exception as email_exc:
            print(f"email warning: {email_exc}", file=sys.stderr)
        print(body, file=sys.stderr)
        return 1

    print("FreeSkillz.xyz API smoke test passed")
    for note in notes:
        print(f"- {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
