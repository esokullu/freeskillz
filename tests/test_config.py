from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_reads_webshare_and_ytdlp_proxy_env(monkeypatch) -> None:
    monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", "user")
    monkeypatch.setenv("WEBSHARE_PROXY_PASSWORD", "pass")
    monkeypatch.setenv("WEBSHARE_FILTER_IP_LOCATIONS", "us, tr")
    monkeypatch.setenv("WEBSHARE_RETRIES_WHEN_BLOCKED", "4")
    monkeypatch.setenv("YTDLP_PROXY_URL", "socks5://user:pass@proxy.example:1080")
    monkeypatch.setenv("WEBBRAIN_API_KEY", "wbp_secret")
    monkeypatch.setenv("WEBBRAIN_BROWSER_SESSION_ID", "bs_test")
    monkeypatch.setenv("WEBBRAIN_RUN_TIMEOUT_MS", "90000")
    monkeypatch.setenv("NYTIMES_FETCH_TOKEN", "endpoint-secret")

    cfg = Settings.from_env()

    assert cfg.webshare_proxy_username == "user"
    assert cfg.webshare_proxy_password == "pass"
    assert cfg.webshare_filter_ip_locations == ("us", "tr")
    assert cfg.webshare_retries_when_blocked == 4
    assert cfg.ytdlp_proxy_url == "socks5://user:pass@proxy.example:1080"
    assert cfg.webbrain_api_key == "wbp_secret"
    assert cfg.webbrain_browser_session_id == "bs_test"
    assert cfg.webbrain_run_timeout_ms == 90_000
    assert cfg.nytimes_fetch_token == "endpoint-secret"
    assert "wbp_secret" not in cfg.redact("wbp_secret endpoint-secret")


def test_settings_requires_complete_webshare_credentials(monkeypatch) -> None:
    monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", "user")
    monkeypatch.delenv("WEBSHARE_PROXY_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="WEBSHARE_PROXY_USERNAME"):
        Settings.from_env()
