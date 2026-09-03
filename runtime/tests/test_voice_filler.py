"""The instant acknowledgement (founder call 2026-09-03: "can we make it reply quicker?").

The model's first token arrives 0.65 to 0.75 s after the caller stops, and nothing on our
side makes that faster (a slimmer prompt saved 50 ms). What the caller feels is the silence,
so the pipeline speaks one short fixed sentence from ``scripts.fillers`` the moment a turn is
handed to the model, and the model is told not to add its own. Fixed wording is config, so the
fillers are scripts, never generated.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from pipecat.frames.frames import LLMContextFrame, TTSSpeakFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import run_test

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
NOW = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


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
    caps = TierCCapabilities(MemoryLedger(fixed_clock), MemorySms(), fixed_clock)
    return VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=fixed_clock)


async def test_filler_speaks_one_fixed_sentence_per_turn_before_the_model_sees_the_context(fixed_clock):
    from spatalk.voice.processors import FillerProcessor

    session = _session(fixed_clock)
    ctx = LLMContext(messages=[{"role": "system", "content": "x"}])
    down, _ = await run_test(
        FillerProcessor(session),
        frames_to_send=[LLMContextFrame(context=ctx), LLMContextFrame(context=ctx)],
        expected_down_frames=[TTSSpeakFrame, LLMContextFrame, TTSSpeakFrame, LLMContextFrame],
        start_timeout=10.0,
    )
    spoken = [f for f in down if isinstance(f, TTSSpeakFrame)]
    assert [f.text for f in spoken] == list(session.cfg.scripts.fillers[:2])
    # Fillers are for the ear, not the record: they never enter the model's context.
    assert all(f.append_to_context is False for f in spoken)


async def test_filler_is_silent_once_the_call_is_ending(fixed_clock):
    from spatalk.voice.processors import FillerProcessor

    session = _session(fixed_clock)
    session.ended = True
    ctx = LLMContext(messages=[{"role": "system", "content": "x"}])
    await run_test(
        FillerProcessor(session),
        frames_to_send=[LLMContextFrame(context=ctx)],
        expected_down_frames=[LLMContextFrame],
        start_timeout=10.0,
    )


def test_fillers_are_short_fixed_wording_in_the_bundle():
    cfg = _cfg()
    assert len(cfg.scripts.fillers) >= 2
    for text in cfg.scripts.fillers:
        assert len(text.split()) <= 3, text
        assert not any(w in text.lower() for w in ("booked", "confirmed", "sent", "done"))


def test_the_prompt_tells_the_model_the_acknowledgement_is_already_spoken():
    from spatalk.brain.prompt import build_system_prompt

    p = build_system_prompt(_cfg(), "voice", NOW).lower()
    assert "already spoken a short acknowledgement" in p
    assert "sure thing" not in p, "the model would double the system's acknowledgement"
