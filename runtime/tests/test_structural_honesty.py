from pathlib import Path

TIER_C = Path(__file__).resolve().parents[1] / "spatalk" / "brain" / "tier_c.py"


def test_tier_c_never_mentions_completed():
    src = TIER_C.read_text(encoding="utf-8")
    assert "Completed" not in src, "Tier C must be unable to construct a Completed outcome"


def test_completed_is_not_importable_from_tier_c_namespace():
    import spatalk.brain.tier_c as tier_c
    assert not hasattr(tier_c, "Completed")


def test_item_draft_has_no_free_text_field():
    """The closed set widened on 2026-09-03 (lead context plan, Task L1), deliberately.

    `returning_client` is a boolean, `practitioner` is a name from the tenant's `team` (or
    "any"), `concern` is one of the tenant's `concerns`. The ledger nulls anything else, so
    the set is still closed and there is still no free text on a tracked item.
    """
    from spatalk.brain.ports import ItemDraft
    assert set(ItemDraft.model_fields) == {"type", "urgency", "service_id", "contact", "preferred_window", "health_context", "returning_client", "practitioner", "concern"}
    assert ItemDraft.model_fields["health_context"].annotation is bool


# --- call notes (call-notes plan, Task N1) -------------------------------------------------
# Model-drafted notes are allowed to exist, in exactly one place: `conversations.notes`. The
# four tests below are the fence around that clarification to non-negotiable 2. They are
# structural on purpose: each one fails if a later change gives the notes a second home, a
# way into a tool schema, a way into a later prompt, or a way to the caller's ear.

RUNTIME = Path(__file__).resolve().parents[1]


def test_no_tool_schema_has_a_notes_parameter():
    """The model still has nowhere to put free text on a tracked item."""
    from pathlib import Path as _Path

    from spatalk.brain.tools import build_tools
    from spatalk.tenants.bundle import load_bundle

    cfg = load_bundle(_Path(RUNTIME) / "tenants" / "skincentrix")
    for tool in build_tools(cfg):
        assert "notes" not in tool.properties, f"{tool.name} exposes a notes parameter"
        assert "notes" not in tool.required


def test_the_notes_live_on_the_conversation_and_nowhere_else():
    from spatalk.brain.ports import ItemDraft
    from spatalk.models import Conversation, Item

    assert {"notes", "notes_model", "notes_at"} <= set(Conversation.__table__.columns.keys())
    assert "notes" not in Item.__table__.columns
    assert "notes" not in ItemDraft.model_fields


def test_the_notes_can_never_re_enter_a_prompt():
    """`build_system_prompt` is a pure function of the config, the channel and the clock."""
    import inspect

    from spatalk.brain.prompt import build_system_prompt

    assert list(inspect.signature(build_system_prompt).parameters) == ["cfg", "channel", "now"]
    prompt_src = (RUNTIME / "spatalk" / "brain" / "prompt.py").read_text(encoding="utf-8")
    assert "notes" not in prompt_src, "the prompt module must not reference the notes at all"


def test_the_notes_never_reach_a_channel():
    """Nothing that speaks or sends can see them: not TTS, not the guard, not a port."""
    notes_src = (RUNTIME / "spatalk" / "ledger" / "notes.py").read_text(encoding="utf-8")
    for forbidden in ("TTSSpeakFrame", "OutputGuardProcessor", "guard(", "render_script",
                      "SmsPort", "send_text", "send_sms", "ctx.sms"):
        assert forbidden not in notes_src, f"the notes module reaches a channel via {forbidden}"

    for package in ("voice", "text", "social"):
        for path in (RUNTIME / "spatalk" / package).rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            assert "ledger.notes" not in src and "ledger import notes" not in src, (
                f"{path} imports the notes drafting module; nothing that talks to a "
                "customer may"
            )
