from datetime import timedelta

import pytest
from sqlalchemy import select

SMS_FROM = "+18885550100"
CALLER = "+19055550101"


@pytest.fixture
async def ctx(sf, registry, fixed_clock):
    """A JobContext on memory ports whose tenant has a toll-free SMS number."""
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    cfg = await registry.get("skincentrix")
    await registry.import_config(cfg.model_copy(update={"sms_from_number": SMS_FROM}), "test")
    registry.invalidate("skincentrix")
    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=Settings(_env_file=None, secret_key="s3cret"),
        sms=MemorySms(),
    )


def _llm(*texts: str):
    from spatalk.brain.driver import FakeLLM, LLMResponse
    return FakeLLM([LLMResponse(text=t, tool_calls=[]) for t in texts])


def _service(ctx, llm):
    from spatalk.text.service import TextConversationService
    return TextConversationService(ctx, llm)


async def _inbound(svc, text: str, msg_id: str, sender: str = CALLER):
    return await svc.handle_inbound(
        tenant_id="skincentrix",
        channel="sms",
        external_id=sender,
        sender=sender,
        text=text,
        provider_message_id=msg_id,
    )


async def test_a_fake_llm_reply_is_sent_and_stored(ctx, sf):
    from spatalk.conversations import get_transcript
    svc = _service(ctx, _llm("We open at ten today."))
    res = await _inbound(svc, "What time do you open today?", "m1")
    assert res.suppressed is False
    assert res.replies == ["We open at ten today."]
    assert ctx.sms.sent == [(SMS_FROM, CALLER, "We open at ten today.")]
    msgs = await get_transcript(sf, res.conversation_id)
    assert [(m.role, m.text) for m in msgs] == [
        ("user", "What time do you open today?"),
        ("assistant", "We open at ten today."),
    ]


async def test_inbound_and_outbound_sms_usage_is_recorded(ctx, sf):
    from spatalk.models import UsageEvent
    svc = _service(ctx, _llm("We open at ten today."))
    await _inbound(svc, "What time do you open today?", "m1")
    async with sf() as s:
        rows = list((await s.scalars(select(UsageEvent).order_by(UsageEvent.id))).all())
    assert [(r.unit, float(r.qty), r.channel) for r in rows] == [
        ("sms_in", 1.0, "sms"),
        ("sms_out", 1.0, "sms"),
    ]


async def test_a_second_message_within_24_hours_joins_the_same_conversation(ctx):
    svc = _service(ctx, _llm("We open at ten today.", "Happy to help."))
    first = await _inbound(svc, "What time do you open today?", "m1")
    ctx.clock.advance(hours=23)
    second = await _inbound(svc, "And on Sunday?", "m2")
    assert second.conversation_id == first.conversation_id


async def test_a_message_after_25_hours_starts_a_new_conversation(ctx):
    svc = _service(ctx, _llm("We open at ten today.", "Happy to help."))
    first = await _inbound(svc, "What time do you open today?", "m1")
    ctx.clock.advance(hours=25)
    second = await _inbound(svc, "And on Sunday?", "m2")
    assert second.conversation_id != first.conversation_id


async def test_a_duplicate_provider_message_id_is_ignored(ctx):
    svc = _service(ctx, _llm("We open at ten today.", "Second reply."))
    await _inbound(svc, "What time do you open today?", "m1")
    again = await _inbound(svc, "What time do you open today?", "m1")
    assert again.suppressed is True and again.reason == "duplicate"
    assert len(ctx.sms.sent) == 1


async def test_an_opted_out_sender_gets_no_reply(ctx, sf):
    from spatalk.conversations import get_transcript
    from spatalk.text.service import add_optout
    await add_optout(sf, "skincentrix", CALLER)
    llm = _llm("We open at ten today.")
    svc = _service(ctx, llm)
    res = await _inbound(svc, "What time do you open today?", "m1")
    assert res.suppressed is True and res.reason == "optout"
    assert ctx.sms.sent == []
    assert llm.calls == []
    msgs = await get_transcript(sf, res.conversation_id)
    assert [(m.role, m.text) for m in msgs] == [("user", "What time do you open today?")]


async def test_controller_human_suppresses_the_brain(ctx, sf):
    from spatalk.conversations import get_transcript
    from spatalk.models import Conversation
    llm = _llm("We open at ten today.", "Second reply.")
    svc = _service(ctx, llm)
    first = await _inbound(svc, "What time do you open today?", "m1")
    async with sf() as s, s.begin():
        (await s.get(Conversation, first.conversation_id)).controller = "human"
    res = await _inbound(svc, "Are you still there?", "m2")
    assert res.conversation_id == first.conversation_id
    assert res.suppressed is True and res.reason == "human"
    assert res.replies == []
    assert len(llm.calls) == 1
    assert len(ctx.sms.sent) == 1
    msgs = await get_transcript(sf, first.conversation_id)
    assert msgs[-1].role == "user" and msgs[-1].text == "Are you still there?"


async def test_history_excludes_staff_text_and_says_a_person_replied(ctx, sf):
    from spatalk.conversations import append_message, start_conversation
    from spatalk.text.service import STAFF_NOTE
    svc = _service(ctx, _llm())
    cid = await start_conversation(sf, "skincentrix", "sms", CALLER, CALLER)
    await append_message(sf, cid, "user", "Can someone call me?")
    await append_message(sf, cid, "staff", "On my way, calling her now")
    await append_message(sf, cid, "staff", "Two minutes")
    assert await svc.history(cid) == [
        {"role": "user", "content": "Can someone call me?"},
        {"role": "assistant", "content": STAFF_NOTE},
    ]


async def test_history_is_limited_to_the_last_twenty_messages(ctx, sf):
    from spatalk.conversations import append_message, start_conversation
    svc = _service(ctx, _llm())
    cid = await start_conversation(sf, "skincentrix", "sms", CALLER, CALLER)
    for i in range(30):
        await append_message(sf, cid, "user", f"message {i}")
    h = await svc.history(cid)
    assert len(h) == 20 and h[0]["content"] == "message 10" and h[-1]["content"] == "message 29"


async def test_a_followup_job_is_enqueued_exactly_once(ctx, sf):
    from spatalk.models import Job
    svc = _service(ctx, _llm("Sure. What day works for you?", "And what time works?"))
    res = await _inbound(svc, "I would like to book something.", "m1")
    await _inbound(svc, "Sometime next week.", "m2")
    async with sf() as s:
        jobs_ = list((await s.scalars(select(Job).where(Job.kind == "text.followup"))).all())
    assert len(jobs_) == 1
    assert jobs_[0].payload["conversation_id"] == str(res.conversation_id)
    assert jobs_[0].run_at == ctx.clock.now() + timedelta(hours=2)


async def test_no_followup_is_scheduled_when_the_reply_is_not_a_question(ctx, sf):
    from spatalk.models import Job
    svc = _service(ctx, _llm("We open at ten today."))
    await _inbound(svc, "What time do you open today?", "m1")
    async with sf() as s:
        assert (await s.scalars(select(Job).where(Job.kind == "text.followup"))).all() == []


async def test_the_followup_is_sent_when_the_customer_stayed_silent(ctx, sf):
    from spatalk import jobs
    from spatalk.models import Conversation
    svc = _service(ctx, _llm("Sure. What day works for you?"))
    res = await _inbound(svc, "I would like to book something.", "m1")
    ctx.clock.advance(hours=2)
    assert await jobs.run_once(sf, ctx) == 1
    assert len(ctx.sms.sent) == 2
    from_number, to, body = ctx.sms.sent[-1]
    assert from_number == SMS_FROM and to == CALLER
    assert body.startswith("Just checking in from Skincentrix")
    async with sf() as s:
        assert (await s.get(Conversation, res.conversation_id)).followup_sent_at is not None


async def test_the_followup_is_not_sent_when_the_user_replied(ctx, sf):
    from spatalk import jobs
    from spatalk.models import Conversation
    svc = _service(ctx, _llm("Sure. What day works for you?", "Thursday works."))
    res = await _inbound(svc, "I would like to book something.", "m1")
    ctx.clock.advance(hours=1)
    await _inbound(svc, "Thursday please.", "m2")
    ctx.clock.advance(hours=1)
    assert await jobs.run_once(sf, ctx) == 1
    assert all("Just checking in" not in body for _, _, body in ctx.sms.sent)
    async with sf() as s:
        assert (await s.get(Conversation, res.conversation_id)).followup_sent_at is None


async def test_a_followup_that_would_land_at_night_moves_to_the_next_open_hour(ctx, sf):
    from zoneinfo import ZoneInfo

    from spatalk.models import Job
    # 00:00 UTC Wednesday is 20:00 Toronto Tuesday; two hours later is 22:00, past 21:00.
    ctx.clock.advance(hours=6)
    svc = _service(ctx, _llm("Sure. What day works for you?"))
    await _inbound(svc, "I would like to book something.", "m1")
    async with sf() as s:
        job = (await s.scalars(select(Job).where(Job.kind == "text.followup"))).one()
    local = job.run_at.astimezone(ZoneInfo("America/Toronto"))
    assert local.date() > ctx.clock.now().astimezone(ZoneInfo("America/Toronto")).date()
    assert 9 <= local.hour < 21


async def test_the_conversation_is_closed_when_the_turn_ends(ctx, sf):
    from spatalk.brain.driver import FakeLLM, LLMResponse, ToolCall
    from spatalk.models import Conversation
    from spatalk.text.service import TextConversationService
    llm = FakeLLM([LLMResponse(text=None, tool_calls=[ToolCall("end_conversation", {})])])
    svc = TextConversationService(ctx, llm)
    res = await _inbound(svc, "That is all, thanks.", "m1")
    assert res.turn.ended is True
    async with sf() as s:
        conv = await s.get(Conversation, res.conversation_id)
    assert conv.closed_at is not None


async def test_a_closed_conversation_is_not_reused(ctx, sf):
    from spatalk.brain.driver import FakeLLM, LLMResponse, ToolCall
    from spatalk.text.service import TextConversationService
    llm = FakeLLM(
        [
            LLMResponse(text=None, tool_calls=[ToolCall("end_conversation", {})]),
            LLMResponse(text="We open at ten today.", tool_calls=[]),
        ]
    )
    svc = TextConversationService(ctx, llm)
    first = await _inbound(svc, "That is all, thanks.", "m1")
    second = await _inbound(svc, "Actually, one more thing.", "m2")
    assert second.conversation_id != first.conversation_id


async def test_health_context_is_propagated_to_the_conversation(ctx, sf):
    from spatalk.models import Conversation
    svc = _service(ctx, _llm("The team will look at that for you."))
    res = await _inbound(svc, "I am pregnant, can I still get a facial?", "m1")
    async with sf() as s:
        assert (await s.get(Conversation, res.conversation_id)).health_context is True


async def test_a_message_the_rules_gate_answers_is_stored_before_the_fixed_reply(ctx, sf):
    """Founder call 2026-09-05: the utterance that trips the gate is part of the transcript on
    every channel, ahead of the fixed reply, so the notes and the request card can show it."""
    from spatalk.brain.driver import FakeLLM
    from spatalk.conversations import get_transcript
    llm = FakeLLM([])
    svc = _service(ctx, llm)
    res = await _inbound(svc, "I have a rash after my laser session", "m1")
    assert llm.calls == [] and res.turn.gate_reason == "clinical"
    msgs = await get_transcript(sf, res.conversation_id)
    assert [m.role for m in msgs[:2]] == ["user", "assistant"]
    assert msgs[0].text == "I have a rash after my laser session"
    assert all(m.role == "assistant" for m in msgs[1:])
    assert "clinical team" in " ".join(m.text for m in msgs[1:])


async def test_the_slot_record_survives_between_texts(ctx, sf):
    """The engine's record follows the thread: the second text lands in the open step."""
    from sqlalchemy import select

    from spatalk.brain.driver import FakeLLM, LLMResponse, ToolCall
    from spatalk.models import Conversation

    llm = FakeLLM([
        LLMResponse(text=None, tool_calls=[ToolCall("start_request", {"kind": "callback"})]),
        LLMResponse(text=None, tool_calls=[ToolCall("answer", {"value": "yes"})]),
    ])
    svc = _service(ctx, llm)
    await _inbound(svc, "call me please", "m1")
    second = await _inbound(svc, "yes", "m2")
    async with sf() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.id == second.conversation_id))
    assert conv.flow["flow"] == "callback" and conv.flow["returning_client"] is True
    cfg = await ctx.registry.get("skincentrix")
    assert second.replies[0] == cfg.scripts.ask_practitioner
