"""拿到百度地图 AK 后的一键真实链路验收。

设计约束：
- **顺序调用**，不并发，避免新账号触发限流。
- 只消耗约 1 + 4 + N 次调用；检索词默认走 narrow 画像，把地点检索压到 4 次，
  因为个人认证的地点检索配额只有 100 次/日。
- 报告写入 .runtime/（已在 .gitignore 中）。真实响应数据不进入仓库。
- AK 本身不出现在标准输出、报告或异常里；错误信息已在适配器层做过脱敏。

用法（在项目根目录执行）：
    .venv/Scripts/python.exe scripts/check_live.py --address "上海市长宁区愚园路" --city 上海市

退出码：0 全部通过；1 有步骤失败；2 未配置 AK（未发起任何请求）。
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
from backend.live_inspection import QUERY_PROFILES  # noqa: E402

OFFICIAL_BASE_URL = "https://api.map.baidu.com"


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return "（无数据）\n"
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="百度地图真实链路验收")
    parser.add_argument("--address", required=True, help="用于地理编码的完整地址，越具体越可靠")
    parser.add_argument("--city", default=None, help="城市名，可省略")
    parser.add_argument(
        "--profile",
        default="narrow",
        choices=sorted(QUERY_PROFILES),
        help="检索词组画像，默认 narrow 以节省配额",
    )
    parser.add_argument("--routes", type=int, default=3, help="验证的步行路线条数，默认 3")
    parser.add_argument("--radius", type=int, default=1500, help="POI 检索半径（米），默认 1500")
    parser.add_argument("--out-dir", default=str(ROOT / ".runtime"), help="报告输出目录，默认 .runtime")
    args = parser.parse_args()

    load_env_file()
    config = BaiduConfig.from_env()

    if not config.ak:
        print("未配置 BAIDU_MAP_AK，未发起任何外部请求。", file=sys.stderr)
        print(
            "请先把 AK 写入项目根目录的 .env。申请步骤见 docs/ak-application-checklist.md。", file=sys.stderr
        )
        return 2

    profile = QUERY_PROFILES[args.profile]
    queries = [query for category in profile for query in profile[category]]
    route_budget = max(0, args.routes)
    official_endpoint = config.base_url.rstrip("/") == OFFICIAL_BASE_URL

    print(f"AK 已配置（{len(config.ak)} 字符，不予显示）")
    print(
        f"base_url={config.base_url}  地点检索版本={config.place_api_version}  超时={config.timeout_seconds}s"
    )
    print(f"检索词组画像={args.profile}，检索词：{'、'.join(queries)}")
    print(f"预计调用：1 次地理编码 + {len(queries)} 次地点检索 + 最多 {route_budget} 次步行路线")
    if not official_endpoint:
        print(
            f"!! base_url 不是官方地址（{OFFICIAL_BASE_URL}），本次结果属于仿真环境，不得当作真实百度数据。"
        )
    print("-" * 60)

    maps = BaiduMapsClient(config)
    report: list[str] = []
    failures: list[str] = []
    counts = {"geocode": 0, "pois": 0, "routes": 0}
    started = time.perf_counter()

    report.append("# 百度地图真实链路验收报告\n")
    if official_endpoint:
        report.append(
            f"**本报告由 `scripts/check_live.py` 对官方接口 {OFFICIAL_BASE_URL} 实际调用生成，是一次真实外部调用。**\n"
        )
    else:
        report.append(
            f"**⚠️ 仿真环境：base_url 为 `{config.base_url}`，不是官方地址 `{OFFICIAL_BASE_URL}`。**\n\n"
            "本次结果**不是真实百度数据**，只能用于验证脚本与适配器本身，"
            "不得写入正式材料、报告或答辩证据。\n"
        )
    report.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"- 地址：{args.address}" + (f"（{args.city}）" if args.city else ""))
    report.append(f"- 检索词组画像：`{args.profile}`")
    report.append(f"- 调用方式：顺序，非并发\n")
    report.append("## 配置\n")
    report.append(
        markdown_table(
            ["项", "值"],
            [
                ["base_url", config.base_url],
                ["地点检索版本", config.place_api_version],
                ["单请求超时(秒)", config.timeout_seconds],
                ["缓存 TTL(秒)", config.cache_ttl_seconds],
                ["并发上限", config.max_concurrency],
            ],
        )
    )

    # 步骤 1：地理编码
    report.append("## 步骤 1：地理编码\n")
    center = None
    try:
        counts["geocode"] += 1
        step = time.perf_counter()
        geocoded = maps.geocode(args.address, args.city)
        elapsed = (time.perf_counter() - step) * 1000
        center = geocoded["location"]
        print(f"[1/3] 地理编码 OK：{center['lng']}, {center['lat']}（{elapsed:.0f} ms）")
        report.append(
            markdown_table(
                ["字段", "值"],
                [
                    ["location", f"{center['lng']}, {center['lat']}"],
                    ["precise（是否精确）", geocoded.get("precise")],
                    ["confidence（置信度）", geocoded.get("confidence")],
                    ["comprehension（解析度）", geocoded.get("comprehension")],
                    ["level（级别）", geocoded.get("level")],
                    ["耗时(ms)", round(elapsed, 1)],
                ],
            )
        )
    except BaiduApiError as error:
        print(f"[1/3] 地理编码失败：{error}", file=sys.stderr)
        failures.append(f"地理编码：{error}")
        report.append(f"**失败**：{error}\n")

    # 步骤 2：地点检索
    report.append("## 步骤 2：地点检索\n")
    found: list[dict] = []
    if center is None:
        report.append("跳过于地理编码失败。\n")
        print("[2/3] 跳过：地理编码未成功")
    else:
        rows = []
        for query in queries:
            try:
                counts["pois"] += 1
                step = time.perf_counter()
                pois = maps.search_pois(
                    location=center, query=query, radius_m=args.radius, city_limit=bool(args.city)
                )
                elapsed = (time.perf_counter() - step) * 1000
                found.extend(pois)
                rows.append([query, len(pois), round(elapsed, 1)])
                print(f"[2/3] 地点检索「{query}」：{len(pois)} 条（{elapsed:.0f} ms）")
            except BaiduApiError as error:
                rows.append([query, "失败", str(error)])
                failures.append(f"地点检索 {query}：{error}")
                print(f"[2/3] 地点检索「{query}」失败：{error}", file=sys.stderr)
        report.append(markdown_table(["检索词", "返回条数", "耗时(ms)"], rows))
        report.append(f"合计返回 {len(found)} 条。\n")
        report.append("> 返回条数为 0 不等于该区域没有设施，也可能是检索词过窄或半径过小。\n")

    # 步骤 3：步行路线
    report.append("## 步骤 3：步行路线规划\n")
    if center is None or not found:
        report.append("跳过于缺少中心点或 POI。\n")
        print("[3/3] 跳过：缺少中心点或 POI")
    else:
        seen: set[str] = set()
        targets = []
        for poi in found:
            key = poi.get("uid") or poi.get("name")
            if key in seen:
                continue
            seen.add(key)
            targets.append(poi)
            if len(targets) >= route_budget:
                break
        rows = []
        for poi in targets:
            try:
                counts["routes"] += 1
                step = time.perf_counter()
                route = maps.walking_route(
                    origin=center, destination=poi["location"], destination_uid=poi.get("uid")
                )
                elapsed = (time.perf_counter() - step) * 1000
                duration = route.get("duration_s")
                minutes = round(duration / 60, 1) if duration is not None else None
                rows.append(
                    [
                        poi.get("name"),
                        route.get("distance_m"),
                        duration,
                        minutes,
                        len(route.get("steps") or []),
                        round(elapsed, 1),
                    ]
                )
                print(
                    f"[3/3] 步行路线「{poi.get('name')}」：{route.get('distance_m')} m / {duration} s（{elapsed:.0f} ms）"
                )
            except BaiduApiError as error:
                rows.append([poi.get("name"), "失败", "", "", "", str(error)])
                failures.append(f"步行路线 {poi.get('name')}：{error}")
                print(f"[3/3] 步行路线「{poi.get('name')}」失败：{error}", file=sys.stderr)
        report.append(
            markdown_table(["设施", "距离(m)", "耗时(s)", "约分钟", "分段数", "请求耗时(ms)"], rows)
        )
        report.append(
            "> API 返回的 `duration` 是步行接口自己的估计，**不得**改写成本项目合成算法里的固定步速；"
            "两者在报告中必须分开表述。\n"
        )

    # 汇总
    total_elapsed = (time.perf_counter() - started) * 1000
    total_calls = sum(counts.values())
    report.append("## 汇总\n")
    report.append(
        markdown_table(
            ["项目", "值"],
            [
                ["地理编码调用", counts["geocode"]],
                ["地点检索调用", counts["pois"]],
                ["步行路线调用", counts["routes"]],
                ["合计调用", total_calls],
                ["总耗时(ms)", round(total_elapsed, 1)],
                ["失败项", len(failures)],
            ],
        )
    )
    if failures:
        report.append("### 失败明细\n")
        report.extend(f"- {item}" for item in failures)
        report.append("")
    report.append("## 结论\n")
    if failures:
        report.append(f"有 {len(failures)} 项失败，**真实链路尚未全部打通**，不得据此宣称真实数据已接入。\n")
    elif official_endpoint:
        report.append("地理编码、地点检索、步行路线三步均返回可用结果，真实链路已跑通。\n")
    else:
        report.append("脚本与适配器三步均走通，但**本次针对的是仿真地址，真实链路仍未验证**。\n")
    report.append(
        "仍需人工核验后才可写入正式材料：POI 分类是否准确（当前按检索词规则归类，需抽查）、"
        "营业状态与容量是否可用、配额实际消耗是否与官方默认值一致。\n"
    )
    report.append(
        "**本报告含接口响应数据，请勿提交到公开仓库。** 报告默认写入 `.runtime/`，该目录已在 `.gitignore` 中。\n"
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"live-verification-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    out_file.write_text("\n".join(report), encoding="utf-8")

    print("-" * 60)
    print(f"合计 {total_calls} 次调用，耗时 {total_elapsed / 1000:.1f} s，失败 {len(failures)} 项")
    print(f"报告已写入：{out_file}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
