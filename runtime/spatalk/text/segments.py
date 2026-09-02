"""Fit a reply into at most two SMS segments without cutting a sentence in half.

The global constraint for this plan: an SMS reply is at most 300 characters, carries no
markdown, and if the brain returns more it is split at a sentence boundary into at most two
messages and never truncated mid-sentence. Whatever does not fit is dropped and logged; the
alternative is a third message the customer did not ask for.
"""

from __future__ import annotations

import re

from loguru import logger

MAX_PARTS = 2
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text) if s]


def _wrap_words(sentence: str, limit: int) -> list[str]:
    """Break one over-long sentence at word boundaries, so no part exceeds the limit."""
    if len(sentence) <= limit:
        return [sentence]
    chunks: list[str] = []
    current = ""
    for word in sentence.split(" "):
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        # A single token longer than the limit (a very long URL) cannot be kept whole and
        # still be sendable, so it is cut at the limit. Ordinary words never reach this.
        while len(word) > limit:
            chunks.append(word[:limit])
            word = word[limit:]
        current = word
    if current:
        chunks.append(current)
    return chunks


def split_sms(text: str, limit: int = 300) -> list[str]:
    """Split ``text`` into at most two parts of at most ``limit`` characters each."""
    body = " ".join(text.split())
    if not body:
        return []
    if len(body) <= limit:
        return [body]
    units = [chunk for sentence in _sentences(body) for chunk in _wrap_words(sentence, limit)]
    parts: list[str] = []
    current = ""
    dropped: list[str] = []
    for unit in units:
        if dropped:
            dropped.append(unit)
            continue
        candidate = f"{current} {unit}".strip()
        if len(candidate) <= limit:
            current = candidate
            continue
        parts.append(current)
        if len(parts) == MAX_PARTS:
            dropped.append(unit)
            current = ""
        else:
            current = unit
    if current:
        parts.append(current)
    if dropped:
        logger.warning(
            "sms reply longer than {} parts of {} characters; dropped {} characters",
            MAX_PARTS,
            limit,
            len(" ".join(dropped)),
        )
    return parts
