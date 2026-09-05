"""Structural honesty layers 1 and 3, as Pipecat frame processors.

`RulesGateProcessor` sits after STT: a band-3 lexicon hit never reaches the model.
`OutputGuardProcessor` sits between the LLM and TTS: a sentence claiming a completed
action is replaced by the tenant's `cannot_complete` script *and* a real item is filed,
so the replacement sentence is true.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from spatalk.brain.audio_tags import drop_unknown_tags
from spatalk.brain.guard import guard
from spatalk.brain.outcomes import Refused
from spatalk.brain.renderer import render, render_script
from spatalk.brain.requests import CaptureRequest, EscalateRequest
from spatalk.brain.rules import health_context_mentioned, rules_gate
from spatalk.voice.echo import scrub_echo
from spatalk.voice.session import VoiceSession

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Echo can only be heard while the assistant's audio is playing at the far end, plus the
# trip back down the line. Speech that starts later than this after the assistant stopped
# is the caller, whatever words they use (founder call 2026-09-03 15:56: "I'd prefer a call
# from the team" was dropped as an echo of "would you prefer a call from the team?" and
# the assistant fell silent).
ECHO_TAIL_SECS = 1.0

# A provisional transcript the transcriber keeps re-sending unchanged is one utterance,
# not many: every copy re-armed the aggregator's turn watchdog (founder call 2026-09-03
# 22:05, a one-word "No" hung the turn for twenty seconds). After this long with no new
# words and no final, the last interim is promoted to a final transcription so the turn
# can close with the caller's words in it.
STALE_INTERIM_SECS = 1.5


class RulesGateProcessor(FrameProcessor):
    """Sits after STT. Band-3 lexicon hits are answered with the fixed script and the model never runs."""

    def __init__(self, session: VoiceSession, *, monotonic: Callable[[], float] = time.monotonic):
        super().__init__(name="rules_gate")
        self._s = session
        self._monotonic = monotonic
        self._bot_speaking = False
        self._bot_stopped_at: float | None = None
        self._utterance_open = False
        self._may_echo = False
        self._last_interim: str | None = None
        self._promotion: asyncio.Task | None = None

    async def _promote_stale_interim(self, frame: InterimTranscriptionFrame):
        await asyncio.sleep(STALE_INTERIM_SECS)
        logger.info("no final transcription after {!r}; promoting the interim", frame.text)
        self._promotion = None
        await self.process_frame(
            TranscriptionFrame(text=frame.text, user_id=frame.user_id, timestamp=frame.timestamp),
            FrameDirection.DOWNSTREAM,
        )

    async def _cancel_promotion(self):
        if self._promotion is not None:
            task, self._promotion = self._promotion, None
            await self.cancel_task(task)

    def _heard_while_assistant_spoke(self) -> bool:
        if self._bot_speaking:
            return True
        return (
            self._bot_stopped_at is not None
            and self._monotonic() - self._bot_stopped_at < ECHO_TAIL_SECS
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._bot_stopped_at = self._monotonic()
        if isinstance(frame, InterimTranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            if frame.text == self._last_interim:
                return
            self._last_interim = frame.text
            await self._cancel_promotion()
            if frame.text.strip():
                self._promotion = self.create_task(self._promote_stale_interim(frame))
        if isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            self._last_interim = None
            await self._cancel_promotion()
            # The caller spoke: any \"still there?\" count starts over.
            self._s.idle_nudges = 0
        if (
            isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame))
            and direction == FrameDirection.DOWNSTREAM
        ):
            if not self._utterance_open:
                # Decided once per utterance, on its first words: only speech the phone
                # picked up while the assistant was talking can be the assistant's echo.
                self._utterance_open = True
                self._may_echo = self._heard_while_assistant_spoke()
            if isinstance(frame, TranscriptionFrame):
                self._utterance_open = False
        if (
            isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame))
            and direction == FrameDirection.DOWNSTREAM
            and self._may_echo
        ):
            # The assistant's own voice, heard back through the phone, is not the caller.
            scrubbed = scrub_echo(frame.text, self._s.recent_bot_text)
            if not scrubbed.strip():
                logger.debug("echo dropped: {!r}", frame.text)
                return
            if scrubbed != frame.text:
                logger.info("echo trimmed: {!r} -> {!r}", frame.text, scrubbed)
                frame.text = scrubbed
        if isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            if health_context_mentioned(frame.text, self._s.cfg) and not self._s.ref.health_context:
                self._s.ref = self._s.ref.model_copy(update={"health_context": True})
            gate = rules_gate(frame.text, self._s.cfg)
            if gate:
                self._s.band = 3
                now = self._s.clock.now()
                # The transcription stops here, so the user aggregator never writes it to the
                # context and the transcript would show the fixed reply to nothing. The
                # caller's turn goes in first; the script follows once it is spoken.
                if self._s.context is not None:
                    self._s.context.add_message({"role": "user", "content": frame.text})
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


class FillerProcessor(FrameProcessor):
    """Sits between the user aggregator and the LLM.

    The model's first token takes about 0.7 s after the caller stops, and the caller hears
    every millisecond of it as silence. The moment a turn is handed to the model, this
    speaks one short fixed sentence from ``scripts.fillers`` ("Okay.", "Let me check."),
    rotating so it does not repeat, so the caller hears a response within a third of a
    second while the answer forms. The prompt tells the model the acknowledgement has been
    spoken, so it goes straight to the answer. The filler never enters the model's context
    or the transcript: it is for the ear, not the record.
    """

    def __init__(self, session: VoiceSession):
        super().__init__(name="filler")
        self._s = session
        self._turn = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            fillers = list(self._s.cfg.scripts.fillers)
            if fillers and not self._s.ended:
                text = fillers[self._turn % len(fillers)]
                self._turn += 1
                await self.push_frame(TTSSpeakFrame(text=text, append_to_context=False))
        await self.push_frame(frame, direction)


class OutputGuardProcessor(FrameProcessor):
    """Sits between LLM and TTS. Blocks completion language unless the turn holds a Completed outcome."""

    def __init__(self, session: VoiceSession):
        super().__init__(name="output_guard")
        self._s = session
        self._buffer = ""
        self._dropping = False

    async def _emit(self, sentence: str):
        # A bracketed tool name or aside is not speech (call on gpt-4.1-nano, 2026-09-03).
        sentence = drop_unknown_tags(sentence.strip())
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
            self._s.remember_spoken(spoken)
            await self.push_frame(LLMTextFrame(text=spoken + " "))
            return
        self._s.remember_spoken(sentence)
        # The trailing space is for the TTS text aggregator, which otherwise sees
        # "Welcome!We have" and speaks it as one run-on sentence.
        await self.push_frame(LLMTextFrame(text=sentence + " "))

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer, self._dropping = "", False
            # A fresh completion began, so an error after this one is a new failed *turn*
            # and not another error from the turn that already apologised (llm failover
            # plan, Task F2). The count itself is cleared only by words coming back: a
            # failed turn pushes this frame too, in `base_llm.process_frame`.
            self._s.model_turn_open = True
            await self.push_frame(frame, direction)
        elif isinstance(frame, LLMTextFrame) and direction == FrameDirection.DOWNSTREAM:
            # The model answered. Whatever run of failures was building up is over.
            self._s.model_failures = 0
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
            if isinstance(frame, TTSSpeakFrame) and direction == FrameDirection.DOWNSTREAM:
                # Fixed scripts (the disclosure, outcomes) pass through here on their way to TTS.
                self._s.remember_spoken(frame.text)
            await self.push_frame(frame, direction)
