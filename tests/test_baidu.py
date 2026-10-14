from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest

from backend.baidu import BaiduApiError, BaiduConfig, BaiduMapsClient, load_env_file


def client_for(handler, **config_overrides):
    config = BaiduConfig(ak="server-only-test-key", cache_ttl_seconds=300, **config_overrides)
    return BaiduMapsClient(
        config,
        transport=httpx.MockTransport(handler),
    )


def test_geocode_normalizes_result_without_leaking_ak():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "status": 0,
                "result": {
                    "location": {"lng": 121.4269, "lat": 31.2168},
                    "precise": 1,
                    "confidence": 80,
                    "comprehension": 100,
                    "level": "道路",
                },
            },
        )

    maps = client_for(handler)
    result = maps.geocode("上海市长宁区愚园路", "上海市")

    assert result["location"] == {"lng": 121.4269, "lat": 31.2168}
    assert result["source"] == "baidu-geocoding-v3"
    assert "server-only-test-key" not in repr(result)
    assert seen[0].url.path == "/geocoding/v3/"
    assert seen[0].url.params["ak"] == "server-only-test-key"
    assert seen[0].url.params["ret_coordtype"] == "bd09ll"


def test_place_search_paginates_and_deduplicates_uids():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        page = request.url.params["page_num"]
        if page == "0":
            data = [
                {"uid": "a", "name": "样例药店 A", "address": "甲路", "location": {"lng": 121.4, "lat": 31.2}},
                {"uid": "duplicate", "name": "重复设施", "address": "乙路", "location": {"lng": 121.41, "lat": 31.21}},
            ]
            data.extend(
                {
                    "uid": f"page-0-{index}",
                    "name": f"分页设施 {index}",
                    "address": "分页路",
                    "location": {"lng": 121.43 + index / 1000, "lat": 31.23},
                }
                for index in range(18)
            )
        else:
            data = [
                {"uid": "duplicate", "name": "重复设施", "address": "乙路", "location": {"lng": 121.41, "lat": 31.21}},
                {"uid": "b", "name": "样例药店 B", "address": "丙路", "location": {"lng": 121.42, "lat": 31.22}},
            ]
        return httpx.Response(200, json={"status": 0, "results": data})

    maps = client_for(handler, max_place_pages=2, place_api_version="v2")
    result = maps.search_pois(location={"lat": 31.2, "lng": 121.4}, query="药店")

    ids = [item["uid"] for item in result]
    assert ids.count("duplicate") == 1
    assert "page-0-17" in ids
    assert ids[-1] == "b"
    assert len(calls) == 2
    assert calls[0].url.params["location"] == "31.200000,121.400000"
    assert calls[0].url.params["scope"] == "2"


def test_place_v3_around_is_default_and_reads_pois_field():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "status": 0,
                "pois": [
                    {"uid": "v3-a", "name": "V3 设施", "location": {"lng": 121.4, "lat": 31.2}},
                ],
            },
        )

    result = client_for(handler, max_place_pages=1).search_pois(
        location={"lat": 31.2, "lng": 121.4},
        query="养老服务",
    )

    assert result[0]["source"] == "baidu-place-v3"
    assert seen[0].url.path == "/place/v3/around"
    assert seen[0].url.params["page_size"] == "20"
    assert seen[0].url.params["ret_coordtype"] == "bd09ll"


def test_place_v2_can_be_selected_explicitly():
    def handler(request: httpx.Request):
        assert request.url.path == "/place/v2/search"
        return httpx.Response(
            200,
            json={"status": 0, "results": [{"uid": "v2-a", "name": "V2 设施", "location": {"lng": 121.4, "lat": 31.2}}]},
        )

    result = client_for(handler, place_api_version="v2", max_place_pages=1).search_pois(
        location={"lat": 31.2, "lng": 121.4},
        query="养老服务",
    )

    assert result[0]["source"] == "baidu-place-v2"


def test_walking_route_keeps_distance_duration_and_steps():
    def handler(request: httpx.Request):
        assert request.url.path == "/direction/v2/walking"
        assert request.url.params["origin"] == "31.216800,121.426900"
        assert request.url.params["destination"] == "31.220800,121.435200"
        return httpx.Response(
            200,
            json={
                "status": 0,
                "result": {
                    "routes": [
                        {
                            "distance": 1240,
                            "duration": 930,
                            "steps": [
                                {"distance": 500, "duration": 360, "instructions": "向东", "name": "愚园路", "path": "121.42,31.21"},
                            ],
                        }
                    ]
                },
            },
        )

    result = client_for(handler).walking_route(
        origin={"lat": 31.2168, "lng": 121.4269},
        destination={"lat": 31.2208, "lng": 121.4352},
    )

    assert result["distance_m"] == 1240
    assert result["duration_s"] == 930
    assert result["steps"][0]["instructions"] == "向东"
    assert result["source"] == "baidu-direction-v2-walking"


def test_repeated_geocode_hits_cache():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 1, "lat": 2}}})

    maps = client_for(handler)
    maps.geocode("同一个地址")
    maps.geocode("同一个地址")

    assert calls == 1


def test_baidu_error_is_normalized_without_response_dump():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"status": 302, "message": "ak invalid"})

    with pytest.raises(BaiduApiError, match="百度地图接口失败"):
        client_for(handler).geocode("地址")


def test_unconfigured_client_fails_before_network_call():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    maps = BaiduMapsClient(BaiduConfig(ak=""), transport=httpx.MockTransport(handler))
    with pytest.raises(BaiduApiError, match="未配置"):
        maps.geocode("地址")
    assert calls == 0


def test_project_env_file_is_actually_loaded(monkeypatch):
    """README 让操作者把 AK 写进 .env；确认写入后真的会被读进配置。"""

    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        pytest.skip("项目已有 .env，跳过以免覆盖真实配置")
    monkeypatch.delenv("BAIDU_MAP_AK", raising=False)
    env_file.write_text("BAIDU_MAP_AK=dotenv-wiring-check\n", encoding="utf-8")
    try:
        load_env_file()
        assert BaiduConfig.from_env().ak == "dotenv-wiring-check"
    finally:
        env_file.unlink(missing_ok=True)


def test_metrics_and_cache_reads_run_concurrently_without_deadlock():
    """metrics() and the cache-hit path must not acquire the two locks in opposite orders."""

    def handler(request: httpx.Request):
        return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 1, "lat": 2}}})

    maps = client_for(handler)
    maps.geocode("并发地址")
    rounds = 300
    barrier = threading.Barrier(12)

    def read_metrics():
        barrier.wait(timeout=10)
        for _ in range(rounds):
            maps.metrics()

    def read_cache():
        barrier.wait(timeout=10)
        for _ in range(rounds):
            maps.geocode("并发地址")

    threads = [threading.Thread(target=read_metrics) for _ in range(6)]
    threads += [threading.Thread(target=read_cache) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not any(thread.is_alive() for thread in threads), "线程未在超时前结束，可能发生锁序死锁"
    snapshot = maps.metrics()
    assert snapshot["cache_hits"] == 6 * rounds
    assert snapshot["network_requests"] == 1


def test_network_requests_are_throttled_to_configured_qps():
    """QPS 是每秒发起数，信号量限不住：发起点必须按 1/QPS 间隔排开。"""

    now = {"t": 100.0}
    sleeps: list[float] = []

    def clock():
        return now["t"]

    def fake_sleep(seconds: float):
        sleeps.append(seconds)
        now["t"] += seconds

    def handler(request: httpx.Request):
        return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 1, "lat": 2}}})

    maps = BaiduMapsClient(
        BaiduConfig(ak="server-only-test-key", qps=4),
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=fake_sleep,
    )
    for index in range(4):
        maps.geocode(f"不同地址 {index}")  # 不同地址保证各自都真实发网络请求

    assert sleeps == [0.25, 0.25, 0.25], f"4 次请求的发起间隔应依次排开 1/4 秒，实际 {sleeps}"
    assert maps.metrics()["network_requests"] == 4


def test_cache_hits_bypass_the_qps_throttle():
    now = {"t": 50.0}
    sleeps: list[float] = []

    def clock():
        return now["t"]

    def fake_sleep(seconds: float):
        sleeps.append(seconds)
        now["t"] += seconds

    def handler(request: httpx.Request):
        return httpx.Response(200, json={"status": 0, "result": {"location": {"lng": 1, "lat": 2}}})

    maps = BaiduMapsClient(
        BaiduConfig(ak="server-only-test-key", qps=1),
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=fake_sleep,
    )
    maps.geocode("同一地址")
    maps.geocode("同一地址")

    assert sleeps == [], "只有真实网络请求才进入节流；本次首请求无需等待、缓存命中不等待"


def test_walking_route_matrix_aligns_rows_and_formats_pairs():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        count = len(request.url.params["destinations"].split("|"))
        rows = [
            {"distance": {"value": 892, "text": "892米"}, "duration": {"value": 762, "text": "13分钟"}},
        ] * count
        return httpx.Response(200, json={"status": 0, "result": rows})

    result = client_for(handler).walking_route_matrix(
        origin={"lat": 31.225074, "lng": 121.435614},
        destinations=[{"lat": 31.229514, "lng": 121.440208}, {"lat": 31.221043, "lng": 121.441749}],
    )

    assert len(result) == 2
    assert result[0]["status"] == "ok" and result[0]["distance_m"] == 892 and result[0]["duration_s"] == 762
    assert result[0]["source"] == "baidu-routematrix-v2-walking"
    assert seen[0].url.path == "/routematrix/v2/walking"
    assert seen[0].url.params["origins"] == "31.225074,121.435614"
    assert seen[0].url.params["destinations"] == "31.229514,121.440208|31.221043,121.441749"


def test_walking_route_matrix_marks_row_errors_without_failing_the_batch():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "status": 0,
                "result": [
                    {"distance": {"value": 500, "text": "500米"}, "duration": {"value": 600, "text": "10分钟"}},
                    {"status": 1, "message": "起终点过近"},
                ],
            },
        )

    result = client_for(handler).walking_route_matrix(
        origin={"lat": 31.2, "lng": 121.4},
        destinations=[{"lat": 31.21, "lng": 121.41}, {"lat": 31.2001, "lng": 121.4001}],
    )

    assert result[0]["status"] == "ok" and result[0]["duration_s"] == 600
    assert result[1]["status"] == "error" and "起终点过近" in result[1]["message"]


def test_walking_route_matrix_rejects_more_than_50_pairs():
    def handler(request: httpx.Request):
        raise AssertionError("超限时应拒绝，不应发起请求")

    with pytest.raises(BaiduApiError, match="乘积上限"):
        client_for(handler).walking_route_matrix(
            origin={"lat": 31.2, "lng": 121.4},
            destinations=[{"lat": 31.2, "lng": 121.4}] * 51,
        )


def test_walking_route_matrix_chunks_to_pair_limit_and_keeps_alignment():
    """批量算路的并发按路线对数计入（告警短信 10/3），必须拆成 ≤3 对/次。"""
    calls = []

    def handler(request: httpx.Request):
        pairs = request.url.params["destinations"].split("|")
        calls.append(len(pairs))
        rows = [
            {"distance": {"value": int(round(float(pair.split(",")[0]) * 10000)), "text": "x"}, "duration": {"value": 600, "text": "x"}}
            for pair in pairs
        ]
        return httpx.Response(200, json={"status": 0, "result": rows})

    destinations = [{"lat": 31.20 + index * 0.01, "lng": 121.4} for index in range(7)]
    maps = BaiduMapsClient(
        BaiduConfig(ak="server-only-test-key", qps=1000, matrix_pairs=3),
        transport=httpx.MockTransport(handler),
    )
    result = maps.walking_route_matrix(origin={"lat": 31.2, "lng": 121.4}, destinations=destinations)

    assert calls == [3, 3, 1], f"matrix_pairs=3 时 7 个终点应拆成 3+3+1 对的三次请求，实际 {calls}"
    assert all(pairs <= 3 for pairs in calls), "任何一次请求的对数都不得超过 3（并发上限）"
    assert [row["distance_m"] for row in result] == [int(round(d["lat"] * 10000)) for d in destinations], "拆块合并后行序必须与请求顺序一致"


def test_matrix_chunks_are_spaced_by_pair_weight():
    """对数计入并发：携带 2 对的矩阵块应把发起时刻推后 2 × 1/QPS。"""
    now = {"t": 10.0}
    sleeps: list[float] = []

    def clock():
        return now["t"]

    def fake_sleep(seconds: float):
        sleeps.append(seconds)
        now["t"] += seconds

    def handler(request: httpx.Request):
        count = len(request.url.params["destinations"].split("|"))
        rows = [{"distance": {"value": 1, "text": "x"}, "duration": {"value": 60, "text": "x"}} for _ in range(count)]
        return httpx.Response(200, json={"status": 0, "result": rows})

    maps = BaiduMapsClient(
        BaiduConfig(ak="server-only-test-key", qps=4, matrix_pairs=2),
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=fake_sleep,
    )
    for dests in ([{"lat": 31.21, "lng": 121.41}, {"lat": 31.22, "lng": 121.42}], [{"lat": 31.51, "lng": 121.41}, {"lat": 31.52, "lng": 121.42}]):
        maps.walking_route_matrix(origin={"lat": 31.2, "lng": 121.4}, destinations=dests)

    assert sleeps == [0.5], f"每个 2 对块应把发起时刻推后 2/4 秒，实际 {sleeps}"
