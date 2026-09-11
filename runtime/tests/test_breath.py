"""How much of one breath the assistant has spent, counted in catalogue entries.

Founder call 14ea2579, 2026-09-11 15:53:14.964-.992: three sentences in one breath, seven
treatment names and three price points, 409 characters and 23.4 s of uninterrupted audio.
That turn is inside the tenant's three-sentence cap, so a sentence cap alone cannot close
it: the guard also has to know how many things one sentence named.
"""

import re
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def _words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z0-9']+", text or "")]


def test_named_items_counts_the_recital_the_model_gave_at_1553():
    """The 15:53:14 sentence scores 3, not 4, and that is the honest floor.

    "Lift and Sculpt" is invisible to the lexicon because "lift" also occurs in "Express
    Lift" and "sculpt" in the "Express Sculpt and Drain lymphatic facial", so neither word
    is distinctive enough to name one entry on its own. Under-counting only delays the cap;
    it never drops a sentence that named nothing, which is the direction that has to be safe.
    """
    from spatalk.brain.breath import named_items

    sentence = "our MesoJet and Sound Therapy, Mirapeel, PureCarbon, and Lift and Sculpt facials"
    assert named_items(sentence, _cfg()) == 3


def test_named_items_ignores_the_clinics_own_name():
    from spatalk.brain.breath import named_items

    assert named_items("Here at Skincentrix we take our time.", _cfg()) == 0


def test_a_catalogue_entry_with_two_distinctive_words_counts_once():
    """"VAMP" and "salmon" are both unique to the VAMP salmon DNA microchanneling, and the
    caller heard one treatment named, not two."""
    from spatalk.brain.breath import named_items

    assert named_items("the VAMP salmon treatment", _cfg()) == 1


def test_item_lexicon_holds_only_words_unique_to_one_entry():
    from spatalk.brain.breath import item_lexicon

    cfg = _cfg()
    lexicon = item_lexicon(cfg)
    assert lexicon, "the skincentrix catalogue must produce a lexicon"
    own = set(_words(cfg.name))
    names = [s.name for s in cfg.services] + [m.name for m in cfg.team]
    for word in lexicon:
        assert len(word) >= 4, f"{word!r} is too short to be distinctive"
        assert word not in own, f"{word!r} is a word of the clinic's own name"
        hits = sum(1 for n in names if word in _words(n))
        assert hits == 1, f"{word!r} occurs in {hits} catalogue entries, not one"


def test_named_items_is_zero_for_a_sentence_that_names_nothing():
    """The 15:52:53 turn ("That's a $50 credit...") named no treatment and must stay
    uncapped however long the breath before it was."""
    from spatalk.brain.breath import named_items

    said = "That's a $50 credit that applies to any of our advanced facials."
    assert named_items(said, _cfg()) == 0
