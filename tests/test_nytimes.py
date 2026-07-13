from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.nytimes import NyTimesFetchError, fetch_nytimes_article, validate_nytimes_url
from app.webbrain_client import WebBrainApiError


ARTICLE_URL = "https://www.nytimes.com/2026/07/12/us/politics/example.html"


def settings(tmp_path: Path) -> Settings:
    return Settings(
        media_tmp_dir=tmp_path,
        media_ttl_seconds=1800,
        max_concurrent_downloads=1,
        max_download_mb=10,
        default_max_height=720,
        webbrain_api_key="wbp_test",
        webbrain_browser_session_id="bs_test",
        webbrain_base_url="https://webbrain.example",
        webbrain_run_timeout_ms=90_000,
    )


class FakeWebBrainClient:
    def __init__(self, api_key: str, base_url: str, timeout: float):
        self.init = {"api_key": api_key, "base_url": base_url, "timeout": timeout}
        self.create = None
        self.wait = None

    def create_run(self, session_id: str, task: str, **options):
        self.create = {"session_id": session_id, "task": task, **options}
        return {
            "run_id": "run_test",
            "status": "completed",
            "result": "Article body",
            "summary": "Article summary",
            "final_url": ARTICLE_URL,
        }

    def wait_for_run(self, session_id: str, run_id: str, **options):
        self.wait = {"session_id": session_id, "run_id": run_id, **options}
        return {"run_id": run_id, "status": "completed", "result": "Article body"}


def test_fetch_uses_webbrain_python_client_contract(tmp_path: Path) -> None:
    clients = []

    def factory(*args, **kwargs):
        client = FakeWebBrainClient(*args, **kwargs)
        clients.append(client)
        return client

    result = fetch_nytimes_article(ARTICLE_URL, settings(tmp_path), client_factory=factory)

    assert result == {
        "url": ARTICLE_URL,
        "run_id": "run_test",
        "status": "completed",
        "article": "Article body",
        "summary": "Article summary",
        "final_url": ARTICLE_URL,
    }
    assert clients[0].init == {
        "api_key": "wbp_test",
        "base_url": "https://webbrain.example",
        "timeout": 120.0,
    }
    assert clients[0].create == {
        "session_id": "bs_test",
        "task": f"fetch the article at {ARTICLE_URL}",
        "wait": True,
        "timeout_ms": 90_000,
    }


def test_fetch_polls_if_waiting_request_returns_running(tmp_path: Path) -> None:
    class RunningClient(FakeWebBrainClient):
        def create_run(self, session_id: str, task: str, **options):
            super().create_run(session_id, task, **options)
            return {"run_id": "run_running", "status": "running"}

    client = RunningClient("wbp_test", "https://webbrain.example", 120)
    result = fetch_nytimes_article(ARTICLE_URL, settings(tmp_path), client_factory=lambda *_args, **_kwargs: client)

    assert result["status"] == "completed"
    assert client.wait == {
        "session_id": "bs_test",
        "run_id": "run_running",
        "timeout": 120.0,
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/article",
        "http://www.nytimes.com/article",
        "https://nytimes.com.evil.example/article",
        "https://user:pass@www.nytimes.com/article",
        "https://www.nytimes.com/",
        "not-a-url",
    ],
)
def test_fetch_rejects_non_nytimes_urls(url: str) -> None:
    with pytest.raises(NyTimesFetchError) as exc:
        validate_nytimes_url(url)
    assert exc.value.status_code == 400


def test_upstream_conflict_is_preserved(tmp_path: Path) -> None:
    class ConflictClient(FakeWebBrainClient):
        def create_run(self, session_id: str, task: str, **options):
            raise WebBrainApiError("Browser already has an active run", status=409)

    with pytest.raises(NyTimesFetchError) as exc:
        fetch_nytimes_article(
            ARTICLE_URL,
            settings(tmp_path),
            client_factory=lambda *_args, **_kwargs: ConflictClient("key", "url", 1),
        )
    assert exc.value.status_code == 409


def test_network_errors_are_reported_as_upstream_failures(tmp_path: Path) -> None:
    class OfflineClient(FakeWebBrainClient):
        def create_run(self, session_id: str, task: str, **options):
            raise TimeoutError("upstream timed out")

    with pytest.raises(NyTimesFetchError) as exc:
        fetch_nytimes_article(
            ARTICLE_URL,
            settings(tmp_path),
            client_factory=lambda *_args, **_kwargs: OfflineClient("key", "url", 1),
        )
    assert exc.value.status_code == 502
    assert "timed out" in str(exc.value)


def test_invalid_run_response_is_rejected(tmp_path: Path) -> None:
    class InvalidClient(FakeWebBrainClient):
        def create_run(self, session_id: str, task: str, **options):
            return None

    with pytest.raises(NyTimesFetchError, match="invalid run response"):
        fetch_nytimes_article(
            ARTICLE_URL,
            settings(tmp_path),
            client_factory=lambda *_args, **_kwargs: InvalidClient("key", "url", 1),
        )
