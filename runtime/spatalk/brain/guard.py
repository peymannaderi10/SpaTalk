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
    m = _pattern(DEFAULT_COMPLETION_LEXICON + list(cfg.lexicons.completion)).search(text)
    if m:
        return GuardResult(replacement, True, m.group(0).lower())
    return GuardResult(text, False, None)
