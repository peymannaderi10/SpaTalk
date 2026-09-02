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
