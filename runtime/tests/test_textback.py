"""Task B3: one missed-call text-back per caller per day, and never a wrong one.

Every test names the behaviour the plan lists. The rules that keep this safe are the
interesting ones: an opted-out number is never texted, a caller id that is really our own
number (or the clinic's own line, which is what a lost caller id looks like) is never texted,
and a caller is never texted twice inside a day.
"""

import uuid

import pytest
from sqlalchemy import select

SMS_FROM = "+18885550100"
CALLER = "+19055550101"
# The registry fixture registers this as the tenant's own voice number.
OUR_VOICE_NUMBER = "+19055550100"
# tenants/skincentrix/tenant.yaml carries public_phone "905-703-7546", not in E.164.
CLINIC_PUBLIC_PHONE = "+19057037546"


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
        settings=Settings(secret_key="s3cret"),
        sms=MemorySms(),
    )


async def _voice_session(ctx, sf, caller: str | None = CALLER):
    """A finished voice call: a conversation row plus the session the pipeline held."""
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.conversations import start_conversation
    from spatalk.voice.session import VoiceSession
    cfg = await ctx.registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "v3:call-1", caller)
    ref = ConversationRef(
        conversation_id=cid, tenant=cfg, channel="voice", caller_phone=caller
    )
    caps = TierCCapabilities(ledger=MemoryLedger(ctx.clock), sms=MemorySms(), clock=ctx.clock)
    return VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=ctx.clock)


async def _schedule(ctx, session, *, spoke: bool = False, seconds: float = 5.0) -> bool:
    from spatalk.text.textback import schedule_missed_call_textback
    return await schedule_missed_call_textback(
        ctx, session, had_user_speech=spoke, duration_s=seconds
    )


# ----- when a text-back is owed -------------------------------------------------------


async def test_a_five_second_hangup_texts_the_caller_back_once(ctx, sf):
    from spatalk import jobs
    from spatalk.models import Textback
    session = await _voice_session(ctx, sf)
    assert await _schedule(ctx, session, spoke=False, seconds=5.0) is True
    assert await jobs.run_once(sf, ctx) == 1
    assert len(ctx.sms.sent) == 1
    from_number, to, body = ctx.sms.sent[0]
    assert (from_number, to) == (SMS_FROM, CALLER)
    assert body.startswith("Hi, this is Skincentrix's assistant. You just called us.")
    assert "https://skincentrix.janeapp.com" in body
    async with sf() as s:
        rows = list((await s.scalars(select(Textback))).all())
    assert [(r.tenant_id, r.phone) for r in rows] == [("skincentrix", CALLER)]


async def test_a_long_call_the_caller_never_spoke_on_is_texted_back(ctx, sf):
    session = await _voice_session(ctx, sf)
    assert await _schedule(ctx, session, spoke=False, seconds=95.0) is True


async def test_the_text_back_records_outbound_sms_usage(ctx, sf):
    from spatalk import jobs
    from spatalk.models import UsageEvent
    session = await _voice_session(ctx, sf)
    await _schedule(ctx, session)
    await jobs.run_once(sf, ctx)
    async with sf() as s:
        rows = list((await s.scalars(select(UsageEvent))).all())
    assert [(r.unit, float(r.qty), r.channel) for r in rows] == [("sms_out", 1.0, "sms")]


async def test_the_text_back_conversation_is_linked_to_the_voice_call(ctx, sf):
    from spatalk import jobs
    from spatalk.conversations import get_transcript
    from spatalk.models import Conversation
    session = await _voice_session(ctx, sf)
    await _schedule(ctx, session)
    await jobs.run_once(sf, ctx)
    async with sf() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.channel == "sms"))
    assert conv.external_ref == CALLER and conv.caller == CALLER
    assert conv.external_session == str(session.ref.conversation_id)
    assert conv.last_message_at is not None
    msgs = await get_transcript(sf, conv.id)
    assert [m.role for m in msgs] == ["assistant"]
    assert msgs[0].text.startswith("Hi, this is Skincentrix's assistant.")


async def test_a_reply_to_the_text_back_continues_the_same_conversation(ctx, sf):
    from spatalk import jobs
    from spatalk.brain.driver import FakeLLM, LLMResponse
    from spatalk.models import Conversation
    from spatalk.text.service import TextConversationService
    session = await _voice_session(ctx, sf)
    await _schedule(ctx, session)
    await jobs.run_once(sf, ctx)
    async with sf() as s:
        texted = await s.scalar(select(Conversation).where(Conversation.channel == "sms"))
    svc = TextConversationService(
        ctx, FakeLLM([LLMResponse(text="We open at ten today.", tool_calls=[])])
    )
    result = await svc.handle_inbound(
        tenant_id="skincentrix",
        channel="sms",
        external_id=CALLER,
        sender=CALLER,
        text="What time do you open?",
        provider_message_id="m1",
    )
    assert result.conversation_id == texted.id


# ----- when no text-back is owed -------------------------------------------------------


async def test_a_full_conversation_is_not_texted_back(ctx, sf):
    from spatalk.models import Job
    session = await _voice_session(ctx, sf)
    assert await _schedule(ctx, session, spoke=True, seconds=95.0) is False
    async with sf() as s:
        assert (await s.scalars(select(Job))).all() == []


async def test_a_second_missed_call_within_24_hours_is_not_texted_again(ctx, sf):
    from spatalk import jobs
    session = await _voice_session(ctx, sf)
    await _schedule(ctx, session)
    await jobs.run_once(sf, ctx)
    ctx.clock.advance(hours=23)
    assert await _schedule(ctx, session) is False
    assert len(ctx.sms.sent) == 1


async def test_a_missed_call_a_day_later_is_texted_back_again(ctx, sf):
    from spatalk import jobs
    session = await _voice_session(ctx, sf)
    await _schedule(ctx, session)
    await jobs.run_once(sf, ctx)
    ctx.clock.advance(hours=25)
    assert await _schedule(ctx, session) is True


async def test_a_second_call_before_the_job_runs_does_not_queue_a_second_text(ctx, sf):
    from spatalk.models import Job
    session = await _voice_session(ctx, sf)
    assert await _schedule(ctx, session) is True
    assert await _schedule(ctx, session) is False
    async with sf() as s:
        assert len(list((await s.scalars(select(Job))).all())) == 1


async def test_an_opted_out_caller_is_never_texted_back(ctx, sf):
    from spatalk.models import Job
    from spatalk.text.service import add_optout
    await add_optout(sf, "skincentrix", CALLER)
    session = await _voice_session(ctx, sf)
    assert await _schedule(ctx, session) is False
    async with sf() as s:
        assert (await s.scalars(select(Job))).all() == []


async def test_a_caller_who_opts_out_before_the_job_runs_is_not_texted(ctx, sf):
    from spatalk import jobs
    from spatalk.text.service import add_optout
    session = await _voice_session(ctx, sf)
    assert await _schedule(ctx, session) is True
    await add_optout(sf, "skincentrix", CALLER)
    assert await jobs.run_once(sf, ctx) == 1
    assert ctx.sms.sent == []


async def test_a_caller_id_that_is_the_clinics_public_phone_is_not_texted_back(ctx, sf):
    session = await _voice_session(ctx, sf, caller=CLINIC_PUBLIC_PHONE)
    assert await _schedule(ctx, session) is False


async def test_a_caller_id_that_is_one_of_our_own_numbers_is_not_texted_back(ctx, sf):
    session = await _voice_session(ctx, sf, caller=OUR_VOICE_NUMBER)
    assert await _schedule(ctx, session) is False


async def test_a_call_with_no_caller_id_is_not_texted_back(ctx, sf):
    session = await _voice_session(ctx, sf, caller=None)
    assert await _schedule(ctx, session) is False


async def test_a_tenant_without_an_sms_number_never_texts_back(ctx, sf, registry):
    cfg = await registry.get("skincentrix")
    await registry.import_config(cfg.model_copy(update={"sms_from_number": None}), "test")
    registry.invalidate("skincentrix")
    session = await _voice_session(ctx, sf)
    assert await _schedule(ctx, session) is False


# ----- the pipeline's end-of-call decision ---------------------------------------------


class _StubContext:
    """Stands in for the Pipecat LLMContext: `_finalize` reads nothing but `messages`."""

    def __init__(self, messages):
        self.messages = messages


async def test_the_end_of_a_hangup_call_schedules_the_text_back(ctx, sf):
    from datetime import datetime, timezone

    from spatalk.models import Job
    from spatalk.voice.pipeline import _finalize
    session = await _voice_session(ctx, sf)
    session.started_at = datetime.now(timezone.utc)
    await _finalize(ctx, session, _StubContext([{"role": "assistant", "content": "Hi there."}]))
    async with sf() as s:
        job = (await s.scalars(select(Job).where(Job.kind == "sms.textback"))).one()
    assert job.payload == {
        "tenant_id": "skincentrix",
        "to": CALLER,
        "conversation_id": str(session.ref.conversation_id),
    }


async def test_the_end_of_a_real_conversation_schedules_no_text_back(ctx, sf):
    from datetime import datetime, timedelta, timezone

    from spatalk.models import Job
    from spatalk.voice.pipeline import _finalize
    session = await _voice_session(ctx, sf)
    session.started_at = datetime.now(timezone.utc) - timedelta(minutes=3)
    messages = [
        {"role": "assistant", "content": "Hi there."},
        {"role": "user", "content": "What time do you open?"},
        {"role": "assistant", "content": "We open at ten today."},
    ]
    await _finalize(ctx, session, _StubContext(messages))
    async with sf() as s:
        assert (await s.scalars(select(Job).where(Job.kind == "sms.textback"))).all() == []


async def test_the_text_back_job_payload_is_the_documented_shape(ctx, sf):
    from spatalk.models import Job
    session = await _voice_session(ctx, sf)
    await _schedule(ctx, session)
    async with sf() as s:
        job = (await s.scalars(select(Job))).one()
    assert job.kind == "sms.textback"
    assert set(job.payload) == {"tenant_id", "to", "conversation_id"}
    assert uuid.UUID(job.payload["conversation_id"]) == session.ref.conversation_id
