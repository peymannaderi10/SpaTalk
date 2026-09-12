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

# Words a caller hangs off the end of a category name without naming a treatment: "the facial
# one", "an express treatment". Stripped before the category test, never when they are the
# whole utterance ("one" on its own names nothing).
KIND_TAIL = frozenset({"one", "ones", "treatment", "treatments", "option", "options"})


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


# A clause of a caller's turn opens on one of these when the clause is a question. `is_question`
# cannot be used on a whole turn: it reads a question WORD anywhere in the text, which is right
# for a three-word tool argument and wrong for a sentence ("the mesojet one, that's what I
# want"). "any" is deliberately absent — "any is fine" is the answer to the window question, in
# the tenant's own script.
TURN_OPENERS = frozenset({
    "what", "what's", "whats", "whatre", "which", "how", "how's", "hows", "when", "where", "why",
    "who", "who's", "whos", "do", "does", "did", "can", "could", "is", "are", "was", "were",
    "will", "would", "should", "have", "has", "am", "may", "must", "isn't", "isnt", "don't",
    "dont", "doesn't", "doesnt",
})
# Words a caller hangs off the front of a clause before they get to it.
TURN_LEAD_IN = frozenset({
    "and", "but", "so", "or", "um", "uh", "er", "oh", "ok", "okay", "yeah", "yep", "yes", "no",
    "nope", "well", "sorry", "actually", "hey", "hi", "please", "just", "like", "then", "also",
})
_CLAUSE = re.compile(r"[.?!,;:]+|\band\b|\bbut\b|\bso\b")


def turn_asked(said: str) -> bool:
    """Did the caller's whole turn ask something, on top of whatever else it did?

    The sibling of `is_question` for a different text: `is_question` judges the short argument
    a model passed to a tool, where a bare "what" or "again" is the caller asking to be told
    something; this judges the caller's own transcription for the turn, where the same word is
    ordinary speech. A turn asks when it carries a question mark, or when one of its clauses
    opens on an interrogative. Pure text, no tenant config; nothing here is spoken or stored.
    """
    text = (said or "")
    if "?" in text:
        return True
    lowered = re.sub(r"[^a-z0-9' ]+", " ", text.lower())
    for clause in _CLAUSE.split(text.lower()):
        words = re.sub(r"[^a-z0-9' ]+", " ", clause).split()
        while words and words[0] in TURN_LEAD_IN:
            words.pop(0)
        if words and words[0] in TURN_OPENERS:
            return True
    return any(p in " ".join(lowered.split()) for p in QUESTION_PHRASES)


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


def category_placeholders(cfg: TenantConfig) -> dict[str, str]:
    """The catalog entries that stand for a whole category rather than a treatment, as
    `{service_id: category}`.

    Skincentrix's `services.yaml` carries them under "what callers ask for by category":
    `Facial`, `Laser hair removal`, `Microchanneling`. They are recognised by shape rather
    than by a new schema field, so no tenant bundle has to be re-authored: an entry whose id
    or name *is* its category, or whose name is a strict subset of the names of two or more
    other entries in the same category ("Laser hair removal" inside "Laser hair removal,
    small area"). A real treatment carries a word the others do not, so it is never caught.
    """
    by_category: dict[str, list] = {}
    for s in cfg.services:
        by_category.setdefault(s.category, []).append(s)
    found: dict[str, str] = {}
    for s in cfg.services:
        if s.id == s.category or _normalise(s.name) == s.category:
            found[s.id] = s.category
            continue
        mine = set(_normalise(s.name).split())
        wider = [
            o for o in by_category[s.category]
            if o.id != s.id and mine < set(_normalise(o.name).split())
        ]
        if len(wider) >= 2:
            found[s.id] = s.category
    return found


def _kind(cfg: TenantConfig, category: str, placeholders: dict[str, str]) -> Match:
    """A kind, with the category's specific treatments as the candidates behind it."""
    return Match(
        kind="kind",
        value=category,
        candidates=tuple(
            s.id for s in cfg.services if s.category == category and s.id not in placeholders
        ),
    )


def _named_kind(
    text: str, cfg: TenantConfig, categories: list[str], placeholders: dict[str, str]
) -> str | None:
    """The category `text` names, by the category word itself or by a placeholder's name."""
    words = text.split()
    while len(words) > 1 and words[-1] in KIND_TAIL:
        words.pop()
    stem = " ".join(words)
    named = {_normalise(cfg.service(i).name): c for i, c in placeholders.items()}
    for candidate in (stem, stem[:-1] if stem.endswith("s") else stem):
        if candidate in categories:
            return candidate
        if candidate in named:
            return named[candidate]
    return None


def match_service(said: str, cfg: TenantConfig) -> Match:
    text = _normalise(said)
    if not text:
        return Match(kind="none")
    categories = sorted({s.category for s in cfg.services})
    placeholders = category_placeholders(cfg)
    named = _named_kind(text, cfg, categories, placeholders)
    if named is not None:
        return _kind(cfg, named, placeholders)
    # A placeholder is not a treatment, so it is out of the running: with "Facial" in the
    # list, "acne facial" and "classic facial" were a coin-flip "did you mean Facial or
    # Acne facial?" and "the facial one" was an exact match on a row that names nothing
    # (founder call 2026-09-11 01:41:26).
    options = [(s.id, s.name) for s in cfg.services if s.id not in placeholders]
    # "hydroabrasion facial": the words that are not a category name pick the service.
    words = text.split()
    rest = [w for w in words if w not in categories and (w[:-1] if w.endswith("s") else w) not in categories]
    if rest and len(rest) < len(words):
        narrowed = _best(" ".join(rest), options)
        if narrowed.kind != "none":
            return narrowed
        # The category word is the only thing the caller named ("maybe a facial"), so this is
        # a kind. Fuzzy-matching the whole phrase instead answers `which` — "did you mean the
        # Acne facial or the Classic facial?" — to someone who has chosen nothing.
        return _named_category(cfg, words, categories, placeholders) or Match(kind="none")
    match = _best(text, options)
    if match.kind == "none":
        return _named_category(cfg, words, categories, placeholders) or match
    return match


def _named_category(
    cfg: TenantConfig, words: list[str], categories: list[str], placeholders: dict[str, str]
) -> Match | None:
    """A kind for the first category word among `words`, or None when there is none."""
    for cat in categories:
        if cat in words or cat + "s" in words:
            return _kind(cfg, cat, placeholders)
    return None


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
