import uuid
from pathlib import Path
BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _said(pushed):
    """What the caller would hear, which is the tenant's own wording and nothing else.

    A tool turn also pushes one `ToolTurnDoneFrame` — the handler telling the guard its half
    of the turn is over (model-words memo, A4) — so the frames are filtered by kind rather
    than compared whole.
    """
    from pipecat.frames.frames import TTSSpeakFrame

    return [f.text for f in pushed if isinstance(f, TTSSpeakFrame)]


async def test_handler_speaks_rendered_text_and_disables_llm_rerun(fixed_clock):
    from pipecat.frames.frames import TTSSpeakFrame, EndFrame
    from spatalk.brain.flow import Slots
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.brain.tools import TOOL_NAMES
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.handlers import register_tool_handlers
    from spatalk.voice.session import VoiceSession
    cfg = load_bundle(BUNDLE)
    ledger = MemoryLedger(fixed_clock)
    caps = TierCCapabilities(ledger=ledger, sms=MemorySms(), clock=fixed_clock)
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101")
    session = VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=fixed_clock)
    pushed, queued, results = [], [], []

    class FakeLLM:
        registered = {}
        def register_function(self, name, handler, **kw): self.registered[name] = handler
        async def push_frame(self, frame, direction=None): pushed.append(frame)

    class FakeWorker:
        async def queue_frames(self, frames): queued.extend(frames)

    class Params:
        def __init__(self, name, args):
            self.function_name, self.arguments, self.llm = name, args, llm
        async def result_callback(self, result, properties=None):
            results.append((result, properties))

    llm = FakeLLM()
    session.worker = FakeWorker()
    register_tool_handlers(llm, session)
    assert set(llm.registered) == set(TOOL_NAMES)
    # Every slot of a cancellation is in the record: the engine offers file_request.
    session.slots = Slots(flow="cancel", first_name="Dana", phone="+19055550101", phone_confirmed=True)
    await llm.registered["file_request"](Params("file_request", {}))
    assert isinstance(pushed[0], TTSSpeakFrame) and pushed[0].text.startswith("I've sent that to the team")
    assert results[0][1].run_llm is False and session.band == 2 and ledger.items[0].type == "cancel"
    assert session.slots.flow is None
    await llm.registered["end_conversation"](Params("end_conversation", {}))
    assert session.ended and isinstance(queued[-1], EndFrame)
    assert "Thanks for calling" in _said(pushed)[1]


def _world(fixed_clock, slots=None):
    """A registered handler set over a real bundle, with the frames and results it produced."""
    import uuid
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.handlers import register_tool_handlers
    from spatalk.voice.session import VoiceSession

    cfg = load_bundle(BUNDLE)
    ledger = MemoryLedger(fixed_clock)
    caps = TierCCapabilities(ledger=ledger, sms=MemorySms(), clock=fixed_clock)
    ref = ConversationRef(
        conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101"
    )
    session = VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=fixed_clock)
    if slots is not None:
        session.slots = slots
    pushed, queued, results = [], [], []

    class FakeLLM:
        def __init__(self): self.registered = {}
        def register_function(self, name, handler, **kw): self.registered[name] = handler
        async def push_frame(self, frame, direction=None): pushed.append(frame)

    class FakeWorker:
        async def queue_frames(self, frames): queued.extend(frames)

    llm = FakeLLM()

    class Params:
        def __init__(self, name, args):
            self.function_name, self.arguments, self.llm = name, args, llm
        async def result_callback(self, result, properties=None):
            results.append((result, properties))

    session.worker = FakeWorker()
    register_tool_handlers(llm, session)
    return session, llm, Params, pushed, queued, results, ledger


async def test_an_ignored_tool_is_refused_in_words_that_name_what_is_missing(fixed_clock):
    """Founder call 2026-09-10 20:55:35. Mid-booking the caller said "can you book me that
    facial?"; the model called start_request, which the treatment step does not offer, the
    engine ignored it (`tool start_request ignored at this step with args {'kind': 'booking'}`)
    and the handler spoke "What did you have in mind?" with run_llm=False. The caller's
    sentence was never answered, so he said it again. An ignored call says nothing and lets
    the model answer from the whole conversation instead — and, since 2026-09-11, is told
    what the record is waiting on and what it may call instead rather than only that
    something was refused."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import MAX_REJECTIONS_PER_TURN

    slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session, llm, Params, pushed, _queued, results, _ledger = _world(fixed_clock, slots)
    await llm.registered["start_request"](Params("start_request", {"kind": "new_booking"}))
    assert _said(pushed) == [], "an ignored tool spoke"
    assert results[0][1].run_llm is True
    assert results[0][0]["ignored"] is True and results[0][0]["spoken"] is False
    assert session.slots == slots
    reason = results[0][0]["rejection"]
    assert "start_request" in reason and "which treatment they want" in reason
    assert "choose_service" in reason and "answer_question" in reason
    # A model that keeps calling the tool cannot loop: past the ceiling the runtime speaks
    # the open question itself and stops re-running the model.
    for _ in range(MAX_REJECTIONS_PER_TURN):
        await llm.registered["start_request"](Params("start_request", {"kind": "new_booking"}))
    assert results[-1][1].run_llm is False
    assert _said(pushed) == [session.cfg.scripts.ask_after_offers]


async def test_the_ignored_budget_resets_when_the_caller_speaks(fixed_clock):
    """One re-run per caller turn, not one per call: the gate clears the count on every final
    transcription, the way it clears the "still there?" count."""
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import RulesGateProcessor

    slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session, llm, Params, pushed, _queued, results, _ledger = _world(fixed_clock, slots)
    await llm.registered["start_request"](Params("start_request", {"kind": "new_booking"}))
    assert session.ignored_tools == 1
    gate = RulesGateProcessor(session)
    await gate.process_frame(
        TranscriptionFrame(text="the mesojet one", user_id="u", timestamp="t"),
        FrameDirection.DOWNSTREAM,
    )
    assert session.ignored_tools == 0


async def test_a_tool_the_step_does_offer_speaks_the_outcome_and_the_confirmation_only(fixed_clock):
    """Was `…_still_speaks_the_next_question`. Memo §7 decision 1: "every outcome sentence
    the caller hears is a tenant script; every question realises the act the runtime named."
    So the tool result carries the tenant's outcome wording and a confirmation of a value the
    resolver could not settle, and never a plain step question — that one is the model's, from
    the same reply that called the tool, and `OutputGuardProcessor` speaks the script only if
    that reply asked nothing."""
    from spatalk.brain.flow import Slots

    slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session, llm, Params, pushed, _queued, results, _ledger = _world(fixed_clock, slots)
    await llm.registered["choose_service"](Params("choose_service", {"said": "mesojet facial"}))
    assert session.slots.service_id == "mesojet_facial"
    assert _said(pushed) == [], "the tool result spoke a plain step question"
    assert session.runtime_asked_this_turn is False
    assert results[0][1].run_llm is False and results[0][0]["ignored"] is False
    # A value the resolver could not settle is the one question the runtime still asks here.
    session2, llm2, Params2, pushed2, _q2, results2, _l2 = _world(
        fixed_clock, Slots(flow="new_booking", returning_client=True)
    )
    await llm2.registered["choose_practitioner"](Params2("choose_practitioner", {"said": "Ellen"}))
    assert _said(pushed2) == [session2.cfg.scripts.confirm_match.format(value="Helen")]
    assert session2.runtime_asked_this_turn is True
    assert results2[0][1].run_llm is False


async def test_a_question_shaped_answer_hands_the_turn_back_with_a_reason(fixed_clock):
    """Founder call 2026-09-11 01:41:26. `choose_service(said='the facial one')` on a caller
    who had asked what the facial offer was: the slot filled and the runtime asked the next
    question. Now nothing is spoken, the record does not move, and the model gets the turn
    back with a readable reason in the tool result."""
    from spatalk.brain.flow import Slots

    slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session, llm, Params, pushed, _queued, results, _ledger = _world(fixed_clock, slots)
    await llm.registered["choose_service"](
        Params("choose_service", {"said": "Sorry, what was the- what was the facial one again?"})
    )
    assert _said(pushed) == [], "a refused tool call spoke"
    assert results[0][1].run_llm is True
    assert session.slots == slots
    assert results[0][0]["ignored"] is True and results[0][0]["spoken"] is False
    assert "question" in results[0][0]["rejection"].lower()
    # And what the record is still waiting on, so the model has somewhere to go.
    assert "which treatment" in results[0][0]["rejection"]


async def test_a_tool_result_does_not_repeat_the_question_just_asked(fixed_clock):
    """The other path into the same fixed question. V1 suppressed a repeat only inside
    `OutputGuardProcessor`, so the tool-result path could still speak a question the caller
    had just heard on a record that had not moved. The second ignored call in a caller turn
    is the reachable case: past the ceiling its fallback is the open question, and by then
    the caller has already been asked it."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import MAX_REJECTIONS_PER_TURN

    slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session, llm, Params, pushed, _queued, results, _ledger = _world(fixed_clock, slots)
    session.remember_question(session.cfg.scripts.ask_after_offers)
    for _ in range(MAX_REJECTIONS_PER_TURN + 1):
        await llm.registered["start_request"](Params("start_request", {"kind": "new_booking"}))
    assert _said(pushed) == [], "the fixed question came back on an unchanged record"
    assert results[-1][1].run_llm is False
    # And a tool the step does offer speaks no plain question at all now, on any turn: the
    # only wording the handler adds is an outcome or a confirmation (memo §7 decision 1).
    session.ignored_tools = 0
    await llm.registered["choose_service"](Params("choose_service", {"said": "mesojet facial"}))
    assert _said(pushed) == []
    assert session.slots.service_id == "mesojet_facial"


def _one_slot_short_booking():
    """The founder's record at 15:56:02, one answer short of complete (14ea2579)."""
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    return Slots(
        flow="new_booking", returning_client=False, offers_done=True, service_id="mesojet_facial",
        practitioner="any", first_name="Dana", phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(part_of_day="afternoon"),
    )


async def test_the_captured_line_is_followed_by_the_tenants_link_offer(fixed_clock):
    """Founder call 14ea2579, 2026-09-11 15:56:02.950. The route question was asked in front
    of the ledger and talked over; the booking never became an item. The filing happens on
    the turn the last slot lands, and the link is put after it as an extra."""
    session, llm, Params, pushed, _queued, results, ledger = _world(
        fixed_clock, _one_slot_short_booking()
    )
    cfg = session.cfg
    await llm.registered["answer"](Params("answer", {"value": "no"}))
    assert _said(pushed) == [cfg.scripts.captured_booking, cfg.scripts.link_offer]
    assert session.slots.filed is True
    assert session.slots.flow == "new_booking"
    assert session.receipts == [f"item:{ledger.items[0].id}"]
    assert session.band == 2
    assert session.runtime_asked_this_turn is True
    assert results[0][1].run_llm is False


async def test_the_link_offer_answer_sends_the_link_and_files_nothing_more(fixed_clock):
    session, llm, Params, pushed, _queued, _results, ledger = _world(
        fixed_clock, _one_slot_short_booking()
    )
    await llm.registered["answer"](Params("answer", {"value": "no"}))
    await llm.registered["answer"](Params("answer", {"value": "yes"}))
    assert len(ledger.items) == 1
    assert len(session.caps._sms.sent) == 1
    assert _said(pushed)[-1] == session.cfg.scripts.link_sent.format(
        service="MesoJet and Sound Therapy facial"
    )
    assert session.slots.flow is None


def _the_1556_booking():
    """The founder's record at 15:56:17, one answer short of complete (14ea2579)."""
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    return Slots(
        flow="new_booking", returning_client=False, offers_done=True, service_id="mesojet_facial",
        practitioner="any", first_name="Payman", phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(part_of_day="afternoon"),
    )


async def test_a_clinical_escalation_keeps_the_call_open_and_parks_the_booking(fixed_clock):
    """Founder call 14ea2579, 2026-09-11 15:56:30.765. `escalate {'reason':'clinical'}` for a
    pre-treatment question queued an EndFrame 38 ms later and the carrier cut the leg at
    15:56:39.742, mid-"is there anything else I can help with?"."""
    session, llm, Params, pushed, queued, _results, ledger = _world(
        fixed_clock, _the_1556_booking()
    )
    await llm.registered["escalate"](Params("escalate", {"reason": "clinical"}))
    assert queued == [], "a clinical escalation queued an EndFrame"
    assert session.ended is False
    assert ledger.items == []
    assert _said(pushed) == [session.cfg.scripts.clinical_offer]
    assert session.slots.flow == "clinical"
    assert session.slots.parked.service_id == "mesojet_facial"
    assert session.runtime_asked_this_turn is True
    assert session.band == 3


async def test_saying_yes_to_the_clinical_offer_files_the_item_and_gives_the_booking_back(fixed_clock):
    session, llm, Params, pushed, queued, _results, ledger = _world(
        fixed_clock, _the_1556_booking()
    )
    await llm.registered["escalate"](Params("escalate", {"reason": "clinical"}))
    await llm.registered["answer"](Params("answer", {"value": "yes"}))
    assert ledger.items[0].type == "escalation_clinical"
    assert ledger.items[0].urgency == "urgent"
    assert ledger.items[0].contact.name == "Payman"
    assert _said(pushed)[-1] == session.cfg.scripts.clinical
    assert queued == []
    assert session.ended is False
    assert session.slots.flow == "new_booking"
    assert session.slots.service_id == "mesojet_facial"
    assert session.slots.parked is None
    assert session.runtime_asked_this_turn is True


async def test_a_model_called_emergency_escalation_still_ends_the_call(fixed_clock):
    from pipecat.frames.frames import EndFrame

    session, llm, Params, pushed, queued, _results, ledger = _world(fixed_clock)
    await llm.registered["escalate"](Params("escalate", {"reason": "emergency"}))
    assert isinstance(queued[-1], EndFrame)
    assert session.ended is True
    assert ledger.items[0].type == "escalation_emergency"
    assert "911" in _said(pushed)[0]


async def test_a_model_called_complaint_escalation_leaves_the_line_open(fixed_clock):
    session, llm, Params, pushed, queued, _results, ledger = _world(fixed_clock)
    await llm.registered["escalate"](Params("escalate", {"reason": "complaint"}))
    assert queued == []
    assert session.ended is False
    assert ledger.items[0].type == "escalation_complaint"
    assert _said(pushed) == [session.cfg.scripts.complaint]


async def test_a_slot_recorded_on_a_question_turn_hands_the_turn_back_once(fixed_clock):
    """Founder call 14ea2579, 2026-09-11 15:55:00.682 to 15:55:09.081. The caller asked "How
    much does it cost?"; the model recorded the treatment it had inferred two turns earlier
    and the runtime spoke `ask_practitioner` 11 ms later. The price took three turns and
    8.4 s to arrive. The write stands; the turn goes back so the question gets answered."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.frames import ToolTurnDoneFrame

    slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session, llm, Params, pushed, _queued, results, _ledger = _world(fixed_clock, slots)
    session.caller_said = "How much does it cost?"
    session.caller_asked = True
    await llm.registered["choose_service"](
        Params("choose_service", {"said": "MesoJet and Sound Therapy facial"})
    )
    assert session.slots.service_id == "mesojet_facial", "the write did not survive"
    assert _said(pushed) == [], "ask_practitioner was spoken over the caller's question"
    assert session.runtime_asked_this_turn is False
    assert results[0][1].run_llm is True
    assert "answer_first" in results[0][0]
    assert "choose_practitioner" in results[0][0]["answer_first"]
    done = [f for f in pushed if isinstance(f, ToolTurnDoneFrame)]
    assert done and done[-1].handed_back is True
    assert session.signals.counts()["model_rerun"] == 1


async def test_the_hand_back_is_spent_once_per_caller_turn(fixed_clock):
    from spatalk.brain.flow import Slots

    slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session, llm, Params, pushed, _queued, results, _ledger = _world(fixed_clock, slots)
    session.caller_said = "How much does it cost?"
    session.caller_asked = True
    await llm.registered["choose_service"](
        Params("choose_service", {"said": "MesoJet and Sound Therapy facial"})
    )
    spoken_before = _said(pushed)
    await llm.registered["choose_practitioner"](Params("choose_practitioner", {"said": "anyone"}))
    assert results[-1][1].run_llm is False
    assert "answer_first" not in results[-1][0]
    assert _said(pushed) == spoken_before


async def test_an_answer_with_no_question_in_it_still_costs_one_model_call(fixed_clock):
    """The no-regression pin on today's one-call-per-turn path."""
    from spatalk.brain.flow import Slots

    slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session, llm, Params, pushed, _queued, results, _ledger = _world(fixed_clock, slots)
    session.caller_said = "the mesojet one"
    session.caller_asked = False
    await llm.registered["choose_service"](Params("choose_service", {"said": "mesojet facial"}))
    assert results[0][1].run_llm is False
    assert "answer_first" not in results[0][0]
    assert _said(pushed) == []


async def test_a_confirmation_the_runtime_owes_beats_the_hand_back(fixed_clock):
    """Fixed wording is still law, and a `Pending` never buys a model turn."""
    from spatalk.brain.flow import Slots

    session, llm, Params, pushed, _queued, results, _ledger = _world(
        fixed_clock, Slots(flow="new_booking", returning_client=True)
    )
    session.caller_said = "How much does it cost?"
    session.caller_asked = True
    await llm.registered["choose_practitioner"](Params("choose_practitioner", {"said": "Ellen"}))
    assert _said(pushed) == [session.cfg.scripts.confirm_match.format(value="Helen")]
    assert results[0][1].run_llm is False
    assert "answer_first" not in results[0][0]


async def test_the_receipt_is_recorded_before_the_outcome_is_spoken(fixed_clock):
    """The order is the honest one: the ledger answers, the receipt is written, then the
    sentence that asserts it goes out. A ledger that returns nothing gets no receipt and the
    refusal wording, which asserts nothing."""
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    slots = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
        first_name="Dana", phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(), team_note_asked=True,
    )
    session, llm, Params, pushed, _queued, _results, ledger = _world(fixed_clock, slots)
    await llm.registered["file_request"](Params("file_request", {}))
    assert session.receipts == [f"item:{ledger.items[0].id}"]
    # And the receipt was there before the sentence that asserts it: the guard would have
    # retracted `captured` otherwise.
    assert _said(pushed)[0].startswith("I've sent that to the team as a request")
