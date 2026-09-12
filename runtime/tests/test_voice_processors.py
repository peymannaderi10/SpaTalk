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



def _the_1556_booking():
    """The founder's booking record at 15:56, every required slot on it and unfiled."""
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    return Slots(
        flow="new_booking", returning_client=False, offers_done=True,
        service_id="mesojet_facial", practitioner="any", first_name="Payman",
        phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(part_of_day="afternoon"), team_note_asked=True,
    )


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


async def test_the_models_own_question_is_spoken_when_the_runtime_has_none(fixed_clock):
    """Was `test_the_model_does_not_ask_a_question_while_a_flow_is_open`, and it was right
    for the runtime it was written against. Memo §3: "Then the trailing-question suppression
    from `voice-regression-V1` is relaxed, because it was right for a runtime that asked its
    own question on top and is wrong once the model owns the question." The V1 defect it was
    written for — two questions in one breath, the second identical on every turn — is now
    prevented at the source: the runtime asks nothing here."""
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
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame, LLMFullResponseEndFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["That's our fifty-dollar credit.", "Would you like to hear about any of those?"]
    assert [f for f in down if isinstance(f, TTSSpeakFrame)] == []


async def test_a_fixed_confirmation_still_beats_the_models_own_question(fixed_clock):
    """The one case the hold survives: a `Pending` is open, the wording is law, and the
    model's guess at it is dropped rather than asked alongside."""
    from spatalk.brain.flow import Pending, Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(
        flow="new_booking", returning_client=True,
        pending=Pending(kind="match", slot="practitioner", value="Helen Courbetis"),
    )
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("Sure. "),
        LLMTextFrame("Did you want Ellen or Helen?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame, TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["Sure."]
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == [
        session.cfg.scripts.confirm_match.format(value="Helen")
    ]


async def test_a_tool_turn_waits_for_the_handler_and_then_lets_the_models_question_out(fixed_clock):
    """The orchestrator's amendment: one model call per caller turn, so the question the
    caller hears on a slot-filling turn comes from the same reply that called the tool.

    The guard cannot decide at the end of the completion, because Pipecat queues the
    function calls and pushes `LLMFullResponseEndFrame` without waiting for them — verified
    in the installed source: `pipecat/services/google/llm.py` calls
    `run_function_calls(function_calls)` and pushes the end frame in its `finally`, and
    `LLMService._run_sequential_function_calls` only puts the calls on a queue. So it waits
    for the handler's `ToolTurnDoneFrame`, which arrives after the runtime's own lines."""
    from pipecat.frames.frames import FunctionCallInProgressFrame

    from spatalk.brain.flow import Slots
    from spatalk.voice.frames import ToolTurnDoneFrame
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking")
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("Got it. "),
        LLMTextFrame("Who would you like to see?"),
        FunctionCallInProgressFrame(
            function_name="answer", tool_call_id="1", arguments={"value": "yes"}
        ),
        LLMFullResponseEndFrame(),
        ToolTurnDoneFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, FunctionCallInProgressFrame,
            LLMFullResponseEndFrame, LLMTextFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["Got it.", "Who would you like to see?"]
    # And the runtime's own question is not asked on top of it.
    assert [f for f in down if isinstance(f, TTSSpeakFrame)] == []


async def test_a_tool_turn_with_no_question_from_the_model_gets_the_step_script(fixed_clock):
    """The fallback A4 keeps. A reply that called the tool and asked nothing would otherwise
    leave the caller with silence, so the runtime's own question fills it — after the
    handler's lines, which is what the done frame is for."""
    from pipecat.frames.frames import FunctionCallInProgressFrame

    from spatalk.brain.flow import Slots
    from spatalk.voice.frames import ToolTurnDoneFrame
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    frames = [
        LLMFullResponseStartFrame(),
        FunctionCallInProgressFrame(
            function_name="choose_service", tool_call_id="1", arguments={"said": "mesojet"}
        ),
        LLMFullResponseEndFrame(),
        ToolTurnDoneFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, FunctionCallInProgressFrame, LLMFullResponseEndFrame,
            TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == [
        session.cfg.scripts.ask_after_offers
    ]


async def test_a_turn_handed_back_to_the_model_gets_no_question_from_the_runtime(fixed_clock):
    """A refused tool or a side question: another completion is coming, so the runtime asks
    nothing and the model's one-step-behind question does not go out on top of it."""
    from pipecat.frames.frames import FunctionCallInProgressFrame

    from spatalk.brain.flow import Slots
    from spatalk.voice.frames import ToolTurnDoneFrame
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("Sure. "),
        LLMTextFrame("Shall I look that up?"),
        FunctionCallInProgressFrame(
            function_name="answer_question", tool_call_id="1", arguments={}
        ),
        LLMFullResponseEndFrame(),
        ToolTurnDoneFrame(handed_back=True),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, FunctionCallInProgressFrame,
            LLMFullResponseEndFrame
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == ["Sure."]
    assert [f for f in down if isinstance(f, TTSSpeakFrame)] == []


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
    # And the call says so: a repeat the runtime declined is rung-0 evidence, not silence.
    assert session.signals.counts()["repeat"] == 1


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


async def test_a_silent_model_turn_gets_the_question_unless_it_was_just_asked(fixed_clock):
    """V1 let a turn with no words from the model have the script "however recently it was
    last asked", which is how "What did you have in mind?" went out twice more on the founder
    call of 2026-09-11 (01:41:12.841 and 01:41:16.795, both on completions the caller's next
    fragment had cancelled: `prompt tokens: 0, completion tokens: 0`). The rule is now the
    same on every path: the same rendered question is never spoken twice running on an
    unchanged record. A question the runtime has *not* just asked still fills a silent turn."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    frames = [LLMFullResponseStartFrame(), LLMFullResponseEndFrame()]
    # Nothing asked yet: a silent turn is still given the script.
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
    # The two cancelled completions of 01:41:12 to 01:41:17, replayed: the record has not
    # moved and the caller has just heard those words, so the line stays quiet.
    for _ in range(2):
        again, _ = await run_test(
            OutputGuardProcessor(session), frames_to_send=frames,
            expected_down_frames=[LLMFullResponseStartFrame, LLMFullResponseEndFrame],
            start_timeout=10.0,
        )
        assert not any(isinstance(f, TTSSpeakFrame) for f in again)
    # The record moves and the next question is asked.
    session.slots = session.slots.with_(service_id="mesojet_facial")
    moved, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMFullResponseEndFrame, TTSSpeakFrame
        ],
        start_timeout=10.0,
    )
    assert [f.text for f in moved if isinstance(f, TTSSpeakFrame)] == [
        session.cfg.scripts.ask_practitioner
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


async def test_a_fragment_is_not_a_turn_and_its_words_are_kept(fixed_clock):
    """Founder call 2026-09-11 01:41:11 to 01:41:17. Soniox sent "Um.", "Well." and "What was
    the, uh-" as three final transcriptions; each one started a user turn, interrupted the
    assistant, ran the model and re-spoke "What did you have in mind?". The gate sits between
    STT and the aggregator, so it is the one layer that can decide an utterance is not a turn
    at all: a content-free fragment goes no further, and its words are held and put in front
    of the next transcription so nothing the caller said is lost."""
    from pipecat.processors.frame_processor import FrameDirection
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    gate = RulesGateProcessor(session)
    down = []

    async def collect(frame, direction=FrameDirection.DOWNSTREAM):
        down.append(frame)

    gate.push_frame = collect
    for text in ("Um.", "Well.", "What was the, uh-"):
        await gate.process_frame(
            TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM
        )
    assert down == [], "a fragment reached the aggregator"
    await gate.process_frame(
        TranscriptionFrame(text="the station one again?", user_id="u", timestamp="t"),
        FrameDirection.DOWNSTREAM,
    )
    forwarded = [f.text for f in down if isinstance(f, TranscriptionFrame)]
    assert len(forwarded) == 1
    assert forwarded[0].endswith("the station one again?")
    for word in ("Um", "Well", "What was the"):
        assert word in forwarded[0], f"{word!r} was dropped: {forwarded[0]!r}"
    # A one-word answer is still a turn (V1's "No").
    down.clear()
    await gate.process_frame(
        TranscriptionFrame(text="No.", user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM
    )
    assert [f.text for f in down if isinstance(f, TranscriptionFrame)] == ["No."]


async def test_okay_at_a_yes_no_step_is_an_answer_not_a_fragment(fixed_clock):
    """The gate asks the flow which steps take a yes or a no, so it can never disagree with
    `step_tools`. At the offers question "Okay." is an answer and goes through; at the
    treatment question it is a hesitation and is held."""
    from pipecat.processors.frame_processor import FrameDirection
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    down = []

    async def collect(frame, direction=FrameDirection.DOWNSTREAM):
        down.append(frame)

    # "Would you like to hear our new-client offers?" is open.
    session.slots = Slots(flow="new_booking", returning_client=False)
    gate = RulesGateProcessor(session)
    gate.push_frame = collect
    await gate.process_frame(
        TranscriptionFrame(text="Okay.", user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM
    )
    assert [f.text for f in down if isinstance(f, TranscriptionFrame)] == ["Okay."]
    # "What did you have in mind?" is open: nothing there takes a yes or a no.
    down.clear()
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    gate2 = RulesGateProcessor(session)
    gate2.push_frame = collect
    await gate2.process_frame(
        TranscriptionFrame(text="Okay.", user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM
    )
    assert down == []

# --- one egress to the wire, and receipt-or-retract (model-words memo, §3) ----------------


async def test_a_paraphrased_outcome_claim_is_retracted_when_nothing_was_filed(fixed_clock):
    """The failure every surveyed project has (memo §6.3). The model says the true-sounding
    thing before any tool ran; the completion lexicon never covered it."""
    from spatalk.voice.processors import OutputGuardProcessor

    session, ledger = _session(fixed_clock)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("I've passed that to the team and someone will call you back. "),
        LLMTextFrame("Anything else?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == [session.cfg.scripts.cannot_complete]
    # The replacement sentence is true: an item exists, and its id is now a receipt.
    assert len(ledger.items) == 1 and session.receipts == [f"item:{ledger.items[0].id}"]
    assert session.guard_blocks == 1


async def test_the_replacement_sentence_is_not_guarded_again(fixed_clock):
    """`cannot_complete` itself says "I've passed it to the team". Without a guard-owned
    re-entrancy flag the retraction retracts itself, forever."""
    from spatalk.voice.processors import OutputGuardProcessor

    session, ledger = _session(fixed_clock)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("I've booked you in for Thursday."),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == [session.cfg.scripts.cannot_complete]
    assert len(ledger.items) == 1, "the retraction filed exactly one item"


async def test_a_stall_that_implies_an_outcome_never_reaches_the_wire(fixed_clock):
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ledger = _session(fixed_clock)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("Let me book that in for you."),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == [session.cfg.scripts.cannot_complete]


async def test_a_fixed_script_from_upstream_goes_out_with_its_receipt_and_is_held_without_one(fixed_clock):
    """A `TTSSpeakFrame` the gate or a tool handler pushed passes through the same egress.
    With a receipt it goes out untouched; with none, the outcome script is retracted too —
    which is what makes the guarantee structural rather than a matter of call order."""
    from spatalk.voice.processors import OutputGuardProcessor

    session, ledger = _session(fixed_clock)
    captured = session.cfg.scripts.captured.format(confirm_by="by 4 pm")
    session.remember_receipt("item", "42")
    down, _ = await run_test(
        OutputGuardProcessor(session),
        frames_to_send=[TTSSpeakFrame(text=captured, append_to_context=True)],
        expected_down_frames=[TTSSpeakFrame], start_timeout=10.0,
    )
    assert [f.text for f in down if isinstance(f, TTSSpeakFrame)] == [captured]
    assert ledger.items == []

    session2, ledger2 = _session(fixed_clock)
    down2, _ = await run_test(
        OutputGuardProcessor(session2),
        frames_to_send=[TTSSpeakFrame(text=captured, append_to_context=True)],
        expected_down_frames=[TTSSpeakFrame], start_timeout=10.0,
    )
    assert [f.text for f in down2 if isinstance(f, TTSSpeakFrame)] == [
        session2.cfg.scripts.cannot_complete
    ]
    assert len(ledger2.items) == 1, "the retraction filed the item its sentence asserts"


# --- rung 0: the call reports on itself (memo §6) -----------------------------------------


async def test_a_caller_who_repeats_himself_is_recorded(fixed_clock):
    """Sandbank et al.: repetition and re-prompt counts are the cheapest members of the
    feature family that added about 20% F1 to failure detection. The comparison happens in
    memory and only its similarity is kept."""
    from pipecat.processors.frame_processor import FrameDirection

    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    proc = RulesGateProcessor(session)
    pushed = []

    async def collect(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    proc.push_frame = collect
    for text in ("can you book me that facial", "can you book me that facial, the mesojet one"):
        await proc.process_frame(
            TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM
        )
    assert session.signals.counts()["caller_repeat"] == 1
    assert session.signals.turn == 2
    for s in session.signals.as_json()["signals"]:
        assert set(s["detail"]) <= {"similarity"}


async def test_the_turn_analysers_verdict_is_recorded_and_so_is_its_absence(fixed_clock):
    """OSS §8.4(a): five fields, free, and the prerequisite for every turn-taking decision.
    The silence fallback emits no prediction at all — verified in the installed source: on a
    timeout `_process_speech_segment` returns `result_data = None` and the strategy pushes no
    `MetricsFrame` — so "the fallback fired" is a turn with no verdict, and that is the shape
    this records."""
    from pipecat.frames.frames import MetricsFrame, UserStoppedSpeakingFrame
    from pipecat.metrics.metrics import TurnMetricsData

    from spatalk.voice.observers import TurnSignalObserver
    from tests.test_ops_latency import _push

    session, _ = _session(fixed_clock)
    obs = TurnSignalObserver(session)
    md = TurnMetricsData(
        processor="BaseSmartTurn", is_complete=False, probability=0.22, e2e_processing_time_ms=13.4
    )
    await _push(obs, MetricsFrame(data=[md]))
    await _push(obs, UserStoppedSpeakingFrame())
    await _push(obs, UserStoppedSpeakingFrame())
    c = session.signals.counts()
    assert c["turn_prediction"] == 1 and c["turn_no_prediction"] == 1
    detail = session.signals.as_json()["signals"][0]["detail"]
    assert detail["is_complete"] is False and detail["probability"] == 0.22 and detail["ms"] == 13


# --- one breath a caller turn (founder call 14ea2579, 2026-09-11) -------------------------
#
# `persona.max_sentences_per_turn` was a prompt string and nothing else, and the guard had
# no length opinion of any kind: `guard_blocks=0` at 15:56:39.990 says it saw every word of
# two monologues (15:53:14, three sentences and seven treatments in 23.4 s; 15:54:05, five
# sentences in 29.7 s) and objected to none. The budget below is spent per *caller* turn,
# not per completion, because that is what the caller's ear experiences.


def _truncations(session):
    return [s for s in session.signals.as_json()["signals"] if s["kind"] == "truncated"]


async def test_a_fourth_statement_sentence_is_dropped_and_the_question_still_goes_out(fixed_clock):
    """Skincentrix sets three sentences a turn. The fourth statement is dropped; the model's
    own question is not, because dropping it would leave the turn with no question at all and
    the runtime's fallback is suppressible by `asked_already` (it fired three times on this
    call: 15:54:36.993, 15:54:38.922, 15:54:46.518)."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    assert session.cfg.persona.max_sentences_per_turn == 3
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("We open at nine in the morning. "),
        LLMTextFrame("We close at seven on weekdays. "),
        LLMTextFrame("The suite is on the second floor. "),
        LLMTextFrame("There is parking out back. "),
        LLMTextFrame("Would you like to come in?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame, LLMTextFrame, LLMTextFrame,
            LLMFullResponseEndFrame,
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == [
        "We open at nine in the morning.",
        "We close at seven on weekdays.",
        "The suite is on the second floor.",
        "Would you like to come in?",
    ]
    everything = " ".join(f.text for f in down if hasattr(f, "text"))
    assert "parking" not in everything, f"the capped sentence reached the wire: {everything!r}"
    assert session.signals.counts()["truncated"] == 1
    assert _truncations(session)[0]["detail"] == {"reason": "sentences"}


async def test_a_sentence_naming_more_services_than_the_item_budget_ends_the_turn(fixed_clock):
    """The 15:53:14 recital, replayed. Three sentences is inside the tenant's sentence cap,
    so only the item budget can stop it. The first sentence is spoken WHOLE — the egress
    cannot cut inside a sentence without leaving a fragment on the wire — and the next
    statement is the one that goes."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame(
            "our MesoJet and Sound Therapy, Mirapeel, PureCarbon, and Lift and Sculpt "
            "facials are all popular. "
        ),
        LLMTextFrame("The Hydrabrasion, the Buccal Reset and the HydrationFIX are the other three. "),
        LLMTextFrame("Which of those sounds right?"),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames,
        expected_down_frames=[
            LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame, LLMFullResponseEndFrame,
        ],
        start_timeout=10.0,
    )
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said[0].startswith("our MesoJet") and said[-1] == "Which of those sounds right?"
    assert len(said) == 2
    assert "Hydrabrasion" not in " ".join(said)
    assert session.spoken_items >= 3
    assert _truncations(session) and _truncations(session)[0]["detail"] == {"reason": "items"}


async def test_a_tenant_script_is_never_capped(fixed_clock):
    """Non-negotiable 3: the outcome wording is the tenant's law. The egress may refuse it —
    the guard already does — but it may never shorten it. If a `cannot_complete` sentence
    could be capped, a retraction could be silenced and the false claim it retracted would
    stand on the wire alone."""
    from datetime import datetime, timezone

    from spatalk.brain.flow import Slots
    from spatalk.brain.renderer import render_script
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    # A real receipt, so the script is not retracted for asserting an action nothing did.
    session.remember_receipt("item", "1")
    script = render_script(
        "captured", session.cfg, datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc), urgent=False
    )
    frames = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("We open at nine in the morning. "),
        LLMTextFrame("We close at seven on weekdays. "),
        LLMTextFrame("The suite is on the second floor. "),
        LLMTextFrame("There is parking out back. "),
        LLMFullResponseEndFrame(),
        TTSSpeakFrame(text=script),
    ]
    down, _ = await run_test(
        OutputGuardProcessor(session), frames_to_send=frames, start_timeout=10.0
    )
    assert session.turn_capped is True
    spoken = [f.text for f in down if isinstance(f, TTSSpeakFrame)]
    assert script in spoken, f"the tenant's script was capped: {spoken!r}"
    assert session.signals.counts()["truncated"] == 1, "the cap is recorded once a caller turn"


async def test_the_budget_spans_the_two_completions_of_a_hand_back(fixed_clock):
    """15:53:13.970 `answer_question` then the recital at 15:53:14.990: two completions, one
    caller turn, and the caller heard them as one breath. They share one budget. The second
    completion still gets its floor of one sentence, so a caller turn is never answered with
    silence — do not remove the floor to make the arithmetic tidier."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    guard_proc = OutputGuardProcessor(session)
    first = [
        LLMFullResponseStartFrame(),
        LLMTextFrame("We open at nine in the morning. "),
        LLMTextFrame("We close at seven on weekdays. "),
        LLMTextFrame("The suite is on the second floor. "),
        LLMFullResponseEndFrame(),
        LLMFullResponseStartFrame(),
        LLMTextFrame("There is parking out back. "),
        LLMTextFrame("The door is the blue one. "),
        LLMFullResponseEndFrame(),
    ]
    down, _ = await run_test(guard_proc, frames_to_send=first, start_timeout=10.0)
    said = [f.text.strip() for f in down if isinstance(f, LLMTextFrame)]
    assert said == [
        "We open at nine in the morning.",
        "We close at seven on weekdays.",
        "The suite is on the second floor.",
        "There is parking out back.",
    ]
    assert session.signals.counts()["truncated"] == 1
    assert _truncations(session)[0]["detail"] == {"reason": "sentences"}


async def test_a_caller_turn_resets_the_speech_budget(fixed_clock):
    """The caller spoke: the model gets a fresh breath."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session.spoken_sentences = 5
    session.spoken_items = 7
    session.turn_capped = True
    await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            TranscriptionFrame(text="what was the first one", user_id="u", timestamp="t")
        ],
        expected_down_frames=[TranscriptionFrame], start_timeout=10.0,
    )
    assert session.spoken_sentences == 0
    assert session.spoken_items == 0
    assert session.turn_capped is False


async def test_a_held_fragment_does_not_reset_the_speech_budget(fixed_clock):
    """15:54:32.984, mid-monologue. A held fragment is not a turn — `_turn_text` returns None
    and the gate returns before the session bookkeeping — so it does not buy the model a
    fresh breath in the middle of the sentence the caller is trying to cut into."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session.spoken_sentences = 3
    session.spoken_items = 4
    session.turn_capped = True
    await run_test(
        RulesGateProcessor(session),
        frames_to_send=[TranscriptionFrame(text="Um, what's the, uh.", user_id="u", timestamp="t")],
        expected_down_frames=[], start_timeout=10.0,
    )
    assert session.spoken_sentences == 3
    assert session.spoken_items == 4
    assert session.turn_capped is True


# --- a caller who cannot get a word in stops the audio (founder call 14ea2579) ------------
#
# Two independent gates in two processes swallowed the founder between 15:54:32.19 and
# 15:54:35.555 — 3.37 s of being talked over. GATE 1: `_turn_text` returns None for a
# content-free utterance and `process_frame` returns without pushing, so a held fragment
# never reaches `MinWordsUserTurnStartStrategy` at all ("fragment held" at 15:54:32.984 and
# 15:54:34.537, with no min_words line at either instant). GATE 2, the worse half: "Hello?"
# and "Stop." are NOT fragments, so they pass this gate and are killed downstream by
# min_words=3 — and not merely ignored, DELETED, because the strategy's else branch calls
# `trigger_reset_aggregation` AFTER `_handle_transcription` appended the text. At 15:55:02.691
# a one-word final was reset away: no "fragment held" line, no such word in the stored
# transcript, and nothing in the Gemini context (compare the dumps at 15:55:00.944 and
# 15:55:06.645). The gate is the only layer upstream of both, so it acts here.


def _marker():
    """An ordinary data frame the gate forwards untouched, used to pin the order in which a
    gate-driven interruption arrives relative to the utterance that caused it."""
    return TTSSpeakFrame(text="--marker--")


async def test_a_second_cut_in_while_the_assistant_speaks_stops_the_audio(fixed_clock):
    """One held fragment is a backchannel ("Oh."). Two is a caller who cannot get in."""
    from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
                                       InterruptionFrame)
    from pipecat.tests.utils import SleepFrame

    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    down, up = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            BotStartedSpeakingFrame(), BotStoppedSpeakingFrame(), BotStartedSpeakingFrame(),
            TranscriptionFrame(text="Um, what's the, uh.", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
            _marker(),
            SleepFrame(sleep=0.2),
            TranscriptionFrame(text="What's the, uh.", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
        ],
        start_timeout=10.0,
    )
    assert [f for f in down if isinstance(f, TranscriptionFrame)] == []
    assert len([f for f in down if isinstance(f, InterruptionFrame)]) == 1
    assert len([f for f in up if isinstance(f, InterruptionFrame)]) == 1
    order = [type(f).__name__ for f in down if isinstance(f, (TTSSpeakFrame, InterruptionFrame))]
    assert order == ["TTSSpeakFrame", "InterruptionFrame"], (
        f"the cut-in did not wait for the second fragment: {order}"
    )


async def test_a_single_stop_word_while_the_assistant_speaks_stops_the_audio_without_a_model_turn(
    fixed_clock,
):
    """"Hello?" is not a fragment and not an escalation, so on 2026-09-11 it went straight to
    the aggregator and was deleted there. It asks for the floor, so it gets the floor at
    once — and it still runs no model turn, because one word is not an answer."""
    from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
                                       InterruptionFrame)
    from pipecat.tests.utils import SleepFrame

    from spatalk.voice.processors import RulesGateProcessor

    class Ctx:
        def __init__(self):
            self.messages = []

        def add_message(self, message):
            self.messages.append(message)

    session, _ = _session(fixed_clock)
    session.context = Ctx()
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            BotStartedSpeakingFrame(), BotStoppedSpeakingFrame(), BotStartedSpeakingFrame(),
            TranscriptionFrame(text="Hello?", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
            BotStoppedSpeakingFrame(),
            TranscriptionFrame(text="What was the first one?", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
        ],
        start_timeout=10.0,
    )
    assert len([f for f in down if isinstance(f, InterruptionFrame)]) == 1
    said = [f.text for f in down if isinstance(f, TranscriptionFrame)]
    assert len(said) == 1, said
    assert said[0].startswith("Hello?") and said[0].endswith("What was the first one?")
    assert session.context.messages == [], "the stop word ran a model turn of its own"


async def test_a_short_word_the_bargein_gate_would_delete_is_held_not_forwarded(fixed_clock):
    """The 15:55:02.691 loss. One word the founder said reached no transcript, no context and
    no model, because the aggregator deleted it on the three-word floor. It is held here
    instead, and goes in front of the next utterance that carries content."""
    from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
                                       InterruptionFrame)
    from pipecat.tests.utils import SleepFrame

    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    down, up = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            BotStartedSpeakingFrame(), BotStoppedSpeakingFrame(), BotStartedSpeakingFrame(),
            TranscriptionFrame(text="What?", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
            _marker(),
            SleepFrame(sleep=0.2),
            BotStoppedSpeakingFrame(),
            TranscriptionFrame(text="I said how much.", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
        ],
        start_timeout=10.0,
    )
    # "What?" is not a stop request and it is the first cut-in, so nothing is interrupted yet.
    assert [f for f in down if isinstance(f, InterruptionFrame)] == []
    assert [f for f in up if isinstance(f, InterruptionFrame)] == []
    said = [f.text for f in down if isinstance(f, TranscriptionFrame)]
    assert len(said) == 1, said
    assert "What?" in said[0] and "I said how much." in said[0]


async def test_a_long_cut_in_is_left_to_the_aggregator(fixed_clock):
    """At or above the floor the aggregator does the right thing itself, so the gate does
    nothing: no double interruption and no double barge-in count."""
    from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
                                       InterruptionFrame)
    from pipecat.tests.utils import SleepFrame

    from spatalk.brain.rules import INTERRUPT_MIN_WORDS
    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    said_by_caller = "Can you stop talking? Hello?"
    assert len(said_by_caller.split()) >= INTERRUPT_MIN_WORDS
    down, up = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            BotStartedSpeakingFrame(), BotStoppedSpeakingFrame(), BotStartedSpeakingFrame(),
            TranscriptionFrame(text=said_by_caller, user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
        ],
        start_timeout=10.0,
    )
    assert [f.text for f in down if isinstance(f, TranscriptionFrame)] == [said_by_caller]
    assert [f for f in down if isinstance(f, InterruptionFrame)] == []
    assert [f for f in up if isinstance(f, InterruptionFrame)] == []


async def test_the_disclosure_cannot_be_cut_off(fixed_clock):
    """The gate sits upstream of `MuteUntilFirstBotCompleteUserMuteStrategy`, which suppresses
    interruptions until the bot's first BotStoppedSpeakingFrame, so it has to mirror that
    itself or it fires a pointless upstream interruption into STT during the disclosure."""
    from pipecat.frames.frames import BotStartedSpeakingFrame, InterruptionFrame
    from pipecat.tests.utils import SleepFrame

    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    down, up = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            BotStartedSpeakingFrame(),
            TranscriptionFrame(text="Um.", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
            TranscriptionFrame(text="Hello?", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
            TranscriptionFrame(text="Stop.", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
        ],
        start_timeout=10.0,
    )
    assert [f for f in down if isinstance(f, InterruptionFrame)] == []
    assert [f for f in up if isinstance(f, InterruptionFrame)] == []


async def test_a_band_three_word_over_the_assistant_stops_the_audio_before_its_script(fixed_clock):
    """A band-3 word must not queue its 911 script behind the sentence the caller cut into."""
    from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
                                       InterruptionFrame)
    from pipecat.tests.utils import SleepFrame

    from spatalk.voice.processors import RulesGateProcessor

    class Ctx:
        def __init__(self):
            self.messages = []

        def add_message(self, message):
            self.messages.append(message)

    session, ledger = _session(fixed_clock)
    session.context = Ctx()

    class FakeWorker:
        async def queue_frames(self, frames):
            pass

    session.worker = FakeWorker()
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            BotStartedSpeakingFrame(), BotStoppedSpeakingFrame(), BotStartedSpeakingFrame(),
            TranscriptionFrame(text="Seizure.", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
        ],
        start_timeout=10.0,
    )
    spoken = [f for f in down if isinstance(f, (InterruptionFrame, TTSSpeakFrame))]
    assert [type(f).__name__ for f in spoken] == ["InterruptionFrame", "TTSSpeakFrame"]
    assert "911" in spoken[1].text
    assert len(ledger.items) == 1 and ledger.items[0].type == "escalation_emergency"
    assert session.context.messages == [{"role": "user", "content": "Seizure."}]


# --- the caller's own turn, for the tool handler to read (founder call 14ea2579) ----------
#
# 15:55:00.682: the caller's whole turn was "How much does it cost?" and the model recorded
# it as `choose_service{'said': 'MesoJet and Sound Therapy facial'}`. The engine's only
# question detector runs on the ARGUMENT, so it never saw a question. The runtime has had
# the caller's real words at the gate all along; this is where they get put down.


async def test_the_gate_records_whether_the_callers_turn_asked_something(fixed_clock):
    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    session.answer_owed_spent = True
    await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            TranscriptionFrame(text="How much does it cost?", user_id="u", timestamp="t")
        ],
        expected_down_frames=[TranscriptionFrame], start_timeout=10.0,
    )
    assert session.caller_said == "How much does it cost?"
    assert session.caller_asked is True
    assert session.answer_owed_spent is False
    # The next turn answers rather than asks, and the flag goes with it.
    await run_test(
        RulesGateProcessor(session),
        frames_to_send=[TranscriptionFrame(text="The mesojet one.", user_id="u", timestamp="t")],
        expected_down_frames=[TranscriptionFrame], start_timeout=10.0,
    )
    assert session.caller_said == "The mesojet one."
    assert session.caller_asked is False


async def test_a_held_fragment_is_part_of_the_question_the_gate_records(fixed_clock):
    """The question detector sees the same merged turn the model does."""
    from pipecat.tests.utils import SleepFrame

    from spatalk.brain.flow import Slots
    from spatalk.voice.processors import RulesGateProcessor

    session, _ = _session(fixed_clock)
    session.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            TranscriptionFrame(text=" Um.", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
            TranscriptionFrame(text="What's the price?", user_id="u", timestamp="t"),
            SleepFrame(sleep=0.2),
        ],
        expected_down_frames=[TranscriptionFrame], start_timeout=10.0,
    )
    assert "Um." in session.caller_said and "What's the price?" in session.caller_said
    assert session.caller_asked is True


async def test_the_clinical_offer_the_gate_speaks_is_not_asked_twice(fixed_clock):
    """The gate pushes `scripts.clinical_offer` and returns before the transcription reaches
    the aggregator, so no model turn runs and `OutputGuardProcessor._finish_turn` never fires
    for that frame. `_egress` calls `remember_spoken` (for the echo scrubber), not
    `remember_question`, so on the caller's next turn the record was still at the clinical
    offer and the same sentence was rendered again with `asked_already` False. The record
    group is making the clinical offer a step of its own, which makes that path reachable
    more often, so it is closed here."""
    from spatalk.voice.processors import RulesGateProcessor

    session, ledger = _session(fixed_clock)
    ended = []

    class FakeWorker:
        async def queue_frames(self, frames):
            ended.extend(type(f).__name__ for f in frames)

    session.worker = FakeWorker()
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[
            TranscriptionFrame(text="I have a rash after my peel", user_id="u", timestamp="t")
        ],
        expected_down_frames=[TTSSpeakFrame], start_timeout=10.0,
    )
    assert down[0].text == session.cfg.scripts.clinical_offer
    assert ledger.items == [] and ended == []
    assert session.asked_already(session.cfg.scripts.clinical_offer) is True
    assert session.runtime_asked_this_turn is True


async def test_the_gate_firing_clinical_again_at_the_offer_keeps_the_parked_booking(fixed_clock):
    """Founder call 14ea2579, the deterministic door into the same loss. The clinical offer
    is open with the booking parked behind it; the caller re-asks the clinical question
    instead of answering, the lexicon matches ("is it safe"), and the gate opens the clinical
    flow a second time. The offer is spoken again and nothing is filed — but the booking must
    still be there when the call ends."""
    from spatalk.brain.flow import open_flow
    from spatalk.voice.processors import RulesGateProcessor

    session, ledger = _session(fixed_clock)
    session.slots = open_flow("clinical", _the_1556_booking(), "voice", "+19055550101")
    assert session.slots.parked.service_id == "mesojet_facial"
    down, _ = await run_test(
        RulesGateProcessor(session),
        frames_to_send=[TranscriptionFrame(text="I mean, is it safe?", user_id="u", timestamp="t")],
        expected_down_frames=[TTSSpeakFrame], start_timeout=10.0,
    )
    assert down[0].text == session.cfg.scripts.clinical_offer
    assert ledger.items == []
    assert session.slots.flow == "clinical"
    assert session.slots.parked is not None
    assert session.slots.parked.service_id == "mesojet_facial"
