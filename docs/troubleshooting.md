# 常见问题排查

## 连接失败：Workspace endpoint is invalid

业务空间专属域名（`{WorkspaceId}.cn-beijing.maas.aliyuncs.com`）可能对部分账号/空间不可用。程序检测到 `IllegalEndpoint` 会自动回退公共域名 `wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=...`，无需手动处理。

## 会话中断：Response stream timeout

服务端约 60 秒无响应流时会主动断开会话，属正常机制（直播长时间静音/音乐时可能出现）。程序会自动重连（指数退避，最多 30 秒），播放器线程只启动一次，重连不中断。

## 日志末尾：ffmpeg 退出码 255

按 `Ctrl+C` 时终端中断信号会同时传给 ffmpeg，255 是正常中断退出码，已静音该日志，可忽略。

## 终端中文乱码

Windows 控制台默认 GBK 编码，程序已自动切换 UTF-8 输出。若在其它工具（如重定向到文件）里仍乱码，可设置环境变量 `PYTHONIOENCODING=utf-8`。

## 端口被占用

默认端口 8765 被占用时，用 `--overlay-port <其它端口>` 换一个，浮层地址同步变化。

## 直播间视频直链在 OBS 里不播放

- 直链约 6 小时过期：重新运行 `--obs-video`
- 媒体源对 HLS 直播支持不稳：改用 VLC 视频源或浏览器源 `http://127.0.0.1:8765/video`
- YouTube/Twitch 的 CDN 会拦截非浏览器客户端，本地播放页对这两家自动改用官方嵌入播放器

## 终端原文/译文对不上

原文是 ASR 整句识别完成后打印，译文是流式输出的，快语速时两者在屏幕上会错位，属于显示时序问题，不是翻译错误。OBS 浮层只显示完成的整句，不受影响。

## 缺 Key / 业务空间 ID

复制 `.env.example` 为 `.env` 并填写；也可用 `--mock` 先验证采集链路，用 `tools/check_connection.py` 验证连接。

## Twitch 频道未开播

`The channel is not currently live` 表示频道当前未直播，开播后同一命令即可。

## 翻译质量差 / 断句不准

- 快语速主播：`--vad-silence-ms 300~500` 让断句更及时
- 专有名词：`--hotwords '{"原文词":"译文词"}'`
- 极短句（语气词、单个词）翻译价值低，属正常现象
