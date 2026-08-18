# 开发指南

## 1. 环境准备

```powershell
cd live-interpreter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # 填入百炼 Key 与业务空间 ID
```

## 2. 代码结构

```
main.py                 CLI 入口：参数解析、配置加载、会话编排
capture.py              采集层：yt-dlp 解析 + ffmpeg 转码
qwen_translate.py       翻译层：Qwen WebSocket 协议实现
playback.py             输出层：声卡播放 + WAV
captions.py             终端字幕 + 事件回调
overlay.py              服务层：字幕浮层 / 画面源 / 媒体代理
stats.py                延迟统计
tools/check_connection.py  连通性诊断
```

模块之间通过**回调**解耦：`run_pipeline` 把 `on_output_audio`、`on_output_text` 等回调注入 `QwenTranslator`，翻译事件从服务端到输出层的路径完全由主流程控制。

## 3. 快速上手

```powershell
# 无 Key 验证采集链路（推荐先跑这个）
python main.py "任意.wav" --mock

# 连通性检查
python tools\check_connection.py

# 本地文件翻译 + 统计 + 落盘（不依赖直播平台缓冲，便于对照测试）
python main.py "测试音频.wav" --lang zh --no-play --save-out out.wav --stats

# 真实直播
python main.py "https://www.youtube.com/watch?v=<直播ID>" --lang zh --stats
```

## 4. 核心流程走读

### main.py

1. `amain()`：加载 `.env` → 校验参数 → 启动浮层服务（`--overlay/--obs-video`）→ 校验 Key/语言/业务空间 → 初始化播放器 → 进入 `run_pipeline`
2. `run_pipeline()`：播放器只启动一次；循环内每次尝试「连接翻译会话 → 同时跑发送/接收两个任务 → 等任一方结束」
3. 异常时按指数退避重连；音频源读完时发送 `session.finish` 优雅收尾

### qwen_translate.py

- `connect()`：建立 WebSocket，发送 `session.update`（模态、语言、音色、热词、声音复刻、VAD）
- `send_audio()`：把 16kHz PCM 分块 base64 后通过 `input_audio_buffer.append` 推送
- `receive_loop()`：事件分发——音频进播放器、译文文本进字幕、VAD/完成事件进统计
- `close()`：发送 `session.finish`，等待 `session.finished` 后关闭

### overlay.py

- `broadcast()` 把字幕事件推给所有 WebSocket 客户端（异步安全）
- `/video` 页面通过 `/api/video_info` 获取播放方案：YouTube/Twitch 官方嵌入，其它平台 hls.js
- `/media` 是 HLS 代理：清单做同源改写、分片流式转发（供非官方平台兜底）

## 5. 扩展点

### 目标语言 / 音色

修改 `qwen_translate.SUPPORTED_LANGUAGES`（须服务端支持语音输出）与 `VOICES`（官方音色列表）。运行 `python main.py --help` 即可看到新的可选值。

### 热词 / 声音复刻 / VAD

已通过 CLI 与 `.env` 暴露，无需改代码：`--hotwords`、`--voice-clone`、`--vad-silence-ms`。

### 自定义 TTS 管线（ASR + LLM + TTS）

如果想用自有/开源 TTS（如 CosyVoice）替代模型固定音色，替换 `qwen_translate.py` 即可：

- 复用 `capture.py` 采集
- 新翻译器实现 `connect / send_audio / receive_loop / close` 四个接口
- 输出事件对齐：`on_output_audio(bytes)`、`on_output_text_done(str)`、`on_input_text_done(str)`
- `main.py` 的 `make_translator()` 换成新类，其余（播放、字幕、浮层、统计）不动

### 视觉增强（画面输入）

官方协议已支持 `input_image_buffer.append`（base64 图片帧）。实现思路：

1. `capture.py` 增加视频帧采集（ffmpeg 第二个输出流，按 1~2 秒取帧）
2. `QwenTranslator` 增加 `send_image(frame)`，复用 `input_image_buffer.append`
3. 在 `send_loop` 中与音频并行推送画面帧

### 多语言同时输出

官方约定一个会话一个目标语言。按 `translation sessions ≈ 活跃源语言 × 目标语言数` 开多个 `QwenTranslator` 实例，各自把音频分块发送，字幕/浮层按语言通道区分。

### 字幕样式

浮层样式在 `overlay.html`，支持 URL 参数：`size`、`show_source`、`position`、`ttl`。OBS 里也可用「自定义 CSS」覆盖。

## 6. 测试

| 层级 | 手段 |
|---|---|
| 采集链路 | `--mock`（无 Key，看 RMS 电平） |
| 连接 | `tools/check_connection.py` |
| 延迟 | `--stats`（首字/结束/整句 p50/p95） |
| 质量 | 本地文件 + 官方字幕/DeepL 对照，`--save-out` 落盘反复听 |
| 长期稳定性 | 真实直播挂 1~2 小时，观察重连次数（`-v` 日志） |

改动后先跑：`python -m py_compile main.py capture.py qwen_translate.py overlay.py playback.py captions.py stats.py`。

## 7. 代码规范

- Python 3.10+，全量类型注解
- 异步为主（asyncio），阻塞调用放到 `asyncio.to_thread`
- 日志用 `logging`（模块级 logger），面向用户的输出用 `print(..., flush=True)`
- Windows 控制台输出统一 UTF-8（`_setup_stdio`）
- 提交信息使用 Conventional Commits：`feat:` / `fix:` / `docs:` / `refactor:` / `chore:`

## 8. 贡献流程

1. Fork 仓库，创建特性分支
2. 开发 + 本地验证（至少跑通 `--mock` 与一次真实翻译）
3. 提交并推送，创建 Pull Request
4. 说明改动内容与测试结果

注意：**不要把 `.env` 提交**（已 gitignore）；新依赖请同步更新 `requirements.txt`。
