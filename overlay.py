"""OBS 字幕浮层：本地 HTTP + WebSocket 服务，把译文实时推给浏览器源。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote, urljoin

import aiohttp
from aiohttp import web

import capture

logger = logging.getLogger("overlay")

OVERLAY_HTML = (Path(__file__).with_name("overlay.html")).read_text(
    encoding="utf-8"
)
VIDEO_HTML = (Path(__file__).with_name("video.html")).read_text(encoding="utf-8")
HLS_JS = Path(__file__).with_name("hls.min.js")
VIDEO_URL_CACHE_SECONDS = 120  # 直播流地址会过期，超过此时间重新解析


class OverlayServer:
    """单端口同时提供字幕页面（HTTP）与实时推送（WebSocket）。"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        video_source: str | None = None,
        video_proxy: str | None = None,
    ):
        self.host = host
        self.port = port
        self._video_source = video_source
        self._video_proxy = video_proxy
        self._video_url: str | None = None
        self._video_ts = 0.0
        self._clients: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/", self._handle_overlay)
        app.router.add_get("/favicon.ico", self._handle_favicon)
        app.router.add_get("/video", self._handle_video)
        app.router.add_get("/api/video_url", self._handle_video_url)
        app.router.add_get("/api/video_info", self._handle_video_info)
        app.router.add_get("/media", self._handle_media)
        if HLS_JS.exists():
            app.router.add_get("/hls.min.js", self._handle_hls_js)
        app.router.add_get("/ws", self._handle_ws)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info(
            "字幕浮层已启动：http://%s:%s/ （OBS 浏览器源或普通浏览器打开此地址）",
            self.host,
            self.port,
        )

    async def stop(self) -> None:
        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_overlay(self, request: web.Request) -> web.Response:
        return web.Response(text=OVERLAY_HTML, content_type="text/html", charset="utf-8")

    async def _handle_favicon(self, request: web.Request) -> web.Response:
        return web.Response(status=204)

    async def _handle_video(self, request: web.Request) -> web.Response:
        if self._video_source is None:
            return web.Response(
                text="未启用直播间视频源（运行时加 --obs-video）",
                content_type="text/plain",
                charset="utf-8",
            )
        return web.Response(text=VIDEO_HTML, content_type="text/html", charset="utf-8")

    async def _handle_video_url(self, request: web.Request) -> web.Response:
        if self._video_source is None:
            return web.json_response({"error": "no video source"})
        try:
            url = await self.get_video_url()
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=502)
        return web.json_response({"url": self._proxy_url(url)})

    async def _handle_video_info(self, request: web.Request) -> web.Response:
        """返回播放方案：YouTube/Twitch 用官方嵌入，其余走 HLS 代理。"""
        if self._video_source is None:
            return web.json_response({"error": "no video source"})
        info = self._embed_info(self._video_source)
        if info["kind"] == "hls":
            try:
                info["url"] = self._proxy_url(await self.get_video_url())
            except Exception as exc:
                return web.json_response({"error": str(exc)}, status=502)
        return web.json_response(info)

    @staticmethod
    def _embed_info(source: str) -> dict:
        m = re.search(
            r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{6,})",
            source,
        )
        if m:
            return {
                "kind": "youtube",
                "embed": f"https://www.youtube.com/embed/{m.group(1)}?autoplay=1",
            }
        m = re.search(r"twitch\.tv/([A-Za-z0-9_]{3,})", source)
        if m:
            return {
                "kind": "twitch",
                "embed": (
                    f"https://player.twitch.tv/?channel={m.group(1)}"
                    "&parent=127.0.0.1&autoplay=true"
                ),
            }
        return {"kind": "hls"}

    async def _handle_hls_js(self, request: web.Request) -> web.Response:
        return web.Response(
            text=HLS_JS.read_text(encoding="utf-8"),
            content_type="application/javascript",
            charset="utf-8",
        )

    def _proxy_url(self, url: str) -> str:
        """把远端流地址转成同源代理地址，绕开跨域限制。"""
        return f"/media?url={quote(url, safe='')}"

    async def _handle_media(self, request: web.Request) -> web.StreamResponse | web.Response:
        """代理 HLS 流：清单做同源改写，分片原样转发。"""
        url = request.query.get("url")
        if not url:
            return web.Response(text="missing url", status=400)
        headers = {"User-Agent": "Mozilla/5.0"}
        if "Range" in request.headers:
            headers["Range"] = request.headers["Range"]
        try:
            upstream = await asyncio.to_thread(self._fetch_sync, url, headers)
            content_type = upstream.headers.get(
                "Content-Type", "application/octet-stream"
            )
            if "mpegurl" in content_type:
                # HLS 清单：把分片地址改写为同源代理，支持相对路径
                body = upstream.read().decode("utf-8", errors="replace")
                upstream.close()
                body = self._rewrite_manifest(body, url)
                return web.Response(
                    text=body,
                    content_type=content_type,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Cache-Control": "no-store",
                    },
                )
            # 媒体分片：流式转发（保留 206 Range 语义）
            stream = web.StreamResponse(status=upstream.status)
            stream.headers["Content-Type"] = content_type
            stream.headers["Access-Control-Allow-Origin"] = "*"
            stream.headers["Cache-Control"] = "no-store"
            if upstream.headers.get("Content-Length"):
                stream.content_length = int(upstream.headers["Content-Length"])
            if upstream.headers.get("Content-Range"):
                stream.headers["Content-Range"] = upstream.headers["Content-Range"]
            await stream.prepare(request)
            while True:
                chunk = upstream.read(65536)
                if not chunk:
                    break
                await stream.write(chunk)
            upstream.close()
            await stream.write_eof()
            return stream
        except Exception as exc:
            logger.warning("媒体代理失败: %s", exc)
            return web.Response(text=str(exc), status=502)

    def _fetch_sync(self, url: str, headers: dict) -> object:
        """用标准库抓上游（aiohttp 的请求特征会被部分 CDN 拒绝）。"""
        req = urllib.request.Request(url, headers=headers)
        if self._video_proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler(
                    {
                        "http": self._video_proxy,
                        "https": self._video_proxy,
                    }
                )
            )
            return opener.open(req, timeout=30)
        return urllib.request.urlopen(req, timeout=30)

    def _rewrite_manifest(self, text: str, base_url: str) -> str:
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if "#EXT-X-KEY:" in line:
                lines.append(
                    re.sub(
                        r'URI="([^"]+)"',
                        lambda m: f'URI="{self._proxy_url(urljoin(base_url, m.group(1)))}"',
                        line,
                    )
                )
            elif stripped and not stripped.startswith("#"):
                lines.append(self._proxy_url(urljoin(base_url, stripped)))
            else:
                lines.append(line)
        return "\n".join(lines) + "\n"

    async def get_video_url(self) -> str:
        """解析直播间视频直链（带缓存，地址过期后自动重新解析）。"""
        now = time.monotonic()
        if self._video_url and (now - self._video_ts) < VIDEO_URL_CACHE_SECONDS:
            return self._video_url
        if self._video_source is None:
            raise RuntimeError("未设置直播间地址")
        url = await asyncio.to_thread(
            capture.resolve_video_url, self._video_source, self._video_proxy
        )
        self._video_url = url
        self._video_ts = time.monotonic()
        logger.info("直播间视频流已解析")
        return url

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    # 预留控制指令通道，目前忽略客户端消息
                    pass
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
        finally:
            self._clients.discard(ws)
        return ws

    def broadcast(self, event: dict) -> None:
        """向所有已连接的浮层推送字幕事件。"""
        if not self._clients:
            return
        data = json.dumps(event, ensure_ascii=False)
        for ws in list(self._clients):
            if not ws.closed:
                asyncio.create_task(self._safe_send(ws, data))

    @staticmethod
    async def _safe_send(ws: web.WebSocketResponse, data: str) -> None:
        try:
            await ws.send_str(data)
        except Exception:
            try:
                await ws.close()
            except Exception:
                pass
