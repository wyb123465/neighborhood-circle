from __future__ import annotations

import threading
import time

import httpx
import pytest

from backend.baidu import BaiduConfig, BaiduMapsClient
from backend.live_inspection import CATEGORY_QUERIES, inspect_live


def test_live_partial_pipeline_deduplicates_facilities_and_keeps_route_evidence():
    def handler(request: httpx.Request):
        if request.url.path == "/geocoding/v3/":
            return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 121.4, "lat": 31.2}, "precise": 1}})
        if request.url.path == "/place/v3/around":
            query = request.url.params["query"]
            return httpx.Response(
                200,
                json={
                    "status": 0,
                    "results": [
                        {"uid": "shared", "name": f"{query}共享设施", "address": "甲路", "location": {"lng": 121.41, "lat": 31.21}},
                        {"uid": query, "name": f"{query}独有设施", "address": "乙路", "location": {"lng": 121.42, "lat": 31.22}},
                    ],
                },
            )
        if request.url.path == "/direction/v2/walking":
            return httpx.Response(
                200,
                json={"status": 0, "result": {"routes": [{"distance": 500, "duration": 600, "steps": []}]}},
            )
        if request.url.path == "/routematrix/v2/walking":
            count = len(request.url.params["destinations"].split("|"))
            rows = [{"distance": {"value": 500, "text": "500米"}, "duration": {"value": 600, "text": "10分钟"}} for _ in range(count)]
            return httpx.Response(200, json={"status": 0, "result": rows})
        raise AssertionError(request.url.path)

    maps = BaiduMapsClient(
        BaiduConfig(ak="test", max_place_pages=1, qps=1000),
        transport=httpx.MockTransport(handler),
    )
    result = inspect_live(
        maps,
        address="样例地址",
        city="样例城市",
        categories=["医疗", "养老"],
        radius_m=1500,
        minutes=15,
        max_facilities=10,
    )

    assert result["mode"] == "live-partial"
    assert result["facility_count"] == 7
    assert result["category_summary"]["医疗"]["reachable"] == 4
    assert result["facilities"][0]["route"]["within_threshold"] is True
    assert result["performance"]["route_mode"] == "batch"
    assert "blind_spots" in result
    assert set(result["blind_spots"]["kinds"]) == {"菜市场", "药店", "小学"}
    assert any("不是居民人口覆盖率" in warning for warning in result["warnings"])


def test_live_partial_pipeline_surfaces_route_failure_without_fabricating_reachability():
    def handler(request: httpx.Request):
        if request.url.path == "/geocoding/v3/":
            return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 121.4, "lat": 31.2}}})
        if request.url.path == "/place/v3/around":
            return httpx.Response(
                200,
                json={"status": 0, "results": [{"uid": "one", "name": "设施", "location": {"lng": 121.41, "lat": 31.21}}]},
            )
        if request.url.path in ("/direction/v2/walking", "/routematrix/v2/walking"):
            return httpx.Response(200, json={"status": 302, "message": "quota"})
        raise AssertionError(request.url.path)

    maps = BaiduMapsClient(BaiduConfig(ak="test", max_place_pages=1, qps=1000), transport=httpx.MockTransport(handler))
    result = inspect_live(
        maps,
        address="样例地址",
        city=None,
        categories=["医疗"],
        radius_m=1500,
        minutes=15,
    )

    assert result["facilities"][0]["route"]["status"] == "error"
    assert result["category_summary"]["医疗"]["reachable"] == 0
    assert result["category_summary"]["医疗"]["route_errors"] == 1
    assert result["category_summary"]["医疗"]["center_to_facility_rate"] is None
    assert result["performance"]["route_mode"] == "individual-fallback"
    assert any("批量算路失败" in warning for warning in result["warnings"])


def test_live_partial_pipeline_marks_missing_matrix_duration_as_route_error():
    def handler(request: httpx.Request):
        if request.url.path == "/geocoding/v3/":
            return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 121.4, "lat": 31.2}}})
        if request.url.path == "/place/v3/around":
            return httpx.Response(
                200,
                json={"status": 0, "results": [{"uid": "one", "name": "设施", "location": {"lng": 121.41, "lat": 31.21}}]},
            )
        if request.url.path == "/routematrix/v2/walking":
            return httpx.Response(
                200,
                json={"status": 0, "result": [{"distance": {"value": 500, "text": "500米"}, "duration": None}]},
            )
        if request.url.path == "/direction/v2/walking":
            return httpx.Response(200, json={"status": 302, "message": "quota"})
        raise AssertionError(request.url.path)

    maps = BaiduMapsClient(BaiduConfig(ak="test", max_place_pages=1, qps=1000), transport=httpx.MockTransport(handler))
    result = inspect_live(
        maps,
        address="样例地址",
        city=None,
        categories=["医疗"],
        radius_m=1500,
        minutes=15,
    )

    route = result["facilities"][0]["route"]
    assert route["status"] == "error"
    assert "未返回耗时" in route["message"]
    assert result["category_summary"]["医疗"]["route_errors"] == 1


def test_live_partial_pipeline_marks_missing_individual_duration_as_route_error():
    def handler(request: httpx.Request):
        if request.url.path == "/geocoding/v3/":
            return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 121.4, "lat": 31.2}}})
        if request.url.path == "/place/v3/around":
            return httpx.Response(
                200,
                json={"status": 0, "results": [{"uid": "one", "name": "设施", "location": {"lng": 121.41, "lat": 31.21}}]},
            )
        if request.url.path == "/routematrix/v2/walking":
            return httpx.Response(200, json={"status": 302, "message": "quota"})
        if request.url.path == "/direction/v2/walking":
            return httpx.Response(
                200,
                json={"status": 0, "result": {"routes": [{"distance": 500, "duration": None, "steps": []}]}},
            )
        raise AssertionError(request.url.path)

    maps = BaiduMapsClient(BaiduConfig(ak="test", max_place_pages=1, qps=1000), transport=httpx.MockTransport(handler))
    result = inspect_live(
        maps,
        address="样例地址",
        city=None,
        categories=["医疗"],
        radius_m=1500,
        minutes=15,
    )

    route = result["facilities"][0]["route"]
    assert route["status"] == "error"
    assert "未返回耗时" in route["message"]


def run_live_with_delays(delays, concurrency=4):
    """Run inspect_live while recording how many POI queries were in flight at once."""

    in_flight = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def handler(request: httpx.Request):
        if request.url.path == "/geocoding/v3/":
            return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 121.4, "lat": 31.2}}})
        if request.url.path == "/place/v3/around":
            query = request.url.params["query"]
            with lock:
                in_flight["now"] += 1
                in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
            try:
                time.sleep(delays.get(query, 0.0))
            finally:
                with lock:
                    in_flight["now"] -= 1
            return httpx.Response(
                200,
                json={
                    "status": 0,
                    "results": [
                        {
                            "uid": f"uid-{query}",
                            "name": f"名称-{query}",
                            "address": "样例路",
                            "location": {"lng": 121.41, "lat": 31.21},
                        }
                    ],
                },
            )
        if request.url.path == "/direction/v2/walking":
            return httpx.Response(200, json={"status": 0, "result": {"routes": [{"distance": 500, "duration": 600, "steps": []}]}})
        if request.url.path == "/routematrix/v2/walking":
            count = len(request.url.params["destinations"].split("|"))
            rows = [{"distance": {"value": 500, "text": "500米"}, "duration": {"value": 600, "text": "10分钟"}} for _ in range(count)]
            return httpx.Response(200, json={"status": 0, "result": rows})
        raise AssertionError(request.url.path)

    maps = BaiduMapsClient(
        BaiduConfig(ak="test", max_place_pages=1, max_concurrency=concurrency, qps=1000),
        transport=httpx.MockTransport(handler),
    )
    result = inspect_live(
        maps,
        address="样例地址",
        city=None,
        categories=["医疗", "养老"],
        radius_m=1500,
        minutes=15,
        max_facilities=20,
    )
    return result, in_flight["peak"]


def collect_queries(**inspect_kwargs):
    """Run inspect_live with an empty POI response and record the place-search queries."""

    seen: list[str] = []

    def handler(request: httpx.Request):
        if request.url.path == "/geocoding/v3/":
            return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 121.4, "lat": 31.2}}})
        if request.url.path == "/place/v3/around":
            seen.append(request.url.params["query"])
            return httpx.Response(200, json={"status": 0, "results": []})
        raise AssertionError(f"没有 POI 时不应发起额外请求：{request.url.path}")

    maps = BaiduMapsClient(BaiduConfig(ak="test", max_place_pages=1, qps=1000), transport=httpx.MockTransport(handler))
    result = inspect_live(
        maps,
        address="样例地址",
        city=None,
        categories=["医疗", "养老", "教育", "购物"],
        radius_m=1500,
        minutes=15,
        **inspect_kwargs,
    )
    return result, sorted(seen)


def test_full_profile_is_default_and_costs_ten_place_queries():
    result, queries = collect_queries()

    assert result["performance"]["query_profile"] == "full"
    assert result["performance"]["poi_queries"] == 10 == len(queries)
    assert result["parameters"]["query_profile"] == "full"


def test_narrow_profile_costs_four_queries_and_keeps_competition_required_kinds():
    result, queries = collect_queries(query_profile="narrow")

    assert result["performance"]["query_profile"] == "narrow"
    assert result["performance"]["poi_queries"] == 4 == len(queries)
    # POI 检索并发执行，请求到达顺序不确定，因此只断言集合。
    assert set(queries) == {"药店", "养老院", "小学", "菜市场"}
    # 赛题 40% 的评分项要求识别「1 公里内没有菜市场、药店或小学」的盲区，
    # narrow 画像必须保留这三类，否则省下配额却丢掉评分项。
    assert {"菜市场", "药店", "小学"} <= set(queries)
    assert any("narrow" in warning for warning in result["warnings"])


def test_unknown_profile_is_rejected_before_any_request():
    def handler(request: httpx.Request):
        raise AssertionError("画像无效时不应发起任何请求")

    maps = BaiduMapsClient(BaiduConfig(ak="test", max_place_pages=1, qps=1000), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="画像无效"):
        inspect_live(
            maps,
            address="样例地址",
            city=None,
            categories=["医疗"],
            radius_m=1500,
            minutes=15,
            query_profile="turbo",
        )


def test_poi_queries_run_concurrently_and_merge_in_fixed_order():
    queries = [query for category in ("医疗", "养老") for query in CATEGORY_QUERIES[category]]
    ascending = {query: 0.01 * index for index, query in enumerate(queries)}
    descending = {query: 0.01 * (len(queries) - index) for index, query in enumerate(queries)}

    first, peak_first = run_live_with_delays(ascending)
    second, peak_second = run_live_with_delays(descending)

    assert peak_first >= 2 and peak_second >= 2, "POI 检索没有真正并发执行"
    assert peak_first <= 4 and peak_second <= 4, "并发度超过了 max_concurrency"

    # Reversing which query answers first must not change the merged output.
    assert first["facilities"] == second["facilities"]
    assert first["category_summary"] == second["category_summary"]
    assert {facility["matched_queries"][0] for facility in first["facilities"]} == set(queries)
    assert first["performance"]["poi_query_concurrency"] == 4
