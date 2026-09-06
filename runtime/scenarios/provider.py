"""promptfoo python provider: runs one brain turn against Tier C with in-memory ports.

promptfoo calls :func:`call_api` synchronously, once per test case, in a fresh Python
process. Every turn gets its own ledger and SMS port, so a case can assert on exactly
what the turn filed and sent. Nothing here touches Postgres, Slack or the telephony
provider; the only network call is the LLM itself.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Coroutine

from spatalk.brain.driver import OPENAI, Brain, GeminiClient, OpenAIClient, provider_for
from spatalk.brain.flow import Slots
from spatalk.brain.ports import MemoryLedger, MemorySms
from spatalk.brain.requests import ConversationRef
from spatalk.brain.tier_c import TierCCapabilities
from spatalk.clock import SystemClock
from spatalk.tenants.bundle import load_bundle

BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "tenants"
    / os.environ.get("SCENARIO_TENANT", "skincentrix")
)


def _make_llm():
    """The vendor `LLM_MODEL` names, so a swap drill grades the model it claims to grade.

    `voice.pipeline.make_llm` and `text.service.make_text_llm` read the same variable the
    same way (operations plan, Task E6); if this one did not, step 3 of
    docs/runbooks/model-swap.md would score the old vendor and call it the new one.
    """
    model = os.environ.get("LLM_MODEL", "gemini-2.5-flash")
    if provider_for(model) == OPENAI:
        return OpenAIClient(api_key=os.environ["OPENAI_API_KEY"], model=model)
    return GeminiClient(api_key=os.environ["GOOGLE_API_KEY"], model=model)


def _clock():
    return SystemClock()


async def _run(vars_: dict) -> dict:
    cfg = load_bundle(BUNDLE)
    if vars_.get("sms_number"):
        cfg = cfg.model_copy(update={"sms_from_number": vars_["sms_number"]})
    clock = _clock()
    ledger, sms = MemoryLedger(clock), MemorySms()
    caps = TierCCapabilities(ledger=ledger, sms=sms, clock=clock)
    brain = Brain(_make_llm(), caps, clock)
    ref = ConversationRef(
        conversation_id=uuid.uuid4(),
        tenant=cfg,
        channel=vars_.get("channel", "voice"),
        caller_phone=vars_.get("caller", "+19055550101"),
    )
    slots = Slots.model_validate(vars_["slots"]) if vars_.get("slots") else Slots()
    r = await brain.turn(ref, list(vars_.get("history") or []), vars_["user"], slots)
    return {
        "text": r.reply,
        "said": r.said,
        "slots": r.slots.model_dump(mode="json"),
        "band": r.band,
        "gate_reason": r.gate_reason,
        "tool_calls": r.tool_calls,
        "outcomes": [o.kind for o in r.outcomes],
        "guard_blocked": r.guard_blocked,
        "ended": r.ended,
        "health_context": r.health_context,
        "items": [
            {
                "type": i.type,
                "urgency": i.urgency,
                "health_context": i.health_context,
                "has_name": bool(i.contact.name),
                "has_phone": bool(i.contact.phone),
            }
            for i in ledger.items
        ],
        "sms_sent": len(sms.sent),
    }


def _run_sync(coro: Coroutine[Any, Any, dict]) -> dict:
    """Run one turn from synchronous code, whether or not a loop is already running.

    promptfoo has no loop, so :func:`asyncio.run` is used directly. Under pytest-asyncio
    the caller is already inside a loop, so the turn goes to a worker thread with a loop
    of its own instead of raising "asyncio.run() cannot be called from a running event loop".
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def call_api(prompt: str, options: dict, context: dict) -> dict:
    return {"output": _run_sync(_run(context["vars"]))}
