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
