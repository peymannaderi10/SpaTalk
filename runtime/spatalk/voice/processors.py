"""Structural honesty layers 1 and 3, as Pipecat frame processors.

`RulesGateProcessor` sits after STT: a band-3 lexicon hit never reaches the model.
`OutputGuardProcessor` sits between the LLM and TTS: a sentence claiming a completed
action is replaced by the tenant's `cannot_complete` script *and* a real item is filed,
so the replacement sentence is true.
"""

from __future__ import annotations

import re

from loguru import logger
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from spatalk.brain.guard import guard
from spatalk.brain.outcomes import Refused
from spatalk.brain.renderer import render, render_script
from spatalk.brain.requests import CaptureRequest, EscalateRequest
from spatalk.brain.rules import health_context_mentioned, rules_gate
from spatalk.voice.session import VoiceSession

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class RulesGateProcessor(FrameProcessor):
    """Sits after STT. Band-3 lexicon hits are answered with the fixed script and the model never runs."""

    def __init__(self, session: VoiceSession):
        super().__init__(name="rules_gate")
        self._s = session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            if health_context_mentioned(frame.text, self._s.cfg) and not self._s.ref.health_context:
                self._s.ref = self._s.ref.model_copy(update={"health_context": True})
            gate = rules_gate(frame.text, self._s.cfg)
            if gate:
                self._s.band = 3
                now = self._s.clock.now()
                try:
                    out = await self._s.caps.escalate(
                        self._s.ref, EscalateRequest(reason=gate.reason)
                    )
                    logger.info(
                        "rules gate: {} ({!r}) -> item {}", gate.reason, gate.matched, out.item_id
                    )
                except Exception as e:  # noqa: BLE001  ledger down: say so, never promise a callback
                    logger.exception("rules gate could not file escalation: {}", e)
                    out = Refused(reason="unavailable")
                await self.push_frame(
                    TTSSpeakFrame(text=render(out, self._s.cfg, now), append_to_context=True)
                )
                self._s.ended = True
                if self._s.worker is not None:
                    await self._s.worker.queue_frames([EndFrame()])
                return
        await self.push_frame(frame, direction)


class OutputGuardProcessor(FrameProcessor):
    """Sits between LLM and TTS. Blocks completion language unless the turn holds a Completed outcome."""

    def __init__(self, session: VoiceSession):
        super().__init__(name="output_guard")
        self._s = session
        self._buffer = ""
        self._dropping = False

    async def _emit(self, sentence: str):
        sentence = sentence.strip()
        if not sentence or self._dropping:
            return
        g = guard(sentence, self._s.has_completed, self._s.cfg, replacement="")
        if g.blocked:
            # Everything after a blocked sentence belonged to the same false claim, so the
            # rest of the turn is dropped rather than half-spoken.
            self._dropping = True
            self._s.guard_blocks += 1
            self._s.band = max(self._s.band, 2)
            now = self._s.clock.now()
            try:
                await self._s.caps.capture(self._s.ref, CaptureRequest(kind="question"))
                spoken = render_script("cannot_complete", self._s.cfg, now, urgent=False)
            except Exception as e:  # noqa: BLE001  ledger down: nothing was filed, promise nothing
                logger.exception("guard could not file the blocked claim: {}", e)
                spoken = render(
                    Refused(reason="unavailable"), self._s.cfg, now, channel=self._s.ref.channel
                )
            logger.warning("guard blocked ({}): {!r}", g.matched, sentence)
            await self.push_frame(LLMTextFrame(text=spoken))
            return
        await self.push_frame(LLMTextFrame(text=sentence))

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer, self._dropping = "", False
            await self.push_frame(frame, direction)
        elif isinstance(frame, LLMTextFrame) and direction == FrameDirection.DOWNSTREAM:
            self._buffer += frame.text
            parts = SENTENCE_END.split(self._buffer)
            for complete in parts[:-1]:
                await self._emit(complete)
            self._buffer = parts[-1]
        elif isinstance(frame, LLMFullResponseEndFrame):
            await self._emit(self._buffer)
            self._buffer, self._dropping = "", False
            await self.push_frame(frame, direction)
        elif isinstance(frame, InterruptionFrame):
            self._buffer, self._dropping = "", False
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)
