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
