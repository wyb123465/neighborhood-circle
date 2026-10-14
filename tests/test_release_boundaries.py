import json

import httpx
from fastapi.testclient import TestClient

from backend.baidu import BaiduConfig, BaiduMapsClient, request_key
from backend.live_isochrone import build_isochrone
from backend.main import app
from backend.live_inspection import inspect_live, subtype_matches


def test_replay_without_ak_and_status_preserves_recorded_preset(tmp_path, monkeypatch):
    params = {"address": "测试道路", "city": "上海市", "ret_coordtype": "bd09ll", "output": "json"}
    fixture = tmp_path / "recorded.json"
    fixture.write_text(
        json.dumps(
            {
                "address": "测试道路",
                "city": "上海市",
                "recorded_at": "2026-10-03 12:00:00",
                "fixtures": {
                    request_key("/geocoding/v3/", params): {
                        "path": "/geocoding/v3/",
                        "params": params,
                        "response": {"status": 0, "result": {"location": {"lat": 31.2, "lng": 121.4}}},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BAIDU_REPLAY_FILE", str(fixture))

    def no_network(request):
        raise AssertionError("replay must not use network")

    maps = BaiduMapsClient(
        BaiduConfig(ak="", replay_file=str(fixture)), transport=httpx.MockTransport(no_network)
    )
    assert maps.configured
    assert maps.geocode("测试道路", "上海市")["location"]["lat"] == 31.2
    assert maps.metrics()["network_requests"] == 0
    with TestClient(app) as client:
        status = client.get("/api/live/status").json()
        assert status["mode"] == "live-replay" and status["configured"]
        assert status["replay_preset"]["city"] == "上海市"
        assert str(tmp_path) not in json.dumps(status)


def test_invalid_replay_file_is_explained_and_never_falls_back_to_network(monkeypatch, tmp_path):
    monkeypatch.setenv("BAIDU_REPLAY_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setenv("BAIDU_MAP_AK", "test-only")
    with TestClient(app) as client:
        status = client.get("/api/live/status").json()
        assert not status["configured"]
        assert status["mode"] == "configuration-error"
        response = client.get("/api/live/geocode", params={"address": "测试道路"})
        assert response.status_code == 502
        assert "回放文件不可用" in response.json()["detail"]


def test_same_isochrone_parameters_with_changed_durations_change_evidence():
    def result(duration):
        def handler(request):
            count = len(request.url.params["destinations"].split("|"))
            return httpx.Response(
                200,
                json={
                    "status": 0,
                    "result": [{"duration": {"value": duration}, "distance": {"value": 600}}] * count,
                },
            )

        maps = BaiduMapsClient(BaiduConfig(ak="test", qps=10000), transport=httpx.MockTransport(handler))
        return build_isochrone(maps, center={"lat": 31.2, "lng": 121.4}, refine=False)

    a, b = result(600), result(1200)
    assert a["evidence_id"] != b["evidence_id"]
    assert a["summary"]["coarse"]["reachable"] > b["summary"]["coarse"]["reachable"]


def test_live_inspect_coordinate_inputs_validate_before_external_requests():
    with TestClient(app) as client:
        for params in ({"lat": 31.2}, {"address": "测试道路", "lat": 31.2, "lng": 121.4}, {}):
            assert client.get("/api/live/inspect", params=params).status_code == 400
        assert client.get("/api/live/inspect", params={"lat": 31.2, "lng": 121.4}).status_code == 502


def test_full_poi_page_at_page_limit_is_incomplete():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": 0,
                "results": [
                    {"uid": str(i), "name": "药店", "location": {"lat": 31.2, "lng": 121.4}}
                    for i in range(20)
                ],
            },
        )

    maps = BaiduMapsClient(
        BaiduConfig(ak="test", max_place_pages=1, qps=1000), transport=httpx.MockTransport(handler)
    )
    pois = maps.search_pois(location={"lat": 31.2, "lng": 121.4}, query="药店", radius_m=2000)
    assert len(pois) == 20 and not pois.complete and pois.radius_m == 2000


def test_training_businesses_and_school_annexes_do_not_count_as_primary_schools():
    assert not subtype_matches({"name": "vipkidn美国小学"}, "小学")
    assert not subtype_matches({"name": "某小学游泳馆"}, "小学")
    assert not subtype_matches({"name": "教育中心", "detail_info": {"tag": "教育培训;培训机构"}}, "小学")
    assert subtype_matches({"name": "万航渡路小学(总校)"}, "小学")


def test_inspection_evidence_tracks_poi_facts_and_is_reproducible():
    def result(name):
        def handler(request):
            if request.url.path.startswith("/geocoding/"):
                return httpx.Response(
                    200, json={"status": 0, "result": {"location": {"lat": 31.2, "lng": 121.4}}}
                )
            if request.url.path.startswith("/place/"):
                return httpx.Response(
                    200,
                    json={
                        "status": 0,
                        "results": [{"uid": "one", "name": name, "location": {"lat": 31.201, "lng": 121.4}}],
                    },
                )
            return httpx.Response(
                200, json={"status": 0, "result": [{"distance": {"value": 120}, "duration": {"value": 120}}]}
            )

        maps = BaiduMapsClient(BaiduConfig(ak="test", qps=10000), transport=httpx.MockTransport(handler))
        return inspect_live(
            maps,
            address="测试地址",
            city=None,
            categories=["医疗"],
            radius_m=1500,
            minutes=15,
            query_profile="narrow",
        )

    first = result("药店甲")
    assert first["evidence_id"] == result("药店甲")["evidence_id"]
    assert first["evidence_id"] != result("药店乙")["evidence_id"]
