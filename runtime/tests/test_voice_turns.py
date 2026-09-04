"""A caller's short, quiet answer ends the turn, and a silent caller is nudged once.

Founder call 2026-09-03 22:05: after "Have you been in to see us before?" the caller said
"No". The transcriber heard it and opened a turn, but the voice-activity detector never
registered the word as speech, and the only thing that closed a turn was the detector
saying the caller had stopped. Soniox kept re-sending the same provisional "No." every
second, each one re-arming the aggregator's five-second safety timer, so the turn hung for
twenty seconds until the caller said "No" again, louder.

Four settings and one small processor rule close that class of failure, and the founder's
question "what if they don't reply for a while, should we ask again?" is answered with one
fixed line after ten seconds and the goodbye after the next ten.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.tests.utils import SleepFrame, run_test

NOW = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def _session(fixed_clock):
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.voice.session import VoiceSession

    cfg = _cfg()
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101")
    return VoiceSession(ref=ref, cfg=cfg, caps=TierCCapabilities(MemoryLedger(fixed_clock), MemorySms(), fixed_clock), clock=fixed_clock)


def test_the_detector_hears_a_short_quiet_word_and_the_watchdog_is_two_seconds():
    from spatalk.voice.pipeline import (
        IDLE_NUDGE_SECS,
        TURN_STOP_WATCHDOG_SECS,
        VAD_CONFIDENCE,
        VAD_MIN_VOLUME,
        VAD_START_SECS,
        user_turn_params,
    )

    params = user_turn_params()
    vad = params.vad_analyzer.params
    assert vad.confidence == VAD_CONFIDENCE <= 0.6
    assert vad.start_secs == VAD_START_SECS <= 0.15
    assert vad.min_volume == VAD_MIN_VOLUME <= 0.4
    assert params.user_turn_stop_timeout == TURN_STOP_WATCHDOG_SECS == 2.0
    assert params.user_idle_timeout == IDLE_NUDGE_SECS == 10.0


def test_soniox_finalizes_a_pause_on_its_own():
    """A finalized transcript reaches the aggregator even when the detector missed the speech."""
    from spatalk.settings import Settings
    from spatalk.voice.pipeline import SONIOX_ENDPOINT_DELAY_MS, make_stt

    stt = make_stt(Settings(_env_file=None, secret_key="s", soniox_api_key="k", stt_provider="soniox"))
    assert stt._settings.max_endpoint_delay_ms == SONIOX_ENDPOINT_DELAY_MS <= 1000
    assert stt._settings.endpoint_latency_adjustment_level is not None


async def test_a_repeated_provisional_transcript_is_forwarded_once(fixed_clock):
    """Soniox re-sends the same interim every second; each copy re-armed the turn watchdog."""
    from spatalk.voice.processors import RulesGateProcessor

    session = _session(fixed_clock)
    frames = [
        InterimTranscriptionFrame(text="No.", user_id="u", timestamp="t"),
        InterimTranscriptionFrame(text="No.", user_id="u", timestamp="t"),
        InterimTranscriptionFrame(text="No.", user_id="u", timestamp="t"),
        InterimTranscriptionFrame(text="No, thanks.", user_id="u", timestamp="t"),
    ]
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=frames,
        expected_down_frames=[InterimTranscriptionFrame, InterimTranscriptionFrame],
        start_timeout=10.0,
    )
    assert [f.text for f in down] == ["No.", "No, thanks."]


async def test_a_stale_provisional_transcript_becomes_final(fixed_clock):
    """When no final arrives for a while, the last interim is promoted so the turn can close
    with the caller's words in it, instead of hanging or closing empty."""
    from spatalk.voice import processors
    from spatalk.voice.processors import RulesGateProcessor

    session = _session(fixed_clock)
    frames = [
        InterimTranscriptionFrame(text="No.", user_id="u", timestamp="t"),
        SleepFrame(sleep=processors.STALE_INTERIM_SECS + 0.5),
    ]
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=frames,
        expected_down_frames=[InterimTranscriptionFrame, TranscriptionFrame],
        start_timeout=10.0,
    )
    assert isinstance(down[-1], TranscriptionFrame) and down[-1].text == "No."


async def test_a_final_transcript_cancels_the_promotion(fixed_clock):
    from spatalk.voice import processors
    from spatalk.voice.processors import RulesGateProcessor

    session = _session(fixed_clock)
    frames = [
        InterimTranscriptionFrame(text="No.", user_id="u", timestamp="t"),
        TranscriptionFrame(text="No, it's my first time.", user_id="u", timestamp="t"),
        SleepFrame(sleep=processors.STALE_INTERIM_SECS + 0.5),
    ]
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=frames,
        expected_down_frames=[InterimTranscriptionFrame, TranscriptionFrame],
        start_timeout=10.0,
    )
    assert [f.text for f in down] == ["No.", "No, it's my first time."]


def test_a_silent_caller_is_nudged_once_then_let_go(fixed_clock):
    from pipecat.frames.frames import EndFrame, TTSSpeakFrame

    from spatalk.brain.renderer import render_script
    from spatalk.voice.resilience import idle_frames

    cfg = _cfg()
    session = _session(fixed_clock)
    first = idle_frames(session, cfg, NOW)
    assert len(first) == 1 and isinstance(first[0], TTSSpeakFrame)
    assert first[0].text == render_script("still_there", cfg, NOW, urgent=False)
    assert not session.ended
    second = idle_frames(session, cfg, NOW)
    assert [type(f) for f in second] == [TTSSpeakFrame, EndFrame]
    assert second[0].text == render_script("goodbye", cfg, NOW, urgent=False)
    assert session.ended
    assert idle_frames(session, cfg, NOW) == []


async def test_the_callers_next_words_reset_the_nudge_count(fixed_clock):
    from spatalk.voice.processors import RulesGateProcessor
    from spatalk.voice.resilience import idle_frames

    session = _session(fixed_clock)
    idle_frames(session, session.cfg, NOW)
    assert session.idle_nudges == 1
    await run_test(
        RulesGateProcessor(session),
        frames_to_send=[TranscriptionFrame(text="Sorry, yes, a facial.", user_id="u", timestamp="t")],
        expected_down_frames=[TranscriptionFrame],
        start_timeout=10.0,
    )
    assert session.idle_nudges == 0


def test_the_still_there_line_is_config_and_claims_nothing():
    from spatalk.tenants.schema import Scripts

    cfg = _cfg()
    assert "still there" in cfg.scripts.still_there.lower()
    assert Scripts.model_fields["still_there"].default
    for claim in ("sent", "booked", "confirmed", "passed it"):
        assert claim not in cfg.scripts.still_there
