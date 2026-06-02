#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量字幕生成器 - Windows 适配版
用法：
  python tools/batch_subtitle.py --input D:/videos --lang zh
  python tools/batch_subtitle.py --input D:/videos --lang en --bilingual
  python tools/batch_subtitle.py --input D:/videos --lang zh --upload D:/upload_ready
"""
import os
import sys
import re
import json
import shutil
import argparse
import platform
import subprocess
from pathlib import Path

SUPPORTED_VIDEO = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".m4v"}
SUPPORTED_AUDIO = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}


def is_windows():
    return platform.system() == "Windows"


def to_posix(path: Path) -> str:
    """Windows 路径转成命令行友好的正斜杠格式（Git Bash / MSYS2 兼容）"""
    if is_windows():
        drive, rest = os.path.splitdrive(str(path))
        if drive:
            return "/" + drive[0].lower() + rest.replace("\\", "/")
    return str(path).replace("\\", "/")


def find_whisper_cli(config: dict) -> Path:
    """按优先级查找 whisper-cli 可执行文件"""
    # 1. 配置文件指定
    if config.get("whisper_cli"):
        p = Path(config["whisper_cli"])
        if p.exists():
            return p

    # 2. Windows 常见位置
    if is_windows():
        candidates = [
            Path("D:/srtskills/whisper/Release/whisper-cli.exe"),
            Path("C:/whisper/Release/whisper-cli.exe"),
            Path(os.environ.get("LOCALAPPDATA", ""), "whisper/whisper-cli.exe"),
        ]
        for c in candidates:
            if c.exists():
                return c

    # 3. PATH 中查找
    name = "whisper-cli.exe" if is_windows() else "whisper-cli"
    found = shutil.which(name)
    if found:
        return Path(found)

    raise FileNotFoundError(
        "找不到 whisper-cli。\n"
        "请在 config.json 中设置 whisper_cli 路径，或把 whisper-cli.exe 加入 PATH。\n"
        "下载地址：https://github.com/ggml-org/whisper.cpp/releases"
    )


def find_ffmpeg(config: dict) -> Path:
    """查找带 libass 的 ffmpeg"""
    if config.get("ffmpeg"):
        p = Path(config["ffmpeg"])
        if p.exists():
            return p

    found = shutil.which("ffmpeg")
    if found:
        return Path(found)

    raise FileNotFoundError(
        "找不到 ffmpeg。\n"
        "Windows 请下载完整版：https://github.com/BtbN/FFmpeg-Builds/releases\n"
        "解压后在 config.json 中设置 ffmpeg 路径。"
    )


def find_model(config: dict) -> Path:
    """查找 whisper 模型文件"""
    if config.get("model"):
        p = Path(config["model"])
        if p.exists():
            return p

    candidates = [
        Path("D:/srtskills/ggml-large-v3-turbo.bin"),
        Path("D:/whisper-models/ggml-large-v3-turbo.bin"),
        Path.home() / ".cache/whisper.cpp/ggml-large-v3-turbo.bin",
    ]
    for c in candidates:
        if c.exists():
            return c

    raise FileNotFoundError(
        "找不到 whisper 模型文件。\n"
        "请在 config.json 中设置 model 路径，或下载模型到 D:/srtskills/ 下。\n"
        "镜像下载（国内）：\n"
        "curl -L -o D:/srtskills/ggml-large-v3-turbo.bin \\\n"
        "  https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"
    )


def load_config() -> dict:
    """加载配置文件，不存在则返回空配置"""
    config_path = Path(__file__).parent.parent / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {}


def extract_audio(ffmpeg: Path, video: Path, out_dir: Path) -> Path:
    """从视频提取 16k 单声道 wav（whisper 要求格式）"""
    wav = out_dir / (video.stem + "_audio16k.wav")
    if wav.exists():
        print(f"  [跳过] 音轨已存在: {wav.name}")
        return wav

    cmd = [
        str(ffmpeg), "-y", "-i", str(video),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(wav)
    ]
    print(f"  [抽音轨] {video.name} → {wav.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 抽音轨失败:\n{result.stderr[-500:]}")
    return wav


def run_whisper(whisper_cli: Path, model: Path, audio: Path,
                out_dir: Path, lang: str, threads: int = 4) -> Path:
    """调用 whisper-cli 识别，输出 SRT"""
    out_stem = out_dir / (audio.stem.replace("_audio16k", "_whisper"))
    srt_path = Path(str(out_stem) + ".srt")

    if srt_path.exists():
        print(f"  [跳过] SRT 已存在: {srt_path.name}")
        return srt_path

    cmd = [
        str(whisper_cli),
        "-m", str(model),
        "-f", str(audio),
        "-l", lang,
        "-osrt",
        "-of", str(out_stem),
        "-t", str(threads),
    ]
    print(f"  [识别] {audio.name} (lang={lang}) ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not srt_path.exists():
        raise RuntimeError(f"whisper 识别失败:\n{result.stderr[-500:]}")
    return srt_path


def apply_corrections(srt_path: Path, corrections: list[tuple]) -> Path:
    """将纠错规则应用到 SRT，返回纠错后的 SRT 路径"""
    if not corrections:
        return srt_path

    out_path = srt_path.parent / srt_path.name.replace("_whisper", "_corrected")
    text = srt_path.read_text(encoding="utf-8-sig")
    n_fix = 0
    for wrong, right in corrections:
        if wrong and wrong in text:
            text = text.replace(wrong, right)
            n_fix += 1
    out_path.write_text(text, encoding="utf-8")
    print(f"  [纠错] 应用 {len(corrections)} 条规则，命中 {n_fix} 处 → {out_path.name}")
    return out_path


def burn_subtitles(ffmpeg: Path, video: Path, srt: Path,
                   out_dir: Path, fontsize: int = 48,
                   style: str = "box", font: str = "Arial") -> Path:
    """
    把 SRT 直接烧录进视频（Windows 兼容方式，不依赖 libass）
    使用 subtitles filter（需要 ffmpeg 支持 libass 或 ass filter）
    """
    out_video = out_dir / (video.stem + "_字幕版" + video.suffix)
    if out_video.exists():
        print(f"  [跳过] 成片已存在: {out_video.name}")
        return out_video

    # Windows 路径中的冒号需要转义给 ffmpeg filter
    srt_str = str(srt).replace("\\", "/").replace(":", "\\:")

    # 字幕样式参数
    force_style = (
        f"FontName={font},"
        f"FontSize={fontsize},"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"BorderStyle={'3' if style == 'box' else '1'},"
        f"Outline=2,Shadow=1,Alignment=2,MarginV=30"
    )

    cmd = [
        str(ffmpeg), "-y", "-i", str(video),
        "-vf", f"subtitles='{srt_str}':force_style='{force_style}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_video)
    ]
    print(f"  [烧录] → {out_video.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 烧录失败:\n{result.stderr[-500:]}")
    return out_video


def collect_corrections_interactive() -> list[tuple]:
    """交互式收集纠错规则（可选）"""
    print("\n[纠错] 输入纠错规则（格式：错词=>对词），空行结束：")
    pairs = []
    while True:
        line = input("  > ").strip()
        if not line:
            break
        if "=>" in line:
            a, b = line.split("=>", 1)
            pairs.append((a.strip(), b.strip()))
    return pairs


def copy_to_upload(finished: Path, upload_dir: Path):
    """把成片复制到上传目录"""
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / finished.name
    shutil.copy2(finished, dest)
    print(f"  [上传目录] 已复制 → {dest}")


def process_one(video: Path, work_dir: Path, args, config: dict,
                whisper_cli: Path, ffmpeg: Path, model: Path,
                corrections: list[tuple]) -> dict:
    """处理单个视频，返回结果信息"""
    print(f"\n{'='*50}")
    print(f"处理: {video.name}")
    result = {"file": video.name, "status": "ok", "outputs": []}

    try:
        # 1. 提取音轨
        if video.suffix.lower() in SUPPORTED_VIDEO:
            audio = extract_audio(ffmpeg, video, work_dir)
        else:
            audio = video  # 已经是音频文件

        # 2. whisper 识别
        srt_raw = run_whisper(whisper_cli, model, audio, work_dir,
                              args.lang, threads=config.get("threads", 4))

        # 3. 应用纠错
        srt_final = apply_corrections(srt_raw, corrections)
        result["srt"] = str(srt_final)
        result["outputs"].append(str(srt_final))

        # 4. 烧录字幕
        if not args.srt_only:
            finished = burn_subtitles(
                ffmpeg, video, srt_final, work_dir,
                fontsize=config.get("fontsize", 48),
                style=config.get("style", "box"),
                font=config.get("font", "Arial")
            )
            result["video"] = str(finished)
            result["outputs"].append(str(finished))

            # 5. 复制到上传目录
            if args.upload:
                copy_to_upload(finished, Path(args.upload))

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"  [错误] {e}")

    return result


def main():
    ap = argparse.ArgumentParser(description="批量字幕生成器（Windows 适配版）")
    ap.add_argument("--input", required=True,
                    help="输入目录（含视频/音频文件）或单个文件路径")
    ap.add_argument("--lang", default="zh",
                    help="识别语言代码，如 zh / en / ja（默认 zh）")
    ap.add_argument("--bilingual", action="store_true",
                    help="双语模式（外语 + 中文翻译，需配合 Claude 纠错翻译步骤）")
    ap.add_argument("--srt-only", action="store_true",
                    help="只生成 SRT，不烧录视频")
    ap.add_argument("--upload", default=None,
                    help="烧录完成后自动复制成片到此目录（如 D:/upload_ready）")
    ap.add_argument("--corrections", default=None,
                    help="纠错规则文件路径（每行 错词=>对词）")
    ap.add_argument("--interactive-corrections", action="store_true",
                    help="交互式输入纠错规则")
    ap.add_argument("--work-dir", default=None,
                    help="中间文件输出目录，默认与输入同级的 subtitle_work/")
    ap.add_argument("--recursive", action="store_true",
                    help="递归处理子目录中的视频")
    args = ap.parse_args()

    config = load_config()

    # 收集纠错规则
    corrections = []
    if args.corrections and Path(args.corrections).exists():
        for line in Path(args.corrections).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=>" in line:
                a, b = line.split("=>", 1)
                corrections.append((a.strip(), b.strip()))
        print(f"[纠错] 从文件加载 {len(corrections)} 条规则")
    if args.interactive_corrections:
        corrections += collect_corrections_interactive()

    # 查找工具
    try:
        whisper_cli = find_whisper_cli(config)
        ffmpeg = find_ffmpeg(config)
        model = find_model(config)
        print(f"[工具] whisper-cli: {whisper_cli}")
        print(f"[工具] ffmpeg:      {ffmpeg}")
        print(f"[工具] 模型:        {model}")
    except FileNotFoundError as e:
        print(f"\n[错误] {e}")
        sys.exit(1)

    # 收集输入文件
    input_path = Path(args.input)
    if input_path.is_file():
        videos = [input_path]
        base_dir = input_path.parent
    else:
        pattern = "**/*" if args.recursive else "*"
        all_files = list(input_path.glob(pattern))
        videos = [f for f in all_files
                  if f.suffix.lower() in SUPPORTED_VIDEO | SUPPORTED_AUDIO]
        base_dir = input_path

    if not videos:
        print(f"[警告] 在 {args.input} 中未找到支持的视频/音频文件")
        sys.exit(0)

    print(f"\n[批量] 共找到 {len(videos)} 个文件")

    # 工作目录
    work_dir = Path(args.work_dir) if args.work_dir else base_dir / "subtitle_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    print(f"[工作目录] {work_dir}")

    # 批量处理
    results = []
    for video in sorted(videos):
        r = process_one(video, work_dir, args, config,
                        whisper_cli, ffmpeg, model, corrections)
        results.append(r)

    # 汇总报告
    print(f"\n{'='*50}")
    ok = [r for r in results if r["status"] == "ok"]
    err = [r for r in results if r["status"] == "error"]
    print(f"[完成] 成功 {len(ok)} / 失败 {len(err)} / 共 {len(results)}")
    if err:
        print("\n[失败列表]")
        for r in err:
            print(f"  ✗ {r['file']}: {r.get('error', '未知错误')}")

    # 保存报告
    report_path = work_dir / "batch_report.json"
    report_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n[报告] 已保存到 {report_path}")


if __name__ == "__main__":
    main()
