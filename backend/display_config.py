"""Public browser-map configuration, separate from server credentials."""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def display_config() -> dict:
    if os.getenv("NEIGHBORHOOD_IGNORE_ENV") == "1":
        return {"configured": False, "reason": "offline", "provider": "baidu-gl"}
    local = dotenv_values(ROOT / ".env")
    browser_key = (os.getenv("BAIDU_BROWSER_AK") or local.get("BAIDU_BROWSER_AK") or "").strip()
    server_key = os.getenv("BAIDU_MAP_AK") or local.get("BAIDU_MAP_AK") or ""
    reason = "not_configured"
    if browser_key and browser_key == server_key:
        reason = "key_type_conflict"
    elif browser_key and not re.fullmatch(r"[A-Za-z0-9]{32}", browser_key):
        reason = "invalid_config"
    elif browser_key:
        # A browser AK is intentionally public; protect it with Referer rules.
        return {"configured": True, "provider": "baidu-gl", "browser_ak": browser_key}
    return {"configured": False, "reason": reason, "provider": "baidu-gl"}
