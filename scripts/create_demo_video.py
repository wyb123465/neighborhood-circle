"""Compose an explicitly labelled walkthrough from actual UI screenshots.

Optional build dependency: pip install --target .runtime/video-tools imageio-ffmpeg
Screenshots are captured through the browser tools; this script does not automate UI.
"""
from __future__ import annotations

import json
import argparse
import math
import os
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".runtime/video-tools"))
import imageio_ffmpeg


def wrap(text, draw, font, width):
    lines, line = [], ""
    for char in text:
        if draw.textlength(line + char, font=font) > width:
            lines.append(line)
            line = ""
        line += char
    if line:
        lines.append(line)
    return lines


def timestamp(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenes', default='scripts/demo-scenes.json')
    parser.add_argument('--version', default='0.4.1')
    parser.add_argument('--stem', default='邻里圈-三分钟分步演示')
    args = parser.parse_args()
    scenes_file = ROOT / args.scenes
    scenes = json.loads(scenes_file.read_text(encoding="utf-8"))
    work = ROOT / (".runtime/video-build-" + args.version)
    work.mkdir(parents=True, exist_ok=True)
    output = ROOT / "output/video"
    output.mkdir(parents=True, exist_ok=True)
    for scene in scenes:
        if not (ROOT / "output/screenshots" / scene["image"]).is_file():
            raise SystemExit(f"缺少实际运行截图：{scene['image']}")
    powershell = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    subprocess.run([powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/synthesize_narration.ps1"), "-SceneFile", str(scenes_file), "-OutDir", str(work)], check=True)
    font_path = "C:/Windows/Fonts/msyh.ttc"
    title_font, body_font, label_font = (ImageFont.truetype(font_path, size) for size in (36, 29, 23))
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    elapsed, subtitles, manifest = 0, [], []
    for index, scene in enumerate(scenes):
        audio = work / f"voice-{index:02}.wav"
        with wave.open(str(audio)) as wav:
            voice_duration = wav.getnframes() / wav.getframerate()
        duration = max(20, math.ceil(voice_duration + 3))
        frame = Image.new("RGB", (1920, 1080), "#f5f7f7")
        draw = ImageDraw.Draw(frame)
        draw.text((52, 22), scene["title"], fill="#1d3028", font=title_font)
        draw.text((1160, 32), f"v{args.version} / 实际运行截图 / 分步演示", fill="#687872", font=label_font)
        screenshot = ImageOps.contain(Image.open(ROOT / "output/screenshots" / scene["image"]).convert("RGB"), (1816, 790), Image.Resampling.LANCZOS)
        frame.paste(screenshot, ((1920 - screenshot.width) // 2, 95))
        draw.line((52, 906, 1868, 906), fill="#d9e1df", width=2)
        caption_lines = wrap(scene["voice"], draw, body_font, 1816)
        for line_index, line in enumerate(caption_lines):
            draw.text((52, 926 + 39 * line_index), line, font=body_font, fill="#42534d")
        draw.rectangle((0, 1074, round(1920 * (index + 1) / len(scenes)), 1079), fill="#197257")
        frame_path = work / f"frame-{index:02}.png"
        frame.save(frame_path)
        clip = work / f"clip-{index:02}.mp4"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", str(frame_path), "-i", str(audio), "-af", "apad", "-t", str(duration), "-r", "12", "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(clip)], check=True)
        subtitles.append(f"{index+1}\n{timestamp(elapsed)} --> {timestamp(elapsed+duration)}\n{scene['voice']}\n")
        manifest.append({"image": scene["image"], "start_s": elapsed, "duration_s": duration, "title": scene["title"]})
        elapsed += duration
        print(f"已编码 {index+1}/{len(scenes)}：{scene['title']}", flush=True)
    (work / "clips.txt").write_text("\n".join(f"file 'clip-{i:02}.mp4'" for i in range(len(scenes))), encoding="utf-8")
    video = output / (args.stem + '.mp4')
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(work / "clips.txt"), "-c", "copy", "-movflags", "+faststart", str(video)], check=True)
    (output / (args.stem + '.srt')).write_text("\n".join(subtitles), encoding="utf-8")
    (output / ('video-manifest-v' + args.version + '.json')).write_text(json.dumps({"duration_s": elapsed, "source": "actual UI screenshots; step-by-step presentation; synthesized Chinese narration", "scenes": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：{elapsed} 秒，{video}")


if __name__ == "__main__":
    main()
