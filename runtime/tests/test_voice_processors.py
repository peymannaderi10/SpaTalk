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
    assert session.band == 3 and ledger.items[0].type == "escalation_clinical"
    assert ended == ["EndFrame"]


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
    assert down[0].append_to_context is True and ledger.items[0].type == "escalation_clinical"
