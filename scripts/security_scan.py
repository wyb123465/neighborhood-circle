"""远端仓库发布前的安全扫描：确认跟踪文件里没有密钥、本地产物与真实原始响应。

用法（在项目根目录或仓库根执行）：
    .venv/Scripts/python.exe scripts/security_scan.py

检查项（对应交付清单「远端仓库安全检查」）：
1. 跟踪文件中不得出现 .env / .runtime / fixtures.json；
2. 不得出现 32 位 AK 形态的字符串（百度 AK 为 32 位字母数字）；
3. 不得出现非空 BAIDU_MAP_AK= 赋值；
4. 不得出现疑似真实百度原始响应的大段 JSON（status/pois/district 字段组合）；
5. 不得出现 11 位手机号或身份证号形态的明文。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

AK_LIKE = re.compile(r"\b[A-Za-z0-9]{32}\b")
AK_ASSIGN = re.compile(r"^[ \t]*(?:export[ \t]+)?BAIDU_MAP_AK[ \t]*=[ \t]*([^\s#]+)", re.MULTILINE)
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
RAW_RESPONSE_HINT = re.compile(r'"(pois|results|district)"\s*:')
FORBIDDEN_PATHS = (".env", ".runtime", "fixtures.json", "route-audit-", "live-verification-")


def tracked_files(repo: Path) -> list[str]:
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                ".",
            ],
            capture_output=True,
            check=True,
        )
        names = sorted(set(name for name in out.stdout.decode("utf-8").split("\0") if name))
        if names:
            return names
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # A downloaded source ZIP has no Git metadata (or can sit inside an
    # ancestor repo's ignored directory). Scan its public source as well.
    excluded = {".git", ".venv", ".runtime", "output", "node_modules", "__pycache__", ".pytest_cache"}
    names = []
    for directory, subdirs, files in os.walk(repo):
        subdirs[:] = [name for name in subdirs if name not in excluded]
        for name in files:
            if name == ".env" or name.startswith(".env.") and name != ".env.example":
                continue
            names.append((Path(directory) / name).relative_to(repo).as_posix())
    return sorted(names)


def scan(repo: Path) -> list[str]:
    findings: list[str] = []
    for rel in tracked_files(repo):
        path = repo / rel
        if not path.is_file() or path.suffix in {".png", ".jpg", ".pdf", ".ico"}:
            continue
        lowered = rel.lower()
        basename = lowered.rsplit("/", 1)[-1]
        # .env.example 是公开的安全模板，不算违规；其余 .env/.runtime 产物一律拒绝。
        if (
            basename == ".env"
            or lowered.endswith("/.env")
            or ".runtime/" in lowered
            or basename == "fixtures.json"
        ):
            findings.append(f"[路径] {rel} 不应入库")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in AK_LIKE.finditer(text):
            token = match.group(0)
            if (
                token.isdigit()
                or token.lower() in {"e", "t"}
                or all(c in "0123456789abcdef" for c in token.lower())
                and len(token) in {7, 8}
            ):
                continue  # 纯数字、短哈希等常见误报
            # Government source URLs use 32-character document identifiers.
            # Restrict this exception to URL paths, never AK query parameters.
            if all(c in "0123456789abcdef" for c in token.lower()):
                urls = re.finditer(r"https?://[^\s)]+", text)
                if any(
                    url.start() <= match.start()
                    and match.end() <= url.end()
                    and (urlparse(url.group()).hostname or "").endswith(".gov.cn")
                    and token in urlparse(url.group()).path
                    for url in urls
                ):
                    continue
            line = text[: match.start()].count("\n") + 1
            findings.append(f"[疑似AK] {rel}:{line} 出现 32 位字母数字串 {token[:6]}…")
        for assigned in AK_ASSIGN.finditer(text):
            value = assigned.group(1).strip("\"'")
            if value and value not in {"在这里粘贴你的AK", "你的32位AK", "dotenv-wiring-check"}:
                findings.append(f"[AK赋值] {rel} 出现非空 BAIDU_MAP_AK 赋值")
        # 原始响应检查只针对数据型文件：代码文件解析响应字段、文档举例都是正常形态。
        if path.suffix in {".json", ".txt"} and RAW_RESPONSE_HINT.search(text):
            findings.append(f"[疑似原始响应] {rel} 出现 POI/结果字段组合")
        for match in PHONE.finditer(text):
            line = text[: match.start()].count("\n") + 1
            findings.append(f"[疑似手机号] {rel}:{line}")
            break
        for match in ID_CARD.finditer(text):
            line = text[: match.start()].count("\n") + 1
            findings.append(f"[疑似身份证号] {rel}:{line}")
            break
    return findings


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    findings = scan(repo)
    if findings:
        print(f"发现 {len(findings)} 处疑似问题：")
        for item in findings:
            print("  -", item)
        return 1
    print("安全扫描通过：公开源码中未发现密钥、本地产物、真实原始响应或个人信息。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
