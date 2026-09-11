from pathlib import Path
BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def test_human_request():
    from spatalk.brain.rules import rules_gate
    assert rules_gate("Can I speak to a real person please?", _cfg()).reason == "human_request"


def test_clinical_post_treatment():
    from spatalk.brain.rules import rules_gate
    assert rules_gate("I have a rash after my laser session yesterday", _cfg()).reason == "clinical"
    assert rules_gate("Is it safe to do a peel while pregnant?", _cfg()).reason == "clinical"


def test_tenant_additions_apply():
    from spatalk.brain.rules import rules_gate
    assert rules_gate("Do you offer financing?", _cfg()).reason == "payment"


def test_no_match_for_ordinary_question():
    from spatalk.brain.rules import rules_gate
    assert rules_gate("How much is the express facial and are you open Sunday?", _cfg()) is None


def test_word_boundaries():
    from spatalk.brain.rules import rules_gate
    assert rules_gate("I'm calling from Spain about a facial", _cfg()) is None   # 'pain' inside 'Spain'


def test_volunteered_health_context_is_flagged_not_gated():
    from spatalk.brain.rules import health_context_mentioned, rules_gate
    text = "I'm pregnant, can I still book a facial next week?"
    assert rules_gate(text, _cfg()) is None
    assert health_context_mentioned(text, _cfg())
    text2 = "I'm on blood thinners and I'd like the microchanneling"
    assert rules_gate(text2, _cfg()) is None and health_context_mentioned(text2, _cfg())
    assert not health_context_mentioned("How much is a facial?", _cfg())


def test_symptom_after_treatment_is_still_gated():
    from spatalk.brain.rules import rules_gate
    assert rules_gate("I'm diabetic and now there's swelling after my session", _cfg()).reason == "clinical"


def test_asking_whether_this_is_a_real_person_is_not_a_request_for_one():
    from spatalk.brain.rules import rules_gate
    cfg = _cfg()
    assert rules_gate("Am I talking to a real person?", cfg) is None
    assert rules_gate("Are you a real person or a robot?", cfg) is None
    assert rules_gate("is this a real person", cfg) is None
    # A request in the same breath still gates; only the identity clause is blanked.
    assert rules_gate("Are you a bot? I want to speak to a person.", cfg).reason == "human_request"
    assert rules_gate("I'd rather talk to a real person", cfg).reason == "human_request"
    # The other gates are untouched by the identity clause.
    assert rules_gate("Are you a real person? I have a rash after my peel", cfg).reason == "clinical"


def test_asking_whether_a_treatment_hurts_is_a_booking_question():
    """Founder decision 2026-09-05: a caller asking whether a facial hurts is asking about the
    treatment, not reporting a symptom, so the pain words gate nothing."""
    from spatalk.brain.rules import rules_gate
    cfg = _cfg()
    assert rules_gate("Does the laser hurt?", cfg) is None
    assert rules_gate("Is the microneedling painful?", cfg) is None
    assert rules_gate("does it hurt, and is there much pain afterwards?", cfg) is None


def test_an_emergency_gates_to_its_own_reason_ahead_of_everything():
    from spatalk.brain.rules import rules_gate
    cfg = _cfg()
    assert rules_gate("I can't breathe", cfg).reason == "emergency"
    assert rules_gate("My throat is closing after the injections", cfg).reason == "emergency"
    assert rules_gate("I think I'm having an allergic reaction", cfg).reason == "emergency"
    # Even next to a request for a person, the 911 line comes first.
    assert rules_gate("I can't breathe, get me a real person", cfg).reason == "emergency"
    # A rash is a clinical question, not an emergency.
    assert rules_gate("I have a rash after my peel", cfg).reason == "clinical"


def test_a_bare_answer_at_the_name_step_is_not_a_billing_or_complaint_escalation():
    """Founder call 2026-09-10 20:56:19. The recogniser heard the caller's first name, Peyman,
    as "payment"; the payment lexicon matched the two-word answer to "Could I get your first
    name?", an urgent escalation with no name on it was filed and the call ended. A bare
    answer to the name question is a name, whatever word came back, so the two lexicons whose
    words collide with first names stand down for it. The three whose scripts cannot wait -
    an emergency, a request for a person, a clinical concern - do not."""
    from spatalk.brain.rules import rules_gate

    cfg = _cfg()
    # Outside the name step the lexicon is unchanged.
    assert rules_gate("Yeah, payment.", cfg).reason == "payment"
    assert rules_gate("Yeah, payment.", cfg, name_step=True) is None
    assert rules_gate("It's Bill.", cfg, name_step=True) is None
    assert rules_gate("Um, refund", cfg, name_step=True) is None
    # "Sue" is a first name and a word in the complaint lexicon.
    assert rules_gate("Sue", cfg).reason == "complaint"
    assert rules_gate("Sue", cfg, name_step=True) is None
    # A whole sentence is not a name, so the lexicons still apply at the name step.
    assert (
        rules_gate("Actually, can I pay over the phone with my card?", cfg, name_step=True).reason
        == "payment"
    )
    # The three that cannot wait gate however few words the caller uses.
    assert rules_gate("Seizure.", cfg, name_step=True).reason == "emergency"
    assert rules_gate("I can't breathe", cfg, name_step=True).reason == "emergency"
    assert rules_gate("Operator", cfg, name_step=True).reason == "human_request"
    assert rules_gate("Burning.", cfg, name_step=True).reason == "clinical"


def test_a_fragment_with_no_content_words_is_not_a_turn():
    """Founder call 2026-09-11 01:41:11 to 01:41:17. "Um.", "Well." and "What was the, uh-"
    each arrived from the recogniser as a *final* transcription, each started and stopped a
    user turn of its own, and each cost a model run and a re-spoken step question while the
    caller was still assembling his sentence. A hesitation carries no answer and no question:
    it is not a turn. A question mark is content, so "What?" still is one, and so is every
    one-word answer the steps actually take."""
    from spatalk.brain.rules import is_fragment

    for text in ("Um.", " Well.", "What was the, uh-", "so, um", "Okay.", "the", "uh the"):
        assert is_fragment(text), text
    for text in (
        "No.",              # V1 fixed the one-word "No"; it must stay a turn
        "Yes",
        "Sue",
        "What?",            # a repair request: the caller wants the question again
        "Mhm.",             # an affirmative backchannel is a yes, not a hesitation
        "Mm",
        "Right.",
        "Alright",
        "the facial one",
        "Helen",
        "Um, the mesojet",
        "Seizure.",
    ):
        assert not is_fragment(text), text


def test_okay_is_a_fragment_except_where_it_answers_a_yes_no_question():
    """"Okay." is on the founder's filler list for item 3 and is also how a caller says yes to
    "Would you like to hear our new-client offers?". So it stands down at a step whose question
    takes a yes or a no, the way the complaint and payment lexicons stand down at the name
    step. Everywhere else it is a caller thinking aloud."""
    from spatalk.brain.rules import is_fragment

    for text in ("Okay.", "ok", "um, okay"):
        assert is_fragment(text), text
        assert not is_fragment(text, yes_no_step=True), text
    # Standing down is only for that one word: a hesitation is a hesitation at every step.
    for text in ("Um.", "Well.", "What was the, uh-"):
        assert is_fragment(text, yes_no_step=True), text


def test_digits_are_content_so_a_phone_number_is_always_a_turn():
    """A number is the answer to "What's the best number to reach you on?" and it carries no
    letters at all. The first cut of `is_fragment` stripped digits along with the punctuation,
    so `re.sub` left no words and every phone number was held back as a hesitation. Caught in
    review before a live call; the founder would have given his number and heard nothing."""
    from spatalk.brain.rules import is_fragment

    for text in (
        "416 555 0199",
        "4165550199",
        "416-555-0199",
        "it is 905 703 7546",
        "Um, 416 555 0199",
        "99",
    ):
        assert not is_fragment(text), text
        assert not is_fragment(text, yes_no_step=True), text
    # Nothing but punctuation is still nothing.
    assert is_fragment("...") and is_fragment("") and is_fragment("   ")
