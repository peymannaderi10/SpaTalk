from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def _apply(slots, name, args, channel="voice", caller="+19055550101", said=""):
    from spatalk.brain.flow import apply

    return apply(slots, name, args, _cfg(), channel, caller, caller_said=said)


def test_start_request_opens_a_flow_and_returning_yes_no_are_stored():
    from spatalk.brain.flow import Slots

    a = _apply(Slots(), "start_request", {"kind": "new_booking"})
    assert a.slots.flow == "new_booking" and a.say == ()
    b = _apply(a.slots, "answer", {"value": "yes"})
    assert b.slots.returning_client is True
    # MOVED 2026-09-11 (founder call 1565370e, 21:40:17): "Okay." to "have you been in before?"
    # became `unsure`, which used to be stored as a new client and the call moved on. It is
    # a non-answer: the first one is refused so the model asks again in its own words; the
    # second settles as a new client, so a caller who will not say is still helped.
    c = _apply(a.slots, "answer", {"value": "unsure"})
    assert c.ignored and c.rejection.detail == "needs_yes_or_no"
    assert c.slots.returning_client is None and c.slots.misses == {"returning_client": 1}
    d = _apply(c.slots, "answer", {"value": "unsure"})
    assert d.slots.returning_client is False and not d.ignored


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


def _filled_booking():
    """The founder's record at 15:56:02: every required slot of a new-client booking."""
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    return Slots(
        flow="new_booking", returning_client=False, offers_done=True,
        service_id="mesojet_facial", practitioner="any", first_name="Payman",
        phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(part_of_day="afternoon"), team_note_asked=True,
    )


def test_complete_files_and_route_sends_the_link():
    """MOVED 2026-09-11: the two ROUTE assertions became the link-offer pair below, because
    the route question stood between a complete record and the ledger (founder call
    14ea2579). What this test still pins is `file_request` and the premature refusal."""
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    done = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
        first_name="Dana", phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(), team_note_asked=True,
    )
    a = _apply(done, "file_request", {})
    assert a.file and a.slots.ended_flow and a.slots.filed is True
    early = _apply(Slots(flow="callback"), "file_request", {})
    assert early.ignored and not early.file


def test_a_voice_booking_files_at_the_last_slot_and_then_offers_the_link():
    """Founder call 14ea2579, 2026-09-11 15:56:02.948. The last slot landed and the runtime
    asked the route question instead of filing; the call ended with the booking nowhere but
    the transcript. The record files on that same call, and the link becomes an extra."""
    from spatalk.brain.flow import Step, next_step, step_question

    cfg = _cfg()
    one_short = _filled_booking().with_(team_note_asked=False)
    a = _apply(one_short, "answer", {"value": "no"})
    assert a.file is True and a.send_link is False
    assert a.slots.filed is True and a.slots.ended_flow is False
    assert next_step(a.slots, cfg, "voice") == Step.LINK_OFFER
    assert step_question(Step.LINK_OFFER, a.slots, cfg, "voice") == ("link_offer", {})


def test_yes_to_the_link_sends_it_and_no_says_so_and_neither_files_again():
    filed = _filled_booking().with_(filed=True)
    yes = _apply(filed, "answer", {"value": "yes"})
    assert yes.send_link is True and yes.file is False
    assert yes.slots.link_offered is True and yes.slots.ended_flow is True
    no = _apply(filed, "answer", {"value": "no"})
    assert no.file is False and no.send_link is False
    assert no.say == (("link_declined", {}),)
    assert no.slots.link_offered is True and no.slots.ended_flow is True


def test_a_filed_record_can_never_file_twice():
    """The ledger has no amend path, so a second row for one request is a second job for the
    team. Nothing the link step offers may file, and neither may a record forced back to
    COMPLETE with the offer already answered."""
    from spatalk.brain.flow import Step, next_step, step_tools

    cfg = _cfg()
    filed = _filled_booking().with_(filed=True)
    assert next_step(filed, cfg, "voice") == Step.LINK_OFFER
    for tool in step_tools(Step.LINK_OFFER, filed, cfg, "voice"):
        for args in ({"value": "yes"}, {"value": "no"}, {}):
            assert _apply(filed, tool.name, args).file is False, (tool.name, args)
    answered = filed.with_(link_offered=True)
    assert next_step(answered, cfg, "voice") == Step.COMPLETE
    assert _apply(answered, "answer", {"value": "no"}).file is False


def test_no_sms_number_files_and_ends_in_one_move():
    from spatalk.brain.flow import Step, apply, next_step

    no_sms = _cfg().model_copy(update={"sms_from_number": None})
    one_short = _filled_booking().with_(team_note_asked=False)
    a = apply(one_short, "answer", {"value": "no"}, no_sms, "voice", "+19055550101")
    assert a.file is True and a.slots.ended_flow is True
    assert next_step(a.slots, no_sms, "voice") == Step.QA


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


def test_only_an_emergency_escalation_ends_anything():
    """Founder call 14ea2579, 2026-09-11 15:56:30.765. The model called escalate(clinical)
    for "does it hurt? like, that facial?" — a pre-treatment question the rules lexicon
    deliberately excludes — and driver.py ended the call 38 ms later, mid-sentence. Only the
    emergency script tells the caller to hang up and dial 911, so it is the only reason that
    ends anything (flows.md §1.8; voice-regression-V1 fixed this for the gate path only)."""
    from spatalk.brain.flow import Slots

    for reason in ("human_request", "complaint", "payment", "legal", "unsure"):
        a = _apply(Slots(), "escalate", {"reason": reason})
        assert a.end is False, reason
        assert a.escalate is True, reason
    emergency = _apply(Slots(), "escalate", {"reason": "emergency"})
    assert emergency.end is True and emergency.escalate is True


def test_a_clinical_escalation_opens_the_offer_and_files_nothing():
    from spatalk.brain.flow import Slots

    a = _apply(Slots(), "escalate", {"reason": "clinical"})
    assert a.slots.flow == "clinical" and a.slots.offer_accepted is False
    assert a.escalate is False and a.file is False and a.end is False and a.say == ()


def test_a_clinical_escalation_mid_booking_parks_the_booking():
    """Slot-engine spec line 65: a request in progress is kept, not thrown away. On the
    founder's call the booking was one answer from done when the clinical question came."""
    a = _apply(_filled_booking(), "escalate", {"reason": "clinical"})
    assert a.slots.flow == "clinical"
    assert a.slots.service_id is None
    assert a.slots.first_name == "Payman" and a.slots.phone_confirmed is True
    assert a.slots.parked.flow == "new_booking"
    assert a.slots.parked.service_id == "mesojet_facial"
    assert a.slots.parked.preferred_window.part_of_day == "afternoon"
    assert a.slots.parked.parked is None


def test_the_clinical_offer_is_its_own_step_even_when_the_name_is_known():
    """The offer used to be a special case of Step.NAME, so mid-booking — where the name and
    the number are already on the record — the clinical flow opened at COMPLETE and filed an
    urgent item with no offer at all."""
    from spatalk.brain.flow import Slots, Step, next_step, step_tools

    cfg = _cfg()
    s = Slots(flow="clinical", first_name="Dana", phone="+19055550101", phone_confirmed=True)
    assert next_step(s, cfg, "voice") == Step.CLINICAL_OFFER
    names = [t.name for t in step_tools(Step.CLINICAL_OFFER, s, cfg, "voice")]
    assert names[:1] == ["answer"] and "file_request" not in names


def test_saying_yes_to_the_offer_files_the_clinical_item_and_gives_the_booking_back():
    from spatalk.brain.flow import close_flow, draft_from

    parked = _apply(_filled_booking(), "escalate", {"reason": "clinical"}).slots
    yes = _apply(parked, "answer", {"value": "yes"})
    assert yes.file is True and yes.slots.ended_flow is True
    draft = draft_from(yes.slots, _cfg())
    assert draft.type == "escalation_clinical" and draft.contact.name == "Payman"
    back = close_flow(yes.slots)
    assert back.flow == "new_booking" and back.service_id == "mesojet_facial"
    assert back.preferred_window.part_of_day == "afternoon" and back.parked is None


def test_declining_the_offer_files_nothing_and_gives_the_booking_back():
    from spatalk.brain.flow import close_flow

    parked = _apply(_filled_booking(), "escalate", {"reason": "clinical"}).slots
    no = _apply(parked, "answer", {"value": "no"})
    assert no.file is False and no.say == (("clinical_declined", {}),)
    assert no.slots.ended_flow is True
    back = close_flow(no.slots)
    assert back.flow == "new_booking" and back.service_id == "mesojet_facial"


def test_closing_a_flow_with_nothing_parked_drops_to_qa():
    from spatalk.brain.flow import Slots, close_flow

    back = close_flow(Slots(flow="cancel", ended_flow=True, first_name="Dana"))
    assert back.flow is None and back.ended_flow is False
    assert back.first_name == "Dana" and back.parked is None


def test_a_second_request_at_qa_parks_nothing():
    """The guard on making parking automatic: `start_request` is only offered at Q&A, where
    the previous flow is None or ended, so nothing it opens can park anything."""
    from spatalk.brain.flow import Slots

    a = _apply(Slots(flow="cancel", ended_flow=True), "start_request", {"kind": "new_booking"})
    assert a.slots.parked is None


def test_the_clinical_offer_is_answered_yes_or_no_before_the_name():
    """MOVED 2026-09-11: the open step is now `Step.CLINICAL_OFFER` rather than `Step.NAME`,
    because a known name must not be able to skip the offer. The yes/no behaviour is
    unchanged."""
    from spatalk.brain.flow import Slots, Step, next_step

    s = Slots(flow="clinical")
    assert next_step(s, _cfg(), "voice") == Step.CLINICAL_OFFER
    yes = _apply(s, "answer", {"value": "yes"})
    assert yes.slots.offer_accepted and yes.say == ()
    no = _apply(s, "answer", {"value": "no"})
    assert no.slots.ended_flow and no.say == (("clinical_declined", {}),) and not no.file


def test_change_answer_reopens_a_step():
    """MOVED 2026-09-11: the call carries the caller's own words now. A bare `{"slot": ...}`
    is what "Oh, actually, you know." became on founder call 14ea2579 at 15:56:05, which
    cleared a filled window and re-asked the day; a slot name on its own is no longer evidence
    that the caller asked for anything to change."""
    from spatalk.brain.flow import Slots, Step, next_step

    s = Slots(
        flow="new_booking", returning_client=True, practitioner="Helen Courbetis",
        service_id="hydrabrasion_facial", first_name="Dana",
    )
    a = _apply(s, "change_answer", {"slot": "service", "said": "actually, a different treatment"},
               said="actually, a different treatment")
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
    # And a reader who already has the link is never asked whether they want one.
    from spatalk.brain.flow import Step, next_step

    assert next_step(chat.slots, _cfg(), "chat") == Step.QA
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
    """MOVED 2026-09-11: the un-accepted offer is asked at `Step.CLINICAL_OFFER`, not at
    `Step.NAME`. The post-acceptance half still passes `Step.NAME` and still expects
    `give_name`."""
    from spatalk.brain.flow import Slots, Step, step_tools

    s = Slots(flow="clinical", phone="+19055550101")
    assert [t.name for t in step_tools(Step.CLINICAL_OFFER, s, _cfg(), "voice")][:1] == ["answer"]
    assert "give_name" not in [t.name for t in step_tools(Step.CLINICAL_OFFER, s, _cfg(), "voice")]
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
    # A slot that does hold something is still reopened, when the caller's words ask for it
    # (MOVED 2026-09-11: the call used to need nothing but the slot name).
    b = _apply(s.with_(service_id="mesojet_facial"), "change_answer",
               {"slot": "service", "said": "no, make it the hydrabrasion one"},
               said="no, make it the hydrabrasion one")
    assert not b.ignored and b.slots.service_id is None
    # And the empty-slot refusal still wins over the new one, so the 2026-09-10 20:54:29
    # regression stays covered whatever the caller said.
    c = _apply(s, "change_answer", {"slot": "service", "said": "no, make it the hydrabrasion one"},
               said="no, make it the hydrabrasion one")
    assert c.ignored and c.rejection.detail == "empty_slot"
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
    # MOVED 2026-09-11: `unsure` is a non-answer here too (call 1565370e). The first is refused
    # with a re-ask; the second settles as a new client.
    u = _apply(r, "answer", {"value": "unsure"})
    assert u.ignored and u.rejection.detail == "needs_yes_or_no" and u.slots.returning_client is None
    assert _apply(u.slots, "answer", {"value": "unsure"}).slots.returning_client is False


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


# --- a slot recorded on a question turn owes the caller an answer (defect 5) ---------------


def test_a_slot_recorded_on_a_question_turn_owes_the_caller_an_answer():
    """Founder call 14ea2579, 2026-09-11 15:55:00.682. The caller said exactly "How much does
    it cost?". At 15:55:02.028 the model called choose_service{'said':'MesoJet and Sound
    Therapy facial'} — it rewrote the caller's turn into a service name inferred two turns
    earlier, so `is_question`, which runs on the ARGUMENT, never saw a question. The write was
    right; the price was never answered. The caller asked twice more and got it at
    15:55:09.081: three turns and 8.4 s."""
    from spatalk.brain.flow import Slots, apply

    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=False, offers_done=True)
    a = apply(s, "choose_service", {"said": "MesoJet and Sound Therapy facial"}, cfg, "voice",
              "+19055550101", caller_said="How much does it cost?")
    assert a.slots.service_id == "mesojet_facial"
    assert a.answer_owed is True
    for said in ("the mesojet one", ""):
        b = apply(s, "choose_service", {"said": "MesoJet and Sound Therapy facial"}, cfg,
                  "voice", "+19055550101", caller_said=said)
        assert b.slots.service_id == "mesojet_facial", said
        assert b.answer_owed is False, said
    # The debt follows the write, not the name of the tool that made it.
    name_open = s.with_(service_id="mesojet_facial", practitioner="any")
    c = apply(name_open, "give_name", {"first_name": "Payman"}, cfg, "voice", "+19055550101",
              caller_said="Yeah it's Payman. How much does it cost?")
    assert c.slots.first_name == "Payman" and c.answer_owed is True


def test_any_slot_recorded_on_a_question_turn_owes_the_caller_an_answer():
    """MOVED 2026-09-11: this was `test_only_the_two_tools_that_take_the_callers_words_can_owe
    _an_answer`, which pinned the debt to `choose_service` and `choose_practitioner` and
    asserted the other three steps could never owe one. That scope belonged to the detector
    this fix replaced — `is_question` on the tool ARGUMENT, which only those two tools carry.
    The detector now runs on the caller's own transcript, where nothing distinguishes the name,
    window or returning step: "How much does it cost?" is lost there exactly as it was lost at
    the treatment step on founder call 14ea2579. The brief's condition is a slot recorded, not
    a tool named, so the debt follows the write.

    The negative half of the old test is kept and widened: a turn that asked nothing never
    owes, whichever tool recorded it."""
    from spatalk.brain.flow import Slots, answer_owed

    cfg = _cfg()
    asked = "How much does it cost?"
    answered = "Thursday afternoon is good"
    window_open = Slots(
        flow="new_booking", returning_client=False, offers_done=True, practitioner="any",
        service_id="mesojet_facial", first_name="Payman", phone="+19055550101",
        phone_confirmed=True,
    )
    assert answer_owed(window_open, "choose_window", {"date": "Thursday"}, cfg, "voice",
                       "+19055550101", caller_said=asked) is True
    assert answer_owed(Slots(flow="new_booking"), "answer", {"value": "no"}, cfg, "voice",
                       "+19055550101", caller_said=asked) is True
    name_open = Slots(
        flow="new_booking", returning_client=False, offers_done=True, practitioner="any",
        service_id="mesojet_facial",
    )
    assert answer_owed(name_open, "give_name", {"first_name": "Dana"}, cfg, "voice",
                       "+19055550101", caller_said=asked) is True
    # A turn that asked nothing owes nothing, at every one of those steps.
    for slots, tool, args in (
        (window_open, "choose_window", {"date": "Thursday"}),
        (Slots(flow="new_booking"), "answer", {"value": "no"}),
        (name_open, "give_name", {"first_name": "Dana"}),
    ):
        assert answer_owed(slots, tool, args, cfg, "voice", "+19055550101",
                           caller_said=answered) is False, tool
        assert answer_owed(slots, tool, args, cfg, "voice", "+19055550101",
                           caller_said="") is False, tool
    # A call that records nothing is not a write, so it owes nothing either: the caller's
    # question comes back to the model through the refusal, which already hands the turn over.
    assert answer_owed(name_open, "answer_question", {}, cfg, "voice", "+19055550101",
                       caller_said=asked) is False


def test_a_debt_is_never_owed_on_a_filing_a_confirmation_or_a_refusal():
    from spatalk.brain.flow import Slots, apply
    from spatalk.brain.requests import PreferredWindow

    cfg = _cfg()
    asked = "How much does it cost?"
    last_slot = Slots(
        flow="callback", returning_client=True, practitioner="any", first_name="Dana",
        phone="+19055550101", phone_confirmed=True, preferred_window=PreferredWindow(),
        team_note_asked=True,
    )
    filing = apply(last_slot, "choose_service", {"said": "mesojet facial"}, cfg, "voice",
                   "+19055550101", caller_said=asked)
    assert filing.file is True and filing.answer_owed is False
    confirm = apply(Slots(flow="new_booking", returning_client=True), "choose_practitioner",
                    {"said": "Ellen"}, cfg, "voice", "+19055550101", caller_said=asked)
    assert confirm.slots.pending.kind == "match" and confirm.answer_owed is False
    refused = apply(Slots(flow="new_booking", returning_client=False, offers_done=True),
                    "choose_service", {"said": "what was the facial one again?"}, cfg, "voice",
                    "+19055550101", caller_said=asked)
    assert refused.ignored is True and refused.rejection.detail == "question_shaped"
    assert refused.answer_owed is False


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


def test_a_repeated_clinical_escalation_keeps_the_parked_booking():
    """Founder call 14ea2579, the turn after 15:56:30. The clinical offer is open and the
    caller asks the clinical question again instead of answering yes or no — on that call he
    repeated himself three times. `_open` rebuilt the clinical record from scratch, and the
    booking parked by the first escalation went with it: at the end of the call there was
    nothing for `file_complete_record` to file. A flow re-opened over itself keeps the frame
    it is already holding; depth stays at one, because a parked record never parks another."""
    first = _apply(_filled_booking(), "escalate", {"reason": "clinical"})
    again = _apply(first.slots, "escalate", {"reason": "clinical"})
    assert again.slots.flow == "clinical" and again.end is False
    assert again.slots.parked is not None
    assert again.slots.parked.flow == "new_booking"
    assert again.slots.parked.service_id == "mesojet_facial"
    assert again.slots.parked.parked is None
    # And the booking still comes back when the offer is finally answered.
    from spatalk.brain.flow import close_flow

    no = _apply(again.slots, "answer", {"value": "no"})
    back = close_flow(no.slots)
    assert back.flow == "new_booking" and back.service_id == "mesojet_facial"


def test_a_vague_turn_does_not_clear_a_filled_slot():
    """Founder call 14ea2579, 2026-09-11 15:56:05. The window was filled ("Monday or Tuesday
    of next week"), the system had asked whether there was anything for the team to know, and
    the caller said "Oh, actually, you know." The model read that as a correction and called
    change_answer(slot='window'); the runtime cleared the window and asked "Which day or time
    of day suits you best for the visit?" for the second time. The caller's next words were
    "What? I already-". A slot only reopens on words that name it or carry a new value."""
    from spatalk.brain.flow import Slots, Step, next_step
    from spatalk.brain.requests import PreferredWindow

    s = Slots(
        flow="new_booking", returning_client=False, offers_done=True,
        service_id="mesojet_facial", practitioner="any", first_name="Payman",
        phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(date="2026-09-15", part_of_day="morning"),
    )
    assert next_step(s, _cfg(), "voice") == Step.TEAM_NOTE
    a = _apply(s, "change_answer", {"slot": "window", "said": "Oh, actually, you know."},
               said="Oh, actually, you know.")
    assert a.ignored is True and a.slots == s
    assert a.rejection.reason == "bad_value" and a.rejection.detail == "no_change_named"
    assert next_step(a.slots, _cfg(), "voice") == Step.TEAM_NOTE
    # The model's own argument cannot manufacture the evidence the caller never gave: the
    # caller's transcription wins wherever the channel has one (defect 5, same call).
    b = _apply(s, "change_answer", {"slot": "window", "said": "change the day"},
               said="Oh, actually, you know.")
    assert b.ignored is True and b.slots.preferred_window == s.preferred_window


def test_a_named_slot_or_a_new_value_still_reopens_it():
    """The other half: a real correction is still a correction, by the slot's name or by the
    answer that replaces it."""
    from spatalk.brain.flow import Slots, Step, next_step
    from spatalk.brain.requests import PreferredWindow

    s = Slots(
        flow="new_booking", returning_client=False, offers_done=True,
        service_id="mesojet_facial", practitioner="any", first_name="Payman",
        phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(date="2026-09-15", part_of_day="morning"),
    )
    for words in ("actually, can we make it Wednesday instead", "change the day", "sorry, the afternoon"):
        a = _apply(s, "change_answer", {"slot": "window", "said": words}, said=words)
        assert a.ignored is False, words
        assert a.slots.preferred_window is None, words
        assert next_step(a.slots, _cfg(), "voice") == Step.WINDOW, words
    svc = _apply(s, "change_answer", {"slot": "service", "said": "no, the hydrabrasion one"},
                 said="no, the hydrabrasion one")
    assert svc.ignored is False and svc.slots.service_id is None
    name = _apply(s, "change_answer", {"slot": "name", "said": "my name is Peyman actually"},
                  said="my name is Peyman actually")
    assert name.ignored is False and name.slots.first_name is None
    phone = _apply(s, "change_answer", {"slot": "phone", "said": "use 416 555 0199 instead"},
                   said="use 416 555 0199 instead")
    assert phone.ignored is False and phone.slots.phone is None


def test_a_question_that_only_names_a_slot_is_not_a_change():
    """"What day did I say?" names the slot and asks to be told, which is the 2026-09-10
    20:54:29 mistake in a record that is full rather than empty: the answer is read back, not
    thrown away."""
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    s = Slots(
        flow="new_booking", returning_client=False, offers_done=True,
        service_id="mesojet_facial", practitioner="any", first_name="Payman",
        phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(date="2026-09-15", part_of_day="morning"),
    )
    a = _apply(s, "change_answer", {"slot": "window", "said": "what day did I say?"},
               said="what day did I say?")
    assert a.ignored is True and a.slots == s
    assert a.rejection.detail == "no_change_named"
    # A question that carries the new answer is still a correction.
    b = _apply(s, "change_answer", {"slot": "window", "said": "can we do Wednesday instead?"},
               said="can we do Wednesday instead?")
    assert b.ignored is False and b.slots.preferred_window is None


def test_correcting_the_returning_answer_reopens_the_offers():
    """Founder call 1565370e (2026-09-11 21:40): the offers question had been answered "no" on a
    mis-heard turn while the caller was recorded as unsure; the caller then corrected "I haven't
    been in before". The returning answer was re-asked and stored, but the offers flag stood,
    so a caller who had just become a new client was never offered the new-client deals.
    Changing an upstream answer clears the answers that depended on it."""
    from spatalk.brain.flow import Slots, Step, next_step

    s = Slots(flow="new_booking", returning_client=False, offers_done=True)
    a = _apply(s, "change_answer", {"slot": "returning_client", "said": "I haven't been in before"},
               said="Well, I haven't been in before")
    assert a.slots.returning_client is None and a.slots.offers_done is False
    assert next_step(a.slots, _cfg(), "voice") == Step.RETURNING
    b = _apply(a.slots, "answer", {"value": "no"})
    assert next_step(b.slots, _cfg(), "voice") == Step.OFFERS


def test_the_callers_own_words_decide_a_close_name_even_when_the_model_corrected_it():
    """Founder call dc229ede (2026-09-11 22:51): "is there an Ellen?" reached the tool as
    `said='Helen Courbetis'` and was stored exact; the spec's read-back never happened."""
    from spatalk.brain.flow import Slots

    s = Slots(flow="new_booking", returning_client=False, offers_done=True, service_id="mesojet_facial")
    a = _apply(s, "choose_practitioner", {"said": "Helen Courbetis"}, said="Um, who is there an Ellen?")
    assert a.slots.practitioner is None and a.slots.pending is not None
    assert a.slots.pending.kind == "match" and a.slots.pending.value == "Helen Courbetis"
    # The same words with no caller transcription (a channel without one) still store.
    b = _apply(s, "choose_practitioner", {"said": "Helen Courbetis"})
    assert b.slots.practitioner == "Helen Courbetis"


def test_a_miss_on_a_question_hands_the_turn_back_instead_of_re_asking():
    """Same call, 22:49: "I have pigmentation on my arms, do you have anything for that?" became
    `choose_service('pigmentation on my arms')`; nothing resolved and the runtime re-asked
    "which treatment". The caller asked a question: it is answered, not re-asked."""
    from spatalk.brain.flow import Slots

    s = Slots(flow="new_booking", returning_client=False, offers_done=True)
    a = _apply(s, "choose_service", {"said": "pigmentation on my arms"},
               said="Like, I have pigmentation on my arms. Is do you have anything for that?")
    assert a.ignored and a.rejection.detail == "question_shaped" and a.slots == s
    # A plain miss that asked nothing still re-asks the way it did.
    b = _apply(s, "choose_service", {"said": "the station one"}, said="the station one")
    assert not b.ignored and b.slots.misses.get("service") == 1
    # The caller's words win when they resolve: "sure, the MesoJet one" is the MesoJet.
    c = _apply(s, "choose_service", {"said": "MesoJet and Sound Therapy facial"}, said="Uh, sure. The MesoJet one.")
    assert c.slots.service_id == "mesojet_facial"
