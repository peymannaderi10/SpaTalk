import os
import uuid
from pathlib import Path
import pytest

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _world(fixed_clock, responses, sms_number=None, ledger=None):
    from spatalk.brain.driver import Brain, FakeLLM
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    if sms_number:
        cfg = cfg.model_copy(update={"sms_from_number": sms_number})
    ledger = ledger if ledger is not None else MemoryLedger(fixed_clock)
    sms = MemorySms()
    caps = TierCCapabilities(ledger=ledger, sms=sms, clock=fixed_clock)
    llm = FakeLLM(responses)
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101")
    return Brain(llm, caps, fixed_clock), ref, ledger, sms, llm


async def test_rules_gate_short_circuits_without_llm(fixed_clock):
    from spatalk.brain.driver import LLMResponse
    brain, ref, ledger, sms, llm = _world(fixed_clock, [LLMResponse(text="should not be used", tool_calls=[])])
    r = await brain.turn(ref, [], "I have a rash after my laser treatment")
    assert r.band == 3 and r.gate_reason == "clinical" and "911" in r.reply and r.ended
    assert llm.calls == [] and ledger.items[0].type == "escalation_clinical"


async def test_plain_answer_passes_through_guard(fixed_clock):
    from spatalk.brain.driver import LLMResponse
    brain, ref, *_ = _world(fixed_clock, [LLMResponse(text="The express treatment is $99.", tool_calls=[])])
    r = await brain.turn(ref, [], "How much is the express treatment?")
    assert r.band == 1 and r.reply == "The express treatment is $99." and not r.guard_blocked


async def test_tool_call_reply_is_rendered_not_generated(fixed_clock):
    from spatalk.brain.driver import LLMResponse, ToolCall
    brain, ref, ledger, *_ = _world(fixed_clock, [LLMResponse(text=None, tool_calls=[
        ToolCall("request_appointment_change", {"kind": "cancel", "contact": {"name": "Dana"}})])])
    r = await brain.turn(ref, [], "Cancel my appointment please, it's Dana")
    assert r.band == 2 and r.tool_calls == ["request_appointment_change"]
    assert r.reply.startswith("I've sent that to the team as a request")
    assert "cancel" not in r.reply.lower() and ledger.items[0].type == "cancel"


async def test_guard_blocks_hallucinated_completion_and_files_item(fixed_clock):
    from spatalk.brain.driver import LLMResponse
    brain, ref, ledger, *_ = _world(fixed_clock, [LLMResponse(text="Done, I've booked you for Thursday at 2.", tool_calls=[])])
    r = await brain.turn(ref, [], "Book me Thursday at 2")
    assert r.guard_blocked and "booked" not in r.reply and "passed it to the team" in r.reply
    assert ledger.items[0].type == "question"


async def test_volunteered_health_context_flags_item_and_proceeds(fixed_clock):
    from spatalk.brain.driver import LLMResponse, ToolCall
    brain, ref, ledger, *_ = _world(fixed_clock, [LLMResponse(text=None, tool_calls=[
        ToolCall("capture_request", {"kind": "question", "service_id": "microchanneling", "contact": {"name": "Dana"}})])])
    r = await brain.turn(ref, [], "I'm on blood thinners, is the microchanneling okay for me? I'm Dana")
    assert r.band == 2 and r.health_context and ledger.items[0].health_context is True
    assert "team" in r.reply.lower()


async def test_booking_link_and_end(fixed_clock):
    from spatalk.brain.driver import LLMResponse, ToolCall
    brain, ref, ledger, sms, _ = _world(fixed_clock, [
        LLMResponse(text=None, tool_calls=[ToolCall("send_booking_link", {"service_id": "facial"})]),
        LLMResponse(text=None, tool_calls=[ToolCall("end_conversation", {})])], sms_number="+18885550100")
    r = await brain.turn(ref, [], "Text me the link for a facial")
    assert r.outcomes[0].kind == "link_sent" and sms.sent[0][1] == "+19055550101"
    r2 = await brain.turn(ref, [], "That's all, thanks")
    assert r2.ended and r2.reply.startswith("Thanks for calling")


@pytest.mark.skipif(not os.environ.get("GOOGLE_API_KEY"), reason="live Gemini smoke test")
async def test_gemini_client_calls_a_tool(fixed_clock):
    from spatalk.brain.driver import GeminiClient
    from spatalk.brain.prompt import build_system_prompt
    from spatalk.brain.tools import build_tools
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    client = GeminiClient(api_key=os.environ["GOOGLE_API_KEY"], model=os.environ.get("LLM_MODEL", "gemini-2.5-flash"))
    resp = await client.complete(build_system_prompt(cfg, "voice", fixed_clock.now()),
                                 [{"role": "user", "content": "Can I talk to a real person"}], build_tools(cfg))
    assert any(tc.name == "escalate" for tc in resp.tool_calls)


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="live OpenAI smoke test")
async def test_openai_client_calls_a_tool(fixed_clock):
    """The second vendor (operations plan, Task E6) on the same prompt and the same tools.

    Step 3 of docs/runbooks/model-swap.md is the real check; this is the one-turn version
    that says the wiring reaches OpenAI at all. Skipped without the key, like its twin."""
    from spatalk.brain.driver import OpenAIClient
    from spatalk.brain.prompt import build_system_prompt
    from spatalk.brain.tools import build_tools
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(BUNDLE)
    client = OpenAIClient(api_key=os.environ["OPENAI_API_KEY"],
                          model=os.environ.get("OPENAI_MODEL", "openai:gpt-4.1-nano"))
    resp = await client.complete(build_system_prompt(cfg, "voice", fixed_clock.now()),
                                 [{"role": "user", "content": "Can I talk to a real person"}], build_tools(cfg))
    assert any(tc.name == "escalate" for tc in resp.tool_calls)


async def test_guard_block_with_a_dead_ledger_refuses_and_claims_nothing(fixed_clock):
    """The blocked claim could not be filed, so the caller gets the clinic's number, not a promise."""
    from spatalk.brain.driver import LLMResponse
    from spatalk.brain.ports import MemoryLedger

    class ExplodingLedger(MemoryLedger):
        async def create_item(self, ref, draft):
            raise RuntimeError("database is down")

    brain, ref, *_ = _world(fixed_clock,
                            [LLMResponse(text="Done, I've booked you for Thursday at 2.", tool_calls=[])],
                            ledger=ExplodingLedger(fixed_clock))
    r = await brain.turn(ref, [], "Book me Thursday at 2")
    assert r.guard_blocked and [o.kind for o in r.outcomes] == ["refused"]
    assert r.outcomes[0].reason == "unavailable"
    assert "905-703-7546" in r.reply
    low = r.reply.lower()
    for claim in ("sent", "passed it", "confirm with you", "booked"):
        assert claim not in low, f"refusal claimed an action: {r.reply!r}"
