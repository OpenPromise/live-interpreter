"""终端字幕输出：原文在识别完成后整句显示，译文流式刷新。"""

from __future__ import annotations

import sys
from typing import Callable


class CaptionPrinter:
    def __init__(
        self,
        show_source: bool = True,
        preview: bool = False,
        broadcast: Callable[[dict], None] | None = None,
    ):
        self._show_source = show_source
        self._preview = preview
        self._broadcast = broadcast
        self._output_pending = ""

    def on_input_text_done(self, transcript: str) -> None:
        """源语言整句识别完成。"""
        if self._show_source and transcript:
            print(f"原文: {transcript}")
        if self._broadcast is not None and transcript:
            self._broadcast({"type": "source", "text": transcript})

    def on_output_text(self, pending: str) -> None:
        """译文增量（含待确认预测文本），仅预览模式原地刷新，避免刷屏。"""
        if not self._preview:
            return
        self._output_pending = pending
        sys.stdout.write(f"\r译文: {pending}")
        sys.stdout.flush()

    def on_output_text_done(self, transcript: str) -> None:
        """译文整句完成。"""
        if transcript:
            self._output_pending = transcript
        sys.stdout.write(f"\r译文: {self._output_pending}\n")
        sys.stdout.flush()
        if self._broadcast is not None:
            self._broadcast({"type": "translation", "text": self._output_pending})
