from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def _apply(slots, name, args, channel="voice", caller="+19055550101"):
    from spatalk.brain.flow import apply

    return apply(slots, name, args, _cfg(), channel, caller)


def test_start_request_opens_a_flow_and_returning_yes_no_are_stored():
    from spatalk.brain.flow import Slots

    a = _apply(Slots(), "start_request", {"kind": "new_booking"})
    assert a.slots.flow == "new_booking" and a.say == ()
    b = _apply(a.slots, "answer", {"value": "yes"})
    assert b.slots.returning_client is True
    c = _apply(a.slots, "answer", {"value": "unsure"})
    assert c.slots.returning_client is False


def test_an_answer_lands_only_in_the_open_slot():
    from spatalk.brain.flow import Slots

    s = Slots(flow="new_booking", returning_client=True)   # open step: PRACTITIONER
    a = _apply(s, "give_name", {"first_name": "Ellen"})     # not this step's tool
    assert a.ignored and a.slots == s and a.slots.first_name is None


def test_close_practitioner_match_asks_did_you_mean_and_yes_stores_it():
    from spatalk.brain.flow import Slots

    s = Slots(flow="new_booking", returning_client=True)
    a = _apply(s, "choose_practitioner", {"said": "Ellen"})
    assert a.slots.pending is not None and a.slots.pending.kind == "match"
    assert a.slots.practitioner is None
    b = _apply(a.slots, "answer", {"value": "yes"})
    assert b.slots.practitioner == "Helen Courbetis" and b.slots.pending is None
    c = _apply(a.slots, "answer", {"value": "no"})
    assert c.slots.practitioner is None and c.slots.misses["practitioner"] == 1


def test_two_practitioner_misses_settle_on_any():
    from spatalk.brain.flow import Slots

    s = Slots(flow="new_booking", returning_client=True)
    a = _apply(s, "choose_practitioner", {"said": "xqzv"})
    assert a.slots.misses["practitioner"] == 1 and a.slots.practitioner is None
    b = _apply(a.slots, "choose_practitioner", {"said": "blorp"})
    assert b.slots.practitioner == "any" and ("practitioner_any", {}) in b.say


def test_practitioner_who_does_not_do_the_service():
    from spatalk.brain.flow import Slots

    cfg = _cfg()
    nurse = next(m for m in cfg.team if m.services and "hydrabrasion_facial" not in m.services)
    s = Slots(flow="new_booking", returning_client=False, offers_done=True, service_id="hydrabrasion_facial")
    a = _apply(s, "choose_practitioner", {"said": nurse.name})
    assert a.slots.pending.kind == "not_service" and a.slots.practitioner is None
    yes = _apply(a.slots, "answer", {"value": "yes"})
    assert yes.say[0][0] == "practitioner_suggest" and yes.slots.pending is None
    no = _apply(a.slots, "answer", {"value": "no"})
    assert no.say[0][0] == "practitioner_else"


def test_a_kind_of_treatment_offers_options_or_the_consultation():
    from spatalk.brain.flow import Slots

    s = Slots(flow="new_booking", returning_client=False, offers_done=True)
    a = _apply(s, "choose_service", {"said": "a facial"})
    assert a.slots.pending.kind == "offers" and a.slots.service_id is None


def test_name_sanity_against_the_practitioner_and_refusing_a_name():
    from spatalk.brain.flow import Slots

    s = Slots(
        flow="new_booking", returning_client=True, practitioner="Helen Courbetis",
        service_id="hydrabrasion_facial",
    )
    a = _apply(s, "give_name", {"first_name": "Helen"})
    assert a.slots.pending.kind == "name_staff"
    assert _apply(a.slots, "answer", {"value": "yes"}).slots.first_name == "Helen"
    r1 = _apply(s, "give_name", {"first_name": ""})
    assert r1.slots.misses["name"] == 1 and r1.slots.first_name is None
    r2 = _apply(r1.slots, "give_name", {"first_name": ""})
    assert r2.say[0][0] == "no_name" and r2.slots.ended_flow and not r2.file


def test_phone_on_a_call_is_the_caller_id_unless_they_say_otherwise():
    from spatalk.brain.flow import Slots

    s = Slots(flow="callback", returning_client=True, practitioner="any",
              service_id="hydrabrasion_facial", first_name="Dana",
              phone="+19055550101")                                     # open step: PHONE
    yes = _apply(s, "answer", {"value": "yes"})
    assert yes.slots.phone == "+19055550101" and yes.slots.phone_confirmed
    no = _apply(s, "answer", {"value": "no"})
    assert no.slots.misses["phone"] == 1
    given = _apply(no.slots, "give_phone", {"digits": "416 555 0199"})
    assert given.slots.pending.kind == "phone" and given.slots.pending.value == "+14165550199"
    ok = _apply(given.slots, "answer", {"value": "yes"})
    assert ok.slots.phone == "+14165550199" and ok.slots.phone_confirmed
    bad = _apply(no.slots, "give_phone", {"digits": "555"})
    assert bad.slots.misses["phone"] == 2 and ("phone_fallback", {}) in bad.say
    assert bad.slots.phone == "+19055550101"


def test_sms_takes_the_sender_number_without_asking():
    from spatalk.brain.flow import Slots, Step, next_step

    s = Slots(flow="callback", returning_client=True, practitioner="any",
              service_id="hydrabrasion_facial", first_name="Dana")
    assert next_step(s, _cfg(), "sms") == Step.WINDOW
    a = _apply(s, "choose_window", {"date": "Thursday", "part_of_day": "morning"}, channel="sms")
    assert a.slots.preferred_window.date == "Thursday"


def test_complete_files_and_route_sends_the_link():
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    done = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
        first_name="Dana", phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(), team_note_asked=True,
    )
    a = _apply(done, "file_request", {})
    assert a.file and a.slots.ended_flow
    booking = done.with_(flow="new_booking")
    link = _apply(booking, "answer", {"value": "yes"})           # ROUTE: yes = the link
    assert link.send_link and link.slots.ended_flow
    call = _apply(booking, "answer", {"value": "no"})            # ROUTE: no = the team calls
    assert call.file and call.slots.ended_flow
    early = _apply(Slots(flow="callback"), "file_request", {})
    assert early.ignored and not early.file


def test_the_record_files_itself_when_the_last_slot_lands():
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    s = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
        first_name="Dana", phone="+19055550101", phone_confirmed=True, preferred_window=PreferredWindow(),
    )
    a = _apply(s, "answer", {"value": "no"})            # TEAM_NOTE answered: nothing left to ask
    assert a.file and a.slots.ended_flow
    sms = _apply(
        Slots(flow="question", phone="+14165550199", phone_confirmed=True),
        "give_name", {"first_name": "Dana"}, channel="sms",
    )
    assert sms.file                                     # sms: the sender's number, nothing else to ask
    partial = _apply(Slots(flow="callback"), "answer", {"value": "yes"})   # RETURNING answered
    assert not partial.file


def test_a_second_request_keeps_the_name_and_number_but_not_the_treatment():
    from spatalk.brain.flow import Slots

    done = Slots(
        flow=None, returning_client=True, first_name="Dana", phone="+1", phone_confirmed=True,
        service_id="hydrabrasion_facial", practitioner="Helen Courbetis",
    )
    a = _apply(done, "start_request", {"kind": "callback"})
    assert a.slots.first_name == "Dana" and a.slots.phone_confirmed and a.slots.returning_client is True
    assert a.slots.service_id is None and a.slots.practitioner is None


def test_the_clinical_offer_is_answered_yes_or_no_before_the_name():
    from spatalk.brain.flow import Slots, Step, next_step

    s = Slots(flow="clinical")
    assert next_step(s, _cfg(), "voice") == Step.NAME
    yes = _apply(s, "answer", {"value": "yes"})
    assert yes.slots == s and yes.say == ()
    no = _apply(s, "answer", {"value": "no"})
    assert no.slots.ended_flow and no.say == (("clinical_declined", {}),) and not no.file


def test_change_answer_reopens_a_step():
    from spatalk.brain.flow import Slots, Step, next_step

    s = Slots(
        flow="new_booking", returning_client=True, practitioner="Helen Courbetis",
        service_id="hydrabrasion_facial", first_name="Dana",
    )
    a = _apply(s, "change_answer", {"slot": "service"})
    assert a.slots.service_id is None and next_step(a.slots, _cfg(), "voice") == Step.SERVICE


def test_a_withheld_caller_id_is_asked_for_a_number_outright():
    from spatalk.brain.flow import Slots, Step, next_step, step_question, step_tools

    s = Slots(flow="callback", returning_client=True, practitioner="any",
              service_id="hydrabrasion_facial", first_name="Dana")
    assert next_step(s, _cfg(), "voice") == Step.PHONE
    assert step_question(Step.PHONE, s, _cfg(), "voice") == ("ask_phone", {})
    assert "give_phone" in [t.name for t in step_tools(Step.PHONE, s, _cfg(), "voice")]
    given = _apply(s, "give_phone", {"digits": "416 555 0199"}, caller=None)
    assert given.slots.pending.kind == "phone"


def test_a_booking_on_a_text_channel_ends_with_the_link_and_a_call_without_sms_files():
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    booking = Slots(
        flow="new_booking", returning_client=True, practitioner="any", service_id="facial",
        first_name="Dana", phone="+14165550199", phone_confirmed=True, preferred_window=PreferredWindow(),
    )
    chat = _apply(booking, "answer", {"value": "no"}, channel="chat")     # TEAM_NOTE
    assert chat.send_link and not chat.file
    from spatalk.brain.flow import apply
    no_sms = _cfg().model_copy(update={"sms_from_number": None})
    call = apply(booking, "answer", {"value": "no"}, no_sms, "voice", "+19055550101")
    assert call.file and not call.send_link


def test_a_training_enquiry_is_a_request_too():
    from spatalk.brain.flow import Slots, Step, draft_from, next_step

    a = _apply(Slots(), "start_request", {"kind": "training_enquiry"}, caller=None)
    assert a.slots.flow == "training_enquiry" and next_step(a.slots, _cfg(), "voice") == Step.NAME
    done = a.slots.with_(first_name="Dana", phone="+19055550101", phone_confirmed=True)
    assert draft_from(done, _cfg()).type == "training_enquiry"

