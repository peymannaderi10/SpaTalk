"""Audio tags for the voice channel (founder request 2026-09-03).

Soniox TTS v2 performs bracketed tags such as ``[cheerful]`` instead of reading them aloud
(probe: the same sentence took 3.75 s plain, 3.84 s with [cheerful], 4.78 s with [laughs]).
The model may use them on voice only; they never reach a text channel or a transcript.
"""

from datetime import datetime, timezone
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
NOW = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def test_strip_audio_tags_removes_known_and_unknown_tags_and_tidies_spacing():
    from spatalk.brain.audio_tags import strip_audio_tags

    assert strip_audio_tags("[cheerful] Hi there! [warm] How can I help?") == "Hi there! How can I help?"
    assert strip_audio_tags("[zorblax] Hello") == "Hello"
    assert strip_audio_tags("Sure thing. [laughs] That one's popular.") == "Sure thing. That one's popular."
    assert strip_audio_tags("No tags here.") == "No tags here."
    # Square brackets that are not a tag (a number, a URL fragment) are left alone.
    assert strip_audio_tags("Suite [12] on the left") == "Suite [12] on the left"


def test_the_voice_prompt_offers_the_tag_list_and_the_text_prompts_do_not():
    from spatalk.brain.audio_tags import AUDIO_TAGS
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    voice = build_system_prompt(cfg, "voice", NOW)
    assert "[cheerful]" in voice and all(f"[{t}]" in voice for t in AUDIO_TAGS)
    assert "acknowledgement" in voice.lower()
    for channel in ("sms", "chat", "instagram"):
        text = build_system_prompt(cfg, channel, NOW)
        assert "[cheerful]" not in text and "audio tag" not in text.lower()


def test_the_disclosure_carries_a_tag_for_voice_and_loses_it_for_text():
    from spatalk.brain.audio_tags import strip_audio_tags

    cfg = _cfg()
    assert cfg.scripts.disclosure.startswith("[")
    plain = strip_audio_tags(cfg.scripts.disclosure)
    assert plain.startswith("Hi there") and "AI assistant" in plain


def test_a_bracket_that_is_not_an_audio_tag_is_dropped_before_the_voice():
    """Call on gpt-4.1-nano, 2026-09-03 21:42: the model wrote "[end_conversation]" as text
    instead of calling the tool, and Soniox read the tool name aloud. Only the audio tags the
    voice performs may reach TTS in brackets; anything else in brackets is not speech."""
    from spatalk.brain.audio_tags import drop_unknown_tags

    assert drop_unknown_tags("[end_conversation]") == ""
    assert drop_unknown_tags("[warm] Hello! [capture_request] Anything else?") == "[warm] Hello! Anything else?"
    assert drop_unknown_tags("[warm] Hello there.") == "[warm] Hello there."
    assert drop_unknown_tags("Prices from [two ninety-five] and up.") == "Prices from and up."
    assert drop_unknown_tags("") == ""


async def test_the_guard_never_speaks_a_bracketed_tool_name(fixed_clock):
    import uuid

    from pipecat.frames.frames import (
        LLMFullResponseEndFrame,
        LLMFullResponseStartFrame,
        LLMTextFrame,
    )
    from pipecat.tests.utils import run_test

    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.processors import OutputGuardProcessor
    from spatalk.voice.session import VoiceSession

    cfg = load_bundle(BUNDLE)
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101")
    session = VoiceSession(ref=ref, cfg=cfg, caps=TierCCapabilities(MemoryLedger(fixed_clock), MemorySms(), fixed_clock), clock=fixed_clock)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("[warm] Thanks! "), LLMTextFrame("[end_conversation]"), LLMFullResponseEndFrame()]
    down, _ = await run_test(
        OutputGuardProcessor(session),
        frames_to_send=frames,
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        start_timeout=10.0,
    )
    spoken = [f.text for f in down if isinstance(f, LLMTextFrame)]
    assert spoken == ["[warm] Thanks! "]
