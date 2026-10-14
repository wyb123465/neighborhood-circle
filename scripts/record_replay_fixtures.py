"""录制百度地图真实响应为回放 fixture，供现场演示离线回放。

用法（在项目根目录执行，需要已配置 BAIDU_MAP_AK）：
    .venv/Scripts/python.exe scripts/record_replay_fixtures.py --address "上海市长宁区愚园路" --city 上海市

录制内容：地理编码 + /api/live/inspect + 加密等时圈涉及的全部请求。
产物写入 .runtime/replay/fixtures.json（已 gitignore——交付清单要求
远端仓库不含真实原始响应）。演示时设置 BAIDU_REPLAY_FILE 指向该文件即可，
页面与接口会以 live-replay 模式如实标注，绝不冒充实时的结果。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.baidu import BaiduConfig, BaiduMapsClient, RecordingTransport, load_env_file  # noqa: E402
from backend.live_inspection import inspect_live  # noqa: E402
from backend.live_isochrone import build_isochrone  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="录制回放 fixture（真实响应，本地留存）")
    parser.add_argument("--address", required=True)
    parser.add_argument("--city", default=None)
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--query-profile", choices=("narrow", "full"), default="narrow")
    parser.add_argument("--out", default=str(ROOT / ".runtime" / "replay" / "fixtures.json"))
    args = parser.parse_args()

    load_env_file()
    config = BaiduConfig.from_env()
    if not config.ak:
        print("未配置 BAIDU_MAP_AK，录制需要真实调用。", file=sys.stderr)
        return 2

    inner = httpx.HTTPTransport(local_address="0.0.0.0") if config.force_ipv4 else httpx.HTTPTransport()
    recorder = RecordingTransport(inner)
    maps = BaiduMapsClient(config, transport=recorder)

    print(f"地理编码：{args.address}")
    center = maps.geocode(args.address, args.city)["location"]
    print("录制 inspect（含盲区识别）……")
    inspect = inspect_live(
        maps,
        address=args.address,
        city=args.city,
        categories=["医疗", "养老", "教育", "购物"],
        radius_m=1500,
        minutes=args.minutes,
        max_facilities=10,
        query_profile=args.query_profile,
    )
    print("录制加密等时圈……")
    isochrone = build_isochrone(maps, center=center, minutes=args.minutes)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "address": args.address,
                "city": args.city,
                "minutes": args.minutes,
                "parameters": {"query_profile": args.query_profile, "grid_m": 200, "max_facilities": 10, "selection_strategy": "nearest"},
                "inspect_mode": inspect["mode"],
                "fixtures": recorder.captured,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"已录制 {len(recorder.captured)} 个请求 → {out_path}")
    print("演示时设置环境变量 BAIDU_REPLAY_FILE 指向该文件，接口将以 live-replay 模式回放。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
