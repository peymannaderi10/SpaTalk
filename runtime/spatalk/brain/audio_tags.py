"""Audio tags: bracketed delivery directions for the voice channel.

Soniox TTS v2 performs a tag such as ``[cheerful]`` or ``[laughs]`` instead of reading it
aloud (verified 2026-09-03 by synthesis: plain 3.75 s, [cheerful] 3.84 s, [laughs] 4.78 s,
an unknown tag 3.93 s). The model may place them on voice replies; fixed scripts may carry
them too. They are stripped before a reply reaches a text channel or a transcript, so a
tag is never something a customer reads.
"""

from __future__ import annotations

import re

# The tags the prompt offers. Kept small on purpose: delivery colour, not theatre.
AUDIO_TAGS: tuple[str, ...] = (
    "cheerful", "warm", "reassuring", "curious", "thoughtful", "apologetic", "laughs",
)

# A tag is one or two lowercase words in square brackets, e.g. [warm] or [softly laughs].
_TAG = re.compile(r"\[(?:[a-z]+)(?: [a-z]+)?\]\s*")


def strip_audio_tags(text: str) -> str:
    """Remove every bracketed tag and tidy the spacing left behind."""
    cleaned = _TAG.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


# Anything in square brackets that is not one of the performed tags: a tool name a small
# model wrote as text ("[end_conversation]", call on gpt-4.1-nano 2026-09-03 21:42), a
# stage direction, a bracketed aside. None of it is speech.
_ANY_TAG = re.compile(r"\[[^\]\n]{1,60}\]\s*")


def drop_unknown_tags(text: str) -> str:
    """Remove every bracketed token that is not a known audio tag; known tags stay."""

    def keep_or_drop(match: re.Match) -> str:
        inner = match.group(0).strip()[1:-1].strip().lower()
        return match.group(0) if inner in AUDIO_TAGS else ""

    return _ANY_TAG.sub(keep_or_drop, text or "").strip() if text else text
