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
