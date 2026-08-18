"""阿里云百炼 Qwen3.5-LiveTranslate 实时语音翻译客户端。

官方文档：https://help.aliyun.com/zh/model-studio/qwen3-5-livetranslate-flash-realtime
协议要点：
  - WebSocket + JSON，Bearer Token 鉴权
  - 输入 16kHz 单声道 PCM（base64），输出 24kHz 单声道 PCM
  - session.update 配置目标语种/音色/热词/声音复刻/原文识别
  - 音频增量事件：response.audio.delta；文本增量：response.audio_transcript.text
  - 结束会话前必须发送 session.finish，等待 session.finished
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Callable

import websockets

logger = logging.getLogger("qwen_translate")

# 官方文档：qwen3.5-livetranslate-flash-realtime 支持 60 种语种互译，
# 其中 29 种支持「音频+文本」输出（其余 31 种仅文本）。这里列出语音输出语种。
SUPPORTED_LANGUAGES = {
    "zh": "中文",
    "en": "英语",
    "ar": "阿拉伯语",
    "de": "德语",
    "fr": "法语",
    "es": "西班牙语",
    "pt": "葡萄牙语",
    "id": "印度尼西亚语",
    "it": "意大利语",
    "ko": "韩语",
    "ru": "俄语",
    "th": "泰语",
    "vi": "越南语",
    "ja": "日语",
    "tr": "土耳其语",
    "hi": "印地语",
    "ms": "马来语",
    "nl": "荷兰语",
    "ur": "乌尔都语",
    "nb": "挪威语",
    "sv": "瑞典语",
    "da": "丹麦语",
    "he": "希伯来语",
    "fi": "芬兰语",
    "pl": "波兰语",
    "is": "冰岛语",
    "cs": "捷克语",
    "fil": "菲律宾语",
    "fa": "波斯语",
}

# 官方音色列表（https://help.aliyun.com/zh/model-studio/omni-voice-list）
VOICES = [
    "Aiden", "Alek", "Andre", "Angel", "Arda", "Bea", "Bodega", "Chelsie",
    "Cherry", "Chloe", "Cindy", "Dolce", "Dylan", "Emilien", "Eric", "Ethan",
    "Evan", "Gold", "Griet", "Hana", "Harvey", "Ingrid", "Jada", "Jakub",
    "Jennifer", "Joyner", "Katerina", "Kiki", "Lenn", "Li", "Maia", "Marcus",
    "Marina", "Mia", "Mione", "Momo", "Nofish", "Peter", "Qiao", "Raymond",
    "Rizky", "Rocky", "Roya", "Ryan", "Serena", "Sigga", "Siiri", "Sohee",
    "Sonrisa", "Sunny", "Sunnybobi", "Tina", "Wil",
]

DEFAULT_MODEL = "qwen3.5-livetranslate-flash-realtime"
DEFAULT_REGION = "cn-beijing"
SOURCE_ASR_MODEL = "qwen3-asr-flash-realtime"  # 源语言原文识别
LEGACY_WS_TEMPLATE = (
    "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={model}"
)


class QwenTranslator:
    """Qwen3.5-LiveTranslate 的 WebSocket 客户端。"""

    def __init__(
        self,
        *,
        api_key: str,
        workspace_id: str | None = None,
        region: str = DEFAULT_REGION,
        model: str = DEFAULT_MODEL,
        ws_url: str | None = None,
        output_language: str = "zh",
        voice: str | None = None,
        voice_clone: str = "never",
        hotwords: dict[str, str] | None = None,
        source_language: str | None = None,
        vad_silence_ms: int | None = None,
        enable_source_transcript: bool = True,
        on_output_audio: Callable[[bytes], None] | None = None,
        on_output_text: Callable[[str], None] | None = None,
        on_output_text_done: Callable[[str], None] | None = None,
        on_input_text_done: Callable[[str], None] | None = None,
        on_speech_started: Callable[[], None] | None = None,
        on_speech_stopped: Callable[[], None] | None = None,
        on_response_done: Callable[[], None] | None = None,
    ):
        if output_language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"不支持的目标语言: {output_language}（语音输出可选: {sorted(SUPPORTED_LANGUAGES)}）"
            )
        if voice_clone not in ("never", "once", "always"):
            raise ValueError("voice_clone 只能是 never / once / always")
        if voice and voice not in VOICES:
            logger.warning(
                "音色 %s 不在官方列表 %s 中，服务端可能拒绝",
                voice,
                ", ".join(VOICES),
            )

        if ws_url:
            self._ws_url = ws_url
        elif not workspace_id:
            raise ValueError("需要 workspace_id（QWEN_WORKSPACE_ID）或 ws_url（QWEN_WS_URL）")
        else:
            self._ws_url = (
                f"wss://{workspace_id}.{region}.maas.aliyuncs.com"
                f"/api-ws/v1/realtime?model={model}"
            )

        self._api_key = api_key
        self._output_language = output_language
        self._voice = voice
        self._voice_clone = voice_clone
        self._hotwords = hotwords
        self._source_language = source_language
        self._vad_silence_ms = vad_silence_ms
        self._enable_source_transcript = enable_source_transcript
        self._on_output_audio = on_output_audio
        self._on_output_text = on_output_text
        self._on_output_text_done = on_output_text_done
        self._on_input_text_done = on_input_text_done
        self._on_speech_started = on_speech_started
        self._on_speech_stopped = on_speech_stopped
        self._on_response_done = on_response_done
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._session_finished = asyncio.Event()
        self._event_seq = 0

    def _event(self, etype: str, **extra) -> dict:
        self._event_seq += 1
        return {"event_id": f"event_{self._event_seq}", "type": etype, **extra}

    async def connect(self) -> None:
        logger.info("连接翻译会话: %s", self._ws_url)
        try:
            self._ws = await websockets.connect(
                self._ws_url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                max_size=16 * 1024 * 1024,
            )
        except websockets.exceptions.InvalidStatus as exc:
            body = (
                bytes(exc.response.body).decode("utf-8", errors="replace")
                if exc.response.body
                else ""
            )
            # 业务空间专属域名不可用时，回退到 dashscope 公共域名
            if "IllegalEndpoint" in body:
                legacy_url = LEGACY_WS_TEMPLATE.format(model=self._ws_url.split("model=", 1)[-1])
                logger.warning(
                    "业务空间端点无效（%s），回退到公共域名: %s",
                    body.strip(),
                    legacy_url,
                )
                self._ws_url = legacy_url
                self._ws = await websockets.connect(
                    legacy_url,
                    additional_headers={"Authorization": f"Bearer {self._api_key}"},
                    max_size=16 * 1024 * 1024,
                )
            else:
                raise

        session: dict = {
            "modalities": ["text", "audio"],
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "translation": {"language": self._output_language},
        }
        if self._hotwords:
            session["translation"]["corpus"] = {"phrases": self._hotwords}
        if self._enable_source_transcript:
            asr_cfg: dict = {"model": SOURCE_ASR_MODEL}
            if self._source_language:
                asr_cfg["language"] = self._source_language
            session["input_audio_transcription"] = asr_cfg
        if self._voice:
            session["voice"] = self._voice
        if self._voice_clone != "never":
            session["enable_voice_clone"] = True
            session["voice_clone_options"] = {"frequency": self._voice_clone}
        if self._vad_silence_ms is not None:
            # 快语速/短停顿内容可调小静音阈值，让句子更快切分
            session["turn_detection"] = {
                "type": "server_vad",
                "threshold": 0.2,
                "silence_duration_ms": self._vad_silence_ms,
            }

        await self._ws.send(json.dumps(self._event("session.update", session=session)))
        logger.info(
            "会话已建立：目标语言=%s(%s) 音色=%s 复刻=%s 热词=%s",
            self._output_language,
            SUPPORTED_LANGUAGES[self._output_language],
            self._voice or "默认",
            self._voice_clone,
            bool(self._hotwords),
        )

    async def send_audio(self, pcm16: bytes) -> None:
        if self._ws is None:
            raise RuntimeError("会话未连接")
        payload = self._event(
            "input_audio_buffer.append",
            audio=base64.b64encode(pcm16).decode("ascii"),
        )
        await self._ws.send(json.dumps(payload))

    async def receive_loop(self) -> None:
        """持续读取服务端事件并分发。"""
        if self._ws is None:
            raise RuntimeError("会话未连接")
        async for raw in self._ws:
            event = json.loads(raw)
            etype = event.get("type", "")

            if etype == "response.audio.delta":
                delta = event.get("delta", "")
                if delta and self._on_output_audio:
                    self._on_output_audio(base64.b64decode(delta))
            elif etype in ("response.audio_transcript.text", "response.text.text"):
                # 增量翻译文本（含已确认文本与待确认的预测文本）
                pending = (event.get("text") or "") + (event.get("stash") or "")
                if pending and self._on_output_text:
                    self._on_output_text(pending)
            elif etype == "response.audio_transcript.done":
                if self._on_output_text_done:
                    self._on_output_text_done(event.get("transcript", ""))
            elif etype == "response.text.done":
                if self._on_output_text_done:
                    self._on_output_text_done(event.get("text", ""))
            elif etype == "conversation.item.input_audio_transcription.completed":
                if self._on_input_text_done:
                    self._on_input_text_done(event.get("transcript", ""))
            elif etype == "conversation.item.input_audio_transcription.failed":
                logger.warning("源语言识别失败: %s", event)
            elif etype == "session.finished":
                logger.info("服务端已确认会话结束")
                self._session_finished.set()
            elif etype == "input_audio_buffer.speech_started":
                logger.debug("VAD: 语音开始")
                if self._on_speech_started:
                    self._on_speech_started()
            elif etype == "input_audio_buffer.speech_stopped":
                logger.debug("VAD: 语音结束")
                if self._on_speech_stopped:
                    self._on_speech_stopped()
            elif etype in ("response.done", "session.created", "session.updated"):
                logger.debug("事件: %s", etype)
                if etype == "response.done" and self._on_response_done:
                    self._on_response_done()
            elif "error" in etype:
                logger.error("服务端错误: %s", event)
            else:
                logger.debug("未处理事件: %s", etype)

    async def close(self) -> None:
        """发送 session.finish 并等待服务端收尾后关闭连接。"""
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(self._event("session.finish")))
            try:
                await asyncio.wait_for(self._session_finished.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("等待 session.finished 超时")
        except Exception:
            pass
        finally:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
