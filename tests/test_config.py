from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_reads_webshare_and_ytdlp_proxy_env(monkeypatch) -> None:
    monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", "user")
    monkeypatch.setenv("WEBSHARE_PROXY_PASSWORD", "pass")
    monkeypatch.setenv("WEBSHARE_FILTER_IP_LOCATIONS", "us, tr")
    monkeypatch.setenv("WEBSHARE_RETRIES_WHEN_BLOCKED", "4")
    monkeypatch.setenv("YTDLP_PROXY_URL", "socks5://user:pass@proxy.example:1080")

    cfg = Settings.from_env()

    assert cfg.webshare_proxy_username == "user"
    assert cfg.webshare_proxy_password == "pass"
    assert cfg.webshare_filter_ip_locations == ("us", "tr")
    assert cfg.webshare_retries_when_blocked == 4
    assert cfg.ytdlp_proxy_url == "socks5://user:pass@proxy.example:1080"


def test_settings_requires_complete_webshare_credentials(monkeypatch) -> None:
    monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", "user")
    monkeypatch.delenv("WEBSHARE_PROXY_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="WEBSHARE_PROXY_USERNAME"):
        Settings.from_env()
