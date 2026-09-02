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
    assert "{confirm_by}" in cfg.scripts.captured
    assert cfg.hours["tue"] == [("10:00", "18:00")]
    assert cfg.recording_enabled is False
    assert cfg.retention_days == 30
    assert "911" in cfg.scripts.clinical
    assert cfg.scripts.refuse_unavailable and cfg.scripts.failover and cfg.scripts.loop_guard
    assert cfg.social.comment_mode == "keyword" and cfg.transfer_number is None


def test_scripts_reject_completion_wording():
    from spatalk.tenants.bundle import load_bundle
    from spatalk.tenants.schema import Scripts
    cfg = load_bundle(BUNDLE)
    with pytest.raises(ValueError):
        Scripts.model_validate({**cfg.scripts.model_dump(), "captured": "Great, you're booked for {confirm_by}."})
    with pytest.raises(ValueError):
        Scripts.model_validate({**cfg.scripts.model_dump(), "clinical": "Someone will call you back {confirm_by}."})


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
