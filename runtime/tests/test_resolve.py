from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def test_exact_and_phonetic_practitioner_matches():
    from spatalk.brain.resolve import match_practitioner

    cfg = _cfg()
    assert match_practitioner("Helen", cfg).kind == "exact"
    assert match_practitioner("helen courbetis", cfg).value == "Helen Courbetis"
    m = match_practitioner("Ellen", cfg)
    assert m.kind == "confirm" and m.value == "Helen Courbetis"
    assert match_practitioner("whoever's available", cfg).value == "any"
    assert match_practitioner("no preference", cfg).value == "any"
    assert match_practitioner("xqzv", cfg).kind == "none"


def test_two_members_with_one_first_name_ask_which():
    from spatalk.brain.resolve import match_practitioner
    from spatalk.tenants.schema import TeamMember

    cfg = _cfg()
    cfg2 = cfg.model_copy(update={"team": list(cfg.team) + [TeamMember(name="Amanda Kerr")]})
    m = match_practitioner("Amanda", cfg2)
    assert m.kind == "which" and set(m.candidates) == {"Amanda Coutts", "Amanda Kerr"}


def test_service_matches_by_name_and_by_kind():
    from spatalk.brain.resolve import match_service

    cfg = _cfg()
    assert match_service("hydrabrasion", cfg).value == "hydrabrasion_facial"
    m = match_service("hydroabrasion facial", cfg)
    assert m.value == "hydrabrasion_facial" and m.kind in ("exact", "confirm")
    k = match_service("a facial", cfg)
    assert k.kind == "kind" and k.value == "facial"
    assert match_service("blorp", cfg).kind == "none"


def test_phone_normalising_and_read_back():
    from spatalk.brain.resolve import normalise_phone, spoken_digits, typed_digits

    assert normalise_phone("416 555 0199") == "+14165550199"
    assert normalise_phone("1-416-555-0199") == "+14165550199"
    assert normalise_phone("+1 (416) 555-0199") == "+14165550199"
    assert normalise_phone("555 0199") is None
    assert normalise_phone("four one six") is None
    assert spoken_digits("+14165550199") == "four one six, five five five, zero one nine nine"
    assert typed_digits("+14165550199") == "416-555-0199"


def test_sounds_like_and_first_name():
    from spatalk.brain.resolve import first_name_of, sounds_like

    assert first_name_of("Helen Courbetis") == "Helen"
    assert sounds_like("Ellen", "Helen") and not sounds_like("Dana", "Helen")


def test_a_close_score_with_no_word_in_common_is_not_a_confirmation():
    """Founder call 2026-09-10 20:54:17. The caller asked "what was the station one again?"
    and the runtime answered "Did you mean Free virtual consultation?". `WRatio` scored
    "station one" against "Free virtual consultation" at 0.70 on the letters "station" shares
    with the middle of "consultation" — not one whole word in common. A confirmation is only
    worth asking when some word of what the caller said is some word of the candidate."""
    from spatalk.brain.resolve import match_service

    cfg = _cfg()
    assert match_service("the station one", cfg).kind == "none"
    assert match_service("station one", cfg).kind == "none"
    # A bare "one" used to pick two unrelated treatments to choose between.
    assert match_service("one", cfg).kind == "none"
    # The near-misses the 0.60 threshold exists for still confirm.
    assert match_service("hydroabrasion", cfg).value == "hydrabrasion_facial"
    assert match_service("hydroabrasion facial", cfg).value == "hydrabrasion_facial"
    assert match_service("mirapeel", cfg).value == "mirapeel_facial"
    assert match_service("carbon peel", cfg).value == "purecarbon_facial"


def test_a_misheard_first_name_still_confirms():
    """The shared-word rule must not close the door the phonetic and fuzzy paths open."""
    from spatalk.brain.resolve import match_practitioner

    cfg = _cfg()
    assert match_practitioner("Ellen", cfg).value == "Helen Courbetis"
    assert match_practitioner("Alexandre", cfg).value == "Alexandra Debski"
