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
    session.cfg = session.cfg.model_copy(
        update={"scripts": session.cfg.scripts.model_copy(update={"fillers": ["Okay, let me check.", "Alright, one moment."]})}
    )
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


async def test_skincentrix_has_no_fillers_and_the_processor_stays_silent(fixed_clock):
    """Founder decision 2026-09-03: no "Okay" or "One moment"; the model's first words do it."""
    from spatalk.tenants.schema import Scripts
    from spatalk.voice.processors import FillerProcessor

    cfg = _cfg()
    assert cfg.scripts.fillers == []
    assert Scripts.model_fields["fillers"].default_factory() == []
    session = _session(fixed_clock)
    ctx = LLMContext(messages=[{"role": "system", "content": "x"}])
    await run_test(
        FillerProcessor(session),
        frames_to_send=[LLMContextFrame(context=ctx)],
        expected_down_frames=[LLMContextFrame],
        start_timeout=10.0,
    )


def test_the_prompt_matches_whether_fillers_are_on():
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    without = build_system_prompt(cfg, "voice", NOW).lower()
    assert "open with a brief acknowledgement" in without
    assert "already spoken" not in without
    assert "no preambles" in without and "lead with the specifics" in without

    with_fillers = cfg.model_copy(update={"scripts": cfg.scripts.model_copy(update={"fillers": ["Okay, let me check."]})})
    on = build_system_prompt(with_fillers, "voice", NOW).lower()
    assert "already spoken a short acknowledgement" in on
    assert "sure thing" not in on, "the model would double the system's acknowledgement"
