"""译文音频播放：sounddevice 输出 + 可选 WAV 落盘。"""

from __future__ import annotations

import logging
import queue
import threading
import wave

import numpy as np

logger = logging.getLogger("playback")


def list_devices() -> None:
    import sounddevice as sd

    print(sd.query_devices())


class AudioPlayer:
    """后台线程播放 24kHz 单声道 int16 PCM。"""

    def __init__(
        self,
        *,
        device: int | None = None,
        volume: float = 1.0,
        save_path: str | None = None,
        samplerate: int = 24000,
        play: bool = True,
    ):
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=400)
        self._device = device
        self._volume = float(volume)
        self._save_path = save_path
        self._samplerate = samplerate
        self._play = play
        self._wav = None
        self._dropped = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        if self._wav is None and self._save_path:
            self._wav = wave.open(self._save_path, "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(self._samplerate)
        if not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            if self._play:
                import sounddevice as sd

                with sd.OutputStream(
                    samplerate=self._samplerate,
                    channels=1,
                    dtype="int16",
                    device=self._device or None,
                ) as stream:
                    self._consume(stream)
            else:
                self._consume(None)
        except Exception as exc:
            logger.error("播放线程异常: %s", exc)
        finally:
            if self._wav is not None:
                self._wav.close()
                self._wav = None

    def _consume(self, stream) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            data = np.frombuffer(item, dtype=np.int16)
            if self._volume != 1.0:
                data = (data * self._volume).astype(np.int16)
            if stream is not None:
                stream.write(data)
            if self._wav is not None:
                self._wav.writeframes(item)

    def write(self, pcm16: bytes) -> None:
        try:
            self._queue.put_nowait(pcm16)
        except queue.Full:
            self._dropped += 1
            if self._dropped % 100 == 1:
                logger.warning("播放队列已满，丢弃音频块（累计 %s）", self._dropped)

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)
