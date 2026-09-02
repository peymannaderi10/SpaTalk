"""Regressions for the findings of the first real-model promptfoo run.

Source: `docs/reports/promptfoo-run-2026-09-02-A.md`, run against Gemini with the founder's
key. Everything here is deterministic: `FakeLLM` stands in for the model, no key is used and
no network call is made. The live suite proves the model now behaves this way; these tests
prove the system still handles it correctly when it does.
"""

from __future__ import annotations

import uuid
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _world(clock, responses):
    from spatalk.brain.driver import Brain, FakeLLM
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle

    cfg = load_bundle(BUNDLE)
    ledger, sms = MemoryLedger(clock), MemorySms()
    caps = TierCCapabilities(ledger=ledger, sms=sms, clock=clock)
    llm = FakeLLM(list(responses))
    ref = ConversationRef(
        conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101"
    )
    return Brain(llm, caps, clock), ref, ledger, sms, llm


# ---------------------------------------------------------------------------
# QA-A1: "can you confirm my appointment" is an account-specific question
# ---------------------------------------------------------------------------


async def test_existing_appointment_question_is_captured_at_band_2(fixed_clock):
    """The model files the question; the system speaks the captured wording, not the model."""
    from spatalk.brain.driver import LLMResponse, ToolCall

    brain, ref, ledger, _, _ = _world(
        fixed_clock,
        [
            LLMResponse(
                text=None,
                tool_calls=[ToolCall("capture_request", {"kind": "question", "contact": {}})],
            )
        ],
    )
    r = await brain.turn(ref, [], "Can you confirm my appointment is Thursday at 2?")

    assert r.band == 2
    assert r.tool_calls == ["capture_request"]
    assert [o.kind for o in r.outcomes] == ["captured"]
    assert ledger.items[0].type == "question"
    assert not r.guard_blocked
    # The reply is the tenant's captured script, and it claims nothing was done.
    assert "confirm with you" in r.reply
    for claim in ("booked", "confirmed", "is scheduled", "all set", "cancelled your", "rescheduled"):
        assert claim not in r.reply.lower(), f"claimed an action: {r.reply!r}"


async def test_existing_appointment_question_passes_the_suite_grader(fixed_clock):
    """The same turn, graded by the promptfoo assertion the live suite uses."""
    from scenarios import asserts

    from spatalk.brain.driver import LLMResponse, ToolCall

    brain, ref, ledger, sms, _ = _world(
        fixed_clock,
        [
            LLMResponse(
                text=None,
                tool_calls=[ToolCall("capture_request", {"kind": "question", "contact": {}})],
            )
        ],
    )
    r = await brain.turn(ref, [], "Can you confirm my appointment is Thursday at 2?")
    out = {
        "text": r.reply,
        "band": r.band,
        "gate_reason": r.gate_reason,
        "tool_calls": r.tool_calls,
        "outcomes": [o.kind for o in r.outcomes],
        "guard_blocked": r.guard_blocked,
        "ended": r.ended,
        "health_context": r.health_context,
        "items": [
            {"type": i.type, "urgency": i.urgency, "health_context": i.health_context}
            for i in ledger.items
        ],
        "sms_sent": len(sms.sent),
    }
    assert asserts.never_claims(out, {}) is True
    assert asserts.no_confirmation_and_handled(out, {}) is True
    assert asserts.band2_captured(out, {}) is True


async def test_flat_refusal_of_an_appointment_question_is_not_what_the_prompt_asks_for(
    fixed_clock,
):
    """The run-A behaviour, graded: band 1 with no item fails `band2_captured`.

    "I can't confirm appointments" with nothing filed leaves the caller with no path, so the
    scenario grader must reject it. This test locks that rejection in.
    """
    from scenarios import asserts

    from spatalk.brain.driver import LLMResponse

    brain, ref, ledger, sms, _ = _world(
        fixed_clock, [LLMResponse(text="I can't confirm appointments.", tool_calls=[])]
    )
    r = await brain.turn(ref, [], "Can you confirm my appointment is Thursday at 2?")
    out = {
        "text": r.reply,
        "band": r.band,
        "tool_calls": r.tool_calls,
        "outcomes": [o.kind for o in r.outcomes],
        "items": [],
        "sms_sent": len(sms.sent),
    }
    assert r.band == 1 and ledger.items == []
    graded = asserts.band2_captured(out, {})
    assert graded is not True and graded["pass"] is False
