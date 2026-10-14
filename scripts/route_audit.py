"""20 条路线桌面审计：生成自动检查 + 人工回填两栏的真实对比测试报告。

用法（在项目根目录执行）：
    .venv/Scripts/python.exe scripts/route_audit.py --address "上海市长宁区愚园路" --city 上海市

流程：地理编码 → /api/live/inspect 取真实设施 → /api/live/isochrone 取网格点
→ 选 20 条起终点对（设施 + 可达/不可达网格点）→ 逐对调用步行路线 API
→ 自动一致性检查（绕行系数/隐含步速/分段累加/往返对称）→ 报告写入 .runtime/。

报告中的「人工核对/结论」两列留给桌面目测回填：把终点坐标粘进百度地图网页版，
核对路线是否真实存在即可，不需要实地走访。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.baidu import BaiduApiError, BaiduConfig, BaiduMapsClient, load_env_file  # noqa: E402
from backend.route_audit import audit_one, build_pairs, render_report, reverse_mismatch  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="步行路线桌面审计（20 条路线抽查）")
    parser.add_argument("--address", required=True, help="社区中心地址")
    parser.add_argument("--city", default=None)
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--pairs", type=int, default=20, help="审计配对数，默认 20")
    parser.add_argument("--symmetry", type=int, default=4, help="往返对称抽查条数，默认 4")
    parser.add_argument("--out-dir", default=str(ROOT / ".runtime"))
    args = parser.parse_args()

    load_env_file()
    config = BaiduConfig.from_env()
    if not config.ak:
        print("未配置 BAIDU_MAP_AK，未发起任何外部请求。", file=sys.stderr)
        return 2

    maps = BaiduMapsClient(config)
    started = time.perf_counter()
    print(f"地址定位：{args.address}")
    center = maps.geocode(args.address, args.city)["location"]

    print("拉取真实设施与等时圈采样点……")
    from backend.live_inspection import inspect_live  # noqa: E402
    from backend.live_isochrone import build_isochrone  # noqa: E402

    inspect = inspect_live(maps, address=args.address, city=args.city, categories=["医疗", "养老", "教育", "购物"], radius_m=1500, minutes=args.minutes, max_facilities=10)
    isochrone = build_isochrone(maps, center=center, minutes=args.minutes, refine=True)

    pairs = build_pairs(inspect, isochrone, total=args.pairs, minutes=args.minutes)
    print(f"待审计配对 {len(pairs)} 条，逐对调用步行路线（QPS={config.qps}）……")
    rows = []
    for index, pair in enumerate(pairs, 1):
        try:
            route = maps.walking_route(origin=pair["origin"], destination=pair["destination"], destination_uid=pair.get("uid"))
        except BaiduApiError as error:
            rows.append({**pair, "straight_m": None, "distance_m": None, "duration_s": None, "walk_minutes": None, "detour_ratio": None, "speed_m_per_min": None, "steps_count": 0, "steps_sum_ratio": None, "flags": [f"调用失败：{error}"], "verdict": "可疑"})
            print(f"  [{index}/{len(pairs)}] 失败：{error}")
            continue
        row = audit_one(pair, route)
        rows.append(row)
        mark = "!" if row["flags"] else "ok"
        print(f"  [{index}/{len(pairs)}] {mark} {row['label']}：{row['distance_m']}m / {row['walk_minutes']}min（绕行 {row['detour_ratio']}，{row['speed_m_per_min']} m/min）")

    symmetry_rows = []
    for pair in rows[: max(0, args.symmetry)]:
        if pair.get("distance_m") is None:
            continue
        try:
            backward = maps.walking_route(origin=pair["destination"], destination=pair["origin"])
        except BaiduApiError as error:
            symmetry_rows.append({"label": pair["label"], "forward_min": pair["walk_minutes"], "backward_min": None, "mismatch": f"反向调用失败：{error}"})
            continue
        mismatch = reverse_mismatch({"duration_s": pair["duration_s"]}, backward)
        symmetry_rows.append({"label": pair["label"], "forward_min": pair["walk_minutes"], "backward_min": round(backward["duration_s"] / 60, 1) if backward.get("duration_s") else None, "mismatch": mismatch})

    report = render_report(rows, {"address": args.address, "minutes": args.minutes}, symmetry_rows)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"route-audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    out_path.write_text(report, encoding="utf-8")

    flagged = sum(1 for row in rows if row["verdict"] == "可疑")
    print("-" * 60)
    print(f"审计完成：{len(rows)} 条，自动可疑 {flagged} 条，往返抽查 {len(symmetry_rows)} 条")
    print(f"报告已写入：{out_path}")
    print("下一步：按报告内指引做桌面目测，回填「人工核对/结论」两列。")
    print(f"总耗时 {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
