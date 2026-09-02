"""Per-call meters: what the providers charged for, and how long the caller waited."""

from __future__ import annotations

import time

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    MetricsFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, TTFBMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed

from spatalk.voice.session import VoiceSession

# --- per-stage latency (operations plan, Task E5) ---------------------------------------

# The stage a Pipecat service belongs to, by service, never by pipeline position: the three
# vendors are swap points (`make_stt`, `make_tts`, `make_llm`), so a report keyed on
# position would silently stop reporting the moment a provider changed. The named services
# are the ones those three factories can return today, including the second LLM vendor.
STAGE_BY_SERVICE: dict[str, str] = {
    "SonioxSTTService": "stt",
    "DeepgramFluxSTTService": "stt",
    "GoogleLLMService": "llm",
    "OpenAILLMService": "llm",
    "InworldTTSService": "tts",
    "DeepgramTTSService": "tts",
}

# What the fallback looks for, in this order. STT comes first on purpose: "STTService"
# contains the substring "TTS", so a TTS-first scan files every transcription reading under
# text-to-speech and the two budgets swap places.
_STAGE_MARKERS: tuple[tuple[str, str], ...] = (("STT", "stt"), ("TTS", "tts"), ("LLM", "llm"))


def stage_for_processor(name: str) -> str | None:
    """The budgeted stage a processor's metrics belong to, or None when it is not one.

    Pipecat names a processor `<ClassName>#<n>`, so the class is the part before the `#`.
    An unknown vendor still lands in the right bin through the marker fallback; our own
    processors (the rules gate, the output guard) match nothing and are not budgeted.
    """
    service = name.split("#", 1)[0]
    if service in STAGE_BY_SERVICE:
        return STAGE_BY_SERVICE[service]
    upper = service.upper()
    for marker, stage in _STAGE_MARKERS:
        if marker in upper:
            return stage
    return None


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
            elif isinstance(d, TTFBMetricsData):
                # Operations plan, Task E5: which vendor the caller was waiting on.
                stage = stage_for_processor(d.processor or "")
                if stage is not None:
                    self._s.stage_ttfb_ms.setdefault(stage, []).append(
                        int(round(float(d.value or 0) * 1000))
                    )


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
