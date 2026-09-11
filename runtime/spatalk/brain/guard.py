"""Layer 3 of structural honesty: a lexical output guard.

Every model-generated utterance passes through :func:`guard` before it reaches a
channel. If the sentence claims a completed action and no ``Completed`` outcome
was actually produced this turn, the sentence is replaced wholesale. The guard is
deliberately lexical and deterministic: no model decides whether a claim is true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

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


# An outcome-implying stall (memo §3.2; OpenAI's chat-supervisor filler clause, quoted in
# OSS §8.2): a holding phrase "must NOT indicate whether you can or cannot fulfill an
# action; they should be neutral and not imply any outcome." The assistant cannot book,
# schedule, cancel, reschedule, confirm, file or send, so "let me book that for you" is a
# claim with a delay in front of it. Narrow on purpose: first person singular and immediate
# ("let me", "I'll", "I'm going to", "one moment while I"), never "let's" or "we", so an
# offer the *team* will carry out is untouched. A bare "I'm" is deliberately absent: with a
# gerund it is a present-progressive claim, not a stall, and two of the tenant's own outcome
# scripts are exactly that ("I'm sending a request to the team", "I'm flagging it to the
# team as urgent") — those are receipts, judged below, not stalls.
_STALL_MARKER = (
    r"let me|lemme|i'?ll(?:\s+just|\s+go\s+ahead\s+and)?|i\s?am\s+going\s+to|i'?m\s+going\s+to"
    r"|(?:one\s+moment|hold\s+on|bear\s+with\s+me|give\s+me\s+(?:a|one)\s+\w+)"
    r"(?:\s*,)?\s*(?:while|and)\s+i(?:'?ll)?"
)
_STALL_ACTION = (
    r"book|booking|schedule|scheduling|cancel|cancelling|canceling|reschedule|rescheduling"
    r"|confirm|confirming|file|filing|send|sending|text|texting"
    r"|put\s+you\s+(?:in|down)|pop\s+you\s+(?:in|down)|add\s+you|pencil\s+you|sign\s+you\s+up"
)
STALL_BEFORE_ACTION = re.compile(
    rf"(?<![\w-])(?:{_STALL_MARKER})\b[^.!?]{{0,24}}?\b(?:{_STALL_ACTION})(?![\w-])",
    re.IGNORECASE,
)

# Someone else between the marker and the action moves the actor, and an act the *team*
# carries out is an offer however it is introduced: "I'll have the team send you the booking
# link" is `scripts.link_captured`, which has to reach the caller.
STALL_DELEGATION = re.compile(
    r"(?<![\w-])(?:the\s+team|the\s+clinic|someone|somebody|them|a\s+member)(?![\w-])",
    re.IGNORECASE,
)

# Kept as a list beside the pattern so a reader can see the shape the pattern is for, and so
# a tenant-specific addition has an obvious home if one is ever needed.
DEFAULT_STALL_LEXICON = [
    "let me book", "let me schedule", "let me cancel", "let me file that",
    "one moment while i book", "i'll just put you down", "i'm going to schedule",
    "hold on while i cancel", "let me add you",
]

# An assertion that something has already been filed, sent or passed on. The completion
# lexicon never covered these: they claim a *filing*, not a booking, and they are what a
# confidently phrased model reaches for when it has called no tool at all. Blocked unless
# the conversation holds a receipt — an item the ledger issued, a link the provider
# accepted, a leg the carrier took (memo §3.3, OSS §8.4(g)).
#
# Two rules keep the false-positive rate down. The match is anchored the way the completion
# lexicon is — `_pattern`'s `(?<![\w-])…(?![\w-])` word boundaries — so `refuse_no_name`
# ("Before I pass that to the team, could I get your first name?") does not match
# "i've passed" and is not a receipt. And a sentence that negates the claim is not a claim:
# `refuse_unavailable` carries no receipt phrase at all, so no negation detector is needed
# today and none is added on speculation.
DEFAULT_RECEIPT_LEXICON = [
    "i've passed", "i have passed", "i've sent", "i have sent", "i've filed", "i have filed",
    "i've flagged", "i have flagged", "i've texted", "i have texted", "i've messaged",
    "i've noted", "i have noted", "i've made a note", "i've let the team know",
    "i've added you", "i'm sending a request", "i'm flagging it",
    "passed that to the team", "sent that to the team", "sent an urgent request",
    "your request is in", "that's with the team", "the request is in",
]


@dataclass(frozen=True)
class GuardResult:
    text: str
    blocked: bool
    matched: str | None
    # Which family fired, for the signal log and the log line. None when nothing did.
    family: Literal["completion", "stall", "receipt"] | None = None


def _pattern(terms: list[str]) -> re.Pattern:
    alts = "|".join(re.escape(t) for t in sorted(set(terms), key=len))
    return re.compile(rf"(?<![\w-])(?:{alts})(?![\w-])", re.IGNORECASE)


def _stall(text: str) -> re.Match | None:
    """The first outcome-implying stall in `text`, skipping the ones that delegate."""
    for m in STALL_BEFORE_ACTION.finditer(text):
        if not STALL_DELEGATION.search(m.group(0)):
            return m
    return None


def guard(
    text: str,
    has_completed: bool,
    cfg: TenantConfig,
    replacement: str,
    *,
    receipts: int = 0,
) -> GuardResult:
    """Layer 3. `receipts` is how many actions this conversation can actually show for
    itself — items the ledger issued, a link the provider accepted, a leg the carrier took.
    An utterance that asserts one and cannot be backed by one is replaced, whoever wrote it
    (memo §3.3). The default of 0 is the honest default: nothing has been done yet.

    The order matters. The stall check runs before `_mask_intent`, or "let me get that
    booked" is masked into an offer and never seen; and a stall is blocked *even with* a
    receipt and even with `has_completed`, because "let me book that" is never true on this
    system and a receipt for an item is not a licence to claim a booking.
    """
    stall = _stall(text)
    if stall:
        return GuardResult(replacement, True, stall.group(0).lower().strip(), "stall")
    if not (has_completed or receipts):
        m = _pattern(DEFAULT_RECEIPT_LEXICON).search(text)
        if m:
            return GuardResult(replacement, True, m.group(0).lower(), "receipt")
    if has_completed:
        return GuardResult(text, False, None)
    m = _pattern(DEFAULT_COMPLETION_LEXICON + list(cfg.lexicons.completion)).search(
        _mask_intent(text)
    )
    if m:
        return GuardResult(replacement, True, m.group(0).lower(), "completion")
    return GuardResult(text, False, None)
