"""Prepare recorded route cases and summarize browser-observed comparisons.

The browser observations are collected through the computer-use tool. This
script does not fetch the web map or infer a route from hidden application state.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".runtime/route-crosscheck"


def prepare():
    recorded = json.loads((ROOT / ".runtime/replay/fixtures.json").read_text(encoding="utf-8"))
    rows = []
    for entry in recorded["fixtures"].values():
        if entry["path"] != "/routematrix/v2/walking":
            continue
        for dest, result in zip(entry["params"]["destinations"].split("|"), entry["response"]["result"]):
            rows.append({"origin": entry["params"]["origins"], "destination": dest, "distance_m": result.get("distance", {}).get("value"), "duration_s": result.get("duration", {}).get("value")})
    # First 10 are facility routes in this recording; sample the remaining
    # isochrone routes on both sides of the threshold, not only easy successes.
    facilities, grid = rows[:10], rows[10:]
    selected = facilities + sorted(grid, key=lambda row: abs(row["duration_s"] - 900))[:5]
    for row in sorted(grid, key=lambda row: row["duration_s"])[:3] + sorted(grid, key=lambda row: -row["duration_s"])[:5]:
        if row not in selected:
            selected.append(row)
        if len(selected) == 20:
            break
    for i, row in enumerate(selected):
        row["id"] = i + 1
        row["kind"] = "设施" if i < 10 else "等时圈样点"
        row["url"] = "https://api.map.baidu.com/direction?" + urlencode({"origin": "latlng:" + row["origin"] + "|name:生活圈样例中心", "destination": "latlng:" + row["destination"] + "|name:路线核验终点", "mode": "walking", "region": "上海", "output": "html", "coord_type": "bd09ll", "src": "webapp.neighborhood-circle.demo"})
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "cases.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已准备 {len(selected)} 条路线对照。")


def summarize():
    cases = json.loads((WORK / "cases.json").read_text(encoding="utf-8"))
    observations = json.loads((WORK / "observations.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in observations}
    lines = ["# 真实路线跨时点网页版对照", "", "对照日期：2026-10-13。录制日期：2026-10-03。样例：愚园路中心。", "", "## 方法", "", "用百度官方地图调起 API 将录制中的同一 BD-09 起终点送入百度网页版步行规划，读取页面可见的距离与耗时。选取 10 条设施路线、5 条靠近 15 分钟阈值的等时圈样点，再补充近端和远端样点，共 20 条。由浏览器自动执行并保存可见结果，不冒充人工签字核验。", "", "对照两端来自同一地图平台、相隔 10 天。距离四舍五入、计时模型、数据更新与导航吸附均可能造成差异；本报告不能证明实地准确率或区分这些原因。", "", "| # | 类型 | 录制距离 m | 网页可见结果 | 距离差 m（按显示值） | 15 分钟阈值判断 | 对照链接 |", "| --- | --- | ---: | --- | ---: | --- | --- |"]
    compared, agreement, flags = 0, 0, []
    for case in cases:
        observation = by_id.get(case["id"], {})
        summary = observation.get("summary", "未完成")
        time_match = re.search(r"(?:(\d+)小时)?(?:(\d+)分钟)?", summary)
        distance_match = re.search(r"约([\d.]+)(公里|米)", summary)
        delta, verdict = "未知", "未知"
        if time_match and time_match.group(0) and distance_match:
            minutes = int(time_match.group(1) or 0) * 60 + int(time_match.group(2) or 0)
            meters = float(distance_match.group(1)) * (1000 if distance_match.group(2) == "公里" else 1)
            delta = round(meters - case["distance_m"])
            same = (case["duration_s"] <= 900) == (minutes <= 15)
            verdict = "一致" if same else "不一致，需复核"
            compared += 1
            agreement += int(same)
            if not same:
                flags.append(case["id"])
        lines.append(f"| {case['id']} | {case['kind']} | {case['distance_m']} | {summary}（录制 {round(case['duration_s']/60,1)} 分钟） | {delta} | {verdict} | [同一起终点]({case['url']}) |")
    lines += ["", "## 结果与待复核", "", f"完成 {compared}/{len(cases)} 条网页对照，15 分钟判断一致 {agreement}/{compared}。这只是选定历史样本的跨时点一致性，不是对真实道路的准确率。", f"需重点复核的阈值分歧编号：{', '.join(map(str, flags)) or '无'}。网页分钟为整数，阈值附近还存在显示舍入误差。", "", "- 距离差按网页显示值计算，网页公里通常只有一位小数，不应将差值直接当作距离测量误差。", "- 网页对照仍依赖百度数据，不能发现双方共同存在的道路错误；需团队进一步核对真实过街与出入口。", "- [地图调起 API 官方参数文档](https://lbsyun.baidu.com/docs/webapi?title=mapadjustment/uri/web)", ""]
    path = ROOT / "docs/route-crosscheck-2026-10-13.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"完成 {compared}/{len(cases)}，阈值一致 {agreement}/{compared}；{path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    summarize() if args.summarize else prepare()
