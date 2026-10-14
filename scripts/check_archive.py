"""Validate the public ZIP in an isolated source directory.

Use --python to choose a separately installed reviewer environment. The archive
is not allowed to contain credentials, raw responses, traversal paths or links.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=ROOT / "output/release/neighborhood-circle-v0.6.0-source.zip")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args()
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    python = str(args.python.resolve())
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("BAIDU_") or key in {"AI_API_KEY", "AI_BASE_URL", "PYTHONPATH", "NEIGHBORHOOD_IGNORE_ENV"}:
            env.pop(key, None)
    env["PYTHONUTF8"] = "1"
    with tempfile.TemporaryDirectory(prefix="reviewer-source-", dir=runtime) as temporary:
        destination = Path(temporary).resolve()
        destination.relative_to(runtime.resolve())
        with zipfile.ZipFile(args.archive) as archive:
            for member in archive.infolist():
                target = (destination / member.filename).resolve()
                target.relative_to(destination)
                parts = Path(member.filename).parts
                assert parts[0] == "neighborhood-circle"
                assert not any(p in {".env", ".runtime", ".venv", ".git", "fixtures.json"} for p in parts)
                assert not stat.S_ISLNK(member.external_attr >> 16)
            archive.extractall(destination)
        source = destination / "neighborhood-circle"
        subprocess.run([python, "-m", "pytest", "-q", "--tb=short"], cwd=source, env=env, check=True)
        subprocess.run([python, "scripts/security_scan.py"], cwd=source, env=env, check=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([python, "scripts/serve.py", "--mode", "synthetic", "--port", str(port)], cwd=source, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        try:
            for attempt in range(50):
                if process.poll() is not None:
                    raise RuntimeError("独立源码服务提前退出")
                try:
                    with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                        assert json.load(response)["status"] == "ok"
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("独立源码服务未能启动")
            for path in ("/", "/diagnosis.html", "/home.js", "/workspace.css", "/workspace-store.js", "/workspace-ui.js", "/live.html", "/assistant.html", "/assistant.js", "/assistant-state.js", "/app.js", "/live.js", "/styles.css", "/assets/vendor/leaflet.js"):
                with urllib.request.urlopen(base + path, timeout=5) as response:
                    assert response.status == 200
            with urllib.request.urlopen(base + "/api/live/status", timeout=5) as response:
                assert not json.load(response)["configured"]
            with urllib.request.urlopen(base + "/api/assistant/status", timeout=5) as response:
                assert not json.load(response)["configured"]
            with urllib.request.urlopen(base + "/api/communities/bridge-demo/inspection?category=%E5%85%BB%E8%80%81", timeout=5) as response:
                result = json.load(response)
                assert result["combined_coverage_pct"] == 44.8 and result["gap_count"] == 79
            print("独立源码 ZIP：完整测试、公开源码扫描、HTTP 启动、无 AK 状态与合成预设均通过。")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
