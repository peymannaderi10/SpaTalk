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
from pipecat.frames.frames import TTSSpeakFrame

from spatalk.brain.renderer import render_script
from spatalk.tenants.schema import TenantConfig
from spatalk.voice.session import VoiceSession

# One apology per burst: the SDK's retries and the aggregator's re-sends can raise several
# errors for a single turn within a few seconds.
APOLOGY_INTERVAL_SECS = 10.0


def apology_for_error(
    session: VoiceSession,
    cfg: TenantConfig,
    now: datetime,
    error: str,
    at: float | None = None,
) -> TTSSpeakFrame | None:
    """The frame to speak for a pipeline error, or ``None`` when nothing should be said."""
    if session.ended:
        return None
    t = time.monotonic() if at is None else at
    if session.last_apology_at is not None and t - session.last_apology_at < APOLOGY_INTERVAL_SECS:
        logger.warning("model error within the apology interval, not repeated: {}", error[:160])
        return None
    session.last_apology_at = t
    logger.warning("model error spoken to the caller: {}", error[:200])
    return TTSSpeakFrame(
        text=render_script("model_unavailable", cfg, now, urgent=False), append_to_context=False
    )
