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


def test_a_stall_that_implies_an_outcome_is_blocked():
    """OpenAI's chat-supervisor clause, adopted: a holding phrase "must NOT indicate whether
    you can or cannot fulfill an action; they should be neutral and not imply any outcome."
    The assistant cannot book, so "let me book that" is a claim with a delay in front of it."""
    from spatalk.brain.guard import guard

    cfg = _bundle_cfg()
    for text in (
        "Let me book that for you.",
        "One moment while I book that in.",
        "I'll just put you down for Thursday.",
        "I'm going to schedule that now.",
        "Hold on while I cancel that appointment.",
        "Let me add you to Helen's book.",
    ):
        r = guard(text, False, cfg, replacement="X")
        assert r.blocked is True and r.family == "stall", text


def test_an_offer_and_a_stall_the_assistant_can_keep_are_not_blocked():
    """The line the guard must not cross. An offer names a future the *team* carries out; a
    stall the assistant can honour ("let me check the facts") promises only reading."""
    from spatalk.brain.guard import guard

    cfg = _bundle_cfg()
    for text in (
        "Let's get you booked in with the team.",
        "I'd love to help you get that booked.",
        "Let me check that for you.",
        "One moment while I look at the prices.",
        "One moment, I'll connect you to the team.",       # scripts.transferring
        "I'll have the team send you the booking link.",    # scripts.link_captured
    ):
        r = guard(text, False, cfg, replacement="X")
        assert r.blocked is False and r.text == text, text


def test_an_outcome_claim_needs_a_receipt():
    """Receipt-or-retract (memo §3.3). "I've passed that to the team" is the sentence the
    completion lexicon never covered: it claims a filing, not a booking, and on the founder's
    calls the model reached for it before anything had been filed."""
    from spatalk.brain.guard import guard

    cfg = _bundle_cfg()
    for text in (
        "I've passed that to the team.",
        "I've sent that over and someone will call you back.",
        "I've made a note for the team.",
        "Your request is in.",
        "I've texted you the link.",
    ):
        assert guard(text, False, cfg, "X", receipts=0).blocked is True, text
        assert guard(text, False, cfg, "X", receipts=0).family == "receipt", text
        assert guard(text, False, cfg, "X", receipts=1).blocked is False, text


def test_the_receipt_lexicon_leaves_the_tenants_own_outcome_scripts_alone_once_an_item_exists():
    """Every outcome script asserts a receipt, which is the point: with a receipt they pass,
    without one they are retracted too. Task 2 records the receipt before the frame goes out."""
    from datetime import datetime, timezone

    from spatalk.brain.guard import guard
    from spatalk.brain.renderer import render_script

    cfg = _bundle_cfg()
    now = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)
    for key in ("captured", "clinical", "human_request", "complaint"):
        text = render_script(key, cfg, now, urgent=False)
        assert guard(text, False, cfg, "X", receipts=1).blocked is False, key
        assert guard(text, False, cfg, "X", receipts=0).blocked is True, key
    # `cannot_complete` left this list on 2026-09-11 (call 977f0aa1): it is the replacement for
    # a blocked claim and files nothing, so it must pass with no receipt at all.
    assert guard(render_script("cannot_complete", cfg, now, urgent=False), False, cfg, "X", receipts=0).blocked is False


def test_a_question_and_a_refusal_are_never_receipts():
    """`refuse_no_name` says "before I pass that to the team" and `refuse_unavailable` says
    the opposite of a receipt. Neither may be blocked, receipts or not."""
    from datetime import datetime, timezone

    from spatalk.brain.guard import guard
    from spatalk.brain.renderer import render_script

    cfg = _bundle_cfg()
    now = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)
    for key in ("refuse_no_name", "refuse_unavailable", "ask_name", "ask_service", "goodbye"):
        text = render_script(key, cfg, now, urgent=False)
        assert guard(text, False, cfg, "X", receipts=0).blocked is False, key
