# live-interpreter

YouTube / Twitch 直播的云端同声传译工具（语音转语音）。

抓取直播音频 → 阿里云百炼 Qwen3.5-LiveTranslate 实时翻译 → 播放译文语音，同时支持终端字幕、OBS 字幕浮层和直播间画面源接入。

## 特性

- 语音转语音实时同传：流式 WebSocket，官方宣称约 2.8 秒同传延迟，实测首字延迟约 0.5 秒
- 支持 YouTube / Twitch 直播、直连 HLS（`.m3u8`）、本地音频文件
- 60 种语言识别，29 种支持语音输出（含中/英/日/韩/西/葡/德/法/俄/阿等）
- 53 个官方音色、服务端声音复刻、热词表、源语言提示、VAD 阈值可调
- OBS 集成：字幕浮层（浏览器源）、直播间画面源（`--obs-video`）、译文音频混流（虚拟声卡）
- 延迟统计（`--stats`）、无 Key 采集自检（`--mock`）、连通性检查（`tools/check_connection.py`）

## 快速开始

1. 安装 Python 3.10+、[ffmpeg](https://ffmpeg.org/)、yt-dlp（`pip install yt-dlp`）
2. 安装依赖：`pip install -r requirements.txt`
3. 复制 `.env.example` 为 `.env`，填入 `DASHSCOPE_API_KEY` 和 `QWEN_WORKSPACE_ID`（百炼控制台获取）
4. 运行：

```powershell
python main.py "https://www.youtube.com/watch?v=<直播ID>" --lang zh
```

翻译完成后按 `Ctrl+C` 退出。

## 常用命令

| 场景 | 命令 |
|---|---|
| 翻译直播为中文 | `python main.py "<直播URL>" --lang zh` |
| 指定音色 | `python main.py "<URL>" --voice Serena` |
| 服务端声音复刻 | `python main.py "<URL>" --voice-clone once` |
| 热词表 | `python main.py "<URL>" --hotwords '{"NVIDIA":"英伟达"}'` |
| 快语速主播断句 | `python main.py "<URL>" --vad-silence-ms 400` |
| 延迟统计 | `python main.py "<URL>" --stats` |
| OBS 字幕浮层 | `python main.py "<URL>" --overlay` |
| OBS 直播间画面源 | `python main.py "<URL>" --obs-video` |
| 画面+字幕+翻译一起 | `python main.py "<URL>" --overlay --obs-video` |
| 无 Key 验证采集 | `python main.py "<URL>" --mock --max-seconds 10` |

## 文档

| 文档 | 内容 |
|---|---|
| [docs/README.md](docs/README.md) | 文档索引 |
| [docs/guide.md](docs/guide.md) | 安装配置、命令行参数、测试方法 |
| [docs/deployment.md](docs/deployment.md) | 部署指南（环境、百炼开通、运行、成本） |
| [docs/obs.md](docs/obs.md) | OBS 集成（画面 / 字幕 / 音频） |
| [docs/architecture.md](docs/architecture.md) | 架构与协议详解 |
| [docs/development.md](docs/development.md) | 开发指南与扩展点 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 常见问题排查 |

English: [README.en.md](README.en.md)

## 目录结构

```
live-interpreter/
├── main.py                 # 命令行入口
├── capture.py              # yt-dlp + ffmpeg 音频采集
├── qwen_translate.py       # 百炼 Qwen3.5-LiveTranslate WebSocket 客户端
├── overlay.py              # OBS 字幕浮层 / 画面源本地服务
├── overlay.html            # 字幕浮层页面
├── video.html              # 直播间画面播放页
├── hls.min.js              # 本地 hls.js（HLS 播放兜底）
├── playback.py             # 译文播放（sounddevice）+ WAV 保存
├── captions.py             # 终端字幕
├── stats.py                # 延迟统计
├── tools/check_connection.py  # 连通性检查
├── .env.example            # 配置模板
└── docs/                   # 文档
```

## 注意

- `.env` 含 API Key，已被 `.gitignore` 忽略，不会提交
- 国内网络访问 YouTube/Twitch 需要代理：`--proxy http://127.0.0.1:7890`（百炼 API 本身国内直连）
- 计费：百炼按 token 计费（音频输入约 40 元/百万、音频输出约 160 元/百万，以控制台为准），新用户有免费额度

## 安全

见 [SECURITY.md](SECURITY.md)：API Key 只存 `.env`，不要提交或公开；本地服务默认只绑定 127.0.0.1。

## 贡献

欢迎提交 Issue 与 Pull Request。开发流程与扩展点见 [docs/development.md](docs/development.md)。

## License

[MIT](LICENSE)
