"""Explicit egress diagnostics; never invoked by page/status requests.

Compare domestic and foreign probes because VPN/TUN split routing can expose
different IPv4 addresses even when the client forces the IPv4 address family.
"""

import ipaddress
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.baidu import BaiduConfig


def main():
    config = BaiduConfig.from_env()
    print(
        f"force_ipv4={config.force_ipv4}；AK 末四位={config.ak[-4:] if config.ak else '未配置'}（不显示完整密钥）"
    )
    transport = httpx.HTTPTransport(local_address="0.0.0.0") if config.force_ipv4 else None
    results = {}
    with httpx.Client(transport=transport, timeout=10) as network:
        for name, url in (
            ("国内 ipip", "https://myip.ipip.net"),
            ("国内 3322", "https://ip.3322.net"),
            ("国外 ipify", "https://api.ipify.org"),
        ):
            try:
                response = network.get(url)
                response.raise_for_status()
                match = re.search(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", response.text)
                if not match:
                    raise ValueError("没有 IPv4")
                results[name] = str(ipaddress.IPv4Address(match.group(0)))
                print(f"{name}：{results[name]}")
            except (httpx.HTTPError, ValueError) as error:
                print(f"{name}：诊断失败（{type(error).__name__}）")
    domestic = {results[k] for k in results if k.startswith("国内")}
    if len(domestic) == 1:
        candidate = next(iter(domestic))
        print(f"国内出口候选：{candidate}；应与服务端 AK 的 IP 白名单核对，以真实 API 验收结果为准。")
        if results.get("国外 ipify") and results["国外 ipify"] != candidate:
            print("检测到国内外出口不同，不能把国外查询站结果直接当作百度接口来源。")
        return 0
    print("国内探测结果不足或不一致，请核对代理、VPN/TUN 与路由策略。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
