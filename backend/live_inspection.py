from __future__ import annotations

import math
import hashlib
import json
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .baidu import BaiduApiError, BaiduMapsClient

# 检索词组按「画像」组织。一次体检的地点检索次数 = 展开后的检索词数量，而地点检索在
# 个人认证下只有 100 次/日，所以这个词组的规模直接决定项目每天能跑几次体检。
#
# full   召回优先：10 次地点检索/体检。
# narrow 配额优先：保留赛题明确要求识别的菜市场、药店、小学（1 公里盲区判断）以及演示
#        主线养老，放弃子类细分（医院、社区卫生服务中心、幼儿园、超市、养老服务中心、
#        老年人服务）：4 次地点检索/体检。
QUERY_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "full": {
        "医疗": ("医院", "社区卫生服务中心", "药店"),
        "养老": ("养老院", "养老服务中心", "老年人服务"),
        "教育": ("小学", "幼儿园"),
        "购物": ("菜市场", "超市"),
    },
    "narrow": {
        "医疗": ("药店",),
        "养老": ("养老院",),
        "教育": ("小学",),
        "购物": ("菜市场",),
    },
}
DEFAULT_QUERY_PROFILE = "full"
BLIND_SPOT_KINDS = ("菜市场", "药店", "小学")
BLIND_SPOT_RADIUS_M = 1000
BLIND_SPOT_GRID_M = 250


def subtype_matches(item: dict[str, Any], query: str) -> bool:
    """Conservative exclusion rules; remaining classifications need human QA."""
    name = (item.get("name") or "").lower()
    tag = str((item.get("detail_info") or {}).get("tag") or "")
    if query == "小学":
        return not any(token in name for token in ("vipkid", "美国小学", "培训", "辅导", "托管", "英语", "停车场", "体育馆", "游泳馆")) and "培训机构" not in tag
    if query == "药店":
        return not any(token in name for token in ("宠物", "兽药", "药监", "医药公司"))
    if query == "菜市场":
        return not any(token in name for token in ("监督管理", "管理所", "管理办公室"))
    return True

# 旧引用兼容：等价于 full 画像。
CATEGORY_QUERIES = QUERY_PROFILES[DEFAULT_QUERY_PROFILE]


def resolve_query_profile(profile: str | None) -> tuple[str, dict[str, tuple[str, ...]]]:
    """Resolve an explicit profile, else BAIDU_POI_QUERY_PROFILE, else the full default."""
    name = (profile or os.getenv("BAIDU_POI_QUERY_PROFILE", DEFAULT_QUERY_PROFILE)).strip().lower()
    if name not in QUERY_PROFILES:
        raise ValueError(f"检索词组画像无效：{name}；支持：{'、'.join(QUERY_PROFILES)}。")
    return name, QUERY_PROFILES[name]


def queries_per_category(profile: str | None = None) -> dict[str, int]:
    """How many place-search calls each category costs under a profile."""
    _, resolved = resolve_query_profile(profile)
    return {category: len(queries) for category, queries in resolved.items()}


def balanced_selection(facilities: list[dict[str, Any]], categories: list[str], limit: int, center: dict[str, float] | None = None) -> list[dict[str, Any]]:
    buckets = {
        category: sorted(
            (facility for facility in facilities if category in (facility.get("eligible_categories", facility["categories"]) if center else facility["categories"])),
            key=lambda facility: ((_distance_m(center, facility["location"], center["lat"]) if center else 0), facility.get("name") or "", facility["identity"]),
        )
        for category in categories
    }
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    while len(selected) < limit:
        progressed = False
        for category in categories:
            while buckets[category] and buckets[category][0]["identity"] in selected_ids:
                buckets[category].pop(0)
            if buckets[category] and len(selected) < limit:
                facility = buckets[category].pop(0)
                selected.append(facility)
                selected_ids.add(facility["identity"])
                progressed = True
        if not progressed:
            break
    return selected


def _distance_m(a: dict[str, float], b: dict[str, float], latitude: float) -> float:
    meters_per_lng = 111320.0 * math.cos(math.radians(latitude))
    return math.hypot(
        (a["lng"] - b["lng"]) * meters_per_lng,
        (a["lat"] - b["lat"]) * 111320.0,
    )


def _offset_location(center: dict[str, float], dx_m: float, dy_m: float) -> dict[str, float]:
    return {
        "lat": center["lat"] + dy_m / 111320.0,
        "lng": center["lng"] + dx_m / (111320.0 * math.cos(math.radians(center["lat"]))),
    }


def _build_blind_spot_recommendations(
    *,
    center: dict[str, float],
    point_rows: list[dict[str, Any]],
    kind_rows: dict[str, dict[str, Any]],
    radius_m: int,
    limit_per_kind: int = 3,
) -> list[dict[str, Any]]:
    """Suggest reference points that greedily cover known gap samples.

    The candidates are sampled grid points, not parcels or confirmed project
    sites. Keeping the heuristic explicit makes the result useful for a demo
    without turning an equal-weight sample into a land-use conclusion.
    """
    recommendations: list[dict[str, Any]] = []
    for kind in BLIND_SPOT_KINDS:
        if kind_rows[kind]["status"] == "unknown":
            continue
        gap_points = [
            point for point in point_rows
            if kind in point["missing_kinds"]
        ]
        remaining = set(range(len(gap_points)))
        for rank in range(1, limit_per_kind + 1):
            if not remaining:
                break
            best_index: int | None = None
            best_covered: set[int] = set()
            for candidate_index, candidate in enumerate(gap_points):
                covered = {
                    index
                    for index in remaining
                    if math.hypot(
                        candidate["dx_m"] - gap_points[index]["dx_m"],
                        candidate["dy_m"] - gap_points[index]["dy_m"],
                    ) <= radius_m
                }
                if len(covered) > len(best_covered):
                    best_index = candidate_index
                    best_covered = covered
            if best_index is None or not best_covered:
                break
            candidate = gap_points[best_index]
            remaining -= best_covered
            gap_count = len(gap_points)
            recommendations.append(
                {
                    "kind": kind,
                    "rank": rank,
                    "dx_m": candidate["dx_m"],
                    "dy_m": candidate["dy_m"],
                    "location": _offset_location(center, candidate["dx_m"], candidate["dy_m"]),
                    "gain_count": len(best_covered),
                    "gap_count": gap_count,
                    "gain_ratio_pct": round(len(best_covered) / gap_count * 100, 1) if gap_count else None,
                    "remaining_gap_count": len(remaining),
                    "method": "greedy sample coverage",
                    "note": "网格样点参考位置，不代表可直接建设的地块。",
                }
            )
    return recommendations


def build_blind_spots(
    *,
    center: dict[str, float],
    facilities: list[dict[str, Any]],
    query_success: dict[str, bool],
    radius_m: int = BLIND_SPOT_RADIUS_M,
    grid_m: int = BLIND_SPOT_GRID_M,
    query_evidence: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check 1km service gaps on a transparent local grid.

    This is a straight-line sampling check, separate from walking-time
    isochrones. A failed POI query is unknown, never a confirmed gap.
    """
    axis = range(-radius_m, radius_m + 1, grid_m)
    points = [
        {"dx_m": dx, "dy_m": dy}
        for dy in axis
        for dx in axis
        if math.hypot(dx, dy) <= radius_m
    ]
    source_by_kind = {
        kind: [facility["location"] for facility in facilities if kind in facility.get("matched_kinds", [])]
        for kind in BLIND_SPOT_KINDS
    }
    # Absence requires both a complete result set and a search disk that
    # contains the sample's entire service disk. A found nearby POI can still
    # prove coverage when other results are missing.
    evidence = query_evidence or {kind: {"complete": True, "radius_m": radius_m * 2} for kind in BLIND_SPOT_KINDS}
    reasons: dict[str, set[str]] = {kind: set() for kind in BLIND_SPOT_KINDS}
    point_rows = []
    for point in points:
        point_location = _offset_location(center, point["dx_m"], point["dy_m"])
        missing: list[str] = []
        unknown: list[str] = []
        for kind in BLIND_SPOT_KINDS:
            if not query_success.get(kind, False) or not source_by_kind[kind]:
                reasons[kind].add("检索未完成" if not query_success.get(kind, False) else "检索完成但未返回匹配 POI")
                unknown.append(kind)
                continue
            nearest = min(
                (_distance_m(point_location, facility, center["lat"]) for facility in source_by_kind[kind]),
                default=math.inf,
            )
            if nearest <= radius_m:
                continue
            boundary = evidence.get(kind, {})
            if not boundary.get("complete", False):
                unknown.append(kind)
                reasons[kind].add("检索分页已截断，不能确认设施不存在")
            elif math.hypot(point["dx_m"], point["dy_m"]) + radius_m > boundary.get("radius_m", 0) + 0.01:
                unknown.append(kind)
                reasons[kind].add("检索范围不足以覆盖样点周边 1 公里")
            else:
                missing.append(kind)
        point_rows.append(
            {
                **point,
                "status": "unknown" if unknown else ("gap" if missing else "covered"),
                "known_gap": bool(missing),
                "missing_kinds": missing,
                "unknown_kinds": unknown,
            }
        )

    kind_rows: dict[str, dict[str, Any]] = {}
    for kind in BLIND_SPOT_KINDS:
        unknown_count = sum(kind in point["unknown_kinds"] for point in point_rows)
        known_count = len(points) - unknown_count
        gap_count = sum(kind in point["missing_kinds"] for point in point_rows)
        kind_rows[kind] = {
            "status": "unknown" if not known_count else ("partial" if unknown_count else "complete"),
            "facility_count": len(source_by_kind[kind]),
            "sample_count": len(points),
            "known_count": known_count,
            "unknown_count": unknown_count,
            "gap_count": gap_count if known_count else None,
            "gap_ratio_pct": round(gap_count / known_count * 100, 1) if known_count else None,
            "reason": "；".join(sorted(reasons[kind])) or None,
            "search_evidence": evidence.get(kind),
        }

    recommendations = _build_blind_spot_recommendations(
        center=center,
        point_rows=point_rows,
        kind_rows=kind_rows,
        radius_m=radius_m,
    )
    confirmed_gap_count = sum(point["status"] == "gap" for point in point_rows)
    known_gap_count = sum(point["known_gap"] for point in point_rows)
    return {
        "method": "straight-line grid sampling",
        "radius_m": radius_m,
        "grid_spacing_m": grid_m,
        "center": center,
        "sample_count": len(points),
        "kinds": kind_rows,
        "points": point_rows,
        "combined_gap_count": confirmed_gap_count,
        "confirmed_gap_count": confirmed_gap_count,
        "known_gap_count": known_gap_count,
        "recommendation_limit_per_kind": 3,
        "recommendations": recommendations,
        "warnings": [
            "这是 1 公里直线距离专项检查，不是步行等时圈。",
            "采样点等权，不代表居民人口或土地面积。",
            "POI 检索失败或未纳入当前画像时标记为未知，不认定为设施缺失。",
            "POI 检索成功但没有返回匹配结果时也标记为未知，不把空结果当作确认缺口。",
            "缺口比例分母仅包含该类别已知样点；分页截断或范围不足时未找到设施的样点为未知。",
            "complete 仅表示本次检索证据边界完整，不保证地图数据库没有漏标或设施仍在营业。",
            "规划候选点由已知缺口样点贪心覆盖生成，只是参考位置，不代表地块适宜性或建设收益。",
        ],
    }


def inspect_live(
    maps: BaiduMapsClient,
    *,
    address: str | None,
    city: str | None,
    categories: list[str],
    radius_m: int,
    minutes: int,
    max_facilities: int = 30,
    query_profile: str | None = None,
    center_location: dict[str, float] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if not maps.configured:
        raise BaiduApiError("BAIDU_MAP_AK 未配置，未发起外部请求。")
    if maps.replay_mode and query_profile is None:
        query_profile = (maps.replay_metadata or {}).get("query_profile")
    profile_name, profile = resolve_query_profile(query_profile)
    geocoded = maps.geocode(address, city) if center_location is None else {"location": center_location, "source": "user-bd09ll", "address": address, "city": city}
    center = geocoded["location"]
    facilities: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    query_stats = {category: {"queries": len(profile[category]), "errors": 0} for category in categories}
    query_jobs = [(category, query) for category in categories for query in profile[category]]
    if profile_name != DEFAULT_QUERY_PROFILE:
        warnings.append(
            f"检索词组使用 {profile_name} 画像（每类 1 个检索词），子类召回低于 {DEFAULT_QUERY_PROFILE}，结论须注明画像。"
        )

    # POI queries are independent, so issue them concurrently and let the client's
    # own concurrency limit bound the parallelism. Responses are merged below in a
    # fixed declaration order, so the result never depends on completion order.
    started_poi = time.perf_counter()

    def fetch_query(category: str, query: str):
        try:
            search_radius = max(radius_m, BLIND_SPOT_RADIUS_M * 2) if query in BLIND_SPOT_KINDS else radius_m
            if maps.replay_mode:
                # Legacy recordings searched 1500 m. Preserve their evidence
                # and mark uncovered edge samples unknown instead of inventing
                # missing requests or treating their smaller disk as complete.
                search_radius = maps.recorded_search_radius(query, search_radius)
            items = maps.search_pois(location=center, query=query, radius_m=search_radius, city_limit=bool(city))
            return category, query, items, None
        except BaiduApiError as error:
            return category, query, None, error

    fetched: dict[tuple[str, str], list[dict[str, Any]]] = {}
    query_failures: dict[tuple[str, str], BaiduApiError] = {}
    with ThreadPoolExecutor(max_workers=max(1, maps.config.max_concurrency)) as executor:
        futures = [executor.submit(fetch_query, category, query) for category, query in query_jobs]
        for future in as_completed(futures):
            category, query, items, error = future.result()
            if error is not None:
                query_failures[(category, query)] = error
            else:
                fetched[(category, query)] = items

    for category, query in query_jobs:
        error = query_failures.get((category, query))
        if error is not None:
            query_stats[category]["errors"] += 1
            warnings.append(f"{category}/{query} 检索失败：{error}")
            continue
        for item in fetched.get((category, query), []):
            uid = item.get("uid") or f"{item['name']}:{item['location']['lat']}:{item['location']['lng']}"
            if uid in facilities:
                if query not in facilities[uid]["matched_queries"]:
                    facilities[uid]["matched_queries"].append(query)
                if query in BLIND_SPOT_KINDS and subtype_matches(item, query) and query not in facilities[uid]["matched_kinds"]:
                    facilities[uid]["matched_kinds"].append(query)
                if category not in facilities[uid]["categories"]:
                    facilities[uid]["categories"].append(category)
                if subtype_matches(item, query) and category not in facilities[uid]["eligible_categories"]:
                    facilities[uid]["eligible_categories"].append(category)
                continue
            facilities[uid] = {
                **item,
                "identity": uid,
                "categories": [category],
                "eligible_categories": [category] if subtype_matches(item, query) else [],
                "matched_queries": [query],
                "matched_kinds": [query] if query in BLIND_SPOT_KINDS and subtype_matches(item, query) else [],
                "classification_note": "检索词命中，子类待人工核验" if subtype_matches(item, query) else "子类排除规则命中，不参与专项覆盖",
                "classification_source": "query-rules",
            }
    poi_phase_ms = (time.perf_counter() - started_poi) * 1000

    legacy_selection = maps.replay_mode and (maps.replay_metadata or {}).get("selection_strategy") != "nearest"
    eligible = [f for f in facilities.values() if f["eligible_categories"]]
    ordered = balanced_selection(list(facilities.values()) if legacy_selection else eligible, categories, max_facilities, None if legacy_selection else center)
    if legacy_selection:
        warnings.append("该历史录制按类别与名称选样；新查询按类别兼顾近处设施，不能把旧样例视为新版近处设施清单。")
    category_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "reachable": 0, "route_errors": 0, "query_errors": 0}
    )

    for facility in ordered:
        for category in facility["eligible_categories"]:
            category_totals[category]["total"] += 1

    started_routes = time.perf_counter()

    def route_row_to_evidence(row: dict[str, Any]) -> dict[str, Any]:
        if row.get("status") == "error" or row.get("duration_s") is None:
            return {
                "status": "error",
                "distance_m": row.get("distance_m"),
                "message": row.get("message") or "批量算路未返回耗时",
            }
        duration_s = row.get("duration_s")
        return {
            "status": "ok",
            "distance_m": row.get("distance_m"),
            "duration_s": duration_s,
            "walk_minutes": round(duration_s / 60, 1) if duration_s is not None else None,
            "within_threshold": duration_s is not None and duration_s <= minutes * 60,
            "steps": [],
        }

    def fetch_route_individually(facility: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            route = maps.walking_route(origin=center, destination=facility["location"], destination_uid=facility.get("uid"))
            duration_s = route.get("duration_s")
            if duration_s is None:
                return facility, {
                    "status": "error",
                    "distance_m": route.get("distance_m"),
                    "message": "单点算路未返回耗时",
                }
            return facility, {
                "status": "ok",
                "distance_m": route.get("distance_m"),
                "duration_s": duration_s,
                "walk_minutes": round(duration_s / 60, 1) if duration_s is not None else None,
                "within_threshold": duration_s is not None and duration_s <= minutes * 60,
                "steps": route.get("steps", []),
            }
        except BaiduApiError as error:
            return facility, {"status": "error", "message": str(error)}

    # 主路径：1 次批量算路覆盖全部设施（起终点乘积 ≤50，1 起点 × ≤50 终点）；
    # 批量接口失败时回退为逐设施单独算路，不因接口选择而丢失路线证据。
    route_rows: dict[str, dict[str, Any]] = {}
    route_mode = "batch"
    if ordered:
        try:
            matrix_rows = maps.walking_route_matrix(origin=center, destinations=[f["location"] for f in ordered])
            if len(matrix_rows) != len(ordered):
                raise BaiduApiError("批量算路返回行数与设施数量不一致，无法按序对齐。")
            route_rows = {f["identity"]: route_row_to_evidence(row) for f, row in zip(ordered, matrix_rows)}
        except BaiduApiError:
            route_mode = "individual-fallback"
            warnings.append("批量算路失败，已回退为逐设施单独算路（调用次数与耗时更高）。")
            with ThreadPoolExecutor(max_workers=max(1, maps.config.max_concurrency)) as executor:
                futures = [executor.submit(fetch_route_individually, f) for f in ordered]
                for future in as_completed(futures):
                    facility, route = future.result()
                    route_rows[facility["identity"]] = route

    for facility in ordered:
        route = route_rows[facility["identity"]]
        facility["route"] = route
        for category in facility["eligible_categories"]:
            if route["status"] == "error":
                category_totals[category]["route_errors"] += 1
            elif route["within_threshold"]:
                category_totals[category]["reachable"] += 1
    route_phase_ms = (time.perf_counter() - started_routes) * 1000

    summary = {}
    for category in categories:
        totals = category_totals[category]
        totals["query_errors"] = query_stats[category]["errors"]
        known = totals["total"] - totals["route_errors"]
        retrieved = sum(category in f["eligible_categories"] for f in facilities.values())
        summary[category] = {
            **totals,
            "retrieved": retrieved,
            "evaluated": totals["total"],
            "known": known,
            "unknown": totals["route_errors"],
            "unreachable": known - totals["reachable"],
            "unassessed": retrieved - totals["total"],
            "excluded": sum(category in f["categories"] and category not in f["eligible_categories"] for f in facilities.values()),
            "center_to_facility_rate": round(totals["reachable"] / known * 100, 1) if known else None,
            "status": "partial" if totals["query_errors"] or totals["route_errors"] else ("empty" if not totals["total"] else "complete"),
        }

    if len(ordered) >= max_facilities:
        warnings.append(f"设施结果已截断为 {max_facilities} 条，不能视为完整 POI 清单。")
    warnings.append("当前结果是中心点到设施的路线证据，不是居民人口覆盖率。")
    if maps.replay_mode:
        warnings.append(f"历史录制回放：数据录制于 {(maps.replay_metadata or {}).get('recorded_at') or '未知时间'}，本次没有实时请求。")
    warnings.append("真实模式不输出居民人口覆盖率、连续灰色区域或候选建设方案。")
    warnings.append("POI 类别来自检索词规则；培训、托管等明显非小学结果排除出专项覆盖，剩余类别仍需人工核验。")
    query_success = {
        kind: any(
            kind in profile[category] and (category, kind) not in query_failures
            for category in categories
        )
        for kind in BLIND_SPOT_KINDS
    }
    blind_spots = build_blind_spots(
        center=center,
        facilities=list(facilities.values()),
        query_success=query_success,
        query_evidence={kind: {"radius_m": getattr(fetched.get((category, kind)), "radius_m", 0), "complete": getattr(fetched.get((category, kind)), "complete", False)} for category in categories for kind in BLIND_SPOT_KINDS if kind in profile[category]},
    )
    if any(row["status"] != "complete" for row in blind_spots["kinds"].values()):
        warnings.append("1 公里专项检查存在未知样点，未知不计入缺口。")
    route_errors = sum(facility["route"]["status"] == "error" for facility in ordered)
    evidence_id = hashlib.sha256(json.dumps({
        "method": "live-inspection-v2", "center": center,
        "categories": categories, "minutes": minutes, "radius_m": radius_m,
        "profile": profile_name, "facilities": ordered, "blind_spots": blind_spots,
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return {
        "method_version": "live-inspection-v2",
        "evidence_id": evidence_id,
        "mode": "live-replay" if maps.replay_mode else "live-partial",
        "replay": maps.replay_metadata if maps.replay_mode else None,
        "scope": "center-to-facility-route-evidence",
        "community": {"address": address, "city": city, "center": center},
        "geocode": geocoded,
        "parameters": {
            "categories": categories,
            "radius_m": radius_m,
            "minutes": minutes,
            "max_facilities": max_facilities,
            "query_profile": profile_name,
            "selection_strategy": "name-balanced-legacy" if legacy_selection else "nearest",
        },
        "facility_count": len(ordered),
        "facilities": ordered,
        "category_summary": summary,
        "blind_spots": blind_spots,
        "performance": {
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "poi_phase_ms": round(poi_phase_ms, 1),
            "route_phase_ms": round(route_phase_ms, 1),
            "route_mode": route_mode,
            "query_profile": profile_name,
            "poi_queries": sum(item["queries"] for item in query_stats.values()),
            "poi_query_errors": sum(item["errors"] for item in query_stats.values()),
            "unique_pois_before_limit": len(facilities),
            "routed_facilities": len(ordered),
            "eligible_facilities": len(eligible),
            "route_errors": route_errors,
            "poi_query_concurrency": min(max(1, maps.config.max_concurrency), len(query_jobs)),
            "max_concurrency": maps.config.max_concurrency,
            "truncated": len(facilities) > len(ordered),
            "quota_cost_note": "本次调用次数不等于计费量；地点检索在个人认证下为 100 次/日，详见 docs/baidu-integration.md。",
        },
        "warnings": warnings,
        "source": (
            geocoded["source"] + " + baidu-place-configured + "
            + ("baidu-routematrix-v2-walking" if route_mode == "batch" else "baidu-direction-v2-walking")
        ),
    }
