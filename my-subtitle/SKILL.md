---
name: video-subtitle-windows
description: >
  给任意视频加硬字幕的全流程 Windows 适配版——
  whisper.cpp 本地识别（逐句真实时间戳）→ Claude 通读纠错（同音字/专有名词）→
  生成 SRT → ffmpeg 烧录。支持批量处理整个目录、自动复制成片到上传目录。
  当用户要"给视频加字幕""批量加字幕""视频转字幕""字幕烧录""提取字幕"时使用。
---

# 视频字幕全流程（Windows 版）

**核心流水线：** 抽音轨 → whisper.cpp 识别 → Claude 纠错 → 生成 SRT → 烧录硬字幕

> 用户只提供视频。纠错表（corrections.txt）由你（Claude）通读转写后自动生成，不需要用户提供。

---

## Windows 环境前置

### 工具路径（当前用户环境）

| 工具 | 路径 |
|------|------|
| whisper-cli.exe | `D:\srtskills\whisper\Release\whisper-cli.exe` |
| 识别模型 | `D:\srtskills\ggml-large-v3-turbo.bin` |
| ffmpeg | 系统 PATH 或指定路径 |

### Windows 路径注意事项

- 路径中**不要包含中文字符**——whisper-cli.exe 解析中文路径会截断（已知 bug）
- 工作目录统一用 `D:\srtskills\` 或其他纯英文路径
- 音频/视频文件名有中文时先用 ffmpeg 复制并重命名：
  ```bash
  ffmpeg -i "原始中文名.mp4" -c copy output.mp4
  ```
- Git Bash 里路径写法：`D:\srtskills` → `/d/srtskills`

---

## 步骤

### 0. 探测视频信息

```bash
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height \
  -of default=noprint_wrappers=1 video.mp4
```

记下**时长（秒）和分辨率**，后续烧录 `--res` 参数要用。

### 1. 抽取 16k 单声道音轨

whisper-cli.exe 支持 wav/mp3/flac/ogg，**不支持 mp4**，必须先抽音轨：

```bash
ffmpeg -y -i video.mp4 -ar 16000 -ac 1 -c:a pcm_s16le audio16k.wav
```

### 2. whisper.cpp 识别 → SRT

```bash
# 中文视频
/d/srtskills/whisper/Release/whisper-cli.exe \
  -m /d/srtskills/ggml-large-v3-turbo.bin \
  -f audio16k.wav -l zh -osrt -of video_whisper -t 4

# 英文视频（双语字幕时用 -l en）
/d/srtskills/whisper/Release/whisper-cli.exe \
  -m /d/srtskills/ggml-large-v3-turbo.bin \
  -f audio16k.wav -l en -osrt -of video_whisper -t 4
```

- `-t 4` 线程数，按 CPU 核心数调整
- 不要加 `-ml`（按字数硬切会断在词中间）
- 有开场/结尾音乐时加 `--vad` 避免幻觉字幕

### 3. Claude 纠错（全自动，由你做）

通读 `video_whisper.srt`，结合视频主题找出同音字/专有名词错误，生成 `corrections.txt`：

```
# 格式：错词=>对词
程序儿=>程序员
会计记药=>会议纪要
空白脸=>空白页
```

然后应用：

```bash
python scripts/srt_to_cues.py \
  --srt video_whisper.srt \
  --cues cues.json \
  --corrections-file corrections.txt \
  --out-srt video_final.srt
```

### 4. 烧录硬字幕

**方式一：通过 SRT 直接烧录（Windows 推荐，不依赖 libass）**

```bash
# Windows 路径中冒号需要转义
ffmpeg -y -i video.mp4 \
  -vf "subtitles='D\:/srtskills/video_final.srt':force_style='FontName=Microsoft YaHei,FontSize=48,PrimaryColour=&H00FFFFFF,BorderStyle=3,Outline=2,Alignment=2,MarginV=30'" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart "成片_字幕版.mp4"
```

**方式二：经 ASS 烧录（样式更精细）**

```bash
python scripts/srt_to_ass.py \
  --cues cues.json --out video.ass \
  --fontsize 48 --style box --font "Microsoft YaHei" --res 1920x1080

ffmpeg -y -i video.mp4 -vf "ass=video.ass" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart "成片_字幕版.mp4"
```

**烧录前先抽帧确认样式：**

```bash
ffmpeg -i video.mp4 -vf "ass=video.ass" -ss 10 -frames:v 1 -y sample.png
```

---

## 批量处理

处理整个目录下的所有视频：

```bash
# 基本用法
python tools/batch_subtitle.py --input D:/videos --lang zh

# 只生成 SRT，不烧录
python tools/batch_subtitle.py --input D:/videos --lang zh --srt-only

# 烧录完自动复制到上传目录
python tools/batch_subtitle.py --input D:/videos --lang zh --upload D:/upload_ready

# 带纠错规则
python tools/batch_subtitle.py --input D:/videos --lang zh --corrections corrections.txt

# 递归处理子目录
python tools/batch_subtitle.py --input D:/videos --lang zh --recursive
```

批量处理完成后在 `subtitle_work/` 目录下生成 `batch_report.json` 汇总结果。

---

## 自动上传目录

`--upload D:/upload_ready` 参数会在每个视频烧录完成后自动把成片复制到指定目录，方便统一管理待上传文件。

目录结构示例：
```
D:/upload_ready/
  ├── vlog_01_字幕版.mp4
  ├── vlog_02_字幕版.mp4
  └── ...
```

如需直接上传到 B站，可配合 biliup 等工具在上传目录上挂一个 watcher，实现全自动流水线。

---

## 配置文件

修改 `config.json` 可持久化工具路径和默认参数，避免每次命令行传参：

```json
{
  "whisper_cli": "D:/srtskills/whisper/Release/whisper-cli.exe",
  "model": "D:/srtskills/ggml-large-v3-turbo.bin",
  "ffmpeg": "",
  "threads": 4,
  "fontsize": 48,
  "style": "box",
  "font": "Microsoft YaHei"
}
```

---

## 常见问题（Windows 特有）

| 问题 | 原因 | 解决 |
|------|------|------|
| 路径被截断/模型找不到 | 路径含中文字符 | 把所有文件放到纯英文路径下 |
| `subtitles` filter 报错 | ffmpeg 不支持 libass | 下载完整版 ffmpeg（BtbN 编译版）|
| 中文字幕显示方块 | 字体未安装或名称错误 | 改用 `Microsoft YaHei` 或 `SimHei` |
| emoji/特殊字符文件名报错 | shell 转义问题 | 先用 ffmpeg 复制重命名再处理 |
| whisper 识别出英文幻觉 | 开场/结尾有纯音乐段 | 加 `--vad` 参数 |

---

## 脚本一览

| 脚本 | 作用 |
|------|------|
| `scripts/srt_to_cues.py` | SRT → cues.json，可同时应用纠错表 |
| `scripts/cues_to_srt.py` | cues.json → SRT |
| `scripts/srt_to_ass.py` | cues.json → ASS（单语，精细样式控制）|
| `scripts/bi_ass.py` | 双语 cues → ASS（中文在上大，外文在下小）|
| `scripts/split_bi_cues.py` | 双语长句拆行（中英都顾）|
| `scripts/make_review_html.py` | 交互式核对页（文字+时间轴可改，导出 SRT）|
| `tools/batch_subtitle.py` | **批量处理主脚本**（Windows 适配，支持自动复制到上传目录）|

---

## 泛化到不同视频

- 用户只需提供视频（加可选样式偏好）
- `--res` 和时长由 ffprobe 自动探测
- `corrections.txt` 由 Claude 通读该视频转写后自动生成
- 模型和 whisper-cli 装一次后所有视频复用
- 语言非中文时改 `-l <code>`，字体换 `Arial` 或对应语言字体
