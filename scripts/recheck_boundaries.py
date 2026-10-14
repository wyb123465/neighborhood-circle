"""Targeted current API recheck; private observations do not imply field truth."""
from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.baidu import BaiduConfig, BaiduMapsClient
from backend.live_inspection import inspect_live


def location(text):
    lat, lng = map(float, text.split(","))
    return {"lat": lat, "lng": lng}


def main():
    cases = json.loads((ROOT / ".runtime/route-crosscheck/cases.json").read_text(encoding="utf-8"))
    replay = BaiduMapsClient(replace(BaiduConfig.from_env(), replay_file=str(ROOT / ".runtime/replay/fixtures.json")))
    p = replay.replay_metadata
    inspection = inspect_live(replay, address=p["address"], city=p["city"], categories=["医疗", "养老", "教育", "购物"], minutes=p["minutes"], radius_m=1500, max_facilities=p["max_facilities"], query_profile=p["query_profile"])
    replay.close()
    gaps = [point for point in inspection["blind_spots"]["points"] if "菜市场" in point["missing_kinds"]]
    maps = BaiduMapsClient(replace(BaiduConfig.from_env(), replay_file=None, max_place_pages=1))
    result = {"checked_at": datetime.now().astimezone().isoformat(timespec="seconds"), "routes": [], "markets": []}
    try:
        for case in cases:
            if case["id"] not in (11, 12, 15):
                continue
            row = maps.walking_route(origin=location(case["origin"]), destination=location(case["destination"]))
            result["routes"].append({"id": case["id"], "historical_duration_s": case["duration_s"], "current_duration_s": row["duration_s"], "current_distance_m": row["distance_m"], "url": case["url"]})
        selected = [c for c in cases if c["id"] in (11, 12, 15)]
        matrix = maps.walking_route_matrix(origin=location(selected[0]["origin"]), destinations=[location(c["destination"]) for c in selected])
        for row, measured in zip(result["routes"], matrix):
            row["current_matrix_duration_s"] = measured.get("duration_s")
        if gaps:
            gap = gaps[0]
            center = inspection["community"]["center"]
            position = {"lat": center["lat"]+gap["dy_m"]/111320, "lng": center["lng"]+gap["dx_m"]/(111320*math.cos(math.radians(center["lat"])))}
            result["gap"] = {"dx_m": gap["dx_m"], "dy_m": gap["dy_m"], "location": position}
            for query in ("菜市场", "农贸市场"):
                rows = maps.search_pois(location=position, query=query, radius_m=1000, city_limit=True)
                result["markets"].append({"query": query, "returned": len(rows), "complete": getattr(rows, "complete", False), "names": [r["name"] for r in rows]})
        result["metrics"] = maps.metrics()
    finally:
        maps.close()
    path = ROOT / ".runtime/boundary-recheck.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"routes": result["routes"], "markets": result["markets"], "network_requests": result["metrics"]["network_requests"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
