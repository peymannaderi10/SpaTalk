"""What happens when the model provider fails mid-call.

Founder calls 2026-09-03 21:03 and 21:05 (the second caller of the evening): Google answered
every request with 503 "high demand", Pipecat pushed an ErrorFrame, and the caller heard
nothing until the 45-second idle timeout said goodbye. Two layers now stand between a
transient provider error and silence: the SDK retries the request, and if the turn still
fails the caller hears one fixed sentence asking them to say it again.
"""

from datetime import datetime, timezone
from pathlib import Path

NOW = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def test_both_gemini_clients_retry_transient_errors():
    from spatalk.brain.driver import GeminiClient, gemini_http_options
    from spatalk.settings import Settings
    from spatalk.voice.pipeline import make_llm

    opts = gemini_http_options()
    assert opts.retry_options.attempts == 3
    for status in (429, 500, 502, 503, 504):
        assert status in opts.retry_options.http_status_codes
    assert opts.retry_options.max_delay <= 2.0  # a caller is waiting; no long backoffs on the phone

    voice = make_llm(Settings(_env_file=None, secret_key="s", google_api_key="k", llm_model="gemini-3.5-flash"))
    assert 503 in voice._http_options.retry_options.http_status_codes

    text = GeminiClient("k", "gemini-3.5-flash")
    assert text._http_options.retry_options.attempts == 3


def test_a_model_error_is_answered_with_the_fixed_line_once_per_interval(fixed_clock):
    import uuid

    from pipecat.frames.frames import TTSSpeakFrame

    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.renderer import render_script
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.voice.resilience import APOLOGY_INTERVAL_SECS, apology_for_error
    from spatalk.voice.session import VoiceSession

    cfg = _cfg()
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101")
    session = VoiceSession(ref=ref, cfg=cfg, caps=TierCCapabilities(MemoryLedger(fixed_clock), MemorySms(), fixed_clock), clock=fixed_clock)

    first = apology_for_error(session, cfg, NOW, "503 Service Unavailable", at=100.0)
    assert isinstance(first, TTSSpeakFrame)
    assert first.text == render_script("model_unavailable", cfg, NOW, urgent=False)
    assert first.append_to_context is False
    # The SDK retries produce a burst of errors for one turn: one apology, not four.
    assert apology_for_error(session, cfg, NOW, "503 again", at=100.0 + APOLOGY_INTERVAL_SECS / 2) is None
    assert apology_for_error(session, cfg, NOW, "503 later", at=100.0 + APOLOGY_INTERVAL_SECS + 1) is not None
    session.ended = True
    assert apology_for_error(session, cfg, NOW, "503 after the goodbye", at=200.0) is None


def test_the_model_unavailable_line_is_config_and_asks_the_caller_to_repeat():
    from spatalk.tenants.schema import Scripts

    cfg = _cfg()
    assert "say that once more" in cfg.scripts.model_unavailable
    assert Scripts.model_fields["model_unavailable"].default  # a default exists for tenants without the key
    for claim in ("sent", "booked", "confirmed", "passed it"):
        assert claim not in cfg.scripts.model_unavailable
