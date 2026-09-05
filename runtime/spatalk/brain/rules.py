"""Deterministic rules gate: the band-3 escalation triggers, applied before any model.

Two distinct lexical questions are answered here, and they must not be confused:

* :func:`rules_gate` — does the caller need a human *now*? A symptom, a safety
  question, a complaint, a payment detail or an explicit request for a person all
  stop the assistant and hand the turn to fixed tenant wording.
* :func:`health_context_mentioned` — did the caller volunteer a condition,
  medication, pregnancy or past procedure? That is a flag on the conversation and
  the item so staff know to read the transcript. It never gates the request, and
  the detail itself never leaves the transcript.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spatalk.tenants.schema import TenantConfig

if TYPE_CHECKING:  # pragma: no cover - the reason vocabulary is owned by requests.py (Task 4)
    from spatalk.brain.requests import EscalateReason

DEFAULT_LEXICONS: dict[str, list[str]] = {
    # Life-threatening, or the caller says it is: the one gate whose script says 911 (founder
    # decision 2026-09-05). Checked before every other lexicon, so "I can't breathe, get me a
    # person" is answered with the 911 line and not the callback promise.
    "emergency": ["can't breathe", "cannot breathe", "can not breathe", "not breathing", "trouble breathing",
                  "difficulty breathing", "anaphylaxis", "anaphylactic", "allergic reaction", "chest pain",
                  "severe swelling", "throat closing", "throat is closing", "throat's closing", "passed out",
                  "fainted", "fainting", "unconscious", "bleeding heavily", "heavy bleeding",
                  "won't stop bleeding", "seizure", "heart attack", "call 911"],
    "human_request": ["speak to a person", "talk to a person", "real person", "a human", "an actual person",
                      "speak to someone", "talk to someone", "speak with someone", "receptionist",
                      "front desk", "staff member", "operator", "transfer me", "call me back please"],
    # Concerns and questions: something is wrong now, or the caller is asking whether something is safe.
    # No pain words: "does the laser hurt?" is a question about the treatment, not a symptom
    # (founder call 2026-09-05 12:20, where "painful" sent a booking question to the clinical script).
    "clinical": ["rash", "burn", "burning", "blister", "swelling", "swollen",
                 "bleeding", "infection", "infected", "reaction", "side effect", "side effects",
                 "bruise", "bruising", "numb", "is it safe", "is that safe", "is this safe", "is it normal",
                 "is that normal", "should i be worried", "after my treatment", "after my session", "post treatment",
                 "after the treatment", "fever", "dizzy", "scar", "scarring", "peeling"],
    "complaint": ["complaint", "complain", "unhappy", "refund", "terrible", "awful", "lawyer", "sue", "legal action"],
    "payment": ["credit card", "card number", "visa", "mastercard", "pay now", "make a payment", "payment",
                "invoice", "charge me", "charged", "billing", "pay over the phone", "pay by phone",
                "pay by card", "card details", "take my card", "give you my card"],
}
# Volunteered context: not a gate. The request proceeds; the conversation and item are flagged so staff read the transcript.
HEALTH_CONTEXT_DEFAULT: list[str] = [
    "pregnant", "pregnancy", "breastfeeding", "nursing", "medication", "medications", "on meds", "diabetes", "diabetic",
    "eczema", "psoriasis", "rosacea", "allergy", "allergies", "allergic to", "botox", "filler", "fillers", "accutane",
    "retinol", "blood thinner", "blood thinners", "diagnosed", "surgery", "condition", "sensitive skin", "keloid",
]
ORDER: list[EscalateReason] = ["emergency", "human_request", "clinical", "complaint", "payment"]

# "Am I talking to a real person?" is a question about the assistant, not a request for a
# person. The words overlap with the human-request lexicon ("real person", "a human"), so
# the identity clause is blanked out before that lexicon runs; the model answers it honestly
# under a prompt rule. A request in the same breath ("are you a bot? get me a person") still
# gates, because only the identity clause is removed, up to the next sentence break.
IDENTITY_QUESTION = re.compile(
    r"\b(?:are|r)\s+you\s+(?:a\s+|an\s+)?(?:real|human|actual|live|robot|bot|machine|computer|"
    r"recording|ai|a\.i\.|person)\b[^.?!]*"
    r"|\bam\s+i\s+(?:speaking|talking|chatting)\s+(?:to|with)\s+(?:a\s+|an\s+)?"
    r"(?:real\s+|human\s+|actual\s+|live\s+)?(?:person|human|robot|bot|machine|ai)\b[^.?!]*"
    r"|\bis\s+this\s+(?:a\s+|an\s+)?(?:real\s+|live\s+|actual\s+)?"
    r"(?:person|human|robot|bot|machine|recording|ai)\b[^.?!]*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GateDecision:
    reason: EscalateReason
    matched: str


def _pattern(terms: list[str]) -> re.Pattern:
    alts = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{alts})(?![\w-])", re.IGNORECASE)


def rules_gate(text: str, cfg: TenantConfig) -> GateDecision | None:
    for reason in ORDER:
        terms = DEFAULT_LEXICONS[reason] + list(getattr(cfg.lexicons, reason))
        haystack = IDENTITY_QUESTION.sub(" ", text) if reason == "human_request" else text
        m = _pattern(terms).search(haystack)
        if m:
            return GateDecision(reason=reason, matched=m.group(0).lower())
    return None


def health_context_mentioned(text: str, cfg: TenantConfig) -> bool:
    """True when the caller volunteers a condition, medication, pregnancy or past procedure. Flag only, never a gate."""
    return _pattern(HEALTH_CONTEXT_DEFAULT + list(cfg.lexicons.health_context)).search(text) is not None
