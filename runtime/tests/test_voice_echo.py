"""Echo scrubbing (founder call 2026-09-03).

The assistant's greeting came back through the caller's phone and was transcribed as the
caller's first words: "Thanks for calling Skid Subjects. Hey, I'm Ava. I'm looking to get
some information ...". The scrub trims that echoed prefix, drops a transcription that is
nothing but echo, and leaves a caller's genuine words alone, including words that also
appear in what the assistant said.
"""

import uuid

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.tests.utils import SleepFrame, run_test

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


def test_a_match_that_starts_after_the_first_words_is_the_caller_not_echo():
    """Echo is what the phone heard first, so it is a prefix. A run of the assistant's words
    that only begins three or four words in is the caller repeating the assistant's phrasing
    (founder call 2026-09-03 15:56: "Um, have the team give me a call" was dropped)."""
    from spatalk.voice.echo import scrub_echo

    bot = (
        "I can text you the online booking link right now so you can choose your spot, "
        "or I can have our team give you a call to set it up. Which would you prefer?"
    )
    for said in (
        "Um, have the team give me a call if you can.",
        "Wait, what about have our team give you a call?",
    ):
        assert scrub_echo(said, bot) == said, said
    bot = "Our Mirapeel facial with LED and microcurrent is two ninety-five."
    said = "Wait, what about the Mirapeel facial with LED?"
    assert scrub_echo(said, bot) == said


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


def _gate(session, monotonic=None):
    from spatalk.voice.processors import RulesGateProcessor

    return RulesGateProcessor(session, monotonic=monotonic or (lambda: 50.0))


async def test_the_rules_gate_scrubs_what_was_heard_while_the_assistant_was_speaking(fixed_clock):
    session = _session(fixed_clock)
    session.remember_spoken(GREETING)
    frames = [
        BotStartedSpeakingFrame(),
        InterimTranscriptionFrame(text="Hi there thanks for calling", user_id="u", timestamp="t"),
        TranscriptionFrame(text="Thanks for calling Skid Subjects. Hey, I'm Ava. How much is a facial?", user_id="u", timestamp="t"),
    ]
    down, _ = await run_test(
        _gate(session),
        frames_to_send=frames,
        expected_down_frames=[BotStartedSpeakingFrame, TranscriptionFrame],
        start_timeout=10.0,
    )
    assert [f.text for f in down if isinstance(f, TranscriptionFrame)] == ["How much is a facial?"]


async def test_echo_arriving_just_after_the_assistant_stopped_is_still_scrubbed(fixed_clock):
    """The last of the assistant's audio is still on its way back when BotStoppedSpeaking fires."""
    session = _session(fixed_clock)
    session.remember_spoken(GREETING)
    frames = [
        BotStartedSpeakingFrame(),
        BotStoppedSpeakingFrame(),
        TranscriptionFrame(text="Hi there thanks for calling Skincentrix I'm Ava the clinic's AI assistant", user_id="u", timestamp="t"),
    ]
    await run_test(
        _gate(session, lambda: 50.0),  # the clock does not move: the words arrived at once
        frames_to_send=frames,
        expected_down_frames=[BotStartedSpeakingFrame, BotStoppedSpeakingFrame],
        start_timeout=10.0,
    )


async def test_a_callers_answer_after_the_assistant_finished_is_never_echo(fixed_clock):
    """Founder call 2026-09-03 15:56: "I'd prefer a call from the team", said three seconds
    after "would you prefer a call from the team?", was dropped as echo, so the assistant had
    nothing to answer and fell silent. Whatever the words, speech that starts after the
    assistant's audio has finished is the caller."""
    session = _session(fixed_clock)
    session.remember_spoken(
        "Would you like me to text you that booking link so you can browse all our options, "
        "or would you prefer a call from the team?"
    )
    now = [0.0]

    def monotonic():
        now[0] += 2.0  # every look at the clock is two seconds later than the last
        return now[0]

    frames = [
        BotStartedSpeakingFrame(),
        BotStoppedSpeakingFrame(),
        TranscriptionFrame(text="I'd prefer a call from the team.", user_id="u", timestamp="t"),
    ]
    down, _ = await run_test(
        _gate(session, monotonic),
        frames_to_send=frames,
        expected_down_frames=[BotStartedSpeakingFrame, BotStoppedSpeakingFrame, TranscriptionFrame],
        start_timeout=10.0,
    )
    assert down[-1].text == "I'd prefer a call from the team."


async def test_the_echo_decision_is_made_once_per_utterance_on_its_first_words(fixed_clock):
    """An utterance whose first interim arrived while the assistant spoke is scrubbed to its
    final transcription, even though that final arrives after the assistant stopped; the next
    utterance is judged afresh."""
    session = _session(fixed_clock)
    session.remember_spoken(GREETING)
    now = [0.0]

    def monotonic():
        now[0] += 2.0
        return now[0]

    frames = [
        BotStartedSpeakingFrame(),
        InterimTranscriptionFrame(text="Hi there thanks for", user_id="u", timestamp="t"),
        # System frames overtake queued transcriptions in the harness; let the interim land
        # before the assistant stops, as it does on a real call.
        SleepFrame(sleep=0.3),
        BotStoppedSpeakingFrame(),
        TranscriptionFrame(text="Hi there thanks for calling Skincentrix. I'm Ava. Do you do peels?", user_id="u", timestamp="t"),
        TranscriptionFrame(text="Hi there, I'm Ava's cousin, I'd like to book.", user_id="u", timestamp="t"),
    ]
    down, _ = await run_test(
        _gate(session, monotonic),
        frames_to_send=frames,
        expected_down_frames=[BotStartedSpeakingFrame, BotStoppedSpeakingFrame, TranscriptionFrame, TranscriptionFrame],
        start_timeout=10.0,
    )
    texts = [f.text for f in down if isinstance(f, TranscriptionFrame)]
    assert texts == ["Do you do peels?", "Hi there, I'm Ava's cousin, I'd like to book."]


def test_the_guard_remembers_what_it_let_through_for_the_scrubber(fixed_clock):
    from spatalk.voice.session import VoiceSession

    session = _session(fixed_clock)
    assert isinstance(session, VoiceSession) and session.recent_bot_text == ""
    session.remember_spoken("[warm] We have some wonderful options!")
    assert "wonderful options" in session.recent_bot_text and "[warm]" not in session.recent_bot_text
