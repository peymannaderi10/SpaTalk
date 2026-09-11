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
from rapidfuzz import fuzz
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    FunctionCallInProgressFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from spatalk.brain.audio_tags import drop_unknown_tags
from spatalk.brain.breath import named_items
from spatalk.brain.guard import guard
from spatalk.brain.outcomes import Refused
from spatalk.brain.renderer import render, render_script
from spatalk.brain.flow import (
    Slots,
    Step,
    draft_from,
    next_step,
    open_flow,
    open_question,
    pop_digression,
    step_tools,
)
from spatalk.brain.requests import EscalateRequest
from spatalk.brain.rules import health_context_mentioned, is_fragment, rules_gate
from spatalk.voice.echo import scrub_echo
from spatalk.voice.frames import ToolTurnDoneFrame
from spatalk.voice.session import VoiceSession
from spatalk.voice.steps import sync_context

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

# The caller said it again (rung 0, memo §6). `partial_ratio` rather than the plain ratio,
# because a caller who repeats himself usually adds to it: on the founder's call "can you
# book me that facial" came back as "can you book me that facial, the mesojet one", which
# the plain ratio scores at 0.76 on the length difference alone and the partial at 1.0.
# Floored at three words — the same floor the barge-in gate uses — so a one-word answer
# cannot match every longer sentence that follows it. The comparison happens in memory and
# only the similarity is kept.
CALLER_REPEAT = 0.80
CALLER_REPEAT_MIN_WORDS = 3


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
        # Words from utterances that carried no content, waiting to go in front of the next
        # one that does (see `_turn_text`).
        self._held_fragment = ""
        # The caller's previous turn, for the repeat signal only. One turn deep, exactly as
        # `recent_bot_text` is for the assistant's side, and never persisted.
        self._last_final: str | None = None

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

    def _turn_text(self, text: str) -> str | None:
        """What the caller has actually said, or None when this utterance is not a turn.

        A final (or promoted) transcription of nothing but fillers and function words is a
        hesitation, not an answer and not a question: on the founder's call of 2026-09-11
        01:41 "Um.", "Well." and "What was the, uh-" each became a turn of its own. Held
        rather than dropped, and put in front of the next utterance that does carry content,
        so a word the caller meant is never lost.
        """
        if is_fragment(text, yes_no_step=self._yes_no_step()):
            self._held_fragment = f"{self._held_fragment} {text.strip()}".strip()
            logger.info("fragment held, not a turn: {!r}", text)
            return None
        if self._held_fragment:
            text = f"{self._held_fragment} {text.strip()}".strip()
            self._held_fragment = ""
        return text

    def _yes_no_step(self) -> bool:
        """Does the runtime's open question take a yes or a no? Asked of `step_tools` rather
        than answered from a list here, so the gate can never disagree with the flow."""
        slots = self._s.slots
        if slots.pending is not None:
            return True
        step = next_step(slots, self._s.cfg, self._s.ref.channel)
        tools = step_tools(step, slots, self._s.cfg, self._s.ref.channel)
        return any(t.name == "answer" for t in tools)

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
            text = self._turn_text(frame.text)
            if text is None:
                # Not a turn: the caller is still assembling the sentence. Nothing goes to
                # the aggregator, so no model runs and no step question is re-spoken; the
                # words are kept for the next transcription and the idle nudge still holds
                # the floor if the caller has in fact stopped.
                return
            frame.text = text
            # The caller spoke: any "still there?" count starts over, and so does the
            # allowance for a tool the step did not offer.
            self._s.idle_nudges = 0
            self._s.ignored_tools = 0
            self._s.runtime_asked_this_turn = False
            # And so does the breath the model may spend answering (founder call 14ea2579,
            # 2026-09-11 15:53:14 and 15:54:05). A held fragment never gets here, so it
            # cannot buy a fresh breath in the middle of a monologue.
            self._s.reset_speech_budget()
            self._s.signals.next_turn()
            previous, self._last_final = self._last_final, frame.text
            if previous and len(previous.split()) >= CALLER_REPEAT_MIN_WORDS:
                similarity = fuzz.partial_ratio(previous.lower(), frame.text.lower()) / 100.0
                if similarity >= CALLER_REPEAT:
                    self._s.record_signal("caller_repeat", similarity=similarity)
            if health_context_mentioned(frame.text, self._s.cfg) and not self._s.ref.health_context:
                self._s.ref = self._s.ref.model_copy(update={"health_context": True})
            # A bare answer to "Could I get your first name?" is a name, whatever word the
            # recogniser produced for it (founder call 2026-09-10 20:56:19, where the
            # founder's name Peyman came through as "payment").
            at_name = (
                next_step(self._s.slots, self._s.cfg, self._s.ref.channel) == Step.NAME
            )
            gate = rules_gate(frame.text, self._s.cfg, name_step=at_name)
            if gate:
                self._s.band = 3
                now = self._s.clock.now()
                # The transcription stops here, so the user aggregator never writes it to the
                # context and the transcript would show the fixed reply to nothing. The
                # caller's turn goes in first; the script follows once it is spoken.
                if self._s.context is not None:
                    self._s.context.add_message({"role": "user", "content": frame.text})
                if gate.reason == "clinical":
                    # The offer first, filed only on yes (slot engine design, §4.2). The
                    # call stays open; the record and the context move to the clinical flow.
                    self._s.slots = open_flow(
                        "clinical", self._s.slots, "voice", self._s.ref.caller_phone
                    )
                    sync_context(self._s, now)
                    logger.info("rules gate: clinical ({!r}) -> offer", gate.matched)
                    await self.push_frame(
                        TTSSpeakFrame(
                            text=render_script("clinical_offer", self._s.cfg, now, urgent=False),
                            append_to_context=True,
                        )
                    )
                    return
                try:
                    out = await self._s.caps.escalate(
                        self._s.ref, EscalateRequest(reason=gate.reason)
                    )
                    logger.info(
                        "rules gate: {} ({!r}) -> item {}", gate.reason, gate.matched, out.item_id
                    )
                    # Before the frame that asserts it. The `Refused` branch records nothing,
                    # which is correct: `refuse_unavailable` asserts nothing.
                    self._s.remember_receipt("item", str(out.item_id))
                except Exception as e:  # noqa: BLE001  ledger down: say so, never promise a callback
                    logger.exception("rules gate could not file escalation: {}", e)
                    out = Refused(reason="unavailable")
                await self.push_frame(
                    TTSSpeakFrame(text=render(out, self._s.cfg, now), append_to_context=True)
                )
                # Only the emergency script ends the call, because it is the only one whose
                # wording tells the caller to hang up and dial 911 (flows.md §1.8). The
                # complaint, payment and human-request scripts all promise a callback and the
                # caller is still on the line when they finish: on the founder's call
                # 2026-09-10 20:56:19 a mis-transcribed first name matched the payment
                # lexicon and the EndFrame that followed dropped a live booking.
                if gate.reason == "emergency":
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
    """Sits between LLM and TTS. One private egress is the only path from here to the wire.

    Everything the caller hears on a call goes through `_egress` — the model's own words, a
    tenant script the rules gate or a tool handler pushed from upstream, the step question,
    the guard's own replacement — and everything that goes through it is guarded first
    (model-words memo, §3.1). That is non-negotiable 1's "every model utterance passes
    `guard()` before reaching a channel", made structural instead of conventional.
    """

    def __init__(self, session: VoiceSession):
        super().__init__(name="output_guard")
        self._s = session
        self._buffer = ""
        self._dropping = False
        # A sentence ending in "?" that arrived while a request was open, kept back until the
        # turn ends: see `_emit`.
        self._held: str | None = None
        self._spoke_this_turn = False
        # Sentences of the model's own words this *completion* has put on the wire. Every
        # completion is allowed one whatever the caller turn's budget has left, so a turn is
        # never answered with silence (the hand-back at 15:53:13.970 spends two completions
        # inside one caller turn).
        self._said_this_completion = 0
        # The two halves of a model turn. The question the caller hears is decided once both
        # have arrived: the completion's end frame, and — on a turn that called a tool — the
        # handler's `ToolTurnDoneFrame`, which arrives after the runtime's own fixed lines.
        self._response_ended = False
        self._tool_done = False
        self._handed_back = False
        self._finished = False
        # Guard-owned, not a parameter: set only while the guard's own replacement is on its
        # way out, because `cannot_complete` asserts a receipt itself and would otherwise
        # retract the retraction. Nothing outside this class can set it, and `_egress` takes
        # no argument that would let anything outside this class bypass the guard (memo §3.1;
        # `tests/test_structural_honesty.py` refuses even the *name* of such an argument).
        self._retracting = False

    def _flow_open(self) -> bool:
        return bool(self._s.slots.flow) and not self._s.slots.ended_flow

    async def _release_held(self, *, as_statement: bool = False):
        """Let the held sentence out.

        `as_statement` is set by `_emit`, where the held sentence has turned out not to be
        the last one and so was part of the answer: it is budgeted like any other statement.
        The default is `_finish_turn`'s call, where it is the question that carries the turn
        and goes out whatever the budget has left — dropping it would leave the turn without
        a question at all, and the runtime's fallback is suppressible by `asked_already`.
        """
        held, self._held = self._held, None
        if held is None:
            return
        if as_statement:
            await self._say_statement(held)
            return
        await self._egress(held, model_words=True)

    async def _say_statement(self, sentence: str) -> None:
        """One sentence of the model's own words, against this caller turn's budget.

        Two budgets, because the founder's call broke through each of them separately: the
        tenant's `max_sentences_per_turn` (five sentences from one completion at 15:54:05,
        29.7 s of audio) and the catalogue entries named inside them (three sentences at
        15:53:14 that between them recited seven treatments). The count is added on
        ADMISSION, not on delivery: a sentence naming four services is spoken whole and the
        NEXT statement is the one dropped, because the egress cannot cut inside a sentence
        without leaving a fragment on the wire.
        """
        if self._s.turn_capped:
            # Everything after the cap belongs to the breath that was stopped, the same
            # discipline `_dropping` already applies after a blocked sentence.
            return
        max_sentences = self._s.cfg.persona.max_sentences_per_turn
        max_items = getattr(self._s.cfg.persona, "max_items_per_turn", 3)
        floor = self._said_this_completion == 0
        if not floor and self._s.spoken_sentences >= max_sentences:
            self._cap("sentences")
            return
        if not floor and self._s.spoken_items >= max_items:
            self._cap("items")
            return
        self._s.spoken_sentences += 1
        self._said_this_completion += 1
        self._s.spoken_items += named_items(sentence, self._s.cfg)
        await self._egress(sentence, model_words=True)

    def _cap(self, reason: str) -> None:
        """The breath is spent. Once a caller turn: `_say_statement` short-circuits after."""
        self._s.turn_capped = True
        logger.info("turn capped on {}: the rest of the model's words are dropped", reason)
        self._s.record_signal("truncated", reason=reason)

    async def _egress(
        self, text: str, *, model_words: bool, append_to_context: bool = True
    ) -> None:
        """The only path from this processor to TTS, and the only call site of `guard()`."""
        text = drop_unknown_tags(text.strip())
        if not text:
            return
        if not self._retracting:
            g = guard(
                text, self._s.has_completed, self._s.cfg,
                replacement="", receipts=len(self._s.receipts),
            )
            if g.blocked:
                await self._retract(
                    text, g, model_words=model_words, append_to_context=append_to_context
                )
                return
        self._spoke_this_turn = True
        self._s.remember_spoken(text)
        frame = (
            # The trailing space is for the TTS text aggregator, which otherwise sees
            # "Welcome!We have" and speaks it as one run-on sentence.
            LLMTextFrame(text=text + " ")
            if model_words
            else TTSSpeakFrame(text=text, append_to_context=append_to_context)
        )
        await self.push_frame(frame)

    async def _retract(
        self, sentence: str, g, *, model_words: bool, append_to_context: bool = True
    ) -> None:
        """File a real item, then speak the tenant's replacement, so the sentence the caller
        hears is true. Everything after a blocked sentence belonged to the same false claim,
        so the rest of the turn is dropped rather than half-spoken. The replacement takes the
        frame the blocked sentence would have taken, so a retracted script is still a script.
        """
        self._dropping = True
        self._held = None
        self._s.guard_blocks += 1
        self._s.band = max(self._s.band, 2)
        now = self._s.clock.now()
        out = None
        try:
            out = await self._s.caps.capture(
                self._s.ref, draft_from(Slots(flow="question"), self._s.cfg)
            )
        except Exception as e:  # noqa: BLE001  ledger down: nothing was filed, promise nothing
            logger.exception("guard could not file the blocked claim: {}", e)
        item_id = getattr(out, "item_id", None)
        if item_id is None:
            # Nothing was filed, so nothing may be asserted: the refusal names the clinic's
            # own number and claims no action at all.
            spoken = render(
                Refused(reason="unavailable"), self._s.cfg, now, channel=self._s.ref.channel
            )
        else:
            # The receipt goes in before the sentence that asserts it, which is also what
            # keeps the replacement from being retracted in its turn.
            self._s.remember_receipt("item", str(item_id))
            spoken = render_script("cannot_complete", self._s.cfg, now, urgent=False)
        logger.warning("guard blocked {} ({}): {!r}", g.family, g.matched, sentence)
        self._s.record_signal("guard_block", family=g.family)
        self._retracting = True
        try:
            await self._egress(
                spoken, model_words=model_words, append_to_context=append_to_context
            )
        finally:
            self._retracting = False

    async def _finish_turn(self) -> str | None:
        """Decide the one question the caller hears, once the whole turn is in.

        Returns the runtime's own question, for the caller to speak *after* the completion's
        end frame the way it always has been — the assistant aggregator adds it as an
        utterance of its own — while the model's released words go out inside the completion.

        The runtime named the act and the model found the words (memo §7 decision 1), so the
        model's own question carries the turn. Three things still belong to the runtime: a
        confirmation of a value the resolver could not settle, whose wording is law and which
        the tool handler has already spoken; the fallback for a reply that asked nothing, so
        a turn is never left silent; and the rule that the same rendered question is never
        spoken twice running on an unchanged record.
        """
        if self._finished:
            return None
        self._finished = True
        if self._s.slots.digression is not None and self._spoke_this_turn:
            # The model answered the side question, so the frame has done its job. The narrow
            # fix took `_spoke_this_turn` out of the *repeat suppression* deliberately; it is
            # still the right test for "did the model actually answer". A turn that said
            # nothing leaves the frame open for the next one.
            self._s.slots = pop_digression(self._s.slots, self._s.cfg, "voice")
        if self._handed_back:
            # A refusal or a side question: another completion is coming, so the runtime asks
            # nothing and the model's one-step-behind question does not go out on top of it.
            self._held = None
            return None
        q = open_question(self._s.slots, self._s.cfg, "voice")
        question = None
        if q is not None and not self._s.ended and not self._s.runtime_asked_this_turn:
            rendered = render_script(q.key, self._s.cfg, self._s.clock.now(), urgent=False, **q.fills)
            if self._s.asked_already(rendered):
                # The caller has just heard those exact words and nothing in the record has
                # moved, so there is nothing new to say. V1 made this conditional on the
                # model having spoken, which let the script out twice more on the founder's
                # call of 2026-09-11 (01:41:12.841 and 01:41:16.795, both on completions his
                # next fragment had cancelled: `prompt tokens: 0, completion tokens: 0`).
                # The rule holds whatever the turn contained; a caller who has stopped
                # talking is picked up by the "still there?" nudge, not by a third repeat.
                logger.info("step question not repeated: {!r}", rendered)
                self._s.record_signal("repeat", script=q.key)
            else:
                question = rendered
        if self._held is not None and not (q is not None and q.fixed):
            # The model asked, and the wording is not the tenant's law: its question is the
            # turn, and the runtime's stays unspoken.
            await self._release_held()
            return None
        if self._held is not None:
            logger.info("model question dropped for the fixed confirmation: {!r}", self._held)
            self._held = None
        if question:
            if q.key.endswith("_again"):
                # The same step asked a second time after a miss: the re-prompt count is
                # half of the repair measurement the phase-B ladder is built from.
                self._s.record_signal("reprompt", script=q.key)
            self._s.remember_question(question)
            self._s.runtime_asked_this_turn = True
        return question

    async def _emit(self, sentence: str):
        # A bracketed tool name or aside is not speech (call on gpt-4.1-nano, 2026-09-03).
        sentence = drop_unknown_tags(sentence.strip())
        if not sentence or self._dropping:
            return
        # Whatever was held back was not the last sentence after all, so it was part of the
        # answer: it goes out ahead of this one, and against the same budget.
        await self._release_held(as_statement=True)
        if sentence.endswith("?") and self._flow_open():
            # A trailing question is the model taking the turn, and since 2026-09-11 that is
            # what it is for: the runtime names the act and the model finds the words. It is
            # still held to the end of the turn, because until then it is not known whether
            # the record wants a confirmation in the tenant's own wording instead — which is
            # what kept the caller from hearing two questions in one breath on the founder's
            # call of 2026-09-10 20:54:37 ("Would you like to hear about any of those, or
            # perhaps something else?" then "What did you have in mind?").
            self._held = sentence
            return
        await self._say_statement(sentence)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer, self._dropping, self._held = "", False, None
            self._spoke_this_turn = False
            self._said_this_completion = 0
            self._response_ended = self._tool_done = self._finished = False
            self._handed_back = False
            self._s.tool_called_this_turn = False
            self._s.runtime_asked_this_turn = False
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
        elif isinstance(frame, FunctionCallInProgressFrame):
            # A tool ran this turn: its handler speaks the next question itself.
            self._s.tool_called_this_turn = True
            await self.push_frame(frame, direction)
        elif isinstance(frame, LLMFullResponseEndFrame):
            await self._emit(self._buffer)
            self._buffer, self._dropping = "", False
            self._response_ended = True
            # On a turn with no tool the whole turn is in, so the model's own words are
            # released inside the completion. On a tool turn the runtime's own lines are
            # still on their way — Pipecat queues the function calls and pushes this frame
            # without waiting for them — so the decision waits for the handler's
            # `ToolTurnDoneFrame`.
            question = None
            if not self._s.tool_called_this_turn or self._tool_done:
                question = await self._finish_turn()
            await self.push_frame(frame, direction)
            if question:
                await self._egress(question, model_words=False)
        elif isinstance(frame, ToolTurnDoneFrame):
            self._tool_done = True
            self._handed_back = frame.handed_back
            if self._response_ended:
                question = await self._finish_turn()
                if question:
                    await self._egress(question, model_words=False)
        elif isinstance(frame, InterruptionFrame):
            self._buffer, self._dropping, self._held = "", False, None
            self._said_this_completion = 0
            self._response_ended = self._tool_done = self._finished = False
            self._s.record_signal("bargein")
            await self.push_frame(frame, direction)
        else:
            if isinstance(frame, TTSSpeakFrame) and direction == FrameDirection.DOWNSTREAM:
                # Fixed scripts (the disclosure, the outcomes, the confirmations) reach TTS
                # through the same one door as the model's words, so an outcome sentence with
                # no receipt behind it is retracted whoever wrote it.
                await self._egress(
                    frame.text, model_words=False, append_to_context=frame.append_to_context
                )
                return
            await self.push_frame(frame, direction)
