from pathlib import Path

import pytest

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def test_every_slot_script_has_a_default_and_the_bundle_supplies_it():
    from spatalk.tenants.schema import Scripts

    keys = [
        "ask_returning", "ask_offers", "ask_after_offers", "ask_practitioner",
        "ask_practitioner_again", "practitioner_any", "practitioner_not_service",
        "practitioner_suggest", "practitioner_else", "ask_service", "ask_service_kind",
        "ask_service_again", "confirm_match", "confirm_which", "ask_name", "ask_name_again",
        "no_name", "confirm_name_staff", "ask_phone_same", "ask_phone", "confirm_phone",
        "phone_fallback", "ask_window", "ask_team_note", "ask_route", "clinical_offer",
        "clinical_declined",
    ]
    fields = Scripts.model_fields
    for key in keys:
        assert key in fields, key
        assert fields[key].default not in (None, ""), key
    cfg = _cfg()
    assert cfg.scripts.ask_name == "Could I get your first name?"
    assert cfg.scripts.confirm_match == "Did you mean {value}?"
    assert "911" not in cfg.scripts.clinical and "911" not in cfg.scripts.clinical_text


def test_team_services_are_validated_and_queryable():
    cfg = _cfg()
    helen = next(m for m in cfg.team if m.name.startswith("Helen"))
    assert cfg.member_does(helen.name, "hydrabrasion_facial")
    assert helen.name in [m.name for m in cfg.team_for_service("hydrabrasion_facial")]
    # An empty list means every service.
    anyone = next(m for m in cfg.team if not m.services)
    assert cfg.member_does(anyone.name, "hydrabrasion_facial")
    with pytest.raises(ValueError):
        cfg.model_copy(
            update={"team": [helen.model_copy(update={"services": ["no_such_service"]})]}
        ).check_team_services()


def test_faq_rows_are_bounded_facts_the_bundle_ships():
    from pydantic import ValidationError

    from spatalk.tenants.schema import FaqItem

    cfg = _cfg()
    assert len(cfg.faq) >= 5 and all(item.question and item.answer for item in cfg.faq)
    assert any("48 hours" in item.answer for item in cfg.faq)
    with pytest.raises(ValidationError):
        FaqItem(question="", answer="x")
    with pytest.raises(ValidationError):
        FaqItem(question="q", answer="a" * 601)


def test_a_service_category_is_stored_lowercase_however_it_was_typed():
    from spatalk.tenants.schema import Service

    svc = Service(id="gold_facial", name="Gold Facial", category=" Facial ", booking_url="https://x.test/")
    assert svc.category == "facial"

