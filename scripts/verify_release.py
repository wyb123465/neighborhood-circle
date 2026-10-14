"""Produce reproducible synthetic ground-truth and optional private replay evidence.

This does not claim independent validation of real map data. No live calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["NEIGHBORHOOD_IGNORE_ENV"] = "1"
import httpx
import networkx as nx
from backend.analysis import inspect, network
from backend.sample_data import load_communities
from backend.baidu import BaiduConfig, BaiduMapsClient
from backend.live_inspection import inspect_live
from backend.live_isochrone import build_isochrone


def verify_synthetic():
    rows = []
    for spec in load_communities().values():
        graph = network(spec)
        # Independent shortest-hop BFS, valid because all edges are 160 m.
        assert {data["length"] for _, _, data in graph.edges(data=True)} == {160}
        hops = dict(nx.all_pairs_shortest_path_length(graph))
        for minutes, speed in ((15, 80), (10, 60), (20, 80)):
            result = inspect(spec, ["养老"], minutes=minutes, speed=speed)
            targets = [f["node"] for f in spec["facilities"] if f["category"] == "养老"]
            truth = sum(any(hops[n].get(t, float("inf")) * 160 <= minutes * speed for t in targets) for n in graph)
            assert truth == result["coverage"]["养老"]["count"]
            recommendation = result["recommendations"][0]
            after = inspect(spec, ["养老"], minutes=minutes, speed=speed, addition={"node": recommendation["node"], "category": "养老"})
            assert after["coverage"]["养老"]["count"] - truth == recommendation["gain"]
            assert inspect(spec, ["养老"], minutes=minutes, speed=speed) == result
            rows.append({"community": spec["name"], "minutes": minutes, "speed": speed, "truth_count": truth, "computed_count": result["coverage"]["养老"]["count"], "coverage_pct": result["combined_coverage_pct"], "after_pct": after["combined_coverage_pct"], "evidence_id": result["evidence_id"]})
    return rows


def verify_replay(path: Path):
    recorded = json.loads(path.read_text(encoding="utf-8"))
    def forbid_network(request):
        raise AssertionError("验收回放不允许外部请求")
    maps = BaiduMapsClient(BaiduConfig(ak="", replay_file=str(path)), transport=httpx.MockTransport(forbid_network))
    try:
        preset = maps.replay_metadata
        inspection = inspect_live(maps, address=preset["address"], city=preset["city"], categories=["医疗", "养老", "教育", "购物"], radius_m=1500, minutes=preset["minutes"], max_facilities=preset["max_facilities"], query_profile=preset["query_profile"])
        iso = build_isochrone(maps, center=inspection["community"]["center"], minutes=preset["minutes"], grid_m=preset["grid_m"])
        assert inspection["mode"] == iso["mode"] == "live-replay"
        assert maps.metrics()["network_requests"] == 0
        assert inspection["performance"]["poi_query_errors"] == inspection["performance"]["route_errors"] == 0
        assert iso["summary"]["unknown"] == 0
        return {"recorded_at": preset["recorded_at"], "address": preset["address"], "query_profile": preset["query_profile"], "fixture_count": len(recorded["fixtures"]), "fixture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "facility_count": inspection["facility_count"], "iso_summary": iso["summary"], "evidence_id": iso["evidence_id"], "inspection_evidence_id": inspection["evidence_id"], "blind_spots": inspection["blind_spots"]["kinds"], "metrics": maps.metrics()}
    finally:
        maps.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-file", type=Path)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "output/verification")
    args = parser.parse_args()
    report = {"verified_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "synthetic": verify_synthetic(), "replay": verify_replay(args.replay_file) if args.replay_file else None}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 可复算验收报告", "", f"生成时间：{report['verified_at']}", "", "## 合成真值对比", "", "合成路网采用最短跳数 BFS 独立核对 Dijkstra 距离；全部边长 160 米。候选增益和撤销可复现。", "", "| 样例 | 分钟 | 米/分钟 | BFS 真值 | 算法结果 | 覆盖率 | 模拟后 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["synthetic"]:
        lines.append(f"| {row['community']} | {row['minutes']} | {row['speed']} | {row['truth_count']} | {row['computed_count']} | {row['coverage_pct']}% | {row['after_pct']}% |")
    if report["replay"]:
        r = report["replay"]
        lines += ["", "## 历史真实响应回放", "", f"- 样例：{r['address']}；录制时间：{r['recorded_at']}；画像：{r['query_profile']}。", f"- 录制请求 {r['fixture_count']} 条，设施路线 {r['facility_count']} 条；本次网络请求 0。", f"- 等时圈证据编号：`{r['evidence_id']}`；已知样点 {r['iso_summary']['known']}，未知 {r['iso_summary']['unknown']}。", f"- 设施证据编号：`{r['inspection_evidence_id']}`；编号同时绑定 POI、路线与专项检查结果。", "- 实际搜索范围、分页完整性及未知样点见下表；证据不足不计入缺口。", "- 本次验证证明回放和统计可复现，不能证明地图数据、POI 分类或实际道路当前准确。", "", "| 类别 | 检索半径 m | 分页完整 | 已知样点 | 缺口样点 | 未知样点 |", "| --- | ---: | --- | ---: | ---: | ---: |"]
        for kind, row in r["blind_spots"].items():
            boundary = row.get("search_evidence") or {}
            lines.append(f"| {kind} | {boundary.get('radius_m', '未知')} | {boundary.get('complete', False)} | {row['known_count']} | {row['gap_count'] if row['gap_count'] is not None else '未知'} | {row['unknown_count']} |")
    lines += ["", "## 外部对照与验证边界", "", "- 20 条历史路线已与当前百度网页版对照，17/20 阈值判断一致，3 条边界样点保留分歧；详见 docs/route-crosscheck-2026-10-13.md。", "- 三类 POI 已对照政府公开资料；营业状态、实际通行、出入口及缺口样点仍需进一步核验。", "- API 自身一致性、历史录制和合成真值均不能替代实地测量；同平台网页对照也不是实地准确率。", ""]
    (args.out_dir / "验收报告.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"通过：{len(report['synthetic'])} 组合成真值对比" + (" + 无 AK、零联网历史回放" if report["replay"] else ""))
    print(args.out_dir / "验收报告.md")


if __name__ == "__main__":
    main()
