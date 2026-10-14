from __future__ import annotations

import math

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.baidu import BaiduApiError, BaiduConfig, BaiduMapsClient
from backend.live_isochrone import METERS_PER_DEG_LAT, build_isochrone, lng_scale

CENTER = {"lat": 31.225074, "lng": 121.435614}


def client_for(handler) -> BaiduMapsClient:
    return BaiduMapsClient(
        BaiduConfig(ak="test", qps=1000),
        transport=httpx.MockTransport(handler),
    )


def duration_handler(row_error_at=None):
    """按「直线距离 ÷ 80 米/分钟」生成真实耗时，用于确定性地验证可达分类。"""

    def handler(request: httpx.Request):
        rows = []
        for pair in request.url.params["destinations"].split("|"):
            lat, lng = (float(v) for v in pair.split(","))
            dx = (lng - CENTER["lng"]) * lng_scale(CENTER["lat"])
            dy = (lat - CENTER["lat"]) * METERS_PER_DEG_LAT
            distance_m = math.hypot(dx, dy)
            if row_error_at is not None and math.isclose(dx, row_error_at[0], abs_tol=1.0) and math.isclose(dy, row_error_at[1], abs_tol=1.0):
                rows.append({"status": 1, "message": "单点失败"})
            else:
                rows.append({"distance": {"value": distance_m, "text": "x"}, "duration": {"value": distance_m / 80 * 60, "text": "x"}})
        return httpx.Response(200, json={"status": 0, "result": rows})

    return handler


def test_coarse_grid_classifies_points_by_real_duration():
    maps = client_for(duration_handler())
    result = build_isochrone(maps, center=dict(CENTER), minutes=15, grid_m=200, refine=False)

    # 15 分钟 → 1350m 包围盒；间距逐级放大到 675m 才能装进单次批量算路上限，
    # 网格 5×5 去掉中心 = 24 个采样点。
    assert result["method_version"] == "grid-sample-matrix-v3"
    assert result["parameters"]["coarse_point_count"] == 24
    assert result["parameters"]["refined_point_count"] == 0
    assert result["parameters"]["grid_spacing_m"] == 675
    assert result["summary"]["known"] == 24
    assert result["summary"]["unknown"] == 0

    # 直线 80 米/分钟下：偏差 ≤1200m 的点耗时 ≤900s，网格中恰好 8 个点可达。
    assert result["summary"]["reachable"] == 8
    assert result["summary"]["unreachable"] == 16
    assert result["summary"]["coarse_ratio_pct"] == round(8 / 24 * 100, 1)
    assert result["summary"]["reachable_ratio_pct"] == result["summary"]["coarse_ratio_pct"]

    sample = next(p for p in result["points"] if p["dx_m"] == 675 and p["dy_m"] == 675)
    assert sample["status"] == "reachable"
    assert sample["walk_minutes"] == round(math.hypot(675, 675) / 80, 1)
    assert sample["generation"] == "coarse"
    corner = next(p for p in result["points"] if abs(p["dx_m"]) == 1350)
    assert corner["status"] == "unreachable"
    assert result["performance"]["matrix_calls"] == 12  # ceil(24/2)，默认 2 对/次留并发余量


def test_row_errors_become_unknown_instead_of_silent_drops():
    maps = client_for(duration_handler(row_error_at=(675, 0)))
    result = build_isochrone(maps, center=dict(CENTER), minutes=15, grid_m=200, refine=False)

    assert result["summary"]["unknown"] == 1
    assert result["summary"]["known"] == 23
    unknown_points = [p for p in result["points"] if p["status"] == "unknown"]
    assert len(unknown_points) == 1 and unknown_points[0]["dx_m"] == 675 and unknown_points[0]["dy_m"] == 0
    assert unknown_points[0].get("duration_s") is None, "未知点不得携带耗时，避免被误读"
    assert result["summary"]["reachable"] == 7


def test_adaptive_refinement_targets_threshold_boundary():
    maps = client_for(duration_handler())
    result = build_isochrone(maps, center=dict(CENTER), minutes=15, grid_m=200, refine=True)

    # 预算 32 个加密点 = 4 个锚点 × 3×3 细分；按「耗时最接近阈值」排序，
    # 直线 1350m 的四个轴向点（|duration-900|=112s）最先入选。
    assert result["parameters"]["refined_point_count"] == 32
    assert result["parameters"]["refined_spacing_m"] == 225.0
    assert result["parameters"]["point_count"] == 56

    refined_keys = {(p["dx_m"], p["dy_m"]) for p in result["points"] if p["generation"] == "refined"}
    # 锚点 (1350, 0) 的细分点：dx ∈ {1125,1350,1575}，dy ∈ {-225,0,225}（去中心）。
    assert (1125.0, 0.0) in refined_keys and (1575.0, 225.0) in refined_keys
    # 最低优先级的角锚点 (1350,1350)（|diff|=532s）不应被加密。
    assert (1575.0, 1575.0) not in refined_keys and (1125.0, 1125.0) not in refined_keys
    # 加密点全部完成分类。
    assert all(p["status"] != "pending" for p in result["points"])

    # 直线 80 米/分钟下，每个 1350m 锚点的 8 个细分点中 3 个可达（1125m 系）。
    assert result["summary"]["refined"] == {"count": 32, "known": 32, "reachable": 12}
    # 均匀口径（粗网格）比例不受加密影响；全点比例因边界加密而不同。
    assert result["summary"]["coarse_ratio_pct"] == 33.3
    assert result["summary"]["reachable_ratio_pct"] == round((8 + 12) / 56 * 100, 1)
    # 配额：粗网格 ceil(24/3)=8 次 + 加密 ceil(32/3)=11 次。
    assert result["performance"]["matrix_calls"] == 28  # ceil(24/2) + ceil(32/2)
    assert any("加密" in warning for warning in result["warnings"])


def test_matrix_failure_propagates_as_normalized_error():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"status": 302, "message": "quota"})

    with pytest.raises(BaiduApiError, match="接口失败"):
        build_isochrone(client_for(handler), center=dict(CENTER), minutes=15)


def test_isochrone_endpoint_parameter_contract():
    from backend.main import app

    client = TestClient(app)
    both = client.get("/api/live/isochrone", params={"address": "上海市长宁区愚园路", "lat": 31.2, "lng": 121.4})
    assert both.status_code == 400
    neither = client.get("/api/live/isochrone")
    assert neither.status_code == 400
    half = client.get("/api/live/isochrone", params={"lat": 31.2})
    assert half.status_code == 400
