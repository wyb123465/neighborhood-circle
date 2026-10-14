"""Build a standalone public source archive using a strict allowlist."""

from __future__ import annotations

import hashlib
import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_scan import scan

FILES = {
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    "constraints.txt",
    "home.html",
    "home.js",
    "workspace.css",
    "workspace-ui.js",
    "workspace-store.js",
    "index.html",
    "app.js",
    "live.html",
    "live.js",
    "assistant.html",
    "assistant.js",
    "assistant-state.js",
    "styles.css",
    "start.ps1",
    "start.sh",
    "CHANGELOG.md",
    "geo-map.js",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "SECURITY.md",
    "pyproject.toml",
    "requirements-dev.txt",
    "package.json",
    "package-lock.json",
    ".prettierrc.json",
}
DIRECTORIES = {"backend", "assets", "data", "docs", "tests", "scripts", ".github", ".ui-craft"}
EXTENSIONS = {
    ".py",
    ".js",
    ".cjs",
    ".css",
    ".html",
    ".json",
    ".md",
    ".yml",
    ".yaml",
    ".txt",
    ".ps1",
    ".sh",
    ".png",
    ".jpg",
    ".csv",
}


def source_files():
    files = [ROOT / name for name in FILES if (ROOT / name).is_file()]
    for directory in DIRECTORIES:
        files.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file() and p.suffix in EXTENSIONS and "__pycache__" not in p.parts
        )
    return sorted(files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.7.0", choices=("0.6.0", "0.7.0"))
    args = parser.parse_args()
    findings = scan(ROOT)
    if findings:
        print("源码安全扫描未通过，停止打包：\n" + "\n".join(findings))
        return 1
    files = source_files()
    manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    output = ROOT / "output/release"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"neighborhood-circle-v{args.version}-source.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for p in files:
            bundle.write(p, "neighborhood-circle/" + p.relative_to(ROOT).as_posix())
        bundle.writestr(
            "neighborhood-circle/SOURCE-MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / f"SHA256SUMS-v{args.version}.txt").write_text(f"{sha}  {archive.name}\n", encoding="utf-8")
    print(f"已扫描并打包 {len(files)} 个源码文件（不含 .env、真实响应、其他项目和本地依赖）。")
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
