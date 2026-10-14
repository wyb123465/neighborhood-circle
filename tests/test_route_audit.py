from __future__ import annotations

from backend.route_audit import (
    audit_one,
    build_pairs,
    render_report,
    reverse_mismatch,
    straight_distance_m,
)

CENTER = {"lat": 31.225074, "lng": 121.435614}


def make_pair(label="样例", dx=0.0, dy=800.0):
    from backend.live_isochrone import METERS_PER_DEG_LAT, lng_scale

    return {
        "kind": "网格-测试",
        "label": label,
        "category": "采样点",
        "origin": dict(CENTER),
        "destination": {
            "lat": CENTER["lat"] + dy / METERS_PER_DEG_LAT,
            "lng": CENTER["lng"] + dx / lng_scale(CENTER["lat"]),
        },
    }


def test_audit_flags_impossible_walking_speed():
    pair = make_pair()
    row = audit_one(pair, {"distance_m": 800, "duration_s": 60, "steps": []})  # 800 米/分钟不可能步行
    assert row["verdict"] == "可疑"
    assert any("步速" in flag for flag in row["flags"])
    assert row["speed_m_per_min"] == 800.0


def test_audit_flags_distance_shorter_than_straight_line():
    pair = make_pair(dx=1000, dy=0)  # 直线约 1000m
    row = audit_one(pair, {"distance_m": 300, "duration_s": 300, "steps": []})  # 路网 < 直线 → 坐标系错误特征
    assert row["verdict"] == "可疑"
    assert any("绕行系数" in flag for flag in row["flags"])
    assert row["detour_ratio"] < 1.0


def test_audit_passes_physically_plausible_route():
    pair = make_pair(dx=600, dy=0)  # 直线 600m
    row = audit_one(
        pair, {"distance_m": 750, "duration_s": 600, "steps": [{"distance_m": 400}, {"distance_m": 350}]}
    )
    assert row["verdict"] == "自动通过"
    assert row["flags"] == []
    assert row["detour_ratio"] == 1.25
    assert row["steps_sum_ratio"] == 1.0


def test_audit_flags_missing_or_non_positive_route_values():
    pair = make_pair()
    row = audit_one(pair, {"distance_m": 0, "duration_s": 0, "steps": []})
    assert row["verdict"] == "可疑"
    assert any("距离缺失" in flag for flag in row["flags"])
    assert any("耗时缺失" in flag for flag in row["flags"])


def test_reverse_symmetry_check():
    forward = {"duration_s": 600}
    assert reverse_mismatch(forward, {"duration_s": 640}) is None
    assert "往返耗时差异" in (reverse_mismatch(forward, {"duration_s": 900}) or "")


def test_build_pairs_balances_facilities_and_both_sides_of_boundary():
    inspect = {
        "facilities": [
            {"name": "设施A", "categories": ["医疗"], "location": {"lat": 31.23, "lng": 121.44}},
            {"name": "设施B", "categories": ["养老"], "location": {"lat": 31.22, "lng": 121.43}},
        ]
    }
    isochrone = {
        "center": dict(CENTER),
        "points": [
            {
                "dx_m": 0,
                "dy_m": 675,
                "lat": 31.231,
                "lng": 121.4356,
                "status": "reachable",
                "duration_s": 500,
            },
            {
                "dx_m": 1350,
                "dy_m": 0,
                "lat": 31.225,
                "lng": 121.4477,
                "status": "unreachable",
                "duration_s": 1100,
            },
            {
                "dx_m": 675,
                "dy_m": 675,
                "lat": 31.231,
                "lng": 121.442,
                "status": "reachable",
                "duration_s": 730,
            },
            {
                "dx_m": 1350,
                "dy_m": 675,
                "lat": 31.231,
                "lng": 121.4477,
                "status": "unreachable",
                "duration_s": 1000,
            },
        ],
    }
    pairs = build_pairs(inspect, isochrone, total=4)

    assert len(pairs) == 4
    kinds = [p["kind"] for p in pairs]
    assert kinds.count("设施") == 2
    assert kinds.count("网格-reachable") == 1 and kinds.count("网格-unreachable") == 1
    # 同侧网格点取「耗时离阈值最远」的：unreachable 应选 1100s 那个而非 1000s。
    unreachable = next(p for p in pairs if p["kind"] == "网格-unreachable")
    assert unreachable["destination"]["lat"] == 31.225
    for pair in pairs:
        assert straight_distance_m(pair["origin"], pair["destination"]) > 0


def test_build_pairs_uses_requested_threshold_for_boundary_sampling():
    inspect = {"facilities": []}
    isochrone = {
        "center": dict(CENTER),
        "points": [
            {"dx_m": 0, "dy_m": 0, "lat": 31.225, "lng": 121.4356, "status": "reachable", "duration_s": 550},
            {"dx_m": 600, "dy_m": 0, "lat": 31.225, "lng": 121.442, "status": "reachable", "duration_s": 600},
            {"dx_m": 900, "dy_m": 0, "lat": 31.225, "lng": 121.445, "status": "reachable", "duration_s": 900},
        ],
    }
    pairs = build_pairs(inspect, isochrone, total=1, minutes=10)
    assert pairs[0]["label"] == "(900, 0)"


def test_report_contains_manual_columns_and_guidance():
    pair = make_pair(dx=600, dy=0)
    rows = [audit_one(pair, {"distance_m": 750, "duration_s": 600, "steps": []})]
    report = render_report(rows, {"address": "测试地址", "minutes": 15}, symmetry_rows=[])
    assert "| 人工核对 | 结论 |" in report
    assert "终点坐标（经度,纬度）" in report
    destination = pair["destination"]
    assert f"`{destination['lng']},{destination['lat']}`" in report
    assert "无需实地" in report
    assert "桌面目测" in report
    assert "自动通过" in report
