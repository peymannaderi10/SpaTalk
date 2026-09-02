from pathlib import Path

TIER_C = Path(__file__).resolve().parents[1] / "spatalk" / "brain" / "tier_c.py"


def test_tier_c_never_mentions_completed():
    src = TIER_C.read_text(encoding="utf-8")
    assert "Completed" not in src, "Tier C must be unable to construct a Completed outcome"


def test_completed_is_not_importable_from_tier_c_namespace():
    import spatalk.brain.tier_c as tier_c
    assert not hasattr(tier_c, "Completed")


def test_item_draft_has_no_free_text_field():
    from spatalk.brain.ports import ItemDraft
    assert set(ItemDraft.model_fields) == {"type", "urgency", "service_id", "contact", "preferred_window", "health_context"}
    assert ItemDraft.model_fields["health_context"].annotation is bool
