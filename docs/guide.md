# 使用指南

## 架构与数据流

```
YouTube/Twitch 直播
        │ yt-dlp 解析流地址
        ▼
      ffmpeg ──► 16kHz 单声道 PCM16（0.2s 一块）
        │
        ▼
百炼 Qwen3.5-LiveTranslate（qwen3.5-livetranslate-flash-realtime）
        │ WebSocket 流式语音进 / 语音出
        ▼
译文 24kHz PCM16 ──► sounddevice 播放 / WAV 保存
译文/原文 ──► 终端字幕 / OBS 浮层（WebSocket 推送）
```

翻译引擎为阿里云百炼官方 [实时语音/音视频翻译-千问](https://help.aliyun.com/zh/model-studio/qwen3-5-livetranslate-flash-realtime)：

- 60 种语言互译，其中 29 种支持音频+文本输出（其余 31 种仅文本）
- 官方宣称约 2.8 秒同传延迟，流式语音进、语音出
- 支持预设音色（53 个）、服务端声音复刻（三种频率）、热词表、源语言原文识别
- 支持视觉增强（画面输入），本项目暂未接入，作为后续路线

## 安装

```powershell
cd live-interpreter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

已实测跑通：本地音频文件、直连 HLS、真实 YouTube 直播（ABC News、VTuber 等）。

## 配置（.env）

| 变量 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` | 必填，百炼 API Key |
| `QWEN_WORKSPACE_ID` | 必填，百炼业务空间 ID（也可用 `QWEN_WS_URL` 代替） |
| `QWEN_REGION` | `cn-beijing`（默认）/ `ap-southeast-1` |
| `QWEN_MODEL` | 模型名，默认官方推荐模型 |
| `OUTPUT_LANGUAGE` | 目标语言（29 种语音输出语种之一，默认 zh） |
| `QWEN_VOICE` | 输出音色（53 个官方音色之一，留空用默认） |
| `QWEN_VOICE_CLONE` | `never`（默认）/ `once` / `always` |
| `QWEN_HOTWORDS` | 热词 JSON（源语言词 -> 目标语言词） |
| `QWEN_SOURCE_LANGUAGE` | 源语言提示，留空自动识别 |
| `QWEN_VAD_SILENCE_MS` | VAD 静音判定阈值（默认 1000，快语速可调小） |
| `QWEN_WS_URL` | 覆盖 WebSocket 地址（业务空间域名失效时自动回退公共域名） |
| `PROXY` | 抓流代理（也可用 `--proxy` 参数） |

## 命令行参数

```text
source                     直播/视频 URL 或本地音频文件
--lang {29 种语言}          目标语言（默认 zh）
--voice VOICE              音色（Serena/Ethan/Cherry/Mia 等 53 个）
--voice-clone {never,once,always}  声音复刻频率
--hotwords JSON            热词表，如 '{"NVIDIA":"英伟达"}'
--source-lang LANG         源语言提示
--vad-silence-ms MS        VAD 静音阈值（300~500 适合快语速）
--workspace-id ID          百炼业务空间 ID
--region {cn-beijing,ap-southeast-1}
--model MODEL              模型名
--ws-url URL               覆盖 WebSocket 地址
--overlay                  启动字幕浮层服务（默认端口 8765）
--overlay-port PORT        浮层端口
--obs-video                解析直播间画面源（无需 API Key）
--list-devices             列出音频输出设备
--device IDX               译文输出设备（如 CABLE Input）
--no-play                  不播放译文（可配合 --save-out 落盘）
--save-out FILE            译文保存为 WAV
--volume 0~2               译文音量
--proxy URL                抓流代理
--chunk-ms MS              音频块大小（默认 200）
--max-seconds N            最多采集 N 秒（测试用）
--stats                    统计每段翻译延迟
--show-preview             终端实时预览译文
--mock                     无 Key 模式，验证采集链路
-v                         调试日志
```

## 测试翻译质量与延迟

### 延迟（量化）

```powershell
python main.py "<直播URL>" --lang zh --stats
```

指标含义：

- **首字延迟**：检测到语音 → 收到第一包译文音频。核心指标，实测约 0.5 秒
- **结束延迟**：语音结束 → 该句译文完成
- **整句延迟**：语音开始 → 译文完成（连续长句时的兜底）

注意：测延迟用**有自然停顿的对话/访谈**；统计不含 YouTube/Twitch 平台自身缓冲（一般还有 2~5 秒）。

### 质量（对照测试）

1. 用带官方字幕的视频或自己录音，跑本地文件：`python main.py "测试.wav" --lang zh --save-out out.wav --stats`
2. 打开原视频字幕，或用 DeepL / Google 翻译同一段文本对照
3. 技术/游戏内容加 `--hotwords` 看术语是否翻对
4. 同一段内容换音色对比听感

### 费用

百炼按 token 计费（华北2约：音频输入 40 元/百万、音频输出 160 元/百万），新用户有免费额度，以[百炼控制台](https://bailian.console.aliyun.com/)为准。
