"""Matching a caller's words to the tenant's lists (slot engine design, §5).

Everything here is code, not model: the model passes what the caller said, these
functions decide whether it names something on a list, and only a list value is ever
stored. Thresholds are the memo's starting points; the call tests tune them.
"""
from __future__ import annotations

import re
from typing import Literal

from metaphone import doublemetaphone
from pydantic import BaseModel
from rapidfuzz import fuzz

from spatalk.tenants.schema import TenantConfig

ACCEPT = 0.90
CONFIRM = 0.60

ANY_WORDS = (
    "any", "anyone", "anybody", "whoever", "whoever's available", "no preference",
    "doesn't matter", "does not matter", "either", "no one in particular",
    "nobody in particular", "not really", "no",
)
STRIP_WORDS = ("with", "dr", "dr.", "doctor", "nurse", "the", "a", "an", "please", "to", "see")
DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


class Match(BaseModel, frozen=True):
    kind: Literal["exact", "confirm", "which", "kind", "none"]
    value: str | None = None
    candidates: tuple[str, ...] = ()


def _normalise(text: str) -> str:
    words = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower()).split()
    return " ".join(w for w in words if w not in STRIP_WORDS)


def first_name_of(full: str) -> str:
    return (full or "").split()[0] if full else ""


def sounds_like(a: str, b: str) -> bool:
    """Same phonetic code, or nearly the same spelling: Double Metaphone keeps the H that
    separates Helen from Ellen, and a recogniser drops it, so spelling covers that case."""
    if not a or not b:
        return False
    codes_a = {c for c in doublemetaphone(a) if c}
    codes_b = {c for c in doublemetaphone(b) if c}
    if codes_a & codes_b:
        return True
    return fuzz.ratio(a.lower(), b.lower()) / 100.0 >= 0.8


def _score(said: str, candidate: str) -> float:
    return fuzz.WRatio(said, candidate.lower()) / 100.0


def _best(said: str, options: list[tuple[str, str]]) -> Match:
    """`options` are (value, label) pairs; labels are matched, values returned."""
    if not said or not options:
        return Match(kind="none")
    exact = [
        v for v, label in options
        if _normalise(label) == said or first_name_of(_normalise(label)) == said
    ]
    if len(exact) == 1:
        return Match(kind="exact", value=exact[0])
    if len(exact) > 1:
        return Match(kind="which", candidates=tuple(exact[:2]))
    scored = sorted(((_score(said, label), v) for v, label in options), reverse=True)
    top, value = scored[0]
    if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 0.02 and top >= CONFIRM:
        return Match(kind="which", candidates=(scored[0][1], scored[1][1]))
    if top >= ACCEPT:
        return Match(kind="exact", value=value)
    if top >= CONFIRM:
        return Match(kind="confirm", value=value, candidates=(value,))
    return Match(kind="none")


def match_practitioner(said: str, cfg: TenantConfig) -> Match:
    text = _normalise(said)
    if not text or text in ANY_WORDS or text.startswith(("whoever", "anyone", "anybody")):
        return Match(kind="exact", value="any")
    options = [(m.name, m.name) for m in cfg.team]
    # A single first name that sounds like exactly one team member's first name.
    phonetic = [m.name for m in cfg.team if sounds_like(text, first_name_of(m.name))]
    if len(phonetic) == 1 and _normalise(first_name_of(phonetic[0])) != text:
        return Match(kind="confirm", value=phonetic[0], candidates=(phonetic[0],))
    if len(phonetic) > 1 and all(_normalise(first_name_of(n)) != text for n in phonetic):
        return Match(kind="which", candidates=tuple(phonetic[:2]))
    return _best(text, options)


def match_service(said: str, cfg: TenantConfig) -> Match:
    text = _normalise(said)
    if not text:
        return Match(kind="none")
    categories = sorted({s.category for s in cfg.services})
    singular = text[:-1] if text.endswith("s") else text
    if text in categories or singular in categories:
        return Match(kind="kind", value=text if text in categories else singular)
    options = [(s.id, s.name) for s in cfg.services]
    # "hydroabrasion facial": the words that are not a category name pick the service.
    words = text.split()
    rest = [w for w in words if w not in categories and (w[:-1] if w.endswith("s") else w) not in categories]
    if rest and len(rest) < len(words):
        narrowed = _best(" ".join(rest), options)
        if narrowed.kind != "none":
            return narrowed
    match = _best(text, options)
    if match.kind == "none":
        for cat in categories:
            if cat in text.split() or cat + "s" in text.split():
                return Match(kind="kind", value=cat)
    return match


def normalise_phone(digits: str) -> str | None:
    only = re.sub(r"\D", "", digits or "")
    if len(only) == 11 and only.startswith("1"):
        only = only[1:]
    if len(only) != 10:
        return None
    return "+1" + only


def spoken_digits(e164: str) -> str:
    n = e164[-10:]
    groups = (n[:3], n[3:6], n[6:])
    return ", ".join(" ".join(DIGIT_WORDS[int(d)] for d in g) for g in groups)


def typed_digits(e164: str) -> str:
    n = e164[-10:]
    return f"{n[:3]}-{n[3:6]}-{n[6:]}"
