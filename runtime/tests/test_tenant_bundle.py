from pathlib import Path

import pytest
import yaml

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def test_skincentrix_bundle_loads():
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    assert cfg.id == "skincentrix"
    assert cfg.timezone == "America/Toronto"
    assert cfg.integration_tier == "C"
    assert cfg.service("laser_hair_removal").booking_url.startswith("https://skincentrix.janeapp.com")
    assert "as soon as" in cfg.scripts.captured and "{confirm_by}" not in cfg.scripts.captured
    assert cfg.hours["tue"] == [("10:00", "18:00")]
    assert cfg.recording_enabled is False
    assert cfg.retention_days == 30
    assert "911" in cfg.scripts.emergency and "911" not in cfg.scripts.clinical
    assert cfg.scripts.refuse_unavailable and cfg.scripts.failover and cfg.scripts.loop_guard
    assert cfg.social.comment_mode == "keyword" and cfg.transfer_number is None


def test_scripts_reject_completion_wording():
    from spatalk.tenants.bundle import load_bundle
    from spatalk.tenants.schema import Scripts
    cfg = load_bundle(BUNDLE)
    with pytest.raises(ValueError):
        Scripts.model_validate({**cfg.scripts.model_dump(), "captured": "Great, you're booked for {confirm_by}."})
    with pytest.raises(ValueError):
        Scripts.model_validate({**cfg.scripts.model_dump(), "emergency": "Someone will call you back {confirm_by}."})


def test_only_the_emergency_scripts_say_911():
    """Founder decision 2026-09-05: the 911 line belongs to the emergency script alone, so a rash
    or an aftercare question is never answered with it. Checked on the bundle and on the defaults."""
    from spatalk.tenants.bundle import load_bundle
    from spatalk.tenants.schema import Scripts
    bundle = load_bundle(BUNDLE).scripts.model_dump()
    defaults = {k: f.default for k, f in Scripts.model_fields.items() if isinstance(f.default, str)}
    for source in (bundle, defaults):
        with_911 = {k for k, v in source.items() if "911" in str(v)}
        assert with_911 == {"emergency", "emergency_text"}, with_911


def test_bundle_rejects_invalid_hours(tmp_path):
    from spatalk.tenants.bundle import load_bundle
    src = BUNDLE
    for name in ("tenant.yaml", "services.yaml", "knowledge.md", "scripts.yaml", "guard.yaml"):
        (tmp_path / name).write_text((src / name).read_text(encoding="utf-8"), encoding="utf-8")
    t = yaml.safe_load((tmp_path / "tenant.yaml").read_text(encoding="utf-8"))
    t["hours"]["tue"] = [["10:00", "25:00"]]
    (tmp_path / "tenant.yaml").write_text(yaml.safe_dump(t), encoding="utf-8")
    with pytest.raises(ValueError):
        load_bundle(tmp_path)


def test_bundle_secret_refs_are_names_not_values():
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    for dest in cfg.delivery.destinations:
        if dest.kind == "slack":
            assert dest.webhook_env.isupper() and "http" not in dest.webhook_env


def test_json_roundtrip():
    from spatalk.tenants.bundle import config_from_json, config_to_json, load_bundle
    cfg = load_bundle(BUNDLE)
    assert config_from_json(config_to_json(cfg)) == cfg


def test_bundle_whatsapp_destination_names_an_env_var_not_a_phone_number():
    """whatsapp plan, Task W1: a staff number is personal data and stays out of the repo."""
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    wa = [d for d in cfg.delivery.destinations if d.kind == "whatsapp"]
    assert wa, "skincentrix has no whatsapp destination"
    assert wa[0].address_env == "SKINCENTRIX_WHATSAPP_STAFF"
    assert wa[0].address is None
    assert wa[0].address_env.isupper() and not any(c.isdigit() for c in wa[0].address_env)


def test_bundle_sms_destination_names_an_env_var_and_carries_a_messaging_number():
    """sms staff delivery plan, Task S1: the owner mobile is named; the from-number is not."""
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    sms = [d for d in cfg.delivery.destinations if d.kind == "sms"]
    assert sms, "skincentrix has no sms destination"
    assert sms[0].address_env == "SKINCENTRIX_STAFF_SMS" and sms[0].address is None
    assert sms[0].address_env.isupper() and not any(c.isdigit() for c in sms[0].address_env)
    # The tenant messaging number is the clinic's own, so it belongs in the bundle.
    assert cfg.sms_from_number == "+12899170079"
    # The whatsapp destination from the earlier plan is dormant, not removed.
    assert any(d.kind == "whatsapp" for d in cfg.delivery.destinations)


# --- the catalogue the assistant answers from (defect 8, founder call 14ea2579) ------------

# The clinic publishes only the names of these, not what they do: knowledge.md, "Other
# treatments (ask the team for current pricing)". A "what it does" written here by an engineer
# would be a clinic claim spoken to a caller as fact, so the row stays bare and the assistant
# offers the team, which is the honest answer. If the founder supplies wording it goes in
# services.yaml.
UNPRICED_AND_UNDESCRIBED = {
    "xerf_skin_tightening",
    "laser_facial",
    "fractional_resurfacing",
    "scalp_facial",
    "body_contouring",
    "tattoo_removal",
    "acne_program",
}


def test_a_priced_service_says_what_it_does():
    """A price with no purpose beside it is what the assistant read out at 15:53:14.

    The ceiling is the longest of the clinic's own published descriptions
    (`microchanneling_vamp`, 13 words). It is not a style preference: the recital this test
    was written against — the old `facial` row — was 25 words and 208 characters, so a bound
    set by real copy still catches it by a factor of two. Raise it only for wording the
    founder supplied; do not trim a clinic's clinical copy to fit it.
    """
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    bare = set()
    for s in cfg.services:
        if s.price_text.strip().lower() == "ask the team":
            if not (s.description or "").strip():
                bare.add(s.id)
            continue
        desc = (s.description or "").strip()
        assert desc, f"{s.id} has a price and no description"
        assert 3 <= len(desc.split()) <= 13, f"{s.id}: {len(desc.split())} words"
    assert bare == UNPRICED_AND_UNDESCRIBED


def test_a_service_description_is_not_a_price_list():
    """The `facial` row's description was the recital the model read back, figure for figure.

    Every price in it already sat on the specific sibling row it came from, and every figure
    is still in knowledge.md's "Treatments and prices" section.
    """
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    for s in cfg.services:
        assert "$" not in (s.description or ""), s.id
