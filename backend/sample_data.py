from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "sample_communities.json"


def load_communities() -> dict[str, dict[str, Any]]:
    with DATA_PATH.open(encoding="utf-8") as source:
        items = json.load(source)
    return {item["id"]: item for item in items}
