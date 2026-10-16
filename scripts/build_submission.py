"""Assemble reviewable submission files; never publish or send anything."""

from __future__ import annotations

import hashlib
import argparse
from datetime import date
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "01-项目介绍.pdf": "output/pdf/邻里圈-项目介绍.pdf",
    "02-演示视频.mp4": "output/video/邻里圈-三分钟分步演示.mp4",
    "03-解说字幕.srt": "output/video/邻里圈-解说字幕.srt",
    "04-开源源码.zip": "output/release/neighborhood-circle-v0.4.1-source.zip",
    "05-可复算验收报告.md": "output/verification/验收报告.md",
    "06-路线网页版对照.md": "docs/route-crosscheck-2026-10-13.md",
    "07-POI公开资料核对.md": "docs/poi-crosscheck-2026-10-13.md",
    "08-报名提交说明.md": "docs/submission-guide.md",
    "09-本轮验收记录.md": "docs/acceptance-2026-10-13.md",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=("0.4.1", "0.5.0-beta", "0.6.0", "0.7.0"), default="0.7.0")
    parser.add_argument("--without-video", action="store_true", help="生成待补新视频的资料包，不加入旧视频")
    parser.add_argument("--recording", type=Path, help="参赛人重新录制的视频路径")
    parser.add_argument("--brief", type=Path, help="本次定稿介绍PDF")
    parser.add_argument("--submission-date", type=date.fromisoformat)
    args = parser.parse_args()
    if args.without_video and args.recording:
        parser.error("--without-video和--recording不能同时使用")
    files = dict(FILES)
    if args.version == "0.5.0-beta":
        files.update(
            {
                "01-项目介绍.pdf": "output/pdf/邻里圈-v0.5-项目介绍.pdf",
                "02-演示视频.mp4": "output/video/邻里圈-v0.5-AI分步演示.mp4",
                "03-解说字幕.srt": "output/video/邻里圈-v0.5-AI分步演示.srt",
                "04-开源源码.zip": "output/release/neighborhood-circle-v0.5.0-beta-source.zip",
                "09-本轮验收记录.md": "docs/acceptance-v0.5.md",
                "10-边界补充复核.md": "docs/boundary-recheck-2026-10-13.md",
                "11-AI接入与验收说明.md": "docs/ai-integration.md",
            }
        )
    if args.version == "0.6.0":
        files.update(
            {
                "01-项目介绍.pdf": "output/pdf/邻里圈-v0.6-项目介绍.pdf",
                "02-演示视频.mp4": "output/video/邻里圈-v0.6-工作台分步演示.mp4",
                "03-解说字幕.srt": "output/video/邻里圈-v0.6-工作台分步演示.srt",
                "04-开源源码.zip": "output/release/neighborhood-circle-v0.6.0-source.zip",
                "09-本轮验收记录.md": "docs/acceptance-v0.6.md",
                "10-边界补充复核.md": "docs/boundary-recheck-2026-10-13.md",
                "11-AI接入与验收说明.md": "docs/ai-integration.md",
            }
        )
    if args.version == "0.7.0":
        files.update(
            {
                "01-项目介绍.pdf": "output/pdf/邻里圈-v0.7-项目介绍.pdf",
                "02-演示视频.mp4": "output/video/邻里圈-v0.7-工作台分步演示.mp4",
                "03-解说字幕.srt": "output/video/邻里圈-v0.7-工作台分步演示.srt",
                "04-开源源码.zip": "output/release/neighborhood-circle-v0.7.0-source.zip",
                "09-本轮验收记录.md": "docs/acceptance-v0.7.md",
                "10-边界补充复核.md": "docs/boundary-recheck-2026-10-13.md",
                "11-AI接入与验收说明.md": "docs/ai-integration.md",
                "12-真实样区验证汇总.md": "docs/community-validation-2026-10-14.md",
                "13-POI清洗策略.md": "docs/poi-cleaning.md",
                "14-贡献与维护.md": "GOVERNANCE.md",
                "15-网页地图配置.md": "docs/browser-map.md",
                "16-技术设计.md": "docs/technical-design.md",
            }
        )
    if args.brief:
        files["01-项目介绍.pdf"] = str(args.brief)
    if args.without_video or args.recording:
        files.pop("03-解说字幕.srt", None)
        files.pop("02-演示视频.mp4", None)
    if args.recording:
        files["02-演示视频.mp4"] = str(args.recording)
    if args.submission_date:
        files["17-提交前复核.md"] = "docs/preflight-2026-10-16.md"
        files["18-录制提纲.md"] = "docs/recording-final.md"
    for relative in files.values():
        source = ROOT / relative
        if not source.is_file() or not source.stat().st_size:
            raise SystemExit(f"缺少交付文件：{relative}")
    source_archive = ROOT / files["04-开源源码.zip"]
    with zipfile.ZipFile(source_archive) as source:
        assert not any(
            any(part in {".env", ".runtime", ".venv", ".git", "fixtures.json"} for part in Path(name).parts)
            for name in source.namelist()
        )
    output = ROOT / "output/submission"
    output.mkdir(parents=True, exist_ok=True)
    kind = "提交前材料" if args.without_video else "提交材料"
    suffix = f"-{args.submission_date.isoformat()}" if args.submission_date else ""
    target = output / f"邻里圈-v{args.version}-{kind}{suffix}.zip"
    video_note = (
        "本包不含旧视频。录制新视频后，请上传并填写可访问链接；如需附视频文件，用--recording重新打包。"
        if args.without_video
        else "使用参赛人提供的新录屏。"
        if args.recording
        else "视频为既有实际截图分步讲解，不是连续录屏。"
    )
    checksums = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, relative in files.items():
            source = ROOT / relative
            archive.write(source, name)
            checksums.append(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {name}")
        archive.writestr("SHA256SUMS.txt", "\n".join(checksums) + "\n")
        archive.writestr(
            "提交前必读.txt",
            f"邻里圈 v{args.version}\n\n报名及材料提交截止：2026-10-16 24:00（北京时间），以官网和确认邮件为准。\n官网：https://www.oschina.net/os2026/\n仓库：https://github.com/wyb123465/neighborhood-circle\n\n{video_note}\n参赛人信息按真实报名表填写，最终视频链接仍需核验可访问。\n源码ZIP内为单项目根目录。路线与设施独立核验的限制仍保留。\n本包不含密钥或私有原始响应；没有自动报名、上传视频或发送邮件。\n",
        )
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    checksum = (
        target.with_suffix(".sha256.txt")
        if args.submission_date or args.without_video or args.recording
        else output / f"SHA256SUMS-v{args.version}.txt"
    )
    checksum.write_text(f"{sha}  {target.name}\n", encoding="utf-8")
    print(f"提交材料包：{target}（{target.stat().st_size / 1024 / 1024:.2f} MiB）")


if __name__ == "__main__":
    main()
