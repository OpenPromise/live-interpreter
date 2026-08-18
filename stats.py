"""延迟统计：测量每段语音从开始到译文首包/完成的延迟。"""

from __future__ import annotations

import statistics
import time


class LatencyStats:
    """基于服务端 VAD 事件（speech_started/stopped）与响应事件的延迟统计。

    指标说明：
      - 首字延迟：speech_started -> 第一个 response.audio.delta（边听边译的启动速度）
      - 结束延迟：speech_stopped -> 该段响应完成（整句收尾速度）
      - 整句延迟：speech_started -> 该段响应完成（speech_stopped 未触发时的兜底）
    """

    def __init__(self, verbose: bool = True):
        self._verbose = verbose
        self._speech_start: float | None = None
        self._speech_stop: float | None = None
        self._first_audio: float | None = None
        self._first_lat: list[float] = []
        self._end_lat: list[float] = []
        self._whole_lat: list[float] = []
        self._seg_no = 0

    def speech_started(self) -> None:
        self._speech_start = time.monotonic()
        self._speech_stop = None
        self._first_audio = None

    def speech_stopped(self) -> None:
        self._speech_stop = time.monotonic()

    def audio_delta(self) -> None:
        if self._speech_start is not None and self._first_audio is None:
            self._first_audio = time.monotonic()
            if self._verbose:
                print(
                    f"[stats] 段 {self._seg_no + 1}: 首字延迟 "
                    f"{self._first_audio - self._speech_start:.2f}s"
                )

    def response_done(self) -> None:
        if self._speech_start is not None:
            self._seg_no += 1
            now = time.monotonic()
            if self._first_audio is not None:
                self._first_lat.append(self._first_audio - self._speech_start)
            self._whole_lat.append(now - self._speech_start)
            if self._speech_stop is not None:
                end = now - self._speech_stop
                self._end_lat.append(end)
                if self._verbose:
                    print(f"[stats] 段 {self._seg_no}: 结束延迟 {end:.2f}s")
            else:
                if self._verbose:
                    print(
                        f"[stats] 段 {self._seg_no}: 整句延迟 "
                        f"{self._whole_lat[-1]:.2f}s（语音结束事件未触发）"
                    )
        self._speech_start = None
        self._speech_stop = None
        self._first_audio = None

    def report(self) -> None:
        def pct(xs: list[float], p: float) -> float:
            if not xs:
                return float("nan")
            if len(xs) == 1:
                return xs[0]
            q = statistics.quantiles(sorted(xs), n=100, method="inclusive")
            return q[max(0, min(99, int(p * 100) - 1))]

        print("\n[stats] 汇总（翻译管线延迟，不含直播平台自身缓冲）:")
        print(f"  统计段数: {self._seg_no}")
        print(
            f"  首字延迟(秒): n={len(self._first_lat)} "
            f"p50={pct(self._first_lat, 0.50):.2f} p95={pct(self._first_lat, 0.95):.2f}"
        )
        print(
            f"  结束延迟(秒): n={len(self._end_lat)} "
            f"p50={pct(self._end_lat, 0.50):.2f} p95={pct(self._end_lat, 0.95):.2f}"
        )
        print(
            f"  整句延迟(秒): n={len(self._whole_lat)} "
            f"p50={pct(self._whole_lat, 0.50):.2f} p95={pct(self._whole_lat, 0.95):.2f}"
        )
