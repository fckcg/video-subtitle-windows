#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量字幕生成器 - Windows / macOS 通用版
用法：
  python tools/batch_subtitle.py --input /path/to/videos --lang zh
  python tools/batch_subtitle.py --input /path/to/videos --lang en --bilingual
  python tools/batch_subtitle.py --input /path/to/videos --lang zh --upload /path/to/upload
"""
import os
import sys
import json
import shutil
import argparse
import platform
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional

SUPPORTED_VIDEO = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".m4v"}
SUPPORTED_AUDIO = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}

# Python 版本检查
if sys.version_info < (3, 8):
    print("[错误] 需要 Python 3.8 或以上版本")
    sys.exit(1)


def is_windows() -> bool:
    return platform.system() == "Windows"


def is_mac() -> bool:
    return platform.system() == "Darwin"


def escape_ffmpeg_path(path: Path) -> str:
    """
    把路径转成 ffmpeg subtitles filter 能接受的格式。
    Windows: 反斜杠→正斜杠，冒号转义为 \\:，路径中空格用单引号包裹。
    macOS/Linux: 路径中空格和特殊字符用反斜杠转义。
    """
    s = str(path).replace("\\", "/")
    if is_windows():
        # 只转义驱动器冒号，如 D: → D\:
        if len(s) >= 2 and s[1] == ":":
            s = s[0] + "\\:" + s[2:]
    # 空格转义
    s = s.replace(" ", "\\ ")
    return s


def find_whisper_cli(config: dict) -> Path:
    """按优先级查找 whisper-cli 可执行文件"""
    # 1. 配置文件指定
    if config.get("whisper_cli"):
        p = Path(config["whisper_cli"])
        if p.exists():
            return p

    # 2. 平台特定常见位置
    if is_windows():
        candidates = [
            Path("D:/srtskills/whisper/Release/whisper-cli.exe"),
            Path("C:/whisper/Release/whisper-cli.exe"),
            Path(os.environ.get("LOCALAPPDATA", "C:/Users/default/AppData/Local"))
            / "whisper/whisper-cli.exe",
        ]
    else:
        candidates = [
            Path("/opt/homebrew/bin/whisper-cli"),   # Apple Silicon
            Path("/usr/local/bin/whisper-cli"),       # Intel Mac / Linux
        ]

    for c in candidates:
        if c.exists():
            return c

    # 3. PATH 中查找
    name = "whisper-cli.exe" if is_windows() else "whisper-cli"
    found = shutil.which(name)
    if found:
        return Path(found)

    if is_windows():
        install_hint = (
            "下载地址：https://github.com/ggml-org/whisper.cpp/releases\n"
            "下载 whisper-bin-x64.zip，解压到 D:/srtskills/whisper/"
        )
    else:
        install_hint = "macOS 安装：brew install whisper-cpp"

    raise FileNotFoundError(
        f"找不到 whisper-cli。\n"
        f"请在 config.json 中设置 whisper_cli 路径。\n"
        f"{install_hint}"
    )


def find_ffmpeg(config: dict) -> Path:
    """查找 ffmpeg，优先找带 libass 的版本"""
    if config.get("ffmpeg"):
        p = Path(config["ffmpeg"])
        if p.exists():
            return p

    # macOS：优先找 ffmpeg-full（带 libass）
    if is_mac():
        ffmpeg_full = Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
        if ffmpeg_full.exists():
            return ffmpeg_full

    found = shutil.which("ffmpeg")
    if found:
        return Path(found)

    if is_windows():
        install_hint = (
            "下载完整版：https://github.com/BtbN/FFmpeg-Builds/releases\n"
            "下载 ffmpeg-master-latest-win64-gpl.zip，解压后加入 PATH\n"
            "或在 config.json 中设置 ffmpeg 路径"
        )
    else:
        install_hint = "macOS 安装（带 libass）：brew install ffmpeg-full"

    raise FileNotFoundError(f"找不到 ffmpeg。\n{install_hint}")


def find_model(config: dict) -> Path:
    """查找 whisper 模型文件"""
    if config.get("model"):
        p = Path(config["model"])
        if p.exists():
            return p

    default_cache = Path.home() / ".cache/whisper.cpp/ggml-large-v3-turbo.bin"
    candidates = [default_cache]

    if is_windows():
        candidates = [
            Path("D:/srtskills/ggml-large-v3-turbo.bin"),
            Path("D:/whisper-models/ggml-large-v3-turbo.bin"),
            default_cache,
        ]

    for c in candidates:
        if c.exists():
            return c

    mirror = "https://hf-mirror.com" if is_windows() else "https://huggingface.co"
    model_url = f"{mirror}/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"
    out_path = "D:/srtskills/ggml-large-v3-turbo.bin" if is_windows() else str(default_cache)

    raise FileNotFoundError(
        f"找不到 whisper 模型文件。\n"
        f"请在 config.json 中设置 model 路径，或运行以下命令下载：\n"
        f"curl -L -C - -o {out_path} \\\n"
        f"  {model_url}"
    )


def load_config() -> dict:
    """加载 config.json，不存在则返回空配置"""
    config_path = Path(__file__).parent.parent / "config.json"
    if config_path.exists():
        try:
            text = config_path.read_text(encoding="utf-8")
            # 去掉 JSON 注释行（以 _ 开头的 key 视为注释，直接保留不影响）
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"[警告] config.json 格式错误，使用默认配置：{e}")
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
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 抽音轨失败:\n{result.stderr[-800:]}")
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
        "-pp",  # 打印进度
    ]
    print(f"  [识别] {audio.name} (lang={lang}, threads={threads}) ...")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")

    if result.returncode != 0 or not srt_path.exists():
        stderr_tail = result.stderr[-800:] if result.stderr else "(无输出)"
        raise RuntimeError(f"whisper 识别失败 (code={result.returncode}):\n{stderr_tail}")

    # 统计识别到的条数
    try:
        lines = srt_path.read_text(encoding="utf-8-sig").strip().splitlines()
        n_cues = sum(1 for l in lines if "-->" in l)
        print(f"  [识别完成] {n_cues} 条字幕")
    except Exception:
        pass

    return srt_path


def apply_corrections(srt_path: Path, corrections: List[Tuple[str, str]]) -> Path:
    """将纠错规则应用到 SRT，返回纠错后的 SRT 路径"""
    if not corrections:
        return srt_path

    out_path = srt_path.parent / srt_path.name.replace("_whisper", "_corrected")
    text = srt_path.read_text(encoding="utf-8-sig")
    n_fix = 0
    for wrong, right in corrections:
        if wrong and wrong in text:
            count = text.count(wrong)
            text = text.replace(wrong, right)
            n_fix += count
    out_path.write_text(text, encoding="utf-8")
    print(f"  [纠错] {len(corrections)} 条规则，替换 {n_fix} 处 → {out_path.name}")
    return out_path


def burn_subtitles(ffmpeg: Path, video: Path, srt: Path,
                   out_dir: Path, fontsize: int = 48,
                   style: str = "box", font: str = "Arial") -> Path:
    """把 SRT 烧录进视频（跨平台兼容）"""
    out_video = out_dir / (video.stem + "_字幕版" + video.suffix)
    if out_video.exists():
        print(f"  [跳过] 成片已存在: {out_video.name}")
        return out_video

    srt_escaped = escape_ffmpeg_path(srt)
    border_style = "3" if style == "box" else "1"
    font_for_platform = font if font != "Arial" else (
        "Hiragino Sans GB" if is_mac() else "Microsoft YaHei"
    )

    force_style = (
        f"FontName={font_for_platform},"
        f"FontSize={fontsize},"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"BorderStyle={border_style},"
        f"Outline=2,Shadow=1,Alignment=2,MarginV=30"
    )

    cmd = [
        str(ffmpeg), "-y", "-i", str(video),
        "-vf", f"subtitles='{srt_escaped}':force_style='{force_style}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_video)
    ]

    print(f"  [烧录] → {out_video.name}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 烧录失败:\n{result.stderr[-800:]}")
    return out_video


def load_corrections_file(path: str) -> List[Tuple[str, str]]:
    """从文件加载纠错规则"""
    pairs = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and "=>" in line:
                a, b = line.split("=>", 1)
                pairs.append((a.strip(), b.strip()))
    except Exception as e:
        print(f"[警告] 读取纠错文件失败：{e}")
    return pairs


def collect_corrections_interactive() -> List[Tuple[str, str]]:
    """交互式输入纠错规则"""
    print("\n[纠错] 输入纠错规则（格式：错词=>对词），空行结束：")
    pairs = []
    while True:
        try:
            line = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
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


def process_one(video: Path, work_dir: Path, args: argparse.Namespace,
                config: dict, whisper_cli: Path, ffmpeg: Path, model: Path,
                corrections: List[Tuple[str, str]]) -> dict:
    """处理单个视频，返回结果信息"""
    print(f"\n{'='*55}")
    print(f"处理: {video.name}")
    result: dict = {"file": video.name, "status": "ok", "outputs": []}

    try:
        # 1. 提取音轨（视频格式才需要，音频文件直接用）
        if video.suffix.lower() in SUPPORTED_VIDEO:
            audio = extract_audio(ffmpeg, video, work_dir)
        else:
            audio = video

        # 2. whisper 识别
        srt_raw = run_whisper(
            whisper_cli, model, audio, work_dir,
            args.lang, threads=config.get("threads", 4)
        )

        # 3. 应用纠错
        srt_final = apply_corrections(srt_raw, corrections)
        result["srt"] = str(srt_final)
        result["outputs"].append(str(srt_final))

        # 4. 烧录字幕（--srt-only 时跳过）
        if not args.srt_only:
            finished = burn_subtitles(
                ffmpeg, video, srt_final, work_dir,
                fontsize=config.get("fontsize", 48),
                style=config.get("style", "box"),
                font=config.get("font", "Arial"),
            )
            result["video"] = str(finished)
            result["outputs"].append(str(finished))

            # 5. 复制到上传目录
            if args.upload:
                copy_to_upload(finished, Path(args.upload))

        # 6. 双语提示（--bilingual 模式需要配合 Claude 纠错翻译）
        if args.bilingual:
            print(
                f"  [双语] SRT 已生成：{srt_final.name}\n"
                f"  请把此文件交给 Claude Code 执行双语翻译纠错，\n"
                f"  Claude 会生成 cues_bi.json，再用 scripts/bi_ass.py 烧录双语字幕。"
            )

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"  [错误] {e}")

    return result


def main():
    ap = argparse.ArgumentParser(
        description="批量字幕生成器（Windows / macOS 通用版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 处理单个视频（中文）
  python tools/batch_subtitle.py --input video.mp4 --lang zh

  # 批量处理目录（英文，只生成 SRT）
  python tools/batch_subtitle.py --input ~/Videos --lang en --srt-only

  # 带纠错规则，成片复制到上传目录
  python tools/batch_subtitle.py --input ~/Videos --lang zh \\
      --corrections corrections.txt --upload ~/upload_ready

  # 递归处理子目录
  python tools/batch_subtitle.py --input ~/Videos --lang zh --recursive
        """
    )
    ap.add_argument("--input", required=True,
                    help="输入目录或单个文件路径")
    ap.add_argument("--lang", default="zh",
                    help="识别语言代码：zh / en / ja / ko 等（默认 zh）")
    ap.add_argument("--bilingual", action="store_true",
                    help="双语模式：识别后提示交给 Claude 翻译，再用 bi_ass.py 烧录")
    ap.add_argument("--srt-only", action="store_true",
                    help="只生成 SRT，不烧录视频")
    ap.add_argument("--upload", default=None,
                    help="烧录完成后自动复制成片到此目录")
    ap.add_argument("--corrections", default=None,
                    help="纠错规则文件（每行 错词=>对词，# 开头为注释）")
    ap.add_argument("--interactive-corrections", action="store_true",
                    help="交互式输入纠错规则")
    ap.add_argument("--work-dir", default=None,
                    help="中间文件目录（默认：输入目录下的 subtitle_work/）")
    ap.add_argument("--recursive", action="store_true",
                    help="递归处理子目录")
    args = ap.parse_args()

    config = load_config()

    print(f"[环境] Python {sys.version.split()[0]} | "
          f"{'Windows' if is_windows() else 'macOS' if is_mac() else 'Linux'}")

    # 收集纠错规则
    corrections: List[Tuple[str, str]] = []
    if args.corrections:
        corrections = load_corrections_file(args.corrections)
        print(f"[纠错] 从文件加载 {len(corrections)} 条规则")
    if args.interactive_corrections:
        corrections += collect_corrections_interactive()

    # 查找工具
    try:
        whisper_cli = find_whisper_cli(config)
        ffmpeg = find_ffmpeg(config)
        model = find_model(config)
        print(f"[工具] whisper-cli : {whisper_cli}")
        print(f"[工具] ffmpeg      : {ffmpeg}")
        print(f"[工具] 模型        : {model}")
    except FileNotFoundError as e:
        print(f"\n[错误] {e}")
        sys.exit(1)

    # 收集输入文件
    input_path = Path(args.input)
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_VIDEO | SUPPORTED_AUDIO:
            print(f"[错误] 不支持的文件格式：{input_path.suffix}")
            sys.exit(1)
        videos = [input_path]
        base_dir = input_path.parent
    elif input_path.is_dir():
        pattern = "**/*" if args.recursive else "*"
        all_files = list(input_path.glob(pattern))
        videos = sorted(
            f for f in all_files
            if f.is_file() and f.suffix.lower() in SUPPORTED_VIDEO | SUPPORTED_AUDIO
        )
        base_dir = input_path
    else:
        print(f"[错误] 路径不存在：{args.input}")
        sys.exit(1)

    if not videos:
        print(f"[警告] 未找到支持的视频/音频文件")
        sys.exit(0)

    print(f"\n[批量] 共找到 {len(videos)} 个文件")
    for v in videos:
        print(f"  • {v.name}")

    # 工作目录
    work_dir = Path(args.work_dir) if args.work_dir else base_dir / "subtitle_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    print(f"[工作目录] {work_dir}\n")

    # 批量处理
    results = []
    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}]", end=" ")
        r = process_one(video, work_dir, args, config,
                        whisper_cli, ffmpeg, model, corrections)
        results.append(r)

    # 汇总
    print(f"\n{'='*55}")
    ok  = [r for r in results if r["status"] == "ok"]
    err = [r for r in results if r["status"] == "error"]
    print(f"[完成] 成功 {len(ok)} / 失败 {len(err)} / 共 {len(results)}")
    if err:
        print("\n[失败列表]")
        for r in err:
            print(f"  ✗ {r['file']}: {r.get('error', '未知')}")

    report_path = work_dir / "batch_report.json"
    report_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[报告] {report_path}")


if __name__ == "__main__":
    main()
