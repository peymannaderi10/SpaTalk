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
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    s = Slots(flow="new_booking", phone="+19055550101")   # the caller id, still to confirm
    expect = {
        Step.RETURNING: "answer", Step.OFFERS: "answer", Step.PRACTITIONER: "choose_practitioner",
        Step.SERVICE: "choose_service", Step.NAME: "give_name", Step.PHONE: "answer",
        Step.WINDOW: "choose_window", Step.TEAM_NOTE: "answer", Step.ROUTE: "answer",
    }
    for step, tool in expect.items():
        names = _names(step_tools(step, s, cfg, "voice"))
        assert tool in names, (step, names)
        assert "file_request" not in names or step == Step.ROUTE
        assert "change_answer" in names


def test_phone_step_offers_give_phone_once_the_caller_said_no():
    from spatalk.brain.flow import Slots, Step, step_tools

    s = Slots(flow="callback", first_name="Dana").miss("phone")
    assert "give_phone" in _names(step_tools(Step.PHONE, s, _cfg(), "voice"))
    chat = Slots(flow="callback", first_name="Dana")
    assert "give_phone" in _names(step_tools(Step.PHONE, chat, _cfg(), "chat"))


def test_complete_offers_file_request_and_route_offers_send_link_only_with_sms():
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    assert "file_request" in _names(step_tools(Step.COMPLETE, Slots(flow="callback"), cfg, "voice"))
    route = _names(step_tools(
        Step.ROUTE, Slots(flow="new_booking", phone="+1", phone_confirmed=True), cfg, "voice",
    ))
    assert "send_link" in route and "file_request" in route
    no_sms = cfg.model_copy(update={"sms_from_number": None})
    assert "send_link" not in _names(step_tools(Step.ROUTE, Slots(flow="new_booking"), no_sms, "voice"))


def test_no_tool_carries_contact_lead_or_free_text_beyond_the_three_transients():
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    # `choose_window.date` is closed by `PreferredWindow` (ISO date, weekday or "any").
    allowed_free = {
        ("give_name", "first_name"), ("give_phone", "digits"),
        ("choose_practitioner", "said"), ("choose_service", "said"),
        ("choose_window", "date"),
    }
    for step in Step:
        for tool in step_tools(step, Slots(flow="new_booking"), cfg, "voice"):
            for prop, schema in tool.properties.items():
                assert prop not in ("contact", "notes", "returning_client", "concern"), (tool.name, prop)
                if schema.get("type") == "string" and "enum" not in schema:
                    assert (tool.name, prop) in allowed_free, (tool.name, prop)
