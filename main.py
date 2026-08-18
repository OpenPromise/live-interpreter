"""live-interpreter：YouTube/Twitch 直播同声传译（云端语音转语音）。

翻译引擎：阿里云百炼 Qwen3.5-LiveTranslate（gpt-realtime-translate 的国产替代）。

用法示例：
  python main.py "https://www.youtube.com/watch?v=..." --lang zh
  python main.py "https://www.twitch.tv/xxx" --lang en --voice Serena
  python main.py "local_test.wav" --mock        # 无 Key 验证采集链路
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Callable

from dotenv import load_dotenv

import capture
from overlay import OverlayServer
import qwen_translate
from captions import CaptionPrinter
from playback import AudioPlayer, list_devices
from stats import LatencyStats

INPUT_SAMPLE_RATE = 16000  # 百炼实时翻译模型输入为 16kHz 单声道 PCM


def _setup_stdio() -> None:
    """Windows 控制台默认 GBK，字幕/设备名可能含特殊字符，统一用 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="live-interpreter",
        description="YouTube/Twitch 直播云端同声传译（语音转语音，基于阿里云 Qwen）",
    )
    p.add_argument("source", help="直播/视频 URL，或本地音频文件路径")
    p.add_argument(
        "--lang",
        default=None,
        choices=sorted(qwen_translate.SUPPORTED_LANGUAGES),
        help="目标输出语言（默认取 .env 的 OUTPUT_LANGUAGE，否则 zh）",
    )
    p.add_argument(
        "--voice",
        default=None,
        help=f"输出音色（官方列表，如 Serena/Ethan/Cherry；共 {len(qwen_translate.VOICES)} 个）",
    )
    p.add_argument(
        "--voice-clone",
        choices=["never", "once", "always"],
        default=None,
        help="声音复刻频率：never=用预设音色 / once=服务端复刻一次 / always=每次复刻",
    )
    p.add_argument(
        "--hotwords",
        default=None,
        help='热词表 JSON，如 \'{"NVIDIA":"英伟达"}\'（源语言词 -> 目标语言词）',
    )
    p.add_argument("--source-lang", default=None, help="源语言提示（默认自动识别）")
    p.add_argument(
        "--vad-silence-ms",
        type=int,
        default=None,
        help="VAD 静音判定阈值（毫秒，默认服务端 1000；快语速主播可调小到 300~500）",
    )
    p.add_argument("--workspace-id", default=None, help="百炼业务空间 ID（也可放 .env）")
    p.add_argument(
        "--region",
        choices=["cn-beijing", "ap-southeast-1"],
        default=None,
        help="百炼地域（默认 cn-beijing）",
    )
    p.add_argument("--model", default=None, help="百炼模型名（默认官方推荐模型）")
    p.add_argument("--ws-url", default=None, help="覆盖 WebSocket 地址（调试/网关用）")
    p.add_argument("--list-devices", action="store_true", help="列出音频输出设备")
    p.add_argument("--no-play", action="store_true", help="只出字幕，不播放译文")
    p.add_argument("--save-out", help="把译文音频保存为 WAV 文件")
    p.add_argument("--volume", type=float, default=1.0, help="译文音量（0~2）")
    p.add_argument("--device", type=int, default=None, help="音频输出设备索引")
    p.add_argument("--proxy", default=None, help="抓流代理，如 http://127.0.0.1:7890")
    p.add_argument("--chunk-ms", type=int, default=200, help="音频块大小（毫秒）")
    p.add_argument("--max-seconds", type=float, default=None, help="最多采集多少秒后停止（测试用）")
    p.add_argument("--mock", action="store_true", help="无 API Key 模式：只验证采集链路")
    p.add_argument("--overlay", action="store_true", help="启动 OBS 字幕浮层服务（浏览器源用）")
    p.add_argument("--overlay-port", type=int, default=8765, help="字幕浮层端口（默认 8765）")
    p.add_argument(
        "--obs-video",
        action="store_true",
        help="解析直播间视频流并提供 OBS 浏览器源播放原画面（无需 API Key）",
    )
    p.add_argument("--stats", action="store_true", help="统计每段翻译延迟（p50/p95）")
    p.add_argument(
        "--show-preview",
        action="store_true",
        help="终端实时预览译文（默认只显示完成的整句，避免刷屏）",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    return p


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def parse_hotwords(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit('--hotwords 需要 JSON 字典，如 \'{"NVIDIA":"英伟达"}\'')
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise SystemExit("--hotwords 需要是字符串到字符串的 JSON 字典")
    return value


async def run_mock(
    source: str, chunk_ms: int, proxy: str | None, max_seconds: float | None
) -> None:
    """无 Key 时验证：采集 -> 逐块报告音量电平。"""
    chunk_bytes = int(INPUT_SAMPLE_RATE * 2 * chunk_ms / 1000)
    count = 0
    total_bytes = 0
    last_sec = -1
    async for chunk in capture.iter_pcm16(
        source, chunk_bytes=chunk_bytes, proxy=proxy, max_seconds=max_seconds
    ):
        level = await capture.rms_level(chunk)
        count += 1
        total_bytes += len(chunk)
        sec = int(total_bytes // (INPUT_SAMPLE_RATE * 2))
        if sec != last_sec:
            last_sec = sec
            print(f"已采集 {total_bytes / (INPUT_SAMPLE_RATE * 2):.1f}s 音频，当前电平 RMS={level:.3f}")
    print(f"采集结束，共 {count} 块（{total_bytes / (INPUT_SAMPLE_RATE * 2):.1f} 秒音频）")


async def run_pipeline(
    source: str,
    *,
    api_key: str,
    workspace_id: str | None,
    region: str,
    model: str,
    ws_url: str | None,
    lang: str,
    voice: str | None,
    voice_clone: str,
    hotwords: dict[str, str] | None,
    source_lang: str | None,
    vad_silence_ms: int | None,
    stats: LatencyStats | None,
    chunk_ms: int,
    max_seconds: float | None,
    proxy: str | None,
    player: AudioPlayer | None,
    show_source: bool,
    preview: bool,
    broadcast: Callable[[dict], None] | None,
) -> None:
    chunk_bytes = int(INPUT_SAMPLE_RATE * 2 * chunk_ms / 1000)
    captions = CaptionPrinter(
        show_source=show_source, preview=preview, broadcast=broadcast
    )

    def make_translator() -> qwen_translate.QwenTranslator:
        def audio_cb(data: bytes) -> None:
            if stats is not None:
                stats.audio_delta()
            if player is not None:
                player.write(data)

        return qwen_translate.QwenTranslator(
            api_key=api_key,
            workspace_id=workspace_id,
            region=region,
            model=model,
            ws_url=ws_url,
            output_language=lang,
            voice=voice,
            voice_clone=voice_clone,
            hotwords=hotwords,
            source_language=source_lang,
            vad_silence_ms=vad_silence_ms,
            on_output_audio=audio_cb if (player is not None or stats is not None) else None,
            on_output_text=captions.on_output_text,
            on_output_text_done=captions.on_output_text_done,
            on_input_text_done=captions.on_input_text_done,
            on_speech_started=stats.speech_started if stats else None,
            on_speech_stopped=stats.speech_stopped if stats else None,
            on_response_done=stats.response_done if stats else None,
        )

    backoff = 1.0
    if player is not None:
        player.start()  # 播放器在整个运行期间只启动一次，断线重连不重启线程
    try:
        while True:
            translator = make_translator()
            try:
                await translator.connect()

                async def send_loop() -> None:
                    async for chunk in capture.iter_pcm16(
                        source,
                        chunk_bytes=chunk_bytes,
                        proxy=proxy,
                        max_seconds=max_seconds,
                    ):
                        await translator.send_audio(chunk)

                sender = asyncio.create_task(send_loop())
                receiver = asyncio.create_task(translator.receive_loop())
                done, pending = await asyncio.wait(
                    {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
                )

                failed = [t for t in done if t.exception() is not None]
                if failed:
                    for task in pending:
                        task.cancel()
                    raise failed[0].exception()

                # 正常结束（音频源读完）：先让服务端收尾，再取消接收任务
                await translator.close()
                for task in pending:
                    task.cancel()

                print("\n音频源结束，翻译会话关闭。")
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger = logging.getLogger("main")
                logger.error("会话中断（%s），%s 秒后重连...", exc, backoff)
                try:
                    await translator.close()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
    finally:
        if player is not None:
            player.close()


async def amain(args: argparse.Namespace) -> int:
    load_dotenv()
    setup_logging(args.verbose)

    if args.list_devices:
        list_devices()
        return 0

    if not capture.is_local_file(args.source) and not args.source.startswith(
        ("http://", "https://")
    ):
        print(f"不是本地文件也不是 URL: {args.source}")
        return 2

    overlay: OverlayServer | None = None
    if args.overlay or args.obs_video:
        overlay = OverlayServer(
            port=args.overlay_port,
            video_source=args.source if args.obs_video else None,
            video_proxy=args.proxy,
        )
        try:
            await overlay.start()
        except OSError as exc:
            logging.getLogger("main").warning("本地服务启动失败（端口被占用？）: %s", exc)
            overlay = None
        if args.obs_video and overlay is not None:
            try:
                video_url = await overlay.get_video_url()
                print("直播间视频流已解析：", flush=True)
                print(f"  视频直链: {video_url}", flush=True)
                try:
                    import subprocess

                    proc = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE)
                    proc.communicate(video_url.encode("utf-16-le"))
                    print("  已自动复制到剪贴板，可直接粘贴到 OBS", flush=True)
                except Exception:
                    print("  （未能自动复制，请手动复制上面的地址）", flush=True)
                print(flush=True)
                print("OBS 中添加源（按推荐顺序）：", flush=True)
                print("  1) 来源 → 添加 → VLC 视频源：粘贴直链（HLS 直播最稳，需装 VLC）", flush=True)
                print("  2) 来源 → 添加 → 媒体源：粘贴直链（部分 HLS 直播可能不稳）", flush=True)
                print(
                    f"  3) 来源 → 添加 → 浏览器：URL 填 http://127.0.0.1:{args.overlay_port}/video"
                    "（官方嵌入播放，最省事）",
                    flush=True,
                )
                print(flush=True)
                print(
                    f"本地服务保持运行（浏览器源备用）：http://127.0.0.1:{args.overlay_port}/video",
                    flush=True,
                )
            except Exception as exc:
                print(f"视频流解析失败: {exc}", flush=True)

    if args.mock:
        try:
            await run_mock(args.source, args.chunk_ms, args.proxy, args.max_seconds)
        finally:
            if overlay is not None:
                await overlay.stop()
        return 0

    if args.obs_video and not args.overlay:
        # 只提供直播间视频源，不翻译（无需 API Key）
        print("按 Ctrl+C 退出")
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            if overlay is not None:
                await overlay.stop()
        return 0

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("缺少 DASHSCOPE_API_KEY：请复制 .env.example 为 .env 并填入百炼 API Key，")
        print("或先用 --mock 模式验证采集链路。")
        return 2

    lang = args.lang or os.getenv("OUTPUT_LANGUAGE", "zh")
    if lang not in qwen_translate.SUPPORTED_LANGUAGES:
        print(f"不支持的目标语言: {lang}，语音输出可选: {sorted(qwen_translate.SUPPORTED_LANGUAGES)}")
        return 2

    workspace_id = args.workspace_id or os.getenv("QWEN_WORKSPACE_ID")
    ws_url = args.ws_url or os.getenv("QWEN_WS_URL")
    if not ws_url and not workspace_id:
        print("缺少百炼业务空间 ID（QWEN_WORKSPACE_ID），或直接配置 QWEN_WS_URL。")
        return 2

    voice = args.voice or os.getenv("QWEN_VOICE")
    if voice and voice not in qwen_translate.VOICES:
        logging.getLogger("main").warning(
            "音色 %s 不在官方列表（%s），服务端可能拒绝",
            voice,
            ", ".join(qwen_translate.VOICES),
        )
    voice_clone = args.voice_clone or os.getenv("QWEN_VOICE_CLONE", "never")
    hotwords = parse_hotwords(args.hotwords or os.getenv("QWEN_HOTWORDS"))
    source_lang = args.source_lang or os.getenv("QWEN_SOURCE_LANGUAGE")
    vad_silence_ms = args.vad_silence_ms
    if vad_silence_ms is None and os.getenv("QWEN_VAD_SILENCE_MS"):
        vad_silence_ms = int(os.getenv("QWEN_VAD_SILENCE_MS"))
    region = args.region or os.getenv("QWEN_REGION", qwen_translate.DEFAULT_REGION)
    model = args.model or os.getenv("QWEN_MODEL", qwen_translate.DEFAULT_MODEL)
    stats = LatencyStats() if args.stats else None

    player: AudioPlayer | None = None
    need_output = (not args.no_play) or bool(args.save_out)
    if need_output:
        try:
            player = AudioPlayer(
                device=args.device,
                volume=args.volume,
                save_path=args.save_out,
                play=not args.no_play,
            )
        except Exception as exc:
            logging.getLogger("main").warning("初始化播放失败，降级为纯字幕模式: %s", exc)
            player = None

    print(f"目标语言: {lang}（{qwen_translate.SUPPORTED_LANGUAGES[lang]}）")
    print(f"音色: {voice or '默认'} | 声音复刻: {voice_clone} | 热词: {bool(hotwords)}")
    print("按 Ctrl+C 退出")
    try:
        await run_pipeline(
            args.source,
            api_key=api_key,
            workspace_id=workspace_id,
            region=region,
            model=model,
            ws_url=ws_url,
            lang=lang,
            voice=voice,
            voice_clone=voice_clone,
            hotwords=hotwords,
            source_lang=source_lang,
            vad_silence_ms=vad_silence_ms,
            stats=stats,
            chunk_ms=args.chunk_ms,
            max_seconds=args.max_seconds,
            proxy=args.proxy,
            player=player,
            show_source=not args.verbose,
            preview=args.show_preview,
            broadcast=overlay.broadcast if overlay is not None else None,
        )
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        if overlay is not None:
            await overlay.stop()
        if stats is not None:
            stats.report()
    return 0


def main() -> None:
    _setup_stdio()
    args = build_parser().parse_args()
    try:
        sys.exit(asyncio.run(amain(args)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
