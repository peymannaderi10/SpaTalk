"""A cosmetic concern is a service question, not a clinical one (founder call 977f0aa1,
2026-09-11 21:59). "What do you have for pigmentation on my arm and body?" was treated as
medical, a handoff was claimed, and the caller was told twice that it was a clinical concern.
The clinic treats cosmetic concerns; that is what the SERVICES list is for."""

from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _prompt():
    from datetime import datetime, timezone

    from spatalk.brain.prompt import build_system_prompt
    from spatalk.tenants.bundle import load_bundle

    now = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)
    return build_system_prompt(load_bundle(BUNDLE), "voice", now)


def test_a_cosmetic_concern_is_answered_from_the_services_not_handed_off():
    text = _prompt()
    assert "cosmetic concern" in text
    assert "pigmentation" in text
    assert "not a clinical" in text
    # The rule names the two moves the founder asked for: say what is offered, and where
    # nothing covers the area, say so and suggest the consultation before any request.
    # The offers' own words stay in the knowledge file, so the rule points at "the offer
    # that plans a first visit" rather than naming it.
    assert "say so" in text and "plans a first visit" in text
    # And the clinical line no longer sweeps a cosmetic question up with symptoms.
    assert "A cosmetic concern is not a symptom" in text


def test_the_knowledge_says_what_addresses_pigmentation_and_what_does_not():
    from spatalk.tenants.bundle import load_bundle

    k = load_bundle(BUNDLE).knowledge.lower()
    assert "pigmentation" in k and "mirapeel" in k and "purecarbon" in k
    assert "body" in k and "consultation" in k
