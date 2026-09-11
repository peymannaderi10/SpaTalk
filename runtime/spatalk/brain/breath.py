"""How much of one breath the assistant has spent: the catalogue entries it named.

`persona.max_sentences_per_turn` bounds how many sentences a turn may spend, and on the
founder's call of 2026-09-11 that was not enough: the 15:53:14 turn was three sentences —
inside the tenant's cap — and still recited seven treatments and three prices in 23.4 s of
uninterrupted audio. A caller cannot hold seven names in their head, so the breath has a
second budget, in things named, and this module is the whole of its arithmetic.

Pure and tenant-aware: `re` and the tenant config, no I/O, no model, nothing persisted.
The lexicon is built per call because it costs nothing at a sentence boundary — 42 services
and 11 people is about two hundred words.
"""

from __future__ import annotations

import re

from spatalk.tenants.schema import TenantConfig

# Words of a catalogue entry, lower-cased. Digits stay in ("$99 express treatment"), because
# a number can be the distinctive half of a name.
_WORD = re.compile(r"[A-Za-z0-9']+")

# A word shorter than this is not distinctive enough to name anything: "rf", "led", "dna"
# and "prp" all belong to several entries, and the ones that do not are still too easy for
# ordinary speech to hit by accident.
_MIN_WORD = 4


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def item_lexicon(cfg: TenantConfig) -> dict[str, str]:
    """Distinctive word -> the catalogue entry it names (`Service.id`, or `TeamMember.name`).

    A word qualifies on three conditions, and they are the whole safety story of the item
    budget: it appears in exactly one entry of `cfg.services` + `cfg.team`, it is four
    characters or longer, and it is not a word of `cfg.name`. Under-counting only delays the
    cap and never drops a sentence that named nothing; over-counting is the dangerous
    direction, and these three bound it.
    """
    own = set(_words(cfg.name))
    entries: list[tuple[str, str]] = [(s.id, s.name) for s in cfg.services]
    entries += [(m.name, m.name) for m in cfg.team]
    owner: dict[str, str] = {}
    shared: set[str] = set()
    for key, label in entries:
        for word in set(_words(label)):
            if len(word) < _MIN_WORD or word in own:
                continue
            if word in owner and owner[word] != key:
                shared.add(word)
                continue
            owner[word] = key
    return {word: key for word, key in owner.items() if word not in shared}


def named_items(text: str, cfg: TenantConfig) -> int:
    """How many distinct catalogue entries `text` names.

    Entries, not words: "the VAMP salmon treatment" names one thing, however many of its
    words are distinctive, because that is what the caller heard.
    """
    lexicon = item_lexicon(cfg)
    return len({lexicon[w] for w in _words(text) if w in lexicon})


__all__ = ["item_lexicon", "named_items"]
