# OBS 集成

一套完整的「同传直播间」在 OBS 里需要三个来源：

| 来源 | 内容 | 获取方式 |
|---|---|---|
| 直播间画面 | 原直播视频 | `--obs-video`（直链或浏览器源） |
| 译文字幕 | 译文浮层 | `--overlay`（浏览器源 `http://127.0.0.1:8765/`） |
| 译文语音 | 译音 | VB-Audio 虚拟声卡（`--device` 指向 CABLE Input） |

## 直播间画面（--obs-video）

```powershell
python main.py "https://www.youtube.com/watch?v=<直播ID>" --obs-video
```

运行后自动完成：

1. 解析直播间视频直链（HLS m3u8）并复制到剪贴板
2. 打印 OBS 添加源步骤
3. 保持本地播放服务运行，`http://127.0.0.1:8765/video` 备用

OBS 添加画面源的三种方式（按推荐顺序）：

1. **VLC 视频源**（HLS 直播最稳，需安装 VLC）：来源 → 添加 → VLC 视频源 → 粘贴直链
2. **媒体源**：来源 → 添加 → 媒体源 → 取消勾选「本地文件」→ 粘贴直链（部分 HLS 直播可能不稳）
3. **浏览器**：来源 → 添加 → 浏览器 → URL 填 `http://127.0.0.1:8765/video`（YouTube/Twitch 自动用官方嵌入播放器，最省事）

直链约 6 小时过期，过期后重新运行一次命令即可。播放页每 60 秒自动刷新流地址。

## 字幕浮层（--overlay）

```powershell
python main.py "<直播URL>" --lang zh --overlay
```

浏览器打开 `http://127.0.0.1:8765/` 可预览；OBS 添加浏览器源指向同一地址，宽高按直播画布设置（如 1920x1080）。

浮层 URL 参数：

| 参数 | 说明 | 示例 |
|---|---|---|
| `size` | 译文字号（默认 52） | `?size=64` |
| `show_source` | 是否显示原文（默认 1） | `?show_source=0` |
| `position` | 字幕位置（默认底部） | `?position=top` |
| `ttl` | 每条字幕停留毫秒（默认 9000） | `?ttl=6000` |

## 译文音频混流（虚拟声卡）

1. 安装 [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)（本机已装）
2. 查看设备索引：`python main.py x --list-devices`，找到 `CABLE Input`
3. 翻译时指定输出设备：`--device <CABLE Input 索引>`
4. OBS 添加「音频输入采集」，设备选 `CABLE Output`，即可把译文混入直播

## 完整场景搭建

```powershell
python main.py "https://www.youtube.com/watch?v=<直播ID>" --lang zh --overlay --obs-video --device 5
```

OBS 中：

1. 添加浏览器源 `/video` → 原画面
2. 添加浏览器源 `/` → 译文字幕
3. 添加音频输入采集 CABLE Output → 译音
4. （可选）画面源右键勾选「通过 OBS 控制音频」获取原声
