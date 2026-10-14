from copy import deepcopy
from io import BytesIO

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.analysis import CATEGORIES, inspect, network, report_markdown
from backend.main import app
from backend.sample_data import load_communities

client = TestClient(app)
spec = load_communities()["bridge-demo"]


def test_synthetic_result_is_deterministic_and_explicit():
    first = inspect(spec, list(CATEGORIES))
    assert first == inspect(spec, list(CATEGORIES))
    assert first["mode"] == "synthetic"
    assert "confidence" not in first
    assert first["sample_count"] == 143
    assert first["facility_count"] == 7
    assert first["reachability"]["overestimated_count"] > 0
    assert first["combined_coverage_pct"] <= min(row["pct"] for row in first["coverage"].values())


def test_known_bridge_detour_uses_real_graph_edges():
    graph = network(spec)
    assert not graph.has_edge("6,5", "7,5")
    assert nx.shortest_path_length(graph, "6,5", "7,5", weight="length") == 9 * 160


def test_witness_is_reproducible_and_time_matches_path_length():
    result = inspect(spec, ["养老"])
    graph = network(spec)
    witness = result["witness"]
    distance = sum(graph[a][b]["length"] for a, b in zip(witness["path"], witness["path"][1:]))
    assert witness["network_minutes"] == round(distance / 80, 1)
    assert witness["network_minutes"] > 15 >= witness["straight_minutes"]


def test_facility_filter_and_multicategory_intent():
    result = client.get("/api/communities/bridge-demo/inspection", params={"category": "养老"}).json()
    assert result["facility_count"] == 1
    assert list(result["coverage"]) == ["养老"]
    response = client.post("/api/agent/inspect", json={"request": "查看养老和医疗"})
    assert response.status_code == 200
    assert response.json()["parameters"]["categories"] == ["医疗", "养老"]
    assert response.json()["intent"]["llm_called"] is False


def test_empty_facilities_are_missing_not_invented():
    empty = deepcopy(spec)
    empty["facilities"] = []
    result = inspect(empty, ["养老"])
    assert result["coverage"]["养老"]["pct"] == 0
    assert result["avg_walk_minutes"] is None
    assert result["missing_categories"] == ["养老"]
    assert all(check["gap_count"] == 143 for check in result["one_km_checks"])


def test_recommendation_gain_matches_recomputed_coverage():
    before = inspect(spec, ["养老"])
    recommendation = before["recommendations"][0]
    addition = {"category": recommendation["category"], "node": recommendation["node"]}
    after = inspect(spec, ["养老"], addition=addition)
    assert after["coverage"]["养老"]["count"] - before["coverage"]["养老"]["count"] == recommendation["gain"]
    assert after["coverage"]["养老"]["pct"] == recommendation["after_pct"]
    assert after["gap_count"] < before["gap_count"]
    assert after["one_km_checks"] == before["one_km_checks"]
    assert after["evidence_id"] != before["evidence_id"]
    assert inspect(spec, ["养老"]) == before


def test_faster_speed_and_longer_time_cannot_decrease_coverage():
    slow = inspect(spec, list(CATEGORIES), speed=50)
    fast = inspect(spec, list(CATEGORIES), speed=80)
    longer = inspect(spec, list(CATEGORIES), minutes=20)
    assert slow["combined_coverage_pct"] <= fast["combined_coverage_pct"] <= longer["combined_coverage_pct"]


def test_scene_switch_and_custom_center():
    bridge = inspect(spec, ["养老"])
    grid = inspect(load_communities()["grid-demo"], ["养老"])
    assert grid["coverage"]["养老"]["pct"] > bridge["coverage"]["养老"]["pct"]
    moved = inspect(spec, ["养老"], center="1,1")
    assert moved["witness"]["from"] == "1,1"
    assert moved["reachability"] != bridge["reachability"]
    assert moved["coverage"] == bridge["coverage"]


def test_one_km_subtypes_and_distances():
    result = inspect(spec, ["养老"])
    assert [check["kind"] for check in result["one_km_checks"]] == ["菜市场", "药店", "小学"]
    for check in result["one_km_checks"]:
        assert check["facility_count"] == 1
        assert check["gap_count"] == len(check["gap_nodes"])


def test_report_recomputes_the_same_evidence():
    parameters = {"community_id": "grid-demo", "category": "医疗,养老", "minutes": 20, "speed": 50, "center": "3,3"}
    response = client.post("/api/report", json=parameters)
    assert response.status_code == 200
    expected = inspect(load_communities()["grid-demo"], ["医疗", "养老"], minutes=20, speed=50, center="3,3")
    assert response.text == report_markdown(expected)
    assert "attachment" in response.headers["content-disposition"]
    assert "合成样例" in response.text
    assert "可追溯元数据" in response.text
    assert expected["evidence_id"] in response.text
    assert expected["method_version"] in response.text
    assert expected["dataset_version"] in response.text
    assert "直线范围高估" in response.text
    assert "不等于同时可达" in response.text
    assert "相同参数重复调用应得到相同证据编号" in response.text


def test_report_marks_simulation_state_and_missing_categories():
    before = inspect(spec, ["养老"])
    text = report_markdown(before)
    assert "未启用" in text
    addition = {"category": "养老", "node": before["recommendations"][0]["node"]}
    after = inspect(spec, ["养老"], addition=addition)
    simulated = report_markdown(after)
    assert "已启用" in simulated
    assert addition["node"] in simulated
    empty = deepcopy(spec)
    empty["facilities"] = []
    missing = report_markdown(inspect(empty, ["养老"]))
    assert "缺失设施类别" in missing
    assert "养老" in missing


@pytest.mark.parametrize("params,code", [({"category": "其他"}, 400), ({"minutes": 0}, 422), ({"speed": 101}, 422), ({"minutes": 15.5}, 422), ({"center": "100,100"}, 400), ({"addition_node": "1,1"}, 400), ({"category": "养老", "addition_node": "1,1", "addition_category": "医疗"}, 400)])
def test_invalid_parameters(params, code):
    assert client.get("/api/communities/bridge-demo/inspection", params=params).status_code == code


@pytest.mark.parametrize("user_request", [" ", "今天天气如何"])
def test_unknown_intent_is_not_reported_as_executed(user_request):
    assert client.post("/api/agent/inspect", json={"request": user_request}).status_code == 400


def test_agent_explanation_is_rule_only_without_llm_key(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    body = client.post("/api/agent/inspect", json={"request": "查看养老"}).json()
    explanation = body["explanation"]
    assert explanation["mode"] == "rule-only"
    assert explanation["llm_called"] is False
    assert explanation["error"] is None
    assert explanation["points"]
    assert explanation["basis"]["evidence_id"] == body["evidence_id"]
    assert "同时可达" in explanation["points"][0]


def test_agent_explanation_never_invents_metrics(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    body = client.post("/api/agent/inspect", json={"request": "查看养老和医疗"}).json()
    text = " ".join(body["explanation"]["points"])
    assert "置信度" not in text
    assert "节省" not in text
    assert str(body["combined_coverage_pct"]) in text


@pytest.mark.parametrize("path", ["/.env", "/.git/config", "/backend/main.py", "/data/sample_communities.json", "/requirements.txt", "/api/communities/unknown/inspection"])
def test_private_or_unknown_paths_are_not_served(path):
    assert client.get(path).status_code == 404


def test_map_bitmap_and_public_assets():
    response = client.get("/api/communities/bridge-demo/map.png")
    assert response.status_code == 200
    image = Image.open(BytesIO(response.content)).convert("RGB")
    assert image.size == (2080, 1760)
    assert len(image.getcolors(image.width * image.height)) >= 5
    for asset in ["/", "/app.js", "/styles.css", "/live", "/live.html", "/live.js", "/assets/vendor/leaflet.js", "/assets/vendor/lucide.min.js"]:
        assert client.get(asset).status_code == 200


def test_health_does_not_claim_live_integrations():
    health = client.get("/api/health").json()
    assert health["mode"] == "synthetic"
    assert not health["baidu_connected"] and not health["llm_connected"]


def test_live_status_does_not_expose_or_fake_a_key(monkeypatch):
    monkeypatch.delenv("BAIDU_MAP_AK", raising=False)
    response = client.get("/api/live/status")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "synthetic-only"
    assert body["configured"] is False
    assert body["ak_exposed"] is False
    assert "未发起百度地图请求" in body["message"]


def test_live_geocode_rejects_missing_key_without_external_request(monkeypatch):
    monkeypatch.delenv("BAIDU_MAP_AK", raising=False)
    response = client.get("/api/live/geocode", params={"address": "上海市长宁区愚园路"})
    assert response.status_code == 502
    assert "未配置" in response.json()["detail"]


def test_live_status_reports_query_profile_quota_cost(monkeypatch):
    monkeypatch.delenv("BAIDU_POI_QUERY_PROFILE", raising=False)
    body = client.get("/api/live/status").json()

    assert body["default_query_profile"] == "full"
    profiles = body["query_profiles"]
    assert profiles["full"]["place_queries_per_inspection"] == 10
    assert profiles["narrow"]["place_queries_per_inspection"] == 4
    assert profiles["narrow"]["place_queries_per_category"] == {"医疗": 1, "养老": 1, "教育": 1, "购物": 1}


def test_live_status_exposes_invalid_configured_query_profile(monkeypatch):
    monkeypatch.setenv("BAIDU_POI_QUERY_PROFILE", "turbo")
    body = client.get("/api/live/status").json()

    assert body["query_profile_valid"] is False
    assert body["effective_query_profile"] is None
    assert "检索词组画像无效" in body["message"]


def test_live_inspect_rejects_unknown_query_profile(monkeypatch):
    # 故意不配置 AK：画像校验必须先于建客户端，否则会发真实外部请求。
    monkeypatch.delenv("BAIDU_MAP_AK", raising=False)
    response = client.get("/api/live/inspect", params={"address": "上海市长宁区愚园路", "query_profile": "turbo"})

    assert response.status_code == 400
    assert "画像无效" in response.json()["detail"]


def test_rounded_walk_minutes_do_not_decide_reachability():
    boundary = deepcopy(spec)
    boundary["facilities"] = [{"id": "boundary", "name": "Boundary", "category": "养老", "kind": "养老站", "node": "1,1"}]
    result = inspect(boundary, ["养老"], minutes=18, speed=71)
    facility = result["facilities"][0]
    assert facility["walk_minutes"] == 18.0
    assert facility["within_threshold"] is False
    at_threshold = inspect(boundary, ["养老"], minutes=16, speed=80)
    assert at_threshold["facilities"][0]["within_threshold"] is True
