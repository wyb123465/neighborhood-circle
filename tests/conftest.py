"""Test isolation guards.

backend.baidu.load_env_file() loads the operator's real `.env` at import time,
so any BAIDU_* variable set there (AK, query profile, concurrency) would leak
into the test process and break tests that assert the code's own defaults.
Each test therefore starts from a clean Baidu configuration; tests that need
specific values set them explicitly (monkeypatch.setenv or injected configs).
"""

from __future__ import annotations

import pytest

_BAIDU_VARS = (
    "BAIDU_MAP_AK",
    "BAIDU_API_BASE_URL",
    "BAIDU_PLACE_API_VERSION",
    "BAIDU_API_TIMEOUT",
    "BAIDU_API_CACHE_TTL",
    "BAIDU_API_MAX_PAGES",
    "BAIDU_API_MAX_CONCURRENCY",
    "BAIDU_POI_QUERY_PROFILE",
    "BAIDU_API_FORCE_IPV4",
    "BAIDU_API_QPS",
    "BAIDU_API_MATRIX_PAIRS",
    "BAIDU_REPLAY_FILE",
)


@pytest.fixture(autouse=True)
def clean_baidu_env(monkeypatch):
    for name in _BAIDU_VARS:
        monkeypatch.delenv(name, raising=False)
    for name in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "AI_PROTOCOL"):
        monkeypatch.delenv(name, raising=False)
