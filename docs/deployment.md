# 部署指南

## 1. 环境要求

| 依赖 | 说明 |
|---|---|
| Windows 10/11 | 已在 Windows 实测；Linux/macOS 理论可用（sounddevice 需对应音频后端） |
| Python 3.10+ | 开发环境为 3.12 |
| ffmpeg | 需在 PATH 中（音频采集/转码） |
| yt-dlp | `pip install yt-dlp` 或独立安装 |
| VLC（可选） | OBS 画面源推荐用 VLC 视频源播放 HLS |
| VB-Audio Virtual Cable（可选） | OBS 译音混流用 |

检查环境：

```powershell
python --version
ffmpeg -version
yt-dlp --version
```

## 2. 开通阿里云百炼

1. 注册/登录[阿里云百炼控制台](https://bailian.console.aliyun.com/)
2. 开通模型服务：在模型广场搜索 `qwen3.5-livetranslate-flash-realtime`（实时语音/音视频翻译-千问）并开通
3. 创建 API Key：控制台右上角「API-KEY」管理
4. 获取业务空间 ID：控制台首页右上角账户图标 → 查看并复制
5. 新用户通常有免费额度，实际以控制台为准

> 如果业务空间专属域名报 `Workspace endpoint is invalid`，程序会自动回退公共域名，无需处理（见 troubleshooting）。

## 3. 安装

```powershell
cd live-interpreter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

编辑 `.env`，填入：

```ini
DASHSCOPE_API_KEY=sk-xxxx
QWEN_WORKSPACE_ID=你的业务空间ID
OUTPUT_LANGUAGE=zh
```

完整配置项见 [guide.md](guide.md)。

## 4. 快速验证

```powershell
# 1) 连通性检查（确认 Key / 模型可用）
.\.venv\Scripts\python.exe tools\check_connection.py

# 2) 无 Key 验证采集链路（任选本地文件或直播 URL）
.\.venv\Scripts\python.exe main.py "本地音频.wav" --mock

# 3) 真实翻译（本地文件可避免直播平台缓冲干扰）
.\.venv\Scripts\python.exe main.py "测试音频.wav" --lang zh --save-out out.wav --stats
```

## 5. 运行场景

### 单次翻译（听译文）

```powershell
python main.py "https://www.youtube.com/watch?v=<直播ID>" --lang zh
```

### 完整 OBS 同传直播间

```powershell
python main.py "<直播URL>" --lang zh --overlay --obs-video --device <CABLE Input 索引>
```

OBS 里添加：浏览器源 `/video`（画面）、浏览器源 `/`（字幕）、音频输入采集 CABLE Output（译音）。详见 [obs.md](obs.md)。

### 只开画面源（无需 API Key）

```powershell
python main.py "<直播URL>" --obs-video
```

### 长时间运行

程序支持断线自动重连，可长期挂机。想作为后台服务运行时可用 [NSSM](https://nssm.cc/) 注册：

```powershell
nssm install live-interpreter "C:\path\to\live-interpreter\.venv\Scripts\python.exe" "C:\path\to\live-interpreter\main.py <直播URL> --lang zh --overlay"
nssm start live-interpreter
```

## 6. 代理说明

- 国内访问 YouTube/Twitch 抓流需要代理：`--proxy http://127.0.0.1:7890`
- 百炼 API 本身国内直连，**不要**把翻译请求走海外代理
- 也可以在 `.env` 配置 `PROXY` 作为默认抓流代理

## 7. 成本估算

百炼按 token 计费（华北2/北京参考价）：

| 计费项 | 参考价 |
|---|---|
| 音频输入 | 约 40 元/百万 tokens |
| 图片输入 | 约 3.3 元/百万 tokens |
| 文本输出 | 约 100 元/百万 tokens |
| 音频输出 | 约 160 元/百万 tokens |

实际单价以[百炼控制台](https://bailian.console.aliyun.com/)为准。估算方式：跑 10 分钟后在控制台「用量」页查看 token 消耗，换算成每小时成本。

## 8. 常见部署问题

- 端口 8765 被占用：`--overlay-port <其它端口>`
- 视频直链过期（约 6 小时）：重新运行 `--obs-video`
- 播放/翻译异常：见 [troubleshooting.md](troubleshooting.md)
