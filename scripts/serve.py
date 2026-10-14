"""Explicit launch modes: offline sample, live API, or private replay."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="邻里圈启动器")
    parser.add_argument("--mode", choices=("synthetic", "live", "replay", "assistant"), default="synthetic")
    parser.add_argument(
        "--map-mode",
        choices=("synthetic", "live", "replay"),
        default="synthetic",
        help="assistant 模式中的地图来源",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--replay-file", default=str(ROOT / ".runtime/replay/fixtures.json"))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port 必须介于 1 和 65535")
    maps_mode = args.map_mode if args.mode == "assistant" else args.mode
    if args.mode in {"synthetic", "replay"}:
        os.environ["NEIGHBORHOOD_IGNORE_ENV"] = "1"
        for key in list(os.environ):
            if key.startswith("BAIDU_") or key.startswith("AI_"):
                os.environ.pop(key, None)
    else:
        os.environ.pop("NEIGHBORHOOD_IGNORE_ENV", None)
        os.environ.pop("BAIDU_REPLAY_FILE", None)
    if maps_mode == "synthetic":
        os.environ["BAIDU_MAP_AK"] = ""
        os.environ["BAIDU_REPLAY_FILE"] = ""
    elif maps_mode == "replay":
        replay = Path(args.replay_file).resolve()
        if not replay.is_file():
            parser.error("回放文件不存在；公开源码包默认使用 synthetic 模式。")
        os.environ["BAIDU_REPLAY_FILE"] = str(replay)
    sys.path.insert(0, str(ROOT))
    from backend.baidu import BaiduConfig, BaiduMapsClient
    from backend.main import app
    import uvicorn

    if maps_mode == "live" and not BaiduConfig.from_env().ak:
        parser.error("live 模式需要在本地 .env 配置 BAIDU_MAP_AK。")
    if maps_mode == "replay":
        check = BaiduMapsClient()
        print("历史回放：" + str(check.replay_metadata.get("recorded_at")))
        check.close()
    print(f"邻里圈 {app.version} | {args.mode} | http://{args.host}:{args.port}")
    if args.mode == "assistant":
        print(f"智能助手：http://{args.host}:{args.port}/assistant.html | 地图 {maps_mode}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
