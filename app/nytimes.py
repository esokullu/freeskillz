from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from .config import Settings
from .webbrain_client import WebBrainApiError, WebBrainClient


class NyTimesFetchError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def validate_nytimes_url(url: str) -> str:
    url = url.strip()
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise NyTimesFetchError("A valid New York Times article URL is required", 400) from exc

    host = (parsed.hostname or "").lower()
    is_nytimes = host == "nytimes.com" or host.endswith(".nytimes.com")
    if (
        parsed.scheme.lower() != "https"
        or not is_nytimes
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.strip("/")
    ):
        raise NyTimesFetchError("Only HTTPS article URLs on nytimes.com are supported", 400)
    return url


def fetch_nytimes_article(
    url: str,
    settings: Settings,
    client_factory: Callable[..., WebBrainClient] = WebBrainClient,
) -> dict[str, Any]:
    url = validate_nytimes_url(url)
    if not settings.webbrain_api_key or not settings.webbrain_browser_session_id:
        raise NyTimesFetchError("WebBrain Cloud is not configured", 503)

    timeout_seconds = max(30.0, settings.webbrain_run_timeout_ms / 1000 + 30)
    client = client_factory(
        settings.webbrain_api_key,
        base_url=settings.webbrain_base_url,
        timeout=timeout_seconds,
    )
    try:
        run = client.create_run(
            settings.webbrain_browser_session_id,
            f"fetch the article at {url}",
            wait=True,
            timeout_ms=settings.webbrain_run_timeout_ms,
        )
        if not isinstance(run, dict):
            raise NyTimesFetchError("WebBrain returned an invalid run response")
        if run.get("status") == "running" and run.get("run_id"):
            run = client.wait_for_run(
                settings.webbrain_browser_session_id,
                str(run["run_id"]),
                timeout=timeout_seconds,
            )
            if not isinstance(run, dict):
                raise NyTimesFetchError("WebBrain returned an invalid run response")
    except WebBrainApiError as exc:
        status_code = 409 if exc.status == 409 else 502
        raise NyTimesFetchError(settings.redact(str(exc)), status_code) from exc
    except (OSError, ValueError) as exc:
        raise NyTimesFetchError(settings.redact(str(exc))) from exc

    status = str(run.get("status") or "failed")
    if status != "completed":
        error = settings.redact(str(run.get("error") or "").strip())
        raise NyTimesFetchError(error or f"WebBrain run ended with status {status}")

    return {
        "url": url,
        "run_id": run.get("run_id"),
        "status": status,
        "article": run.get("result"),
        "summary": run.get("summary") or "",
        "final_url": run.get("final_url") or url,
    }
