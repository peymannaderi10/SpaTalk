import uuid
from pathlib import Path
from pipecat.frames.frames import (LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame,
                                   TTSSpeakFrame, TranscriptionFrame)
from pipecat.tests.utils import run_test

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _session(fixed_clock):
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.session import VoiceSession
    cfg = load_bundle(BUNDLE)
    ledger = MemoryLedger(fixed_clock)
    caps = TierCCapabilities(ledger=ledger, sms=MemorySms(), clock=fixed_clock)
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101")
    return VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=fixed_clock), ledger


async def test_guard_replaces_completion_claim_and_drops_rest(fixed_clock):
    from spatalk.voice.processors import OutputGuardProcessor
    session, ledger = _session(fixed_clock)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("Great, I've booked you "), LLMTextFrame("for Thursday. "),
              LLMTextFrame("Anything else?"), LLMFullResponseEndFrame()]
    down, _ = await run_test(OutputGuardProcessor(session), frames_to_send=frames,
                             expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame])
    texts = [f.text for f in down if isinstance(f, LLMTextFrame)]
    assert len(texts) == 1 and "passed it to the team" in texts[0] and "booked" not in texts[0]
    assert session.guard_blocks == 1 and ledger.items[0].type == "question"


async def test_guard_passes_clean_sentences(fixed_clock):
    from spatalk.voice.processors import OutputGuardProcessor
    session, _ = _session(fixed_clock)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("The express treatment is $99. "), LLMTextFrame("Want the link?"),
              LLMFullResponseEndFrame()]
    down, _ = await run_test(OutputGuardProcessor(session), frames_to_send=frames,
                             expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame, LLMFullResponseEndFrame])
    assert [f.text for f in down if isinstance(f, LLMTextFrame)] == ["The express treatment is $99.", "Want the link?"]


async def test_rules_gate_speaks_script_and_swallows_transcription(fixed_clock):
    from spatalk.voice.processors import RulesGateProcessor
    session, ledger = _session(fixed_clock)
    ended = []
    class FakeWorker:
        async def queue_frames(self, frames): ended.extend(type(f).__name__ for f in frames)
    session.worker = FakeWorker()
    down, _ = await run_test(RulesGateProcessor(session),
                             frames_to_send=[TranscriptionFrame(text="I have a rash after my laser", user_id="u", timestamp="t")],
                             expected_down_frames=[TTSSpeakFrame])
    assert "911" in down[0].text and session.band == 3 and ledger.items[0].type == "escalation_clinical"
    assert ended == ["EndFrame"]


async def test_rules_gate_forwards_ordinary_transcription(fixed_clock):
    from spatalk.voice.processors import RulesGateProcessor
    session, _ = _session(fixed_clock)
    await run_test(RulesGateProcessor(session),
                   frames_to_send=[TranscriptionFrame(text="how much is a facial", user_id="u", timestamp="t")],
                   expected_down_frames=[TranscriptionFrame])
    assert session.band == 1
