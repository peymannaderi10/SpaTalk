from pathlib import Path
BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def test_blocks_completion_language_without_completed_outcome():
    from spatalk.brain.guard import guard
    r = guard("Great, I've booked you in for Thursday at 2.", has_completed=False, cfg=_cfg(), replacement="CANNOT")
    assert r.blocked and r.text == "CANNOT" and r.matched == "booked"


def test_allows_completion_language_with_completed_outcome():
    from spatalk.brain.guard import guard
    r = guard("Your appointment is confirmed.", has_completed=True, cfg=_cfg(), replacement="CANNOT")
    assert not r.blocked and r.text == "Your appointment is confirmed."


def test_allows_neutral_text():
    from spatalk.brain.guard import guard
    r = guard("Laser hair removal starts with a free consultation.", False, _cfg(), "CANNOT")
    assert not r.blocked


def test_matches_are_case_insensitive_and_word_bounded():
    from spatalk.brain.guard import guard
    assert guard("It is CONFIRMED.", False, _cfg(), "X").blocked
    assert not guard("The rebooked package is popular.", False, _cfg(), "X").blocked


def _bundle_cfg():
    from pathlib import Path

    from spatalk.tenants.bundle import load_bundle

    return load_bundle(Path(__file__).resolve().parents[1] / "tenants" / "skincentrix")


def test_offering_to_arrange_a_booking_is_not_a_claim():
    from spatalk.brain.guard import guard

    cfg = _bundle_cfg()
    for text in (
        "[warm] I'd love to help you get that booked. Which treatment are you thinking of?",
        "Let's get you booked in with the team.",
        "Want to get that scheduled for next week?",
        "Once we get it confirmed with the nurse, someone will call you.",
    ):
        r = guard(text, False, cfg, replacement="X")
        assert r.blocked is False and r.text == text, text


def test_claims_that_a_booking_happened_are_still_blocked():
    from spatalk.brain.guard import guard

    cfg = _bundle_cfg()
    for text in (
        "I've booked you for Thursday at two.",
        "You're all booked.",
        "I got you booked in for Thursday.",
        "I have you booked with Amanda.",
        "Your appointment is confirmed.",
        "Once we get it confirmed, you're all set.",
    ):
        assert guard(text, False, cfg, replacement="X").blocked is True, text
