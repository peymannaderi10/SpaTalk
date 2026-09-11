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
    assert yes.slots.offer_accepted and yes.say == ()
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


def test_the_clinical_offer_takes_only_yes_or_no_until_it_is_accepted():
    from spatalk.brain.flow import Slots, Step, step_tools

    s = Slots(flow="clinical", phone="+19055550101")
    assert [t.name for t in step_tools(Step.NAME, s, _cfg(), "voice")][:1] == ["answer"]
    assert "give_name" not in [t.name for t in step_tools(Step.NAME, s, _cfg(), "voice")]
    ignored = _apply(s, "give_name", {"first_name": "yes please, that would be great"})
    assert ignored.ignored and ignored.slots.first_name is None
    yes = _apply(s, "answer", {"value": "yes"})
    assert yes.slots.offer_accepted
    assert "give_name" in [t.name for t in step_tools(Step.NAME, yes.slots, _cfg(), "voice")]


def test_words_that_are_not_a_name_are_not_stored_as_one():
    from spatalk.brain.flow import Slots

    s = Slots(flow="callback", returning_client=True, practitioner="any", service_id="facial")
    for said in ("yes please", "actually, make it the hydrabrasion instead", "no", "um", "12"):
        a = _apply(s, "give_name", {"first_name": said})
        assert a.slots.first_name is None and a.slots.misses.get("name") == 1, said
    for said, want in (("it's Dana", "Dana"), ("My name is Dana Whitfield", "Dana"), ("dana", "Dana")):
        assert _apply(s, "give_name", {"first_name": said}).slots.first_name == want, said


def test_a_goodbye_at_the_last_question_files_the_request_first():
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    s = Slots(flow="callback", returning_client=True, practitioner="any", service_id="facial",
              first_name="Dana", phone="+19055550101", phone_confirmed=True, preferred_window=PreferredWindow())
    a = _apply(s, "end_conversation", {})
    assert a.file and a.end and a.slots.team_note_asked
    early = _apply(Slots(flow="callback", returning_client=True), "end_conversation", {})
    assert early.end and not early.file


def test_the_runtime_recites_the_offers_from_the_knowledge_file():
    from spatalk.brain.flow import Slots, offers_text

    text = offers_text(_cfg())
    assert text.startswith("a $50 credit") and "free virtual consultation" in text and " and " in text
    a = _apply(Slots(flow="new_booking", returning_client=False), "answer", {"value": "yes"})
    assert a.say == (("offers_intro", {"offers": text}),) and a.slots.offers_done
    no = _apply(Slots(flow="new_booking", returning_client=False), "answer", {"value": "no"})
    assert no.say == () and no.slots.offers_done


def test_change_answer_for_a_slot_that_holds_nothing_is_ignored():
    """Founder call 2026-09-10 20:54:29. The caller asked "what was the $50 one you said?";
    the model read that as a correction and called change_answer(service) at a step where no
    treatment was stored yet. Nothing was reopened, nothing was said, and the runtime asked
    "What did you have in mind?" for the second time in a row, which is what read as the
    assistant having forgotten the conversation. A change to a slot that holds nothing is not
    a change: it is an ignored call, and an ignored call hands the turn back to the model."""
    from spatalk.brain.flow import Slots

    s = Slots(flow="new_booking", returning_client=False, offers_done=True)
    a = _apply(s, "change_answer", {"slot": "service"})
    assert a.ignored and a.slots == s
    # And the model is told which way it was wrong, so it stops guessing (2026-09-11 memo).
    assert a.rejection.reason == "bad_value" and a.rejection.detail == "empty_slot"
    # A slot that does hold something is still reopened.
    b = _apply(s.with_(service_id="mesojet_facial"), "change_answer", {"slot": "service"})
    assert not b.ignored and b.slots.service_id is None
    # A slot name the engine does not know was already ignored; it stays that way.
    assert _apply(s, "change_answer", {"slot": "mood"}).ignored


def test_change_answer_looks_at_the_slot_not_the_miss_counter():
    """A miss the resolver recorded is not something the caller asked to change: with no
    treatment stored, change_answer(service) is still an ignored call even after a miss."""
    from spatalk.brain.flow import Slots

    s = Slots(flow="new_booking", returning_client=False, offers_done=True, misses={"service": 1})
    assert _apply(s, "change_answer", {"slot": "service"}).ignored


def test_a_question_shaped_answer_is_refused_with_a_reason():
    """Founder call 2026-09-11 01:41. "Sorry, what was the- what was the facial one again?"
    became `choose_service(said='the facial one')`, the resolver filled the slot and the step
    moved on to the practitioner with the caller's question unanswered. A question is not an
    answer: nothing is resolved, nothing is written, and the tool result tells the model to
    answer it. The rejection is a function response to the model, never spoken and never
    stored.

    `Applied.rejection` carries the Parlant shape from 2026-09-11 rather than a flat
    sentence, so each assertion below reads it through `rejection_text` and now also pins
    the reason code and the detail. Nothing that was asserted before has been removed."""
    from spatalk.brain.flow import Slots, rejection_text

    s = Slots(flow="new_booking", returning_client=False, offers_done=True)   # open: SERVICE
    for said in (
        "what was the station one again?",
        "Sorry, what was the- what was the facial one again? The facial one?",
    ):
        a = _apply(s, "choose_service", {"said": said})
        assert a.ignored and a.slots == s, said
        assert a.rejection and "question" in rejection_text(a.rejection).lower(), said
        assert a.rejection.reason == "bad_value" and a.rejection.detail == "question_shaped", said
    # The control still resolves: the same words without the question.
    c = _apply(s, "choose_service", {"said": "the facial one"})
    assert not c.ignored and c.rejection is None
    assert c.slots.service_id or c.slots.pending
    p = Slots(flow="new_booking", returning_client=True)                      # open: PRACTITIONER
    d = _apply(p, "choose_practitioner", {"said": "what was the name again?"})
    assert d.ignored and d.slots == p and d.rejection
    assert d.rejection.detail == "question_shaped"
    e = _apply(p, "choose_practitioner", {"said": "Helen"})
    assert not e.ignored and e.slots.practitioner == "Helen Courbetis"
    # `answer` carries a closed enum, so anything else in it is the same failure.
    r = Slots(flow="new_booking")                                             # open: RETURNING
    g = _apply(r, "answer", {"value": "what do you mean?"})
    assert g.ignored and g.rejection and g.slots.returning_client is None
    assert g.rejection.reason == "bad_value" and g.rejection.detail == "not_a_choice"
    assert _apply(r, "answer", {"value": "unsure"}).slots.returning_client is False


def test_a_generic_category_entry_does_not_fill_the_treatment_slot():
    """The other half of the 01:41:26 defect: "the facial one" moved the step on to the
    practitioner. A kind opens `ask_service_kind` and the treatment slot stays empty."""
    from spatalk.brain.flow import Slots, next_step, step_question

    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=False, offers_done=True)
    a = _apply(s, "choose_service", {"said": "the facial one"})
    assert a.slots.service_id is None
    assert a.slots.pending is not None and a.slots.pending.kind == "offers"
    key, _fills = step_question(next_step(a.slots, cfg, "voice"), a.slots, cfg, "voice")
    assert key == "ask_service_kind"


# --- the side question gets a turn of its own (memo §2) -----------------------------------


def test_answer_question_writes_nothing_and_pushes_one_frame():
    """Founder call 2026-09-11 01:40. "Uh, what was the facial one again?" had nowhere to go
    but `choose_service`, and the resolver matched the generic `facial` entry as exact. The
    tool that fixes it takes no arguments and writes nothing: its only effect is to record
    what the runtime was about to ask and hand the turn to the model."""
    from spatalk.brain.flow import Slots, Step, apply, next_step

    cfg = _cfg()
    before = Slots(flow="new_booking", returning_client=False, offers_done=True)
    assert next_step(before, cfg, "voice") == Step.SERVICE
    a = apply(before, "answer_question", {}, cfg, "voice", "+19055550101")
    assert a.ignored is False and a.say == () and a.file is False and a.send_link is False
    assert a.model_speaks is True
    assert a.slots.digression == Step.SERVICE
    # Not one slot moved, and the open step is where it was.
    assert a.slots.with_(digression=None) == before
    assert next_step(a.slots, cfg, "voice") == Step.SERVICE


def test_the_frame_pops_when_the_record_is_still_at_the_same_step_and_is_dropped_when_it_moved():
    """Resume by completion criterion, not by re-asking (RavenClaw, not Rasa): a caller who
    answered the open question *inside* the side question does not get asked it again."""
    from spatalk.brain.flow import Slots, Step, pop_digression

    cfg = _cfg()
    opened = Slots(flow="new_booking", returning_client=False, offers_done=True, digression=Step.SERVICE)
    assert pop_digression(opened, cfg, "voice").digression is None
    moved = opened.with_(service_id="classic_facial")
    assert pop_digression(moved, cfg, "voice").digression is None
    assert pop_digression(moved, cfg, "voice").service_id == "classic_facial"


def test_the_tool_is_offered_at_every_step_and_carries_no_argument():
    from spatalk.brain.flow import Slots, Step, step_tools

    cfg = _cfg()
    for step in Step:
        tool = next(
            t for t in step_tools(step, Slots(flow="new_booking"), cfg, "voice", transfer_enabled=True)
            if t.name == "answer_question"
        )
        assert tool.properties == {} and tool.required == []
