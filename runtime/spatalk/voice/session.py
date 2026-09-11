"""Per-call state shared by the processors, the tool handlers and the observers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from spatalk.brain.capabilities import Capabilities
from spatalk.brain.flow import Slots
from spatalk.brain.requests import ConversationRef
from spatalk.clock import Clock
from spatalk.ops.signals import SignalLog
from spatalk.tenants.schema import TenantConfig


@dataclass
class VoiceSession:
    ref: ConversationRef
    cfg: TenantConfig
    caps: Capabilities
    clock: Clock
    worker: Any = None
    # The call's LLMContext, which `_finalize` writes to the transcript at the end of the call.
    # The rules gate swallows the transcription it answers, so the caller's words would never
    # reach the context through the user aggregator: the gate adds them itself (founder call
    # 2026-09-05 12:20, where the notes and the card had no record of what tripped the gate).
    context: Any = None
    # True only once a Tier A adapter has actually completed something this call.
    has_completed: bool = False
    band: int = 1
    # The slot engine's record for this call, and whether a tool ran on the current model
    # turn (a turn with none gets the open question re-asked after the model's words).
    slots: Slots = field(default_factory=Slots)
    tool_called_this_turn: bool = False
    # Tools the step did not offer, called since the caller last spoke. The first one hands
    # the turn back to the model so the caller's sentence gets answered from the whole
    # conversation (founder call 2026-09-10 20:55:35, where "can you book me that facial?"
    # became a bare "What did you have in mind?"); the next one falls back to the fixed
    # question, so a model that keeps calling the same tool cannot loop.
    ignored_tools: int = 0
    # The last step question the runtime spoke and the record it was asked on. Asked again
    # word for word with nothing moved, it reads as an assistant that has forgotten the call
    # ("What did you have in mind?" four times, founder call 2026-09-10).
    last_question: str = ""
    last_question_slots: Slots | None = None
    ended: bool = False
    guard_blocks: int = 0
    # What this call can actually show for itself: `item:<id>` for every item the ledger
    # issued, `link:<service_id>` for a booking link the provider accepted, `transfer:<n>`
    # for a leg the carrier took, `platform:<ref>` for a Tier A completion. Receipt-or-
    # retract (model-words memo, §3.3) reads the length of this list and nothing else — the
    # refs are here so a log line can name one, never so a sentence can. Per call, never
    # persisted.
    receipts: list[str] = field(default_factory=list)
    # --- rung 0 (model-words memo, §6) ---
    # Every repeat, re-prompt, repair, refused tool, barge-in and turn verdict of this call,
    # as counts and closed labels. `spatalk.ops.signals` refuses anything that could hold a
    # word somebody said, and Task 7 writes it to the conversation record at the end.
    signals: SignalLog = field(default_factory=SignalLog)
    latencies_ms: list[int] = field(default_factory=list)
    usage: dict[str, float] = field(
        default_factory=lambda: {
            "tts_chars": 0.0,
            # Seconds of audio the line actually carried, which is the unit the voice is
            # priced in; characters over-state an utterance a caller talked over.
            "tts_seconds": 0.0,
            "llm_input_tokens": 0.0,
            "llm_cached_tokens": 0.0,
            "llm_output_tokens": 0.0,
        }
    )
    started_at: datetime | None = None
    # The assistant's recent words, normalised, for the echo scrubber (spatalk.voice.echo).
    recent_bot_text: str = ""
    # When the caller last heard the model_unavailable line (monotonic seconds).
    last_apology_at: float | None = None
    # --- llm failover (llm failover plan, Task F2) ---
    # Turns that reached an apology with no answered turn in between. The second one ends
    # the call on the clinic's own number instead of looping apologies at the caller.
    model_failures: int = 0
    # True once a fresh completion has started (LLMFullResponseStartFrame). It is what tells
    # a new failed *turn* from the burst of errors one turn's retries produce.
    model_turn_open: bool = False
    # Times the caller was asked whether they are still there since they last spoke.
    idle_nudges: int = 0
    # --- operations (operations plan, Task E5) ---
    # Every TTFB reading of the call, in ms, filed under the stage that produced it. The
    # turn number in `latencies_ms` says the caller waited; this says which vendor made
    # them wait, which is the only version of the fact anybody can act on.
    stage_ttfb_ms: dict[str, list[int]] = field(
        default_factory=lambda: {"stt": [], "llm": [], "tts": []}
    )
    # --- live transfer (operations plan, Task E10) ---
    # The Telnyx leg id from the media stream's start message, the carrier client behind
    # `TransferPort`, and whether the tool was in this call's tool list at all. `transferred`
    # is set only after the carrier accepted, and is the reason `_finalize` must not treat
    # the socket closing as an abandoned call.
    call_control_id: str | None = None
    transfer: Any = None
    transfer_enabled: bool = False
    transferred: bool = False
    # The serializer's own InputParams object. After a successful transfer its
    # `auto_hang_up` is switched off, because the EndFrame or CancelFrame that ends our
    # side of the pipeline would otherwise hang up the leg the caller is now talking on.
    hangup_params: Any = None

    def remember_spoken(self, text: str) -> None:
        """Record something the assistant said, so its echo can be recognised."""
        from spatalk.brain.audio_tags import strip_audio_tags
        from spatalk.voice.echo import remember

        self.recent_bot_text = remember(self.recent_bot_text, strip_audio_tags(text))

    def record_signal(self, kind: str, **detail) -> None:
        """Record a rung-0 signal, so a processor does not have to reach two levels deep."""
        self.signals.record(kind, **detail)

    def remember_receipt(self, kind: str, ref: str) -> None:
        """Record proof of an action, before the sentence that asserts it is spoken."""
        if kind not in ("item", "link", "transfer", "platform"):
            raise ValueError(f"unknown receipt kind {kind!r}")
        self.receipts.append(f"{kind}:{ref}")

    def remember_question(self, text: str) -> None:
        """Record the step question the runtime just asked, with the record it was asked on."""
        self.last_question = text
        self.last_question_slots = self.slots

    def asked_already(self, text: str) -> bool:
        """True when those exact words are the last thing the runtime asked and nothing in the
        record has moved since, so asking them again would say nothing new.

        Every path that could speak a fixed question asks this: the tool result, the end of a
        model turn, and the end of a model turn the caller's next words cancelled. The
        rendered text is the identity, because it is what the caller hears — two script keys
        that render to the same sentence are the same sentence twice.
        """
        return bool(text) and text == self.last_question and self.slots == self.last_question_slots
