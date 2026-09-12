"""The voice adapter of the slot engine: the context follows the open step (design §6.5)."""
import uuid
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _session(fixed_clock):
    from pipecat.processors.aggregators.llm_context import LLMContext

    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.prompt import build_system_prompt
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.brain.tools import tools_schema
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.session import VoiceSession

    cfg = load_bundle(BUNDLE)
    ledger = MemoryLedger(fixed_clock)
    caps = TierCCapabilities(ledger=ledger, sms=MemorySms(), clock=fixed_clock)
    ref = ConversationRef(
        conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101"
    )
    s = VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=fixed_clock)
    s.context = LLMContext(
        messages=[{"role": "system", "content": build_system_prompt(cfg, "voice", fixed_clock.now())}],
        tools=tools_schema(cfg),
    )
    return s, ledger


class _Params:
    def __init__(self, name, args, llm):
        self.function_name, self.arguments, self.llm = name, args, llm
        self.results = []

    async def result_callback(self, result, properties=None):
        self.results.append((result, properties))


class _LLM:
    def __init__(self):
        self.frames = []

    async def push_frame(self, frame, direction=None):
        self.frames.append(frame)


def _spoken(llm):
    from pipecat.frames.frames import TTSSpeakFrame

    return [f.text for f in llm.frames if isinstance(f, TTSSpeakFrame)]


async def test_sync_context_puts_the_step_brief_on_the_system_message_and_the_step_tools_on_the_context(fixed_clock):
    from spatalk.brain.flow import STEP_MARKER, Slots
    from spatalk.voice.steps import sync_context

    s, _ = _session(fixed_clock)
    sync_context(s)
    system = [m for m in s.context.messages if m.get("role") == "system"]
    assert len(system) == 1 and system[0]["content"].count(STEP_MARKER) == 1
    assert "start_request" in system[0]["content"].split(STEP_MARKER, 1)[1]
    static = system[0]["content"].split(STEP_MARKER, 1)[0]
    s.slots = Slots(flow="new_booking", returning_client=True)
    sync_context(s)
    system = [m for m in s.context.messages if m.get("role") == "system"]
    assert len(system) == 1 and system[0]["content"].count(STEP_MARKER) == 1
    # The static prefix is byte-for-byte the same: the vendor's cache keeps matching.
    assert system[0]["content"].startswith(static)
    assert "choose_practitioner" in system[0]["content"].split(STEP_MARKER, 1)[1]
    names = [t.name for t in s.context.tools.standard_tools]
    assert "choose_practitioner" in names and "file_request" not in names


async def test_a_slot_tool_says_nothing_and_never_reruns_the_llm(fixed_clock):
    """Was `…_speaks_the_next_question_and_never_reruns_the_llm`, which was the slot engine's
    invariant 4 in code: the runtime spoke the question and the model never got the turn. The
    memo's decision 1 replaces that invariant — the outcome sentence is still the tenant's,
    the question is the model's — so the handler speaks nothing here.

    The orchestrator's amendment of 2026-09-11 keeps `run_llm` False: one model call per
    caller turn is an invariant, so the question comes from the same reply that called the
    tool, and `OutputGuardProcessor` speaks the fixed question only if that reply carried
    none. The tool result still hands the model the fresh readiness report for the next turn.
    """
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="new_booking")
    llm = _LLM()
    params = _Params("answer", {"value": "yes"}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm) == [], "no script; the model words the practitioner question"
    assert s.slots.returning_client is True and s.tool_called_this_turn
    assert params.results[0][1].run_llm is False
    assert s.runtime_asked_this_turn is False
    names = [t.name for t in s.context.tools.standard_tools]
    assert "choose_practitioner" in names
    brief = s.context.messages[0]["content"]
    assert "who they would like to see" in brief


async def test_a_confirmation_is_still_the_runtimes_own_words(fixed_clock):
    """The other half of the split, and the reason phase A is safe: a value the resolver is
    unsure of is read back in the tenant's wording, with no second model call."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import _make_handler

    s, _ = _session(fixed_clock)
    s.slots = Slots(flow="new_booking", returning_client=True)
    llm = _LLM()
    params = _Params("choose_practitioner", {"said": "Ellen"}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm) == [s.cfg.scripts.confirm_match.format(value="Helen")]
    assert params.results[0][1].run_llm is False
    assert s.runtime_asked_this_turn is True
    assert s.signals.counts()["repair"] == 1


async def test_a_slot_tool_never_triggers_a_second_model_run(fixed_clock):
    """The amendment's invariant, on every branch a slot tool can take: one model call per
    caller turn. A second round trip for wording that is read aloud is 0.8 to 1.0 s of
    silence the caller hears, which LIT R4 says is the thing to shorten first."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import _make_handler

    for name, args, slots in (
        ("answer", {"value": "no"}, Slots(flow="new_booking")),
        ("choose_service", {"said": "mesojet facial"},
         Slots(flow="new_booking", returning_client=False, offers_done=True)),
        ("give_name", {"first_name": "Dana"},
         Slots(flow="callback", returning_client=True, practitioner="any",
               service_id="classic_facial")),
        ("choose_practitioner", {"said": "Ellen"}, Slots(flow="new_booking", returning_client=True)),
    ):
        s, _ = _session(fixed_clock)
        s.slots = slots
        llm = _LLM()
        params = _Params(name, args, llm)
        await _make_handler(s)(params)
        assert params.results[0][1].run_llm is False, name


async def test_the_tool_handler_tells_the_guard_when_its_half_of_the_turn_is_done(fixed_clock):
    """Pipecat queues the function calls and pushes `LLMFullResponseEndFrame` without waiting
    for them, so the guard cannot know the runtime's fixed lines are still coming. The
    handler says so itself, last, and says whether the turn went back to the model."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.frames import ToolTurnDoneFrame
    from spatalk.voice.handlers import _make_handler

    s, _ = _session(fixed_clock)
    s.slots = Slots(flow="new_booking")
    llm = _LLM()
    await _make_handler(s)(_Params("answer", {"value": "no"}, llm))
    done = [f for f in llm.frames if isinstance(f, ToolTurnDoneFrame)]
    assert len(done) == 1 and done[0].handed_back is False
    assert llm.frames[-1] is done[0], "the done frame comes after the runtime's own lines"
    # A refused call hands the turn back, and says so.
    s2, _ = _session(fixed_clock)
    s2.slots = Slots(flow="new_booking")
    llm2 = _LLM()
    await _make_handler(s2)(_Params("give_name", {"first_name": "Ellen"}, llm2))
    back = [f for f in llm2.frames if isinstance(f, ToolTurnDoneFrame)]
    assert len(back) == 1 and back[0].handed_back is True


async def test_the_outcome_line_is_still_spoken_and_buys_no_second_model_call(fixed_clock):
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
        first_name="Dana", phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(), team_note_asked=True,
    )
    llm = _LLM()
    params = _Params("file_request", {}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm)[0].startswith("[reassuringly] I've sent that to the team as a request")
    assert params.results[0][1].run_llm is False


async def test_file_request_speaks_the_outcome_and_the_item_has_the_records_contact(fixed_clock):
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
        first_name="Dana", phone="+19055550101", phone_confirmed=True,
        preferred_window=PreferredWindow(), team_note_asked=True,
    )
    llm = _LLM()
    await _make_handler(s)(_Params("file_request", {}, llm))
    assert _spoken(llm)[0].startswith("[reassuringly] I've sent that to the team as a request")
    assert ledger.items[0].contact.name == "Dana" and s.band == 2 and s.slots.flow is None


async def test_a_tool_the_step_did_not_offer_is_refused_in_words_the_model_can_read(fixed_clock):
    """Was `…_is_ignored_and_the_model_answers`. The V1 behaviour — first call silent with
    the turn handed back, second call falls back to the fixed question — was the best a
    *silent* refusal could do. The model is now told why, every time, so the retry counter
    stops being the strategy and becomes only a ceiling (OSS §8.1(e)); the fourth rejection
    in one caller turn speaks the fixed question rather than buying a fourth model call.

    Everything the old case pinned still holds: nothing written, nothing filed, nothing
    spoken, the turn handed back."""
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import MAX_REJECTIONS_PER_TURN, _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="new_booking")
    llm = _LLM()
    handler = _make_handler(s)
    for _ in range(MAX_REJECTIONS_PER_TURN):
        p = _Params("give_name", {"first_name": "Ellen"}, llm)
        await handler(p)
        assert s.slots.first_name is None and ledger.items == []
        assert _spoken(llm) == [] and p.results[0][1].run_llm is True
        reason = p.results[0][0]["rejection"]
        assert "give_name" in reason and "answer" in reason and "yes" in reason
    last = _Params("give_name", {"first_name": "Ellen"}, llm)
    await handler(last)
    assert _spoken(llm) == [s.cfg.scripts.ask_returning]
    assert last.results[0][1].run_llm is False
    assert s.signals.counts()["tool_rejected"] == MAX_REJECTIONS_PER_TURN + 1


async def test_a_side_question_hands_the_turn_over_and_says_nothing(fixed_clock):
    """The 01:40 call, fixed. The caller's question is no longer an answer to the open slot:
    it opens a digression frame, writes nothing, speaks nothing, and the model gets the turn
    with a brief that names what the runtime was about to ask."""
    from spatalk.brain.flow import Slots, Step
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="new_booking", returning_client=False, offers_done=True)
    llm = _LLM()
    params = _Params("answer_question", {}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm) == [] and ledger.items == []
    assert s.slots.digression == Step.SERVICE and s.slots.service_id is None
    assert params.results[0][1].run_llm is True
    assert s.signals.counts()["digression"] == 1
    # The brief the model is about to read names what the runtime was about to ask.
    brief = s.context.messages[0]["content"]
    assert "asked something else" in brief and "which treatment" in brief


async def test_the_last_answer_files_the_request_without_a_second_model_turn(fixed_clock):
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="hydrabrasion_facial",
        first_name="Dana", phone="+19055550101", phone_confirmed=True, preferred_window=PreferredWindow(),
    )
    llm = _LLM()
    await _make_handler(s)(_Params("answer", {"value": "no"}, llm))   # the team-note question
    assert ledger.items[0].type == "callback"
    assert _spoken(llm)[0].startswith("[reassuringly] I've sent that to the team as a request")
