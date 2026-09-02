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
    "human_request": ["speak to a person", "talk to a person", "real person", "a human", "an actual person",
                      "speak to someone", "talk to someone", "speak with someone", "receptionist",
                      "front desk", "staff member", "operator", "transfer me", "call me back please"],
    # Concerns and questions: something is wrong now, or the caller is asking whether something is safe.
    "clinical": ["rash", "burn", "burning", "blister", "swelling", "swollen", "pain", "painful", "hurts",
                 "bleeding", "infection", "infected", "reaction", "allergic reaction", "side effect", "side effects",
                 "bruise", "bruising", "numb", "is it safe", "is that safe", "is this safe", "is it normal",
                 "is that normal", "should i be worried", "after my treatment", "after my session", "post treatment",
                 "after the treatment", "fever", "dizzy", "scar", "scarring", "peeling"],
    "complaint": ["complaint", "complain", "unhappy", "refund", "terrible", "awful", "lawyer", "sue", "legal action"],
    "payment": ["credit card", "card number", "visa", "mastercard", "pay now", "make a payment", "payment",
                "invoice", "charge me", "charged", "billing"],
}
# Volunteered context: not a gate. The request proceeds; the conversation and item are flagged so staff read the transcript.
HEALTH_CONTEXT_DEFAULT: list[str] = [
    "pregnant", "pregnancy", "breastfeeding", "nursing", "medication", "medications", "on meds", "diabetes", "diabetic",
    "eczema", "psoriasis", "rosacea", "allergy", "allergies", "allergic to", "botox", "filler", "fillers", "accutane",
    "retinol", "blood thinner", "blood thinners", "diagnosed", "surgery", "condition", "sensitive skin", "keloid",
]
ORDER: list[EscalateReason] = ["human_request", "clinical", "complaint", "payment"]


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
        m = _pattern(terms).search(text)
        if m:
            return GateDecision(reason=reason, matched=m.group(0).lower())
    return None


def health_context_mentioned(text: str, cfg: TenantConfig) -> bool:
    """True when the caller volunteers a condition, medication, pregnancy or past procedure. Flag only, never a gate."""
    return _pattern(HEALTH_CONTEXT_DEFAULT + list(cfg.lexicons.health_context)).search(text) is not None
