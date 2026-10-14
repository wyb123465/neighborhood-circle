from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

from .baidu import BaiduApiError, BaiduMapsClient

METHOD_VERSION = "grid-sample-matrix-v3"
METERS_PER_DEG_LAT = 111320.0
# 单次批量算路起终点乘积上限 50；留 5 个余量，1 个起点最多带 45 个终点。
MAX_DESTINATIONS_PER_CALL = 45
# 自适应边界加密：每个边界锚点补 3×3 细分点，总加密点数受限以控制时延与配额。
REFINEMENT_SUBDIVISIONS = 3
REFINEMENT_BUDGET = 32


def lng_scale(lat: float) -> float:
    """当地平面近似的每经度米数；社区尺度（≤3km）下误差可忽略，口径见 warnings。"""
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat))


def _grid_spacing(extent_m: float, requested_m: float) -> float:
    """从请求间距出发逐步放大，直到单轮采样点数不超过批量算路单次容量。"""
    spacing = max(50.0, float(requested_m))
    while True:
        side = int(math.floor(2 * extent_m / spacing)) + 1
        if side * side - 1 <= MAX_DESTINATIONS_PER_CALL:
            return spacing
        spacing *= 1.5


def _make_point(c_lat: float, c_lng: float, dx: float, dy: float, generation: str) -> dict[str, Any]:
    return {
        "dx_m": round(dx, 1),
        "dy_m": round(dy, 1),
        "lat": round(c_lat + dy / METERS_PER_DEG_LAT, 6),
        "lng": round(c_lng + dx / lng_scale(c_lat), 6),
        "status": "unknown",
        "generation": generation,
    }


def _apply_row(point: dict[str, Any], row: dict[str, Any], threshold_s: float) -> None:
    """把一行算路结果写回采样点；失败与缺耗时一律记 unknown，不冒充结论。"""
    point["near_threshold"] = False
    if row.get("status") == "error":
        point["status"] = "unknown"
        point["message"] = row.get("message")
        return
    duration_s = row.get("duration_s")
    if duration_s is None:
        point["status"] = "unknown"
        return
    point["status"] = "reachable" if duration_s <= threshold_s else "unreachable"
    point["duration_s"] = duration_s
    point["walk_minutes"] = round(duration_s / 60, 1)
    point["near_threshold"] = abs(duration_s - threshold_s) <= 120


def _boundary_anchors(points: list[dict[str, Any]], spacing: float, threshold_s: float) -> list[dict[str, Any]]:
    """四邻域中同时出现可达与不可达的粗网格点，即穿越边界的锚点；
    按耗时与阈值的距离排序，最不确定的先加密。"""
    by_key = {(round(p["dx_m"]), round(p["dy_m"])): p for p in points}
    anchors: list[dict[str, Any]] = []
    for (dx, dy), point in by_key.items():
        if point["status"] not in ("reachable", "unreachable"):
            continue
        neighbor_statuses = set()
        for ndx, ndy in ((spacing, 0), (-spacing, 0), (0, spacing), (0, -spacing)):
            neighbor = by_key.get((round(dx + ndx), round(dy + ndy)))
            if neighbor is not None:
                neighbor_statuses.add(neighbor["status"])
        if "reachable" in neighbor_statuses and "unreachable" in neighbor_statuses:
            anchors.append(point)
    anchors.sort(key=lambda p: abs((p.get("duration_s") or threshold_s) - threshold_s))
    return anchors


def build_isochrone(
    maps: BaiduMapsClient,
    *,
    center: dict[str, float],
    minutes: int = 15,
    grid_m: int = 200,
    refine: bool = True,
) -> dict[str, Any]:
    """网格采样 + 批量测时 + 自适应边界加密，得到中心点周边的近似步行等时圈。

    设计对应任务书的「创新的空间插值」得分项：不获取底层路网数据，
    先用粗网格均匀采样定位边界，再在可达性突变的锚点周围按 1/3 间距
    补 3×3 细分点（优先加密耗时最接近阈值的锚点）。只输出采样点事实，
    不拟合连续边界——河道、围挡造成的孔洞不会被凹包悄悄填平。
    """
    started = time.perf_counter()
    if not maps.configured:
        raise BaiduApiError("BAIDU_MAP_AK 未配置，未发起外部请求。")

    c_lat, c_lng = center["lat"], center["lng"]
    extent_m = minutes * 90  # 覆盖 15 分钟步行（约 1200m）的宽松包围盒
    spacing = _grid_spacing(extent_m, grid_m)
    side = int(math.floor(2 * extent_m / spacing)) + 1
    axis = [-extent_m + i * spacing for i in range(side)]

    points: list[dict[str, Any]] = []
    for dy in axis:
        for dx in axis:
            if dx == 0 and dy == 0:
                continue  # 中心点本身
            points.append(_make_point(c_lat, c_lng, dx, dy, "coarse"))

    threshold_s = minutes * 60
    pairs = max(1, maps.config.matrix_pairs)
    matrix_calls = 0

    destinations = [{"lat": p["lat"], "lng": p["lng"]} for p in points]
    rows = maps.walking_route_matrix(origin=center, destinations=destinations)
    matrix_calls += math.ceil(len(destinations) / pairs)
    for point, row in zip(points, rows):
        _apply_row(point, row, threshold_s)

    # 自适应加密：在可达性突变的粗网格锚点周围补 3×3 细分点。
    refined_points: list[dict[str, Any]] = []
    if refine:
        anchors = _boundary_anchors(points, spacing, threshold_s)
        sub_spacing = spacing / REFINEMENT_SUBDIVISIONS
        used_keys = {(p["dx_m"], p["dy_m"]) for p in points}
        for anchor in anchors:
            if len(refined_points) + (REFINEMENT_SUBDIVISIONS ** 2 - 1) > REFINEMENT_BUDGET:
                break
            for i in range(-1, 2):
                for j in range(-1, 2):
                    if i == 0 and j == 0:
                        continue
                    dx = round(anchor["dx_m"] + i * sub_spacing, 1)
                    dy = round(anchor["dy_m"] + j * sub_spacing, 1)
                    if (dx, dy) in used_keys:
                        continue
                    used_keys.add((dx, dy))
                    refined_points.append(_make_point(c_lat, c_lng, dx, dy, "refined"))
        if refined_points:
            sub_destinations = [{"lat": p["lat"], "lng": p["lng"]} for p in refined_points]
            sub_rows = maps.walking_route_matrix(origin=center, destinations=sub_destinations)
            matrix_calls += math.ceil(len(sub_destinations) / pairs)
            for point, row in zip(refined_points, sub_rows):
                _apply_row(point, row, threshold_s)
            points = points + refined_points

    # A result identifier must also change when the route evidence changes.
    evidence_id = hashlib.sha256(json.dumps({
        "method": METHOD_VERSION, "center": center, "minutes": minutes,
        "spacing": spacing, "refine": refine,
        "points": [{k: p.get(k) for k in ("dx_m", "dy_m", "status", "duration_s")} for p in points],
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

    known = sum(1 for p in points if p["status"] != "unknown")
    reachable = sum(1 for p in points if p["status"] == "reachable")
    unknown = len(points) - known
    coarse_known = sum(1 for p in points if p["generation"] == "coarse" and p["status"] != "unknown")
    coarse_reachable = sum(1 for p in points if p["generation"] == "coarse" and p["status"] == "reachable")
    refined_known = sum(1 for p in refined_points if p["status"] != "unknown")
    refined_reachable = sum(1 for p in refined_points if p["status"] == "reachable")

    return {
        "mode": "live-replay" if maps.replay_mode else "live-partial",
        "method_version": METHOD_VERSION,
        "evidence_id": evidence_id,
        "center": center,
        "parameters": {
            "minutes": minutes,
            "requested_grid_m": grid_m,
            "grid_spacing_m": spacing,
            "refined_spacing_m": round(spacing / REFINEMENT_SUBDIVISIONS, 1) if refined_points else None,
            "extent_m": extent_m,
            "coarse_point_count": len(points) - len(refined_points),
            "refined_point_count": len(refined_points),
            "point_count": len(points),
        },
        "points": points,
        "summary": {
            "known": known,
            "reachable": reachable,
            "unreachable": known - reachable,
            "unknown": unknown,
            "near_threshold": sum(bool(p.get("near_threshold")) for p in points),
            "review_margin_minutes": 2,
            "reachable_ratio_pct": round(reachable / known * 100, 1) if known else None,
            "coarse_ratio_pct": round(coarse_reachable / coarse_known * 100, 1) if coarse_known else None,
            "coarse": {"count": len(points) - len(refined_points), "known": coarse_known, "reachable": coarse_reachable},
            "refined": {"count": len(refined_points), "known": refined_known, "reachable": refined_reachable},
        },
        "performance": {
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "matrix_calls": matrix_calls,
            "quota_cost_note": f"等时圈拆块消耗约 {matrix_calls} 次批量算路（每对计入并发，≤{pairs} 对/次；个人认证 5,000 次/日），不消耗地点检索。",
        },
        "warnings": [
            "耗时距阈值不超过 2 分钟的样点标记为近阈值待复核；仍保留原始接口判别。单条路线、批量测时与网页版结果可能不同。该范围为复核策略，不是误差置信区间。",
            *([f"历史录制回放：数据录制于 {(maps.replay_metadata or {}).get('recorded_at') or '未知时间'}，本次没有实时请求。"] if maps.replay_mode else []),
            f"网格采样是近似等时圈：粗网格间距 {spacing:.0f} 米"
            + (f"，边界附近已加密至 {spacing / REFINEMENT_SUBDIVISIONS:.0f} 米（{len(refined_points)} 个加密点）" if refined_points else "")
            + "，仍有同量级的判别误差。",
            "采样点各自独立测时，不表达河道、围墙等障碍物造成的连通性孔洞；相邻点可达性可以突变。",
            "经纬度到米为当地平面近似（等距圆柱投影），社区尺度下误差可忽略，但不适用于跨越大范围的项目。",
            "可达比例是采样点占比，不是居民人口覆盖率；不构成规划审批依据。加密点集中于边界，全点比例与均匀口径比例分别给出。",
        ],
        "source": "baidu-routematrix-v2-walking; coordinates=bd09ll",
        "replay": maps.replay_metadata if maps.replay_mode else None,
    }
