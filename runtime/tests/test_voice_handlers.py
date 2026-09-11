import uuid
from pathlib import Path
BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


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
    assert session.ended and isinstance(queued[-1], EndFrame) and "Thanks for calling" in pushed[1].text


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
    assert pushed == [], "an ignored tool spoke"
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
    assert [f.text for f in pushed] == [session.cfg.scripts.ask_after_offers]


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


async def test_a_tool_the_step_does_offer_still_speaks_the_next_question(fixed_clock):
    from spatalk.brain.flow import Slots

    slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session, llm, Params, pushed, _queued, results, _ledger = _world(fixed_clock, slots)
    await llm.registered["choose_service"](Params("choose_service", {"said": "mesojet facial"}))
    assert session.slots.service_id == "mesojet_facial"
    assert [f.text for f in pushed] == [session.cfg.scripts.ask_practitioner]
    assert results[0][1].run_llm is False and results[0][0]["ignored"] is False


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
    assert pushed == [], "a refused tool call spoke"
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
    assert pushed == [], "the fixed question came back on an unchanged record"
    assert results[-1][1].run_llm is False
    # It comes back the moment the record moves.
    session.ignored_tools = 0
    await llm.registered["choose_service"](Params("choose_service", {"said": "mesojet facial"}))
    assert [f.text for f in pushed] == [session.cfg.scripts.ask_practitioner]


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
    assert pushed[0].text.startswith("I've sent that to the team as a request")
