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

    from spatalk.brain.flow import Slots, Step, step_tools
    from spatalk.tenants.bundle import load_bundle

    cfg = load_bundle(_Path(RUNTIME) / "tenants" / "skincentrix")
    for step in Step:
        for tool in step_tools(step, Slots(flow="new_booking"), cfg, "voice", transfer_enabled=True):
            assert "notes" not in tool.properties, f"{tool.name} exposes a notes parameter"
            assert "notes" not in tool.required


def test_file_request_takes_no_arguments():
    """The item is built from the runtime's record, never from a tool argument (§3.2)."""
    from pathlib import Path as _Path

    from spatalk.brain.flow import Slots, Step, step_tools
    from spatalk.tenants.bundle import load_bundle

    cfg = load_bundle(_Path(RUNTIME) / "tenants" / "skincentrix")
    tools = step_tools(Step.COMPLETE, Slots(flow="callback"), cfg, "voice")
    tool = next(t for t in tools if t.name == "file_request")
    assert tool.properties == {} and tool.required == []


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


def test_item_drafts_in_the_request_path_come_only_from_draft_from():
    """An item is built from the slot record, never in a driver (slot engine design, §3.2)."""
    from pathlib import Path as _Path

    for rel in ("spatalk/brain/driver.py", "spatalk/voice/handlers.py", "spatalk/voice/processors.py"):
        src = (_Path(RUNTIME) / rel).read_text(encoding="utf-8")
        assert "ItemDraft(" not in src, rel


# --- one egress to the wire (model-words memo, §3.1) --------------------------------------


def test_only_the_egress_function_can_speak_on_a_call():
    """Memo §3.1: "One private egress function is the only path to TTS, with `guard()` inside
    it and a guard-owned re-entrancy flag; no `skip_guard` parameter anywhere."

    Structural rather than behavioural on purpose. Every earlier false claim on a call
    reached the wire through a code path that had not thought about the guard; the fix that
    lasts is that there is only one path.
    """
    import ast
    from pathlib import Path as _Path

    src = (_Path(RUNTIME) / "spatalk" / "voice" / "processors.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    guard_cls = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "OutputGuardProcessor"
    )
    speakers = set()
    for node in ast.walk(guard_cls):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not (isinstance(callee, ast.Attribute) and callee.attr in ("push_frame", "queue_frame")):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                speakers.add(arg.func.id)
    # The only frames this class constructs and pushes are speech frames, and they are
    # constructed in exactly one method.
    assert speakers <= {"LLMTextFrame", "TTSSpeakFrame"}, speakers
    methods = [
        m.name for m in guard_cls.body
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id in ("LLMTextFrame", "TTSSpeakFrame")
            for c in ast.walk(m)
        )
    ]
    assert methods == ["_egress"], f"speech is constructed in {methods}, not only in _egress"
    assert "skip_guard" not in src


def test_no_model_utterance_reaches_a_channel_without_the_guard():
    """`guard(` appears in `_egress` and nowhere else in the voice package."""
    from pathlib import Path as _Path

    for path in (_Path(RUNTIME) / "spatalk" / "voice").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        if "guard(" not in src:
            continue
        assert path.name == "processors.py", f"{path} calls guard() outside the egress"
        assert src.count("guard(self") + src.count("= guard(") == 1, "more than one guard call"


def test_the_signal_log_is_a_second_place_free_text_cannot_reach():
    """The log is a new per-call record, so it gets the same fence the notes got."""
    from pathlib import Path as _Path

    from spatalk.ops.signals import CLOSED_VALUE, DETAIL_KEYS, SIGNAL_KINDS

    assert "text" not in DETAIL_KEYS and "said" not in DETAIL_KEYS and "notes" not in DETAIL_KEYS
    assert CLOSED_VALUE.pattern == r"^[a-z_]{1,40}$"
    src = (_Path(RUNTIME) / "spatalk" / "ops" / "signals.py").read_text(encoding="utf-8")
    for forbidden in ("TTSSpeakFrame", "render_script", "SmsPort", "send_text", "ItemDraft("):
        assert forbidden not in src, forbidden
    assert all(k == k.lower() and " " not in k for k in SIGNAL_KINDS)
