from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .live_isochrone import METERS_PER_DEG_LAT, lng_scale

METHOD_VERSION = "route-audit-v1"
# 一致性红线的物理依据：成年人步行速度约 50–90 米/分钟；城区路网绕行系数
# （路网距离 ÷ 直线距离）通常在 1.2–1.5，超出 [1.0, 3.0] 视为可疑——
# 低于 1.0 直接指向坐标系/数据错位，高于 3.0 指向路网语义错误或起终点不可达。
SPEED_RANGE_M_PER_MIN = (30.0, 120.0)
DETOUR_RATIO_RANGE = (1.0, 3.0)
STEPS_SUM_TOLERANCE = (0.8, 1.2)
SYMMETRY_TOLERANCE = 0.25


def straight_distance_m(a: dict[str, float], b: dict[str, float]) -> float:
    """当地平面近似的直线距离（米），与等时圈模块同一投影口径。"""
    return math.hypot((b["lng"] - a["lng"]) * lng_scale(a["lat"]), (b["lat"] - a["lat"]) * METERS_PER_DEG_LAT)


def audit_one(pair: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    """对一条真实算路结果做自动化一致性检查，返回带红旗标记的审计行。"""
    straight = straight_distance_m(pair["origin"], pair["destination"])
    distance_m = route.get("distance_m")
    duration_s = route.get("duration_s")
    flags: list[str] = []

    detour = round(distance_m / straight, 2) if distance_m and straight > 0 else None
    if distance_m is None or distance_m <= 0:
        flags.append("路线距离缺失或非正数")
    elif detour is not None and not (DETOUR_RATIO_RANGE[0] <= detour <= DETOUR_RATIO_RANGE[1]):
        flags.append(f"绕行系数 {detour} 超出 [{DETOUR_RATIO_RANGE[0]}, {DETOUR_RATIO_RANGE[1]}]")

    if duration_s is None or duration_s <= 0:
        flags.append("路线耗时缺失或非正数")
    speed = round(distance_m / (duration_s / 60), 1) if distance_m and duration_s and duration_s > 0 else None
    if speed is not None and not (SPEED_RANGE_M_PER_MIN[0] <= speed <= SPEED_RANGE_M_PER_MIN[1]):
        flags.append(f"隐含步速 {speed} 米/分钟超出 [{SPEED_RANGE_M_PER_MIN[0]}, {SPEED_RANGE_M_PER_MIN[1]}]")

    steps = route.get("steps") or []
    steps_sum = sum((s.get("distance_m") or 0) for s in steps)
    steps_ratio = round(steps_sum / distance_m, 2) if distance_m and steps and steps_sum else None
    if steps_ratio is not None and not (STEPS_SUM_TOLERANCE[0] <= steps_ratio <= STEPS_SUM_TOLERANCE[1]):
        flags.append(f"分段累加 {steps_ratio} × 总距离超出容差")

    return {
        **pair,
        "straight_m": round(straight, 1),
        "distance_m": distance_m,
        "duration_s": duration_s,
        "walk_minutes": round(duration_s / 60, 1) if duration_s else None,
        "detour_ratio": detour,
        "speed_m_per_min": speed,
        "steps_count": len(steps),
        "steps_sum_ratio": steps_ratio,
        "flags": flags,
        "verdict": "可疑" if flags else "自动通过",
    }


def reverse_mismatch(forward: dict[str, Any], backward: dict[str, Any]) -> str | None:
    """往返对称性检查：步行往返耗时不应对称差异超过 25%。"""
    a, b = forward.get("duration_s"), backward.get("duration_s")
    if not a or not b:
        return None
    diff = abs(a - b) / max(a, b)
    if diff > SYMMETRY_TOLERANCE:
        return f"往返耗时差异 {round(diff * 100, 1)}% 超过 {SYMMETRY_TOLERANCE * 100:.0f}%"
    return None


def build_pairs(
    inspect: dict[str, Any],
    isochrone: dict[str, Any],
    total: int = 20,
    minutes: int = 15,
) -> list[dict[str, Any]]:
    """从真实体检结果里选出待审计的起终点对：设施 + 等时圈网格点（可达/不可达/未知兼顾）。"""
    center = isochrone["center"]
    threshold_s = minutes * 60
    pairs: list[dict[str, Any]] = []
    for facility in inspect.get("facilities") or []:
        pairs.append(
            {
                "kind": "设施",
                "label": facility.get("name") or "未命名设施",
                "category": "、".join(facility.get("categories") or []),
                "origin": dict(center),
                "destination": dict(facility["location"]),
            }
        )
    by_status: dict[str, list[dict[str, Any]]] = {}
    for point in isochrone.get("points") or []:
        if point.get("duration_s") is None:
            continue
        by_status.setdefault(point["status"], []).append(point)
    # 剩余名额在可达/不可达两侧均分，每侧取「耗时离阈值最远」的，保证边界两侧都被覆盖。
    remaining = max(0, total - len(pairs))
    statuses = [status for status in ("reachable", "unreachable") if by_status.get(status)]
    if statuses:
        per_status = -(-remaining // len(statuses))  # 向上均分
        for status in statuses:
            pool = sorted(by_status[status], key=lambda p: -abs((p.get("duration_s") or 0) - threshold_s))
            for point in pool[:per_status]:
                if len(pairs) >= total:
                    break
                pairs.append(
                    {
                        "kind": f"网格-{status}",
                        "label": f"({point['dx_m']}, {point['dy_m']})",
                        "category": "采样点",
                        "origin": dict(center),
                        "destination": {"lat": point["lat"], "lng": point["lng"]},
                    }
                )
    return pairs[:total]


def render_report(
    rows: list[dict[str, Any]], meta: dict[str, Any], symmetry_rows: list[dict[str, Any]]
) -> str:
    """渲染桌面核验模板：脚本自动检查列已填，人工两列留白待桌面目测后回填。"""
    flagged = sum(1 for row in rows if row["verdict"] == "可疑")
    lines = [
        f"# 路线审计报告：{meta['address']}",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 数据来源：百度地图步行路线 API（coord_type=bd09ll）+ 地理编码 V3",
        f"- 审计算法：{METHOD_VERSION}｜配对数：{len(rows)}｜自动可疑：{flagged} 条",
        f"- 阈值分钟：{meta['minutes']}｜投影：当地平面近似（等距圆柱）",
        "",
        "## 使用方法（桌面核验，无需实地）",
        "",
        "1. 看「自动检查」列：红旗项必须逐条桌面目测；自动通过项随机抽 5 条目测。",
        "2. 目测方式：把「终点坐标」粘贴进百度地图网页版，对比路线是否真实存在、距离量级是否一致。",
        "3. 在「人工核对」与「结论」列回填：核对方式（地图目测/实地）、结论（合理/存疑+原因）。",
        "4. 全部回填后，本报告即为任务书要求的「真实对比测试报告」附件。",
        "",
        f"| # | 类型 | 标签 | 终点坐标（经度,纬度） | 直线m | 路网m | 分钟 | 绕行系数 | 步速m/min | 分段/总 | 自动检查 | 人工核对 | 结论 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for index, row in enumerate(rows, 1):
        check = "；".join(row["flags"]) if row["flags"] else "通过"
        destination = row.get("destination") or {}
        destination_text = f"{destination.get('lng')},{destination.get('lat')}"
        lines.append(
            f"| {index} | {row['kind']} | {row['label']} | `{destination_text}` | {row['straight_m']} | {row['distance_m']} | {row['walk_minutes']} | {row['detour_ratio']} | {row['speed_m_per_min']} | {row['steps_sum_ratio']} | {check} | | |"
        )
    if symmetry_rows:
        lines += [
            "",
            "## 往返对称性抽查",
            "",
            "| 配对 | 正向分钟 | 反向分钟 | 自动检查 |",
            "| --- | ---: | ---: | --- |",
        ]
        for row in symmetry_rows:
            lines.append(
                f"| {row['label']} | {row['forward_min']} | {row['backward_min']} | {row['mismatch'] or '通过'} |"
            )
    lines += [
        "",
        "## 边界说明",
        "",
        "- 本报告只审计「API 数据自身的物理一致性与桌面可核对性」，不构成实地测量结论。",
        "- 步速范围与绕行系数范围是城区一般经验值，个别坡地/滨河路线可人工放宽并注明。",
        "",
    ]
    return "\n".join(lines)
