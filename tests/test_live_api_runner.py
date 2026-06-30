from __future__ import annotations

import os

import pytest

from tests.live_api_smoke import load_config, run_smoke


@pytest.mark.skipif(os.getenv("LIVE_API_TESTS") != "1", reason="set LIVE_API_TESTS=1 to run live REST API smoke tests")
def test_live_api_smoke_suite() -> None:
    notes = run_smoke(load_config())
    assert notes
