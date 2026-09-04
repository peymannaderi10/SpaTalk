"""Per-call state shared by the processors, the tool handlers and the observers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from spatalk.brain.capabilities import Capabilities
from spatalk.brain.requests import ConversationRef
from spatalk.clock import Clock
from spatalk.tenants.schema import TenantConfig


@dataclass
class VoiceSession:
    ref: ConversationRef
    cfg: TenantConfig
    caps: Capabilities
    clock: Clock
    worker: Any = None
    # True only once a Tier A adapter has actually completed something this call.
    has_completed: bool = False
    band: int = 1
    ended: bool = False
    guard_blocks: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    usage: dict[str, float] = field(
        default_factory=lambda: {
            "tts_chars": 0.0,
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
