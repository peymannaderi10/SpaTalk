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


def test_a_question_is_not_an_answer():
    """Founder call 2026-09-11 01:41:17 and 01:41:26. The caller asked the runtime to repeat
    itself — "what was the station one again?", then "Sorry, what was the- what was the facial
    one again? The facial one?" — and both arrived as `choose_service(said=...)`, because the
    service step offers no other tool. The second one resolved and the caller's question was
    never answered. An utterance carrying an interrogative or a repeat marker, or ending in a
    question mark, is a question and never an answer to the open slot."""
    from spatalk.brain.resolve import is_question

    questions = (
        "what was the station one again?",
        "Sorry, what was the- what was the facial one again? The facial one?",
        "what was the facial one again",
        "you said fifty dollars",
        "can you repeat that",
        "which one was the cheaper one",
        "again?",
        "pardon",
        "the mesojet?",
    )
    for said in questions:
        assert is_question(said), said
    answers = (
        "the facial one",
        "the mesojet and sound therapy facial",
        "sorry, the classic facial",
        "whoever's available",
        "no preference",
        "Helen",
        "hydroabrasion",
    )
    for said in answers:
        assert not is_question(said), said


def test_a_generic_category_entry_resolves_to_a_kind():
    """Founder call 2026-09-11 01:41:26. `services.yaml` carries generic entries "for what
    callers ask for by category" — `id: facial, name: Facial, category: facial` and the same
    shape for laser hair removal and microchanneling — and `WRatio` scores any phrase
    containing "facial" at exactly 0.90 against "Facial", which is `ACCEPT`. So "the facial
    one" came back `exact` and the runtime booked "Facial", a catalog row that names no
    treatment. A placeholder stands for a category, so naming one names a kind
    (slot engine design §5, "a facial" -> kind -> ask_service_kind), and it never competes
    with the specific entries behind it."""
    from spatalk.brain.resolve import match_service

    cfg = _cfg()
    m = match_service("the facial one", cfg)
    assert m.kind == "kind" and m.value == "facial" and len(m.candidates) >= 2
    assert "facial" not in m.candidates, "the placeholder is not one of the choices"
    assert "mesojet_facial" in m.candidates
    # A placeholder whose name is not the bare category word is one too.
    laser = match_service("laser hair removal", cfg)
    assert laser.kind == "kind" and laser.value == "laser" and len(laser.candidates) >= 2
    assert "laser_hair_removal" not in laser.candidates
    assert match_service("microchanneling", cfg).kind == "kind"
    # "the express one" and "express treatment" are the category word with a filler tail.
    for said in ("the express one", "express treatment"):
        k = match_service(said, cfg)
        assert k.kind == "kind" and k.value == "express", said
    # A specific treatment is still exact, and the entries behind a category still resolve
    # on their own now that the placeholder is out of their way.
    assert match_service("MesoJet", cfg) .kind == "exact"
    assert match_service("MesoJet", cfg).value == "mesojet_facial"
    assert match_service("classic facial", cfg).value == "classic_facial"
    assert match_service("hydroabrasion facial", cfg).value == "hydrabrasion_facial"
    assert match_service("skin and scalp facial", cfg).value == "scalp_facial"


def test_a_category_word_the_rest_does_not_narrow_is_a_kind():
    """`scenarios/promptfooconfig.yaml` has "I was thinking a facial" -> `ask_service_kind`,
    and taking the placeholder row out of the running left the whole phrase to the fuzzy
    match, which answered `which` — "did you mean the Acne facial or the Classic facial?" on a
    caller who has not chosen anything. When the only thing a caller named is the category,
    that is a kind (slot engine design §5), not a coin-flip between two treatments that happen
    to share the word."""
    from spatalk.brain.resolve import match_service

    cfg = _cfg()
    for said in (
        "I was thinking a facial",
        "maybe a facial",
        "just a facial",
        "some kind of facial",
        "a facial i guess",
        "a laser treatment",
    ):
        m = match_service(said, cfg)
        assert m.kind == "kind", f"{said!r} -> {m}"
        assert len(m.candidates) >= 2, said
    # The words that do narrow it still win.
    assert match_service("the hydrabrasion facial", cfg).value == "hydrabrasion_facial"
    assert match_service("MesoJet facial", cfg).value == "mesojet_facial"
    # "a facial for acne" narrows to the acne treatments rather than the whole category; the
    # clinic has two of those, so it is a `which`, which is the honest answer.
    acne = match_service("a facial for acne", cfg)
    assert acne.kind != "kind"
    assert "acne_facial" in (acne.candidates or (acne.value,))
