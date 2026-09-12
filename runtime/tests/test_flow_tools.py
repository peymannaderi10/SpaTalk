from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def _names(tools):
    return [t.name for t in tools]


def test_qa_offers_start_request_and_nothing_that_files():
    from spatalk.brain.flow import Slots, Step, step_tools

    names = _names(step_tools(Step.QA, Slots(), _cfg(), "voice"))
    assert "start_request" in names and "escalate" in names and "end_conversation" in names
    assert "file_request" not in names and "send_link" not in names and "give_name" not in names


def test_each_step_offers_exactly_its_slot_tool():
    """MOVED 2026-09-11: `Step.ROUTE` became `Step.LINK_OFFER`, and its escape hatch on
    `file_request` went with it — the record is on the ledger before that step exists, so
    `file_request` is now absent at every step but COMPLETE. `change_answer` is absent there
    too: a reopened slot would leave a stale row the ledger has no way to amend."""
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    s = Slots(flow="new_booking", phone="+19055550101")   # the caller id, still to confirm
    expect = {
        Step.RETURNING: "answer", Step.OFFERS: "answer", Step.PRACTITIONER: "choose_practitioner",
        Step.SERVICE: "choose_service", Step.NAME: "give_name", Step.PHONE: "answer",
        Step.WINDOW: "choose_window", Step.TEAM_NOTE: "answer", Step.LINK_OFFER: "answer",
    }
    for step, tool in expect.items():
        names = _names(step_tools(step, s, cfg, "voice"))
        assert tool in names, (step, names)
        assert "file_request" not in names
        assert "change_answer" in names or step == Step.LINK_OFFER


def test_phone_step_offers_give_phone_once_the_caller_said_no():
    from spatalk.brain.flow import Slots, Step, step_tools

    s = Slots(flow="callback", first_name="Dana").miss("phone")
    assert "give_phone" in _names(step_tools(Step.PHONE, s, _cfg(), "voice"))
    chat = Slots(flow="callback", first_name="Dana")
    assert "give_phone" in _names(step_tools(Step.PHONE, chat, _cfg(), "chat"))


def test_complete_offers_file_request_and_route_offers_send_link_only_with_sms():
    """MOVED 2026-09-11: `Step.ROUTE` became `Step.LINK_OFFER` on a record that is already
    filed, and `"file_request" in route` became `"file_request" not in link_offer`."""
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    assert "file_request" in _names(step_tools(Step.COMPLETE, Slots(flow="callback"), cfg, "voice"))
    filed = Slots(flow="new_booking", phone="+1", phone_confirmed=True, filed=True)
    link_offer = _names(step_tools(Step.LINK_OFFER, filed, cfg, "voice"))
    assert "send_link" in link_offer and "file_request" not in link_offer
    no_sms = cfg.model_copy(update={"sms_from_number": None})
    assert "send_link" not in _names(
        step_tools(Step.LINK_OFFER, Slots(flow="new_booking", filed=True), no_sms, "voice")
    )


def test_the_link_offer_offers_answer_and_send_link_and_never_file_request():
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    filed = Slots(
        flow="new_booking", service_id="mesojet_facial", phone="+19055550101",
        phone_confirmed=True, filed=True,
    )
    names = _names(step_tools(Step.LINK_OFFER, filed, cfg, "voice"))
    assert "answer" in names and "send_link" in names
    assert "file_request" not in names and "change_answer" not in names
    no_sms = _names(step_tools(
        Step.LINK_OFFER, filed, cfg.model_copy(update={"sms_from_number": None}), "voice"
    ))
    assert "answer" in no_sms and "send_link" not in no_sms
    unconfirmed = _names(step_tools(Step.LINK_OFFER, filed.with_(phone_confirmed=False), cfg, "voice"))
    assert "answer" in unconfirmed and "send_link" not in unconfirmed


def test_no_tool_carries_contact_lead_or_free_text_beyond_the_three_transients():
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    # `choose_window.date` is closed by `PreferredWindow` (ISO date, weekday or "any").
    allowed_free = {
        ("give_name", "first_name"), ("give_phone", "digits"),
        ("choose_practitioner", "said"), ("choose_service", "said"),
        ("change_answer", "said"),
        ("choose_window", "date"),
    }
    for step in Step:
        for tool in step_tools(step, Slots(flow="new_booking"), cfg, "voice"):
            for prop, schema in tool.properties.items():
                assert prop not in ("contact", "notes", "returning_client", "concern"), (tool.name, prop)
                if schema.get("type") == "string" and "enum" not in schema:
                    assert (tool.name, prop) in allowed_free, (tool.name, prop)


def test_change_answer_carries_the_callers_words():
    """Defect 7, founder call 14ea2579, 15:56:05. The schema was `slot` alone, so the runtime
    had no way to tell a correction from "Oh, actually, you know" and cleared a filled window
    on it. `said` is the caller's own words, read and thrown away like `choose_service.said`:
    the engine judges the turn with it and stores nothing from it."""
    from spatalk.brain.tools import slot_tool

    tool = slot_tool("change_answer", _cfg())
    assert set(tool.properties) == {"slot", "said"}
    assert tool.required == ["slot", "said"]
    assert tool.properties["said"]["type"] == "string"
    assert "notes" not in tool.properties
