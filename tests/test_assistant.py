import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import assistant_api as api
from backend.assistant_model import ModelClient, ModelConfig, ModelError
from backend.assistant_tools import CompareArgs, EvidenceArgs, FinishArgs, InspectArgs, ToolContext
from backend.baidu import BaiduApiError, BaiduConfig, BaiduMapsClient
from backend.live_inspection import balanced_selection, inspect_live
from backend.main import app


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    monkeypatch.setattr(ModelConfig, "from_env", classmethod(lambda cls: ModelConfig()))


def direct_run(manager, task="检查养老缺口并比较候选", session=None, **kwargs):
    request = api.RunRequest(task=task, **kwargs)
    session = session or {
        "id": "a" * 32,
        "data_mode": request.data_mode,
        "snapshots": {},
        "facts": {},
        "latest": None,
        "tasks": [],
        "touched": 0,
    }
    job = api.Job(request, session)
    manager.run(job)
    return job


def call(name, args):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-" + name,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        ],
    }


def test_rule_mode_comparison_is_recomputed_and_followup_reuses_evidence():
    manager = api.RunManager()
    job = direct_run(manager)
    assert job.status == "complete" and job.mode == "rule-only"
    assert job.model_calls == job.map_requests == 0
    first = job.result["comparison"][0]
    assert first["before_pct"] == 44.8 and first["after_pct"] == 92.3
    assert first["gain_count"] == 68 and first["gap_count"] == 11
    job.request.task = "比较前两个候选方案"
    compared, _ = manager.invoke(
        job, ToolContext(job.request, job.session, job.guard), "compare_candidates", {"limit": 3}
    )
    assert len(compared["comparison"]) == 2
    assert job.events[-1]["arguments"]["limit"] == 2
    followup = direct_run(manager, "解释刚才的依据", session=job.session)
    assert followup.status == "complete"
    assert [event["name"] for event in followup.events] == ["read_evidence", "finish"]
    assert followup.map_requests == 0


def test_ambiguous_request_asks_and_does_not_compute():
    job = direct_run(api.RunManager(), "帮我看看")
    assert job.status == "needs_input"
    assert job.result["question"] and job.result["analysis"] is None
    assert job.tool_calls == job.map_requests == 0


def test_real_protocol_loop_uses_tool_outputs_not_provider_text(monkeypatch):
    requests = []

    def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        outputs = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
        if not outputs:
            message = call("inspect_neighborhood", {"categories": ["养老"]})
        elif len(outputs) == 1:
            message = call("compare_candidates", {"limit": 2})
        else:
            message = call(
                "finish", {"fact_ids": [outputs[-1]["facts"][-1]["id"]], "actions": ["verify_site"]}
            )
        return httpx.Response(200, json={"choices": [{"message": message}]})

    config = ModelConfig("https://provider.test/v1", "secret-test", "tools-test")
    monkeypatch.setattr(ModelConfig, "from_env", classmethod(lambda cls: config))
    manager = api.RunManager(lambda conf: ModelClient(conf, transport=httpx.MockTransport(provider)))
    job = direct_run(manager)
    assert job.status == "complete" and job.mode == "llm-agent"
    assert job.model_calls == 3 and job.tool_calls == 3
    assert [e["name"] for e in job.events if e["kind"] == "tool"] == [
        "inspect_neighborhood",
        "compare_candidates",
        "finish",
    ]
    assert "secret-test" not in json.dumps(job.public())
    assert requests[-1]["messages"][-1]["role"] == "tool"


def test_responses_adapter_preserves_reasoning_and_call_outputs():
    bodies = []
    reasoning = {"type": "reasoning", "id": "rs_test", "summary": [], "encrypted_content": "opaque"}

    def provider(request):
        assert request.url.path == "/v1/responses"
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "output": [
                    reasoning,
                    {
                        "type": "function_call",
                        "id": "fc_test",
                        "call_id": "c1",
                        "name": "finish",
                        "arguments": '{"clarify_field":"address"}',
                    },
                ]
            },
        )

    model = ModelClient(
        ModelConfig("https://provider.test/v1", "key", "test", "responses"),
        transport=httpx.MockTransport(provider),
    )
    reply = model.complete([{"role": "user", "content": "检查社区"}], [])
    model.complete([reply, {"role": "tool", "tool_call_id": "c1", "content": "{}"}], [])
    assert bodies[1]["input"][0] == reasoning
    assert bodies[1]["input"][-1]["type"] == "function_call_output"
    model.close()


def test_invalid_tools_and_fabricated_facts_are_rejected():
    manager = api.RunManager()
    job = api.Job(api.RunRequest(task="检查"), {"id": "a" * 32, "facts": {}, "snapshots": {}, "latest": None})
    context = ToolContext(job.request, job.session, job.guard)
    for name, args in [
        ("read_file", {"path": ".env"}),
        ("inspect_neighborhood", {"minutes": 1000}),
        ("finish", {"fact_ids": ["invented"]}),
    ]:
        result, finished = manager.invoke(job, context, name, args)
        assert "error" in result and not finished
    assert all(e["status"] == "error" for e in job.events)
    assert job.map_requests == 0


def test_model_auth_error_redacts_provider_body():
    model = ModelClient(
        ModelConfig("https://provider.test/v1", "very-secret", "test"),
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text="very-secret")),
    )
    with pytest.raises(ModelError, match="HTTP 401") as failure:
        model.complete([], [])
    assert "very-secret" not in str(failure.value)
    model.close()


def test_model_omitted_parameters_inherit_visible_user_controls():
    manager = api.RunManager()
    request = api.RunRequest(task="检查养老", minutes=20, speed=60, community_id="grid-demo")
    session = {"id": "a" * 32, "facts": {}, "snapshots": {}, "latest": None}
    job = api.Job(request, session)
    context = ToolContext(request, session, job.guard)
    result, _ = manager.invoke(job, context, "inspect_neighborhood", {"categories": ["养老"]})
    assert result["parameters"]["minutes"] == 20
    assert result["parameters"]["speed_m_min"] == 60
    assert context.get_snapshot()["analysis"]["inspection"]["community"]["id"] == "grid-demo"


def test_failed_new_scope_does_not_present_old_result(monkeypatch):
    manager = api.RunManager()
    previous = direct_run(manager, "检查养老")
    monkeypatch.setattr(
        ToolContext,
        "inspect_neighborhood",
        lambda *args: (_ for _ in ()).throw(ValueError("new scope failed")),
    )
    job = direct_run(manager, "检查教育", session=previous.session, minutes=20)
    assert job.status == "error" and job.result is None


def test_map_configuration_failure_stops_without_misleading_clarification(monkeypatch):
    class Provider:
        def complete(self, *args):
            return call("inspect_neighborhood", {"categories": ["养老"]})

        def close(self):
            pass

    monkeypatch.setattr(
        ModelConfig, "from_env", classmethod(lambda cls: ModelConfig("https://p.test", "key", "test"))
    )
    monkeypatch.setattr(
        ToolContext,
        "inspect_neighborhood",
        lambda *args: (_ for _ in ()).throw(BaiduApiError("APP IP校验失败")),
    )
    job = direct_run(api.RunManager(lambda conf: Provider()), data_mode="live", address="上海市长宁区愚园路")
    assert job.status == "error" and job.result is None
    assert job.error == "APP IP校验失败" and job.model_calls == 1


def test_repeated_compare_does_not_duplicate_fact_ids():
    job = direct_run(api.RunManager(), "检查养老")
    context = ToolContext(job.request, job.session, job.guard)
    context.compare_candidates(CompareArgs())
    context.compare_candidates(CompareArgs(limit=2))
    ids = context.get_snapshot()["fact_ids"]
    assert len(ids) == len(set(ids))
    assert len([k for k in ids if ":candidate-" in k]) == 2


def test_finish_rejects_mixed_fact_answer_and_clarification():
    job = direct_run(api.RunManager(), "检查养老")
    context = ToolContext(job.request, job.session, job.guard)
    context.read_evidence(EvidenceArgs())
    identity = context.get_snapshot()["fact_ids"][0]
    with pytest.raises(ValueError, match="不能混用"):
        context.finish(FinishArgs(fact_ids=[identity], clarify_field="goal"))
    assert context.finish(FinishArgs(fact_ids=[identity]))["facts"][0]["id"] == identity


def test_live_comparison_counts_overlap_once():
    request = api.RunRequest(task="比较", data_mode="live")
    blind = {
        "radius_m": 1000,
        "points": [{"missing_kinds": ["菜市场"], "dx_m": x, "dy_m": 0} for x in (0, 500, 1500)],
        "recommendations": [
            {"kind": "菜市场", "rank": i + 1, "dx_m": x, "dy_m": 0} for i, x in enumerate((0, 500))
        ],
    }
    snapshot = {
        "id": "s",
        "evidence_id": "s",
        "mode": "live-partial",
        "parameters": {},
        "fact_ids": [],
        "candidate_count": 2,
        "analysis": {"inspection": {"blind_spots": blind}},
    }
    context = ToolContext(
        request, {"latest": "s", "snapshots": {"s": snapshot}, "facts": {}}, lambda reserve: None
    )
    rows = context.compare_candidates(CompareArgs())["comparison"]
    assert [r["independent_gain_count"] for r in rows] == [2, 3]
    assert [r["marginal_gain_count"] for r in rows] == [2, 1]
    assert rows[-1]["cumulative_gain_count"] == 3 and rows[-1]["gap_count"] == 0


def test_budget_and_cancel_guard_before_actual_map_requests(monkeypatch):
    monkeypatch.setenv("AI_MAX_MAP_REQUESTS", "1")
    job = api.Job(api.RunRequest(task="测试"), {})
    network = []

    def handler(request):
        network.append(request.url.path)
        return httpx.Response(200, json={"status": 0, "result": {"location": {"lat": 31.2, "lng": 121.4}}})

    maps = BaiduMapsClient(
        BaiduConfig(ak="test", qps=1000), transport=httpx.MockTransport(handler), request_guard=job.guard
    )
    maps.geocode("第一处地址", None)
    maps.geocode("第一处地址", None)  # A cache hit consumes no additional request.
    with pytest.raises(api.BudgetExceeded):
        maps.geocode("第二处地址", None)
    assert job.map_requests == len(network) == 1
    job.cancel.set()
    with pytest.raises(api.Stopped):
        maps.geocode("第一处地址", None)
    maps.close()


def test_cancel_during_model_wait_prevents_tools(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class SlowModel:
        def complete(self, *args):
            entered.set()
            release.wait(3)
            return call("inspect_neighborhood", {"categories": ["养老"]})

        def close(self):
            pass

    monkeypatch.setattr(
        ModelConfig, "from_env", classmethod(lambda cls: ModelConfig("https://p.test", "key", "test"))
    )
    manager = api.RunManager(lambda conf: SlowModel())
    job = manager.create(api.RunRequest(task="检查养老"))
    assert entered.wait(2)
    job.cancel.set()
    release.set()
    manager.pool.shutdown(wait=True)
    assert job.status == "cancelled" and job.tool_calls == job.map_requests == 0


def test_nearest_sampling_precedes_alphabetical_name():
    center = {"lat": 31.2, "lng": 121.4}
    rows = [
        {"identity": i, "name": name, "categories": ["医疗"], "location": {"lat": 31.2, "lng": lng}}
        for i, name, lng in (("far", "A", 121.42), ("near", "Z", 121.401))
    ]
    assert balanced_selection(rows, ["医疗"], 1, center)[0]["identity"] == "near"
    assert balanced_selection(rows, ["医疗"], 1)[0]["identity"] == "far"


def test_unknown_routes_are_not_in_known_denominator():
    def handler(request):
        path = request.url.path
        if "geocoding" in path:
            return httpx.Response(
                200, json={"status": 0, "result": {"location": {"lat": 31.2, "lng": 121.4}}}
            )
        if "place" in path:
            return httpx.Response(
                200,
                json={
                    "status": 0,
                    "total": 2,
                    "results": [
                        {
                            "uid": str(i),
                            "name": "药店" + str(i),
                            "location": {"lat": 31.2, "lng": 121.4 + i * 0.001},
                        }
                        for i in (1, 2)
                    ],
                },
            )
        if "routematrix" in path:
            return httpx.Response(
                200,
                json={
                    "status": 0,
                    "result": [{"duration": {"value": 600}, "distance": {"value": 500}}, {"duration": None}],
                },
            )
        return httpx.Response(200, json={"status": 302, "message": "quota"})

    maps = BaiduMapsClient(
        BaiduConfig(ak="test", qps=1000, max_place_pages=1), transport=httpx.MockTransport(handler)
    )
    result = inspect_live(
        maps,
        address="样例地址",
        city=None,
        categories=["医疗"],
        minutes=15,
        radius_m=1500,
        query_profile="narrow",
    )
    row = result["category_summary"]["医疗"]
    assert row["known"] == row["unknown"] == 1
    assert row["center_to_facility_rate"] == 100
    maps.close()


def test_assistant_http_validation_and_secret_free_status():
    client = TestClient(app)
    status = client.get("/api/assistant/status")
    assert status.json()["mode"] == "rule-only"
    assert "key" not in status.json() and "base_url" not in status.json()
    assert client.post("/api/assistant/runs", json={"task": "检查", "minutes": 99}).status_code == 422
    assert client.get("/api/assistant/runs/missing").status_code == 404
