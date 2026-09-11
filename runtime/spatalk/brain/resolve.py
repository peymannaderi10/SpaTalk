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
# A `WRatio` in the confirmation band is not on its own worth a "did you mean?": the score
# rewards a substring, and a substring can be pure coincidence. "station one" scored 0.70
# against "Free virtual consultation" on the letters "station" shares with the middle of
# "consultation", and the caller who had asked *what* the offers were was answered with "Did
# you mean Free virtual consultation?" (founder call 2026-09-10 20:54:17). So below ACCEPT a
# match must also share a word: one of the caller's words is one of the candidate's, or its
# beginning, or near enough in spelling that a recogniser could have produced it.
WORD_MATCH = 0.80
MIN_PREFIX_CHARS = 4

ANY_WORDS = (
    "any", "anyone", "anybody", "whoever", "whoever's available", "no preference",
    "doesn't matter", "does not matter", "either", "no one in particular",
    "nobody in particular", "not really", "no",
)
STRIP_WORDS = ("with", "dr", "dr.", "doctor", "nurse", "the", "a", "an", "please", "to", "see")
DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

# A caller asking the runtime to say something again is not answering it. On the founder's
# call of 2026-09-11 01:41 the service step offered only `choose_service`, so "what was the
# station one again?" and "Sorry, what was the- what was the facial one again?" both arrived
# as answers and the second one filled the slot. These markers are whole words, so
# "whichever" and "whoever's" are still answers, and "sorry" is deliberately not one of them:
# "Sorry, the classic facial" is a correction. A question mark anywhere is a marker by itself.
QUESTION_WORDS = frozenset({
    "what", "what's", "whats", "whatre", "which", "again", "repeat", "repeated", "pardon",
})
QUESTION_PHRASES = ("you said", "did you say", "one more time", "say that", "come again")


class Match(BaseModel, frozen=True):
    kind: Literal["exact", "confirm", "which", "kind", "none"]
    value: str | None = None
    candidates: tuple[str, ...] = ()


def is_question(said: str) -> bool:
    """True when the caller asked something rather than answered (see QUESTION_WORDS).

    Pure text, no tenant config: the tools share it so a question can never be resolved into
    a slot. The caller's question itself stays in the transcript and is answered by the model
    in its own words; nothing here is ever spoken or stored.
    """
    if "?" in (said or ""):
        return True
    words = re.sub(r"[^a-z0-9' ]+", " ", (said or "").lower()).split()
    if any(w in QUESTION_WORDS for w in words):
        return True
    joined = " ".join(words)
    return any(p in joined for p in QUESTION_PHRASES)


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


def _words_relate(said_word: str, label_word: str) -> bool:
    """One word of the caller's could be one word of the label's."""
    if said_word == label_word:
        return True
    shorter = min(len(said_word), len(label_word))
    if shorter >= MIN_PREFIX_CHARS and (
        said_word.startswith(label_word) or label_word.startswith(said_word)
    ):
        return True
    return fuzz.ratio(said_word, label_word) / 100.0 >= WORD_MATCH


def shares_a_word(said: str, label: str) -> bool:
    """True when some word of `said` relates to some word of `label` (see WORD_MATCH)."""
    label_words = _normalise(label).split()
    return any(_words_relate(w, lw) for w in said.split() for lw in label_words)


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
    labels = dict(options)
    scored = sorted(((_score(said, label), v) for v, label in options), reverse=True)
    # Below ACCEPT the score alone is not evidence: a shared word has to back it up.
    if scored[0][0] < ACCEPT:
        scored = [(s, v) for s, v in scored if shares_a_word(said, labels[v])]
        if not scored:
            return Match(kind="none")
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
