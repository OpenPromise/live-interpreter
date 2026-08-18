"""直播音频采集：yt-dlp 解析直播流地址 -> ffmpeg 转为 16kHz 单声道 PCM16。"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import AsyncIterator

logger = logging.getLogger("capture")


def is_local_file(source: str) -> bool:
    """本地文件直接交给 ffmpeg，远程地址先走 yt-dlp 解析。"""
    return os.path.exists(source)


def looks_like_direct_media(url: str) -> bool:
    """形如 .m3u8/.mpd/音频文件 的直链无需 yt-dlp，直接交给 ffmpeg。"""
    lowered = url.lower()
    return any(
        ext in lowered
        for ext in (".m3u8", ".mpd", ".mp3", ".m4a", ".aac", ".opus", ".wav", ".flac")
    )


def resolve_stream_url(
    url: str, proxy: str | None = None, format_selector: str = "bestaudio/best"
) -> str:
    """用 yt-dlp 提取直播流的直链地址。"""
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "-f", format_selector,  # 直播流可能没有独立音频轨，回退到 best
        "-g", url,
    ]
    if proxy:
        cmd += ["--proxy", proxy]

    logger.info("解析直播流地址: %s", url)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"yt-dlp 解析失败（code={proc.returncode}）:\n{proc.stderr.strip()}"
        )
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("yt-dlp 没有返回任何流地址")
    logger.info("解析成功: %s", lines[-1])
    return lines[-1]


def resolve_video_url(url: str, proxy: str | None = None) -> str:
    """解析直播间的视频流地址（画面+声音），供 OBS/浏览器播放。"""
    return resolve_stream_url(url, proxy=proxy, format_selector="b/best")


def build_ffmpeg_cmd(
    source: str,
    *,
    proxy: str | None = None,
) -> list[str]:
    """ffmpeg 输出 16kHz / 单声道 / s16le 原始 PCM 到 stdout。"""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
    ]
    if source.startswith(("http://", "https://")):
        # 网络流：低延迟 + 自动重连
        cmd += [
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
        ]
    if proxy and source.startswith(("http://", "https://")):
        cmd += ["-http_proxy", proxy]
    cmd += ["-i", source]
    cmd += [
        "-vn", "-sn", "-dn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        "-f", "s16le",
        "pipe:1",
    ]
    return cmd


async def _drain_stderr(stream: asyncio.StreamReader) -> None:
    """持续读 ffmpeg 的 stderr，避免管道写满导致 ffmpeg 卡死。"""
    while True:
        line = await stream.readline()
        if not line:
            break
        msg = line.decode("utf-8", errors="replace").strip()
        if msg:
            logger.debug("ffmpeg: %s", msg)


async def iter_pcm16(
    source: str,
    *,
    chunk_bytes: int = 6400,  # 16kHz * 2字节 * 0.2s
    proxy: str | None = None,
    max_seconds: float | None = None,
) -> AsyncIterator[bytes]:
    """逐块产出 PCM16 音频数据。生成器被关闭时会杀掉 ffmpeg。"""
    source_is_file = is_local_file(source)
    if source_is_file or looks_like_direct_media(source):
        real_source = source
    else:
        try:
            real_source = await asyncio.to_thread(resolve_stream_url, source, proxy)
        except Exception as exc:
            logger.warning("yt-dlp 解析失败，尝试直接把 URL 交给 ffmpeg: %s", exc)
            real_source = source
    cmd = build_ffmpeg_cmd(real_source, proxy=proxy)

    logger.info("启动 ffmpeg 采集: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(_drain_stderr(proc.stderr))
    total_bytes = 0
    max_bytes = int(max_seconds * 32000) if max_seconds else None
    killed = False
    try:
        while True:
            data = await proc.stdout.read(chunk_bytes)
            if not data:
                break
            total_bytes += len(data)
            if max_bytes is not None and total_bytes >= max_bytes:
                yield data
                break
            yield data
    finally:
        if proc.returncode is None:
            killed = True
            proc.kill()
        await proc.wait()
        stderr_task.cancel()
        # 255 是 Windows 下 ffmpeg 收到终端 Ctrl+C 的常见退出码，属正常中断
        if not killed and proc.returncode not in (0, -9, -15, 255):
            logger.warning("ffmpeg 退出码: %s", proc.returncode)


async def rms_level(chunk: bytes) -> float:
    """计算一块 PCM16 的 RMS 电平（0~1），用于 mock 模式验证采集链路。"""
    import numpy as np

    arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr**2)))
