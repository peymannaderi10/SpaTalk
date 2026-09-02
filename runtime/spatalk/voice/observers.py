"""Per-call meters: what the providers charged for, and how long the caller waited."""

from __future__ import annotations

import time

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    MetricsFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed

from spatalk.voice.session import VoiceSession


class UsageObserver(BaseObserver):
    def __init__(self, session: VoiceSession):
        super().__init__()
        self._s = session

    async def on_push_frame(self, data: FramePushed):
        f = data.frame
        if not isinstance(f, MetricsFrame):
            return
        for d in f.data:
            if isinstance(d, LLMUsageMetricsData):
                v = d.value
                self._s.usage["llm_input_tokens"] += float(getattr(v, "prompt_tokens", 0) or 0)
                self._s.usage["llm_cached_tokens"] += float(
                    getattr(v, "cache_read_input_tokens", 0) or 0
                )
                self._s.usage["llm_output_tokens"] += float(
                    getattr(v, "completion_tokens", 0) or 0
                )
            elif isinstance(d, TTSUsageMetricsData):
                self._s.usage["tts_chars"] += float(d.value or 0)


class TurnLatencyObserver(BaseObserver):
    """User stopped speaking -> bot started speaking, in ms. This is the number the brief's S7 is measured on."""

    def __init__(self, session: VoiceSession):
        super().__init__()
        self._s = session
        self._t0: float | None = None

    async def on_push_frame(self, data: FramePushed):
        f = data.frame
        if isinstance(f, UserStoppedSpeakingFrame):
            self._t0 = time.monotonic()
        elif isinstance(f, BotStartedSpeakingFrame) and self._t0 is not None:
            self._s.latencies_ms.append(int((time.monotonic() - self._t0) * 1000))
            self._t0 = None
