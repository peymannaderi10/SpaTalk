"""What the caller hears when the model fails (founder calls 2026-09-03 21:03 and 21:05).

Google answered every request with 503 "high demand"; Pipecat pushed an ErrorFrame and the
caller heard nothing for forty-five seconds, then the goodbye. The SDK now retries transient
statuses (spatalk.brain.driver.gemini_http_options); when a turn still fails, the pipeline's
``on_pipeline_error`` handler speaks the tenant's fixed ``model_unavailable`` line, once per
interval, so a burst of retries is one apology. The line asks the caller to repeat, and the
repeat is a new turn the model is asked again.

Fixed wording is config (CLAUDE.md non-negotiable 3): the sentence comes from the tenant's
scripts, and it never claims anything was filed or sent.
"""

from __future__ import annotations

import time
from datetime import datetime

from loguru import logger
from pipecat.frames.frames import EndFrame, Frame, TTSSpeakFrame

from spatalk.brain.renderer import render_script
from spatalk.tenants.schema import TenantConfig
from spatalk.voice.session import VoiceSession

# One apology per burst: the SDK's retries and the aggregator's re-sends can raise several
# errors for a single turn within a few seconds.
APOLOGY_INTERVAL_SECS = 10.0
# Failed turns in a row, with no turn the model answered in between, before the caller is
# given the clinic's own number and the call ends (llm failover plan, Task F2). Two: the
# first is a bad moment worth asking the caller to repeat through, the second is an outage
# neither vendor is going to get the caller out of.
MODEL_DOWN_AFTER_TURNS = 2


def apology_for_error(
    session: VoiceSession,
    cfg: TenantConfig,
    now: datetime,
    error: str,
    at: float | None = None,
) -> TTSSpeakFrame | None:
    """The frame to speak for a pipeline error, or ``None`` when nothing should be said.

    On the second failed turn in a row, with no turn the model answered in between, the line
    is ``model_down`` instead: the caller is given the clinic's own number and
    ``session.ended`` is set, because a loop of apologies wastes a person's evening while
    promising them nothing (llm failover plan, Task F2).
    """
    if session.ended:
        return None
    t = time.monotonic() if at is None else at
    # One apology per *turn*, not per error: the SDK's retries and the aggregator's re-sends
    # produce several errors within a few seconds for a single turn. A fresh completion
    # (LLMFullResponseStartFrame, seen by the output guard) is what opens the next turn.
    within_interval = (
        session.last_apology_at is not None
        and t - session.last_apology_at < APOLOGY_INTERVAL_SECS
    )
    if within_interval and not session.model_turn_open:
        logger.warning("model error within the apology interval, not repeated: {}", error[:160])
        return None
    session.last_apology_at = t
    session.model_turn_open = False
    session.model_failures += 1
    if session.model_failures >= MODEL_DOWN_AFTER_TURNS:
        session.ended = True
        logger.error(
            "model failed {} turns in a row; ending the call on the clinic's number: {}",
            session.model_failures,
            error[:200],
        )
        return TTSSpeakFrame(
            text=render_script("model_down", cfg, now, urgent=False), append_to_context=False
        )
    logger.warning("model error spoken to the caller: {}", error[:200])
    return TTSSpeakFrame(
        text=render_script("model_unavailable", cfg, now, urgent=False), append_to_context=False
    )


def error_frames(
    session: VoiceSession,
    cfg: TenantConfig,
    now: datetime,
    error: str,
    at: float | None = None,
) -> list[Frame]:
    """Everything to queue for one pipeline error: nothing, an apology, or a goodbye.

    The ``model_down`` line is followed by an ``EndFrame``, the same shape the idle-timeout
    goodbye uses, so the caller hears the sentence and then the call ends rather than
    sitting in silence until the timeout.
    """
    spoken = apology_for_error(session, cfg, now, error, at=at)
    if spoken is None:
        return []
    return [spoken, EndFrame()] if session.ended else [spoken]
