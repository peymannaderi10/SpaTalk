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


async def test_a_slot_tool_speaks_the_next_question_and_never_reruns_the_llm(fixed_clock):
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="new_booking")
    llm = _LLM()
    params = _Params("answer", {"value": "yes"}, llm)
    await _make_handler(s)(params)
    assert _spoken(llm) == [s.cfg.scripts.ask_practitioner]
    assert s.slots.returning_client is True and s.tool_called_this_turn
    assert params.results[0][1].run_llm is False
    names = [t.name for t in s.context.tools.standard_tools]
    assert "choose_practitioner" in names


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
    assert _spoken(llm)[0].startswith("I've sent that to the team as a request")
    assert ledger.items[0].contact.name == "Dana" and s.band == 2 and s.slots.flow is None


async def test_a_tool_the_step_did_not_offer_is_ignored_and_the_model_answers(fixed_clock):
    """Nothing is written and nothing is said, whatever happens next.

    The spec's answer was to re-ask the open question (slot engine design, §7), which is what
    the second call below still does. But on the founder's call 2026-09-10 20:55:35 the first
    one turned "can you book me that facial?" into a bare "What did you have in mind?" with
    no answer in front of it, so the caller repeated himself. The first ignored call in a
    caller's turn now hands the turn back to the model, which has the step's tools and the
    whole conversation; the second falls back to the script so nothing can loop.
    """
    from spatalk.brain.flow import Slots
    from spatalk.voice.handlers import _make_handler

    s, ledger = _session(fixed_clock)
    s.slots = Slots(flow="new_booking")
    llm = _LLM()
    handler = _make_handler(s)
    first = _Params("give_name", {"first_name": "Ellen"}, llm)
    await handler(first)
    assert s.slots.first_name is None and ledger.items == []
    assert _spoken(llm) == [] and first.results[0][1].run_llm is True
    second = _Params("give_name", {"first_name": "Ellen"}, llm)
    await handler(second)
    assert s.slots.first_name is None and ledger.items == []
    assert _spoken(llm) == [s.cfg.scripts.ask_returning]
    assert second.results[0][1].run_llm is False


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
    assert _spoken(llm)[0].startswith("I've sent that to the team as a request")
