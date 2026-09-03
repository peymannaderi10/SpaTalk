"""Layer 3 of structural honesty: a lexical output guard.

Every model-generated utterance passes through :func:`guard` before it reaches a
channel. If the sentence claims a completed action and no ``Completed`` outcome
was actually produced this turn, the sentence is replaced wholesale. The guard is
deliberately lexical and deterministic: no model decides whether a claim is true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from spatalk.tenants.schema import TenantConfig

DEFAULT_COMPLETION_LEXICON = [
    "booked", "booked you", "is booked", "confirmed", "is confirmed", "is scheduled", "scheduled you",
    "cancelled your", "canceled your", "moved your", "rescheduled", "changed your appointment",
    "you're all set", "you are all set", "all set for", "see you on", "see you at",
]


# "Help you get that booked" is an offer, not a claim (founder call 2026-09-03: the guard
# replaced exactly that sentence with the cannot_complete script and filed a phantom item).
# An intent verb a few words before the completion word turns it into a future the team
# will carry out, so the word is masked before the lexicon runs. Past and present claims
# ("I've booked you", "I got you booked in", "you're all booked") carry no such verb and
# stay blocked. Only forward-looking verbs qualify: "got" and "have" are claims.
INTENT_BEFORE_COMPLETION = re.compile(
    r"\b(?:get|getting|help(?:ing)?(?: you)?(?: get)?|want(?:s|ed)?(?: to get)?|to get|let'?s get)"
    r"\b[^.!?]{0,20}?\b(booked|scheduled|confirmed)\b",
    re.IGNORECASE,
)


def _mask_intent(text: str) -> str:
    return INTENT_BEFORE_COMPLETION.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + "arranged", text)


@dataclass(frozen=True)
class GuardResult:
    text: str
    blocked: bool
    matched: str | None


def _pattern(terms: list[str]) -> re.Pattern:
    alts = "|".join(re.escape(t) for t in sorted(set(terms), key=len))
    return re.compile(rf"(?<![\w-])(?:{alts})(?![\w-])", re.IGNORECASE)


def guard(text: str, has_completed: bool, cfg: TenantConfig, replacement: str) -> GuardResult:
    if has_completed:
        return GuardResult(text, False, None)
    m = _pattern(DEFAULT_COMPLETION_LEXICON + list(cfg.lexicons.completion)).search(
        _mask_intent(text)
    )
    if m:
        return GuardResult(replacement, True, m.group(0).lower())
    return GuardResult(text, False, None)
