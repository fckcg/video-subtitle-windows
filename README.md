# video-subtitle-windows

给任意视频加硬字幕的全流程工具，**Windows 适配版**，基于 [limin112/video-subtitle](https://github.com/limin112/video-subtitle) 扩展。

```
抽音轨 → whisper.cpp 识别 → Claude 纠错 → 生成 SRT → ffmpeg 烧录
```

## 相比原版的改进

- **Windows 路径适配**：解决中文路径截断问题，兼容 Git Bash / CMD / PowerShell
- **批量处理**：一条命令处理整个目录，自动跳过已完成的文件，生成汇总报告
- **自动上传目录**：烧录完成后自动复制成片到指定目录，方便统一管理待上传文件
- **配置文件**：工具路径和默认参数持久化，无需每次传参
- **Windows 字体**：默认使用微软雅黑，中文字幕显示更清晰

## 快速开始

### 1. 安装依赖

**whisper-cli.exe**（语音识别）：
```
https://github.com/ggml-org/whisper.cpp/releases
下载 whisper-bin-x64.zip，解压到 D:\srtskills\whisper\
```

**识别模型**（约 1.6GB，国内镜像）：
```bash
curl -L -C - -o D:/srtskills/ggml-large-v3-turbo.bin \
  https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
```

**ffmpeg**（视频处理）：
```
https://github.com/BtbN/FFmpeg-Builds/releases
下载 ffmpeg-master-latest-win64-gpl.zip，解压后加入 PATH
```

### 2. 克隆本仓库

```bash
git clone https://github.com/fckcg/video-subtitle-windows
cd video-subtitle-windows
```

### 3. 修改配置

编辑 `config.json`，填入你本机的工具路径：

```json
{
  "whisper_cli": "D:/srtskills/whisper/Release/whisper-cli.exe",
  "model": "D:/srtskills/ggml-large-v3-turbo.bin",
  "ffmpeg": "",
  "font": "Microsoft YaHei",
  "fontsize": 48
}
```

### 4. 给单个视频加字幕

```bash
# 第一步：抽音轨
ffmpeg -y -i video.mp4 -ar 16000 -ac 1 -c:a pcm_s16le audio16k.wav

# 第二步：识别
D:/srtskills/whisper/Release/whisper-cli.exe \
  -m D:/srtskills/ggml-large-v3-turbo.bin \
  -f audio16k.wav -l zh -osrt -of video_whisper -t 4

# 第三步：纠错（把 Claude 生成的纠错表保存为 corrections.txt）
python scripts/srt_to_cues.py \
  --srt video_whisper.srt --cues cues.json \
  --corrections-file corrections.txt --out-srt video_final.srt

# 第四步：烧录
python scripts/srt_to_ass.py \
  --cues cues.json --out video.ass --fontsize 48 --font "Microsoft YaHei" --res 1920x1080

ffmpeg -y -i video.mp4 -vf "ass=video.ass" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart 成片_字幕版.mp4
```

### 5. 批量处理整个目录

```bash
# 处理 D:/videos 下所有视频，成片复制到 D:/upload_ready
python tools/batch_subtitle.py \
  --input D:/videos \
  --lang zh \
  --upload D:/upload_ready
```

## 目录结构

```
video-subtitle-windows/
├── SKILL.md                    # Claude Code Skill 说明（核心）
├── README.md                   # 本文件
├── config.json                 # 配置文件（工具路径、默认参数）
├── scripts/
│   ├── srt_to_cues.py          # SRT → cues.json（可应用纠错）
│   ├── cues_to_srt.py          # cues.json → SRT
│   ├── srt_to_ass.py           # cues.json → ASS（单语）
│   ├── bi_ass.py               # 双语 cues → ASS
│   ├── split_bi_cues.py        # 双语长句拆行
│   ├── split_long_cues.py      # 单语长句拆行
│   └── make_review_html.py     # 交互式核对页
├── tools/
│   └── batch_subtitle.py       # 批量处理主脚本（Windows 适配）
└── references/
    ├── burn-in-ffmpeg.md       # ffmpeg 烧录细节
    ├── transcribe-whisper.md   # whisper 识别技巧
    └── bilingual-build-workflow.md  # 双语字幕工作流
```

## 常见问题

**Q: whisper 找不到模型文件？**  
A: 路径不能含中文字符，把 srtskills 目录放在 D:/ 根目录下。

**Q: 中文字幕显示方块？**  
A: config.json 中 font 改成 `Microsoft YaHei`（微软雅黑）。

**Q: ffmpeg 烧录报 subtitles filter 错误？**  
A: 路径中冒号要转义：`D:/path` 写成 `D\:/path`（在 vf 参数内）。

## 致谢

核心脚本来自 [limin112/video-subtitle](https://github.com/limin112/video-subtitle)，感谢原作者的开源工作。
