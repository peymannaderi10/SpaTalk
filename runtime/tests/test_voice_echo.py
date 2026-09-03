"""Echo scrubbing (founder call 2026-09-03).

The assistant's greeting came back through the caller's phone and was transcribed as the
caller's first words: "Thanks for calling Skid Subjects. Hey, I'm Ava. I'm looking to get
some information ...". The scrub trims that echoed prefix, drops a transcription that is
nothing but echo, and leaves a caller's genuine words alone, including words that also
appear in what the assistant said.
"""

import uuid

from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.tests.utils import run_test

GREETING = (
    "Hi there, thanks for calling Skincentrix! I'm Ava, the clinic's AI assistant. "
    "What can I help you with today?"
)


def test_the_real_echo_is_trimmed_and_the_callers_words_survive():
    from spatalk.voice.echo import scrub_echo

    heard = (
        "Thanks for calling Skid Subjects. Hey, I'm Ava. I'm looking to get some information "
        "about what you guys do, what kind of services you have."
    )
    assert scrub_echo(heard, GREETING) == (
        "I'm looking to get some information about what you guys do, what kind of services you have."
    )


def test_a_transcription_that_is_only_echo_becomes_empty():
    from spatalk.voice.echo import scrub_echo

    assert scrub_echo("Hi there thanks for calling Skincentrix I'm Ava the clinic's AI assistant", GREETING) == ""


def test_genuine_speech_is_untouched_even_when_it_repeats_the_assistants_words():
    from spatalk.voice.echo import scrub_echo

    bot = "The Skincentrix Classic facial is a hundred and twenty-five dollars. Which one sounds right?"
    for said in (
        "I want the classic facial please.",
        "How much is the classic facial with the team?",
        "Um, yeah, the first one you said.",
        "Is it safe to do a peel while pregnant?",
    ):
        assert scrub_echo(said, bot) == said, said
    assert scrub_echo("Hello, I'd like to book.", "") == "Hello, I'd like to book."


def test_remember_keeps_only_the_recent_tail():
    from spatalk.voice.echo import RECENT_WORDS, remember

    recent = ""
    for i in range(40):
        recent = remember(recent, f"sentence number {i} with several more words in it here")
    assert len(recent.split()) == RECENT_WORDS
    assert recent.endswith("here")


def _session(fixed_clock):
    from pathlib import Path

    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.session import VoiceSession

    cfg = load_bundle(Path(__file__).resolve().parents[1] / "tenants" / "skincentrix")
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101")
    caps = TierCCapabilities(MemoryLedger(fixed_clock), MemorySms(), fixed_clock)
    return VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=fixed_clock)


async def test_the_rules_gate_drops_pure_echo_and_forwards_the_trimmed_rest(fixed_clock):
    from spatalk.voice.processors import RulesGateProcessor

    session = _session(fixed_clock)
    session.remember_spoken(GREETING)
    frames = [
        InterimTranscriptionFrame(text="Hi there thanks for calling", user_id="u", timestamp="t"),
        TranscriptionFrame(text="Thanks for calling Skid Subjects. Hey, I'm Ava. How much is a facial?", user_id="u", timestamp="t"),
    ]
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=frames,
        expected_down_frames=[TranscriptionFrame],
        start_timeout=10.0,
    )
    assert down[0].text == "How much is a facial?"


def test_the_guard_remembers_what_it_let_through_for_the_scrubber(fixed_clock):
    from spatalk.voice.session import VoiceSession

    session = _session(fixed_clock)
    assert isinstance(session, VoiceSession) and session.recent_bot_text == ""
    session.remember_spoken("[warm] We have some wonderful options!")
    assert "wonderful options" in session.recent_bot_text and "[warm]" not in session.recent_bot_text
