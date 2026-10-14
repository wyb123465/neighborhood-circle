"""Reclassify a fixed snapshot at several thresholds without external calls."""

from __future__ import annotations

import hashlib
import json
import math

from .analysis import inspect
from .sample_data import load_communities


def compare_thresholds(analysis):
    thresholds = (10, 15, 20)
    result = analysis["inspection"]
    rows = []
    if analysis["type"] == "synthetic":
        p = result["parameters"]
        spec = load_communities()[result["community"]["id"]]
        for minutes in thresholds:
            computed = inspect(
                spec, p["categories"], minutes, p["speed_m_min"], p["center"], p.get("addition")
            )
            rows.append(
                {
                    "minutes": minutes,
                    "known": computed["sample_count"],
                    "unknown": 0,
                    "reachable": computed["sample_count"] - computed["gap_count"],
                    "ratio_pct": computed["combined_coverage_pct"],
                    "gap_count": computed["gap_count"],
                    "evidence_id": computed["evidence_id"],
                }
            )
        scope = "synthetic-service-coverage"
        label = "所选各类服务同时可达"
        sample_count = result["sample_count"]
        note = "固定同一片区、路网节点、设施、中心与步速；仅改变时间阈值。分母为等权节点，不是人口。"
        base = result["evidence_id"]
    else:
        iso = analysis.get("isochrone")
        if not iso:
            raise ValueError("本次未完成等时圈，无法比较固定样点的耗时。")
        points = [p for p in iso["points"] if p["generation"] == "coarse"]
        known = [
            p
            for p in points
            if p["status"] != "unknown"
            and isinstance(p.get("duration_s"), (int, float))
            and math.isfinite(p["duration_s"])
            and p["duration_s"] >= 0
        ]
        sample_count = len(points)
        for minutes in thresholds:
            reached = sum(p["duration_s"] <= minutes * 60 for p in known)
            facilities = {}
            for category in result["parameters"]["categories"]:
                selected = [
                    f
                    for f in result["facilities"]
                    if category in f.get("eligible_categories", f["categories"])
                ]
                measured = [
                    f
                    for f in selected
                    if f["route"]["status"] == "ok"
                    and isinstance(f["route"].get("duration_s"), (int, float))
                    and math.isfinite(f["route"]["duration_s"])
                    and f["route"]["duration_s"] >= 0
                ]
                count = sum(f["route"]["duration_s"] <= minutes * 60 for f in measured)
                facilities[category] = {
                    "evaluated": len(selected),
                    "known": len(measured),
                    "unknown": len(selected) - len(measured),
                    "reachable": count,
                }
            rows.append(
                {
                    "minutes": minutes,
                    "known": len(known),
                    "unknown": sample_count - len(known),
                    "reachable": reached,
                    "ratio_pct": round(reached / len(known) * 100, 1) if known else None,
                    "unreachable": len(known) - reached,
                    "facilities": facilities,
                }
            )
        scope = "live-fixed-coarse-center-reachability"
        label = "中心到固定均匀样点可达"
        note = f"复用原始百度秒数，固定本次{sample_count}个均匀样点与{iso['parameters']['extent_m']}米采样范围；未知不进入已知分母，加密点不参与。20分钟结果也只描述这一范围，不代表完整20分钟等时圈或居民服务覆盖。"
        base = iso["evidence_id"]
    evidence = hashlib.sha256(
        json.dumps({"method": "fixed-thresholds-v1", "base": base, "rows": rows}, sort_keys=True).encode()
    ).hexdigest()[:16]
    return {
        "method": "fixed-thresholds-v1",
        "mode": result["mode"],
        "scope": scope,
        "label": label,
        "sample_count": sample_count,
        "rows": rows,
        "base_evidence_id": base,
        "evidence_id": evidence,
        "note": note,
        "external_requests": 0,
    }
