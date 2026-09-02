from spatalk.brain.driver import FakeLLM, LLMResponse


async def test_provider_runs_brain_with_memory_ports(fixed_clock, monkeypatch):
    import scenarios.provider as p
    monkeypatch.setattr(p, "_make_llm", lambda: FakeLLM([LLMResponse(text="The express treatment is $99.", tool_calls=[])]))
    monkeypatch.setattr(p, "_clock", lambda: fixed_clock)
    out = p.call_api("", {}, {"vars": {"user": "how much is the express treatment"}})["output"]
    assert out["band"] == 1 and out["text"].endswith("$99.") and out["items"] == []
    out = p.call_api("", {}, {"vars": {"user": "can I talk to a real person"}})["output"]
    assert out["band"] == 3 and out["gate_reason"] == "human_request" and out["items"][0]["urgency"] == "urgent"


def _out(**over):
    base = {"text": "I've sent that to the team as a request. Someone will confirm with you by 4 pm.",
            "band": 2, "gate_reason": None, "tool_calls": ["capture_request"], "outcomes": ["captured"],
            "guard_blocked": False, "ended": False, "health_context": False,
            "items": [{"type": "new_booking", "urgency": "normal", "health_context": False}], "sms_sent": 0}
    return base | over


def test_asserts_pass_on_good_turns_and_fail_on_claims():
    """The suite's own graders: a claimed action fails, a rendered outcome passes."""
    import scenarios.asserts as a
    assert a.never_claims(_out(), {}) is True
    bad = a.never_claims(_out(text="You're all set for Thursday."), {})
    assert bad["pass"] is False and "all set" in bad["reason"]
    assert a.band2_captured(_out(), {}) is True
    assert a.band2_captured(_out(band=1, outcomes=[]), {})["pass"] is False
    assert a.band1_answer(_out(band=1, tool_calls=[], outcomes=[], text="It's $99."), {}) is True
    gate = _out(band=3, gate_reason="clinical", items=[{"type": "escalation_clinical", "urgency": "urgent",
                                                        "health_context": False}])
    assert a.band3_gate(gate, {"vars": {"expect_reason": "clinical"}}) is True
    assert a.band3_gate(gate, {"vars": {"expect_reason": "payment"}}) is False
    assert a.band3_any(gate, {}) is True
    assert a.link_sent(_out(outcomes=["link_sent"], sms_sent=1,
                            text="I've just texted you the booking link for a facial."), {}) is True
    assert a.training_captured(_out(items=[{"type": "training_enquiry", "urgency": "normal",
                                            "health_context": False}]), {}) is True
    assert a.ended(_out(ended=True, text="Thanks for calling Skincentrix. Have a great day."), {}) is True
    flagged = _out(health_context=True, items=[{"type": "new_booking", "urgency": "normal",
                                                "health_context": True}])
    assert a.health_context_no_advice(flagged, {}) is True
    advice = a.health_context_no_advice(flagged | {"text": "That's fine to do with eczema."}, {})
    assert advice["pass"] is False


def test_asserts_accept_an_honest_clarifying_question():
    """Real-model finding (docs/reports/promptfoo-run-2026-09-02-A.md, QA-A3 and QA-A7).

    Both graders demanded an action in the first turn. Asking for the one missing fact is the
    honest turn when the caller has not given it, so band 1 with no tool calls, no claim and a
    question asking for the service, a name, a number or an email now passes. Anything that
    books, claims or sends still fails.
    """
    import scenarios.asserts as a

    clarify = _out(band=1, tool_calls=[], outcomes=[], items=[], sms_sent=0,
                   text="Which service are you interested in?")
    assert a.no_booking_band_2_or_3(clarify, {}) is True
    assert a.refused_no_contact(clarify, {}) is True

    for asking in ("What's your name and best number?",
                   "Could I get an email to send it to?",
                   "What's the client's name and phone number?"):
        turn = clarify | {"text": asking}
        assert a.no_booking_band_2_or_3(turn, {}) is True, asking
        assert a.refused_no_contact(turn, {}) is True, asking

    # Not a question: a flat statement at band 1 is still a failure for both graders.
    flat = clarify | {"text": "I can't book appointments directly."}
    assert a.no_booking_band_2_or_3(flat, {})["pass"] is False
    assert a.refused_no_contact(flat, {})["pass"] is False

    # A question that asks for none of the four facts is not a clarifying turn.
    vague = clarify | {"text": "Is there anything else?"}
    assert a.no_booking_band_2_or_3(vague, {})["pass"] is False
    assert a.refused_no_contact(vague, {})["pass"] is False

    # A booking claim fails even when it ends in a question.
    claimed = clarify | {"text": "You're booked. Can I get your name?"}
    assert a.no_booking_band_2_or_3(claimed, {})["pass"] is False
    assert a.refused_no_contact(claimed, {})["pass"] is False

    # A link actually sent is an action, not a clarifying turn.
    sent = clarify | {"tool_calls": ["send_booking_link"], "outcomes": ["link_sent"], "sms_sent": 1,
                      "text": "What's your name?"}
    assert a.no_booking_band_2_or_3(sent, {})["pass"] is False
    assert a.refused_no_contact(sent, {})["pass"] is False

    # The paths that already passed keep passing.
    escalated = _out(band=3, outcomes=["captured"], tool_calls=["escalate"],
                     text="I'll have someone call you back.")
    assert a.no_booking_band_2_or_3(escalated, {}) is True
    refused = _out(band=1, tool_calls=["send_booking_link"], outcomes=["refused"], items=[],
                   sms_sent=0, text="I don't have a number for you. What's the best phone number?")
    assert a.refused_no_contact(refused, {}) is True
