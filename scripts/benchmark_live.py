"""Explicit, low-rate cold/warm comparison; never runs as part of CI."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.baidu import BaiduConfig, BaiduMapsClient
from backend.live_inspection import inspect_live


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--address", default="上海市长宁区愚园路")
    parser.add_argument("--city", default="上海市")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/live-cache-benchmark-v07.json")
    args = parser.parse_args()
    if not args.allow_network:
        parser.error("真实基准会消耗配额；显式添加 --allow-network 才会执行")
    config = BaiduConfig.from_env()
    config = replace(
        config, qps=1.0, max_concurrency=1, matrix_pairs=1, cache_ttl_seconds=600, replay_file=""
    )
    if not config.ak:
        parser.error("未配置服务端地图凭证")
    report = {
        "case": args.address,
        "profile": "narrow",
        "max_facilities": 8,
        "rate_units_per_second": 1,
        "note": "同进程同输入冷/热缓存对照；不是批量相对单条提速，也不是现实准确率。",
    }
    maps = BaiduMapsClient(config)
    evidence = []
    try:
        for label in ("cold", "warm"):
            before = maps.metrics()
            started = time.perf_counter()
            result = inspect_live(
                maps,
                address=args.address,
                city=args.city,
                categories=["医疗", "养老", "教育", "购物"],
                radius_m=2000,
                minutes=15,
                max_facilities=8,
                query_profile="narrow",
            )
            after = maps.metrics()
            report[label] = {
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "network_requests": after["network_requests"] - before["network_requests"],
                "cache_hits": after["cache_hits"] - before["cache_hits"],
                "failures": after["failures"] - before["failures"],
                "facility_count": result["facility_count"],
                "evidence_id": result["evidence_id"],
            }
            evidence.append(result["evidence_id"])
            report["center_bd09"] = result["community"]["center"]
        report["same_evidence"] = evidence[0] == evidence[1]
        report["passed"] = (
            report["same_evidence"]
            and report["cold"]["failures"] == 0
            and report["warm"]["failures"] == 0
            and report["warm"]["network_requests"] == 0
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    finally:
        maps.close()


if __name__ == "__main__":
    raise SystemExit(main())
