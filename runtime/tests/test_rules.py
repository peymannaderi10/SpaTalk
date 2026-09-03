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
