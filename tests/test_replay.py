from __future__ import annotations

import json

import httpx
import pytest

from backend.baidu import BaiduApiError, BaiduConfig, BaiduMapsClient, RecordingTransport, request_key


def handler(recorder: list[str]):
    def handle(request: httpx.Request) -> httpx.Response:
        recorder.append(request.url.path)
        return httpx.Response(
            200, json={"status": 0, "result": {"location": {"lng": 121.4, "lat": 31.2}, "level": "道路"}}
        )

    return handle


def test_recorded_fixtures_replay_without_any_network(tmp_path):
    """录制一次后，回放客户端不再触碰网络；指标走 replay_hits。"""
    network_calls: list[str] = []
    recording = RecordingTransport(httpx.MockTransport(handler(network_calls)))
    recorder_config = BaiduConfig(ak="record-key", qps=1000)
    maps = BaiduMapsClient(recorder_config, transport=recording)
    maps.geocode("地址甲")
    maps.geocode("地址乙", "上海市")
    assert len(recording.captured) == 2
    assert len(network_calls) == 2, "录制阶段恰好两次真实调用"

    fixture = tmp_path / "fixtures.json"
    fixture.write_text(json.dumps({"fixtures": recording.captured}, ensure_ascii=False), encoding="utf-8")

    replay_config = BaiduConfig(ak="record-key", replay_file=str(fixture))
    replay_maps = BaiduMapsClient(replay_config)
    assert replay_maps.replay_mode is True

    first = replay_maps.geocode("地址甲")
    second = replay_maps.geocode("地址乙", "上海市")
    assert first["location"]["lat"] == 31.2
    assert second["level"] == "道路"
    assert len(network_calls) == 2, "回放客户端不得发起任何网络请求"

    snapshot = replay_maps.metrics()
    assert snapshot["replay_hits"] == 2
    assert snapshot["network_requests"] == 0


def test_replay_missing_entry_raises_clean_error(tmp_path):
    recording = RecordingTransport(httpx.MockTransport(handler([])))
    maps = BaiduMapsClient(BaiduConfig(ak="record-key", qps=1000), transport=recording)
    maps.geocode("只有这一条")

    fixture = tmp_path / "fixtures.json"
    fixture.write_text(json.dumps({"fixtures": recording.captured}, ensure_ascii=False), encoding="utf-8")

    replay_maps = BaiduMapsClient(BaiduConfig(ak="record-key", replay_file=str(fixture)))
    with pytest.raises(BaiduApiError, match="回放数据缺少该请求"):
        replay_maps.geocode("没有录制过的地址")


def test_request_key_ignores_ak_and_normalizes_value_types():
    with_ak = request_key("/place/v3/around", {"query": "药店", "page_num": 0})
    with_ak_alt = request_key("/place/v3/around", {"query": "药店", "page_num": "0", "ak": "secret"})
    assert with_ak == with_ak_alt, "AK 不参与指纹；int 与 str 的值必须归一成同一把钥匙"


def test_recording_transport_strips_ak_from_captured_params():
    recording = RecordingTransport(httpx.MockTransport(handler([])))
    maps = BaiduMapsClient(BaiduConfig(ak="record-key", qps=1000), transport=recording)
    maps.geocode("AK 剥离检查")
    assert len(recording.captured) == 1
    assert all("ak" not in entry["params"] for entry in recording.captured.values()), "录制产物不得包含 AK"


def test_recording_survives_gzip_responses(tmp_path):
    """真实接口返回 gzip 内容：录制重组必须剥掉 content-encoding，回放才能解析。"""
    import gzip as gzip_mod

    payload = {"status": 0, "result": {"location": {"lng": 121.4, "lat": 31.2}}}

    def gzip_handler(request: httpx.Request) -> httpx.Response:
        body = gzip_mod.compress(json.dumps(payload).encode("utf-8"))
        return httpx.Response(200, content=body, headers={"content-encoding": "gzip"})

    recording = RecordingTransport(httpx.MockTransport(gzip_handler))
    maps = BaiduMapsClient(BaiduConfig(ak="record-key", qps=1000), transport=recording)
    maps.geocode("gzip 地址")

    fixture = tmp_path / "fixtures.json"
    fixture.write_text(json.dumps({"fixtures": recording.captured}, ensure_ascii=False), encoding="utf-8")

    replay_maps = BaiduMapsClient(BaiduConfig(ak="record-key", replay_file=str(fixture)))
    result = replay_maps.geocode("gzip 地址")
    assert result["location"]["lat"] == 31.2, "gzip 录制内容重组后必须可解析"
