import ast
import inspect
import uuid
from pathlib import Path
from pipecat.frames.frames import (LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame,
                                   TTSSpeakFrame, TranscriptionFrame)
from pipecat.tests.utils import run_test

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"

# pipecat's `run_test` waits `start_timeout` seconds for the pipeline to report started.
# The default is 1.0 s, which a cold first run on a developer machine exceeds (QA gate A,
# minor finding: observed as a `TimeoutError` on the very first clean-venv run and
# reproduced by clearing `__pycache__`). Every call in this file passes 10.0 instead.


def test_every_run_test_call_overrides_the_cold_start_timeout():
    """Regression guard for the QA gate A flake: no bare `run_test(...)` in this file."""
    assert inspect.signature(run_test).parameters["start_timeout"].default == 1.0
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_test"
    ]
    assert len(calls) >= 4, f"expected at least 4 run_test calls in this file, found {len(calls)}"
    for call in calls:
        timeouts = [kw.value for kw in call.keywords if kw.arg == "start_timeout"]
        assert timeouts, f"run_test call on line {call.lineno} does not pass start_timeout"
        assert ast.literal_eval(timeouts[0]) >= 10.0, (
            f"run_test call on line {call.lineno} passes a start_timeout below 10 s"
        )


def _session(fixed_clock, ledger=None):
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.session import VoiceSession
    cfg = load_bundle(BUNDLE)
    ledger = ledger if ledger is not None else MemoryLedger(fixed_clock)
    caps = TierCCapabilities(ledger=ledger, sms=MemorySms(), clock=fixed_clock)
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101")
    return VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=fixed_clock), ledger


async def test_guard_replaces_completion_claim_and_drops_rest(fixed_clock):
    from spatalk.voice.processors import OutputGuardProcessor
    session, ledger = _session(fixed_clock)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("Great, I've booked you "), LLMTextFrame("for Thursday. "),
              LLMTextFrame("Anything else?"), LLMFullResponseEndFrame()]
    down, _ = await run_test(OutputGuardProcessor(session), frames_to_send=frames,
                             expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
                             start_timeout=10.0)
    texts = [f.text for f in down if isinstance(f, LLMTextFrame)]
    assert len(texts) == 1 and "passed it to the team" in texts[0] and "booked" not in texts[0]
    assert session.guard_blocks == 1 and ledger.items[0].type == "question"


async def test_guard_passes_clean_sentences(fixed_clock):
    from spatalk.voice.processors import OutputGuardProcessor
    session, _ = _session(fixed_clock)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("The express treatment is $99. "), LLMTextFrame("Want the link?"),
              LLMFullResponseEndFrame()]
    down, _ = await run_test(OutputGuardProcessor(session), frames_to_send=frames,
                             expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame, LLMFullResponseEndFrame],
                             start_timeout=10.0)
    texts = [f.text for f in down if isinstance(f, LLMTextFrame)]
    assert [t.strip() for t in texts] == ["The express treatment is $99.", "Want the link?"]
    # Each sentence leaves the guard with its trailing space, so the TTS text aggregator
    # sees "$99. Want" and splits there; without it the caller heard "Welcome!We have"
    # run together (founder call 2026-09-03 15:56).
    assert "".join(texts) == "The express treatment is $99. Want the link? "


async def test_rules_gate_speaks_script_and_swallows_transcription(fixed_clock):
    from spatalk.voice.processors import RulesGateProcessor
    session, ledger = _session(fixed_clock)
    ended = []
    class FakeWorker:
        async def queue_frames(self, frames): ended.extend(type(f).__name__ for f in frames)
    session.worker = FakeWorker()
    down, _ = await run_test(RulesGateProcessor(session),
                             frames_to_send=[TranscriptionFrame(text="I have a rash after my laser", user_id="u", timestamp="t")],
                             expected_down_frames=[TTSSpeakFrame], start_timeout=10.0)
    assert "911" not in down[0].text and "clinical team" in down[0].text
    # The offer first: nothing filed, the call stays open, the record is on the clinical flow.
    assert down[0].text == session.cfg.scripts.clinical_offer
    assert session.band == 3 and ledger.items == [] and session.slots.flow == "clinical"
    assert ended == []


async def test_rules_gate_speaks_the_911_script_only_for_an_emergency(fixed_clock):
    from spatalk.voice.processors import RulesGateProcessor
    session, ledger = _session(fixed_clock)
    class FakeWorker:
        async def queue_frames(self, frames): pass
    session.worker = FakeWorker()
    down, _ = await run_test(RulesGateProcessor(session),
                             frames_to_send=[TranscriptionFrame(text="I can't breathe", user_id="u", timestamp="t")],
                             expected_down_frames=[TTSSpeakFrame], start_timeout=10.0)
    assert "911" in down[0].text and session.band == 3
    assert ledger.items[0].type == "escalation_emergency" and ledger.items[0].urgency == "urgent"


async def test_rules_gate_forwards_ordinary_transcription(fixed_clock):
    from spatalk.voice.processors import RulesGateProcessor
    session, _ = _session(fixed_clock)
    await run_test(RulesGateProcessor(session),
                   frames_to_send=[TranscriptionFrame(text="how much is a facial", user_id="u", timestamp="t")],
                   expected_down_frames=[TranscriptionFrame], start_timeout=10.0)
    assert session.band == 1


async def test_guard_block_with_a_dead_ledger_speaks_the_refusal(fixed_clock):
    """Ledger down on the guard path: speak the clinic's number, never the cannot_complete promise."""
    from spatalk.brain.ports import MemoryLedger
    from spatalk.voice.processors import OutputGuardProcessor

    class ExplodingLedger(MemoryLedger):
        async def create_item(self, ref, draft):
            raise RuntimeError("database is down")

    session, _ = _session(fixed_clock, ledger=ExplodingLedger(fixed_clock))
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("Great, I've booked you "), LLMTextFrame("for Thursday. "),
              LLMTextFrame("Anything else?"), LLMFullResponseEndFrame()]
    down, _ = await run_test(OutputGuardProcessor(session), frames_to_send=frames,
                             expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
                             start_timeout=10.0)
    texts = [f.text for f in down if isinstance(f, LLMTextFrame)]
    assert len(texts) == 1 and "905-703-7546" in texts[0]
    low = texts[0].lower()
    for claim in ("sent", "passed it", "confirm with you", "booked"):
        assert claim not in low, f"refusal claimed an action: {texts[0]!r}"
    assert session.guard_blocks == 1


async def test_rules_gate_writes_the_callers_words_to_the_context_before_the_script(fixed_clock):
    """Founder call 2026-09-05 12:20: the gate answered 'painful' with the fixed script and filed
    the urgent item, but the utterance itself never reached the transcript, so the notes and the
    request card had no record of what was said. The gate swallows the transcription frame, so
    it must write the caller's turn to the context itself, before the script it speaks."""
    from pipecat.processors.aggregators.llm_context import LLMContext
    from spatalk.voice.processors import RulesGateProcessor
    session, ledger = _session(fixed_clock)
    session.context = LLMContext(messages=[{"role": "system", "content": "prompt"}])
    class FakeWorker:
        async def queue_frames(self, frames): pass
    session.worker = FakeWorker()
    down, _ = await run_test(RulesGateProcessor(session),
                             frames_to_send=[TranscriptionFrame(text="I have a rash after my laser", user_id="u", timestamp="t")],
                             expected_down_frames=[TTSSpeakFrame], start_timeout=10.0)
    turns = [(m["role"], m["content"]) for m in session.context.messages if m["role"] != "system"]
    assert turns == [("user", "I have a rash after my laser")]
    # The script is appended by the assistant aggregator once it is spoken, after the caller's turn.
    assert down[0].append_to_context is True and ledger.items == []
    assert down[0].text == session.cfg.scripts.clinical_offer


async def test_the_open_question_follows_a_side_answer(fixed_clock):
    """Mid-flow, the model answered a price question in words; the runtime re-asks the step."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=True)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("The Classic facial is $125."), LLMFullResponseEndFrame()]
    down, _ = await run_test(OutputGuardProcessor(session), frames_to_send=frames,
                             expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame, TTSSpeakFrame],
                             start_timeout=10.0)
    spoken = [f.text for f in down if isinstance(f, TTSSpeakFrame)]
    assert spoken == [session.cfg.scripts.ask_practitioner]


async def test_no_question_is_repeated_when_a_tool_ran_this_turn(fixed_clock):
    from pipecat.frames.frames import FunctionCallInProgressFrame
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=True)
    frames = [
        LLMFullResponseStartFrame(),
        FunctionCallInProgressFrame(function_name="choose_practitioner", tool_call_id="c1", arguments={"said": "Helen"}),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(OutputGuardProcessor(session), frames_to_send=frames,
                             expected_down_frames=[LLMFullResponseStartFrame, FunctionCallInProgressFrame, LLMFullResponseEndFrame],
                             start_timeout=10.0)
    assert not any(isinstance(f, TTSSpeakFrame) for f in down) and session.tool_called_this_turn


async def test_no_question_outside_a_flow(fixed_clock):
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("We open at nine."), LLMFullResponseEndFrame()]
    down, _ = await run_test(OutputGuardProcessor(session), frames_to_send=frames,
                             expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
                             start_timeout=10.0)
    assert not any(isinstance(f, TTSSpeakFrame) for f in down)


async def test_the_model_does_not_ask_a_question_while_a_flow_is_open(fixed_clock):
    """Founder call 2026-09-10 20:54:37. The model's answer ended "Would you like to hear
    about any of those, or perhaps something else?" and the runtime then spoke "What did you
    have in mind?" - two questions in one breath, the second one word for word the same on
    every turn, which is what read as an assistant with no memory of the call. The slot
    engine's invariant 4 is that every question the caller hears is a tenant script, so a
    trailing question of the model's own is not spoken while a request is open."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("That's our fifty-dollar credit. "),
        LLMTextFrame("Would you like to hear about any of those?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session),
        frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame, TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["That's our fifty-dollar credit."]
    spoken = [f.text for f in down if isinstance(f, TTSSpeakFrame)]
    assert spoken == [session.cfg.scripts.ask_after_offers]
    # A sentence that was never spoken is not something the echo scrubber may trim from the
    # caller's next words.
    assert "would you like" not in session.recent_bot_text


async def test_a_question_in_the_middle_of_an_answer_is_still_spoken(fixed_clock):
    """Only a *trailing* question takes the runtime's turn. One the model asks and then
    answers itself is part of the answer and must reach the caller."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("Do you mean the express one? "),
        LLMTextFrame("Those are all ninety-nine dollars."),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session),
        frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame,
            LLMFullResponseEndFrame, TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["Do you mean the express one?", "Those are all ninety-nine dollars."]


async def test_a_question_is_the_models_own_outside_a_flow(fixed_clock):
    """With no request open the model owns the conversation, so its question is spoken."""
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("We open at nine. "),
        LLMTextFrame("Would you like to book?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session),
        frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame, LLMFullResponseEndFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["We open at nine.", "Would you like to book?"]


async def test_a_turn_that_is_only_a_question_is_not_left_silent(fixed_clock):
    """The held question is the last resort against a silent turn: at a step the runtime has
    no question for, a model turn made of nothing but a question is still spoken."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    # COMPLETE: every slot is in the record, so `step_question` is None.
    session.slots = Slots(
        flow="cancel", first_name="Dana", phone="+19055550101", phone_confirmed=True
    )
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("Shall I pass that on?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session),
        frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["Shall I pass that on?"]


async def test_the_step_question_is_not_repeated_word_for_word(fixed_clock):
    """Founder call 2026-09-10: "What did you have in mind?" four times, twice in a row with
    nothing but a model answer between them, which is what he described as the assistant
    lacking the context of the whole conversation. The step question is the runtime's to ask,
    but it is asked once: while the record has not moved and the caller has just heard those
    exact words, a second identical ask adds nothing, so the model's own closing question
    carries the turn instead."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    guard_proc = OutputGuardProcessor(session)
    first = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("That's our fifty-dollar credit."),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        guard_proc, frames_to_send=first,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame, TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == [
        session.cfg.scripts.ask_after_offers
    ]
    # A second side answer at the same step: the script is not spoken again, and the model's
    # own question is released rather than dropped, so the caller is not left without one.
    second = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("The MesoJet facial is $295. "),
        LLMTextFrame("Would you like to get that set up?"),
        LLMFullResponseEndFrame(),
    ]
    down2, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=second,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame, LLMFullResponseEndFrame
        ],
        start_timeout=10.0,
    )
    assert not any(isinstance(f, TTSSpeakFrame) for f in down2)
    said = [f.text.strip() for f in down2 if isinstance(f, LLMTextFrame)]
    assert said == ["The MesoJet facial is $295.", "Would you like to get that set up?"]


async def test_the_step_question_comes_back_once_the_record_moves(fixed_clock):
    """The suppression is only against repeating itself: a step that moved on asks again."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("The MesoJet facial is $295."),
        LLMFullResponseEndFrame(),
    ]
    await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame, TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    session.slots = session.slots.with_(service_id="mesojet_facial")
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame, TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == [
        session.cfg.scripts.ask_practitioner
    ]


async def test_a_silent_model_turn_still_gets_the_question(fixed_clock):
    """The suppression never leaves a turn with nothing in it: with no words from the model,
    the script is spoken however recently it was last asked."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session.remember_question(session.cfg.scripts.ask_after_offers)
    frames = [LLMFullResponseStartFrame(), LLMFullResponseEndFrame()]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMFullResponseEndFrame, TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == [
        session.cfg.scripts.ask_after_offers
    ]


async def test_a_payment_match_files_the_item_and_leaves_the_line_open(fixed_clock):
    """Founder call 2026-09-10 20:56:19: "rules gate: payment ('payment') -> item 17" and, in
    the same millisecond, "PipelineWorker#0: Closing. Waiting for EndFrame#0". The call died
    mid-booking. docs/reference/flows.md section 1.8 gives that power to the emergency script
    alone, whose wording tells the caller to hang up and dial 911; every other band-3 script
    promises a callback and the caller is still on the line when it finishes."""
    from spatalk.voice.processors import RulesGateProcessor

    session, ledger = _session(fixed_clock)
    ended = []

    class FakeWorker:
        async def queue_frames(self, frames): ended.extend(type(f).__name__ for f in frames)

    session.worker = FakeWorker()
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            TranscriptionFrame(
                text="Can I pay over the phone with my credit card?", user_id="u", timestamp="t"
            )
        ],
        expected_down_frames=[TTSSpeakFrame], start_timeout=10.0,
    )
    assert down[0].text == session.cfg.scripts.payment
    assert ledger.items[0].type == "escalation_payment" and session.band == 3
    assert ended == [] and session.ended is False


async def test_a_complaint_match_leaves_the_line_open_too(fixed_clock):
    from spatalk.voice.processors import RulesGateProcessor

    session, ledger = _session(fixed_clock)
    ended = []

    class FakeWorker:
        async def queue_frames(self, frames): ended.extend(type(f).__name__ for f in frames)

    session.worker = FakeWorker()
    await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            TranscriptionFrame(text="I want a refund, this was terrible", user_id="u", timestamp="t")
        ],
        expected_down_frames=[TTSSpeakFrame], start_timeout=10.0,
    )
    assert ledger.items[0].type == "escalation_complaint"
    assert ended == [] and session.ended is False


async def test_an_emergency_match_is_the_one_that_ends_the_call(fixed_clock):
    from spatalk.voice.processors import RulesGateProcessor

    session, ledger = _session(fixed_clock)
    ended = []

    class FakeWorker:
        async def queue_frames(self, frames): ended.extend(type(f).__name__ for f in frames)

    session.worker = FakeWorker()
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[TranscriptionFrame(text="I can't breathe", user_id="u", timestamp="t")],
        expected_down_frames=[TTSSpeakFrame], start_timeout=10.0,
    )
    assert "911" in down[0].text and ledger.items[0].type == "escalation_emergency"
    assert ended == ["EndFrame"] and session.ended is True


async def test_a_bare_answer_at_the_name_step_is_not_an_escalation(fixed_clock):
    """The founder's own name, heard as "payment" at "Could I get your first name?". The gate
    lets it through to the model, which is where an answer to the name question belongs."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import RulesGateProcessor

    session, ledger = _session(fixed_clock)
    ended = []

    class FakeWorker:
        async def queue_frames(self, frames): ended.extend(type(f).__name__ for f in frames)

    session.worker = FakeWorker()
    session.slots = Slots(
        flow="new_booking", returning_client=True, practitioner="any", service_id="mesojet_facial"
    )
    await run_test(
        RulesGateProcessor(session),
        frames_to_send=[TranscriptionFrame(text=" Yeah, payment.", user_id="u", timestamp="t")],
        expected_down_frames=[TranscriptionFrame], start_timeout=10.0,
    )
    assert ledger.items == [] and ended == [] and session.band == 1
