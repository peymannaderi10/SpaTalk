"""SMS flood guard (plan F, Task F1).

Every route test goes through the real ``POST /telnyx/sms`` with the edge key, a
:class:`MemorySms` and a :class:`FakeLLM`, because the thing under test is the branch that
decides whether a text costs a model call and an outbound segment. The promises: one number
cannot run the bill past a small, known amount; a whole tenant's day has a ceiling; every
suppressed text is still on its conversation; STOP and HELP still work; staff are exempt.
"""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
SMS_FROM = "+18885550100"
STAFF = "+15195550123"
CALLER = "+19055550101"
OTHER = "+19055550102"
THIRD = "+19055550103"
EDGE_KEY = "edge-shared-key"


def _event(text, msg_id, sender=CALLER, to=SMS_FROM):
    return {
        "data": {
            "event_type": "message.received",
            "id": f"evt-{msg_id}",
            "payload": {
                "id": msg_id,
                "direction": "inbound",
                "type": "SMS",
                "text": text,
                "from": {"phone_number": sender},
                "to": [{"phone_number": to, "status": "webhook_delivered"}],
            },
        }
    }


async def _post(client, body):
    return await client.post(
        "/telnyx/sms",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "X-Edge-Key": EDGE_KEY},
    )


async def _guard(registry, **guard):
    """Skincentrix with a messaging number and the given flood-guard settings."""
    from spatalk.tenants.schema import SmsGuard

    cfg = await registry.get("skincentrix")
    cfg = cfg.model_copy(update={"sms_from_number": SMS_FROM, "sms_guard": SmsGuard(**guard)})
    await registry.import_config(cfg, "test")
    registry.invalidate("skincentrix")
    return await registry.get("skincentrix")


async def _blocks(sf):
    from spatalk.models import SmsBlock

    async with sf() as s:
        return list((await s.scalars(select(SmsBlock))).all())


async def _alert_keys(sf):
    from spatalk.models import AlertLog

    async with sf() as s:
        return sorted((await s.scalars(select(AlertLog.key))).all())


async def _user_texts(sf, sender):
    from spatalk.models import Conversation, Message

    async with sf() as s:
        rows = await s.scalars(
            select(Message.text)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.caller == sender, Message.role == "user")
            .order_by(Message.id)
        )
        return list(rows.all())


@pytest.fixture
async def flood(sf, registry, fixed_clock, monkeypatch):
    from spatalk import jobs
    from spatalk.brain.driver import FakeLLM, LLMResponse
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    await registry.add_number(SMS_FROM, "skincentrix", "sms")
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=Settings(
            _env_file=None,
            public_base_url="https://api.test",
            secret_key="s",
            edge_shared_key=EDGE_KEY,
        ),
        sms=MemorySms(),
        llm=FakeLLM([LLMResponse(text="We open at ten.", tool_calls=[])] * 200),
    )
    app = create_app(ctx, start_background=False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        yield client, ctx


# ----- settings and scripts --------------------------------------------------------------


def test_sms_guard_defaults_and_rejects_zero_limits():
    from pydantic import ValidationError

    from spatalk.tenants.schema import SmsGuard

    g = SmsGuard()
    assert (g.burst_limit, g.burst_window_minutes, g.daily_limit, g.mute_hours) == (12, 10, 40, 24)
    assert g.tenant_daily_replies == 400
    with pytest.raises(ValidationError):
        SmsGuard(burst_limit=0)
    with pytest.raises(ValidationError):
        SmsGuard(tenant_daily_replies=0)


def test_the_bundle_carries_the_guard_and_a_paused_script_that_promises_no_reply_time():
    from spatalk.tenants.bundle import load_bundle
    from spatalk.tenants.schema import SmsGuard

    cfg = load_bundle(BUNDLE)
    assert cfg.sms_guard == SmsGuard()
    assert "{confirm_by}" not in cfg.scripts.sms_paused
    assert "{phone}" in cfg.scripts.sms_paused and "paused" in cfg.scripts.sms_paused


# ----- one number ------------------------------------------------------------------------


async def test_the_thirteenth_text_in_ten_minutes_is_stored_unanswered_and_mutes_the_number(
    flood, sf, registry, fixed_clock
):
    client, ctx = flood
    await _guard(registry)
    for i in range(12):
        r = await _post(client, _event(f"hello {i}", f"m{i}"))
        assert r.status_code == 200 and "conversation_id" in r.json()
        fixed_clock.advance(seconds=20)
    assert len(ctx.sms.sent) == 12 and len(ctx.llm.calls) == 12

    r = await _post(client, _event("hello 12", "m12"))
    assert r.json() == {"ok": True, "suppressed": "muted"}
    assert len(ctx.sms.sent) == 12 and len(ctx.llm.calls) == 12, "a muted text cost money"

    blocks = await _blocks(sf)
    assert len(blocks) == 1
    assert (blocks[0].phone, blocks[0].reason) == (CALLER, "flood")
    assert blocks[0].until == fixed_clock.now() + timedelta(hours=24)
    assert await _alert_keys(sf) == [f"sms.flood:skincentrix:{CALLER}"]
    assert (await _user_texts(sf, CALLER))[-1] == "hello 12", "the suppressed text left the record"


async def test_a_muted_number_still_gets_the_carrier_keywords_and_nothing_else(
    flood, sf, registry, fixed_clock
):
    client, ctx = flood
    await _guard(registry, burst_limit=1)
    await _post(client, _event("hi", "k1"))
    fixed_clock.advance(seconds=5)
    r = await _post(client, _event("hi again", "k2"))
    assert r.json()["suppressed"] == "muted"
    before = len(ctx.sms.sent)

    r = await _post(client, _event("HELP", "k3"))
    assert r.json()["handled"] == "keyword" and len(ctx.sms.sent) == before + 1
    r = await _post(client, _event("hello?", "k4"))
    assert r.json()["suppressed"] == "muted" and len(ctx.sms.sent) == before + 1
    r = await _post(client, _event("STOP", "k5"))
    assert r.json()["handled"] == "keyword" and len(ctx.sms.sent) == before + 2
    assert len(ctx.llm.calls) == 1


async def test_the_daily_limit_rolls_over_at_the_tenants_midnight_not_utc(
    flood, sf, registry, fixed_clock
):
    client, ctx = flood
    # The fixed clock is Tuesday 2026-09-01 18:00 UTC, 14:00 in Toronto.
    await _guard(registry, burst_limit=100, daily_limit=3, mute_hours=1)
    for i in range(3):
        r = await _post(client, _event(f"day {i}", f"d{i}"))
        assert "conversation_id" in r.json()
        fixed_clock.advance(minutes=15)
    r = await _post(client, _event("day 3", "d3"))            # 18:45 UTC, the fourth today
    assert r.json()["suppressed"] == "muted"

    fixed_clock.advance(hours=8, minutes=15)                   # 2026-09-02 03:00 UTC = 23:00 Toronto
    r = await _post(client, _event("still today", "d4"))
    assert r.json()["suppressed"] == "muted", "UTC midnight passed but the Toronto day has not"

    fixed_clock.advance(hours=1, minutes=5)                    # 04:05 UTC = 00:05 Toronto
    r = await _post(client, _event("new day", "d5"))
    assert "conversation_id" in r.json() and ctx.sms.sent[-1][2] == "We open at ten."


async def test_a_permanent_block_never_expires_and_never_answers(flood, sf, registry, fixed_clock):
    from spatalk.text.flood import block

    client, ctx = flood
    cfg = await _guard(registry)
    await block(ctx, cfg, OTHER, created_by="cli:test")

    r = await _post(client, _event("hello", "b1", sender=OTHER))
    assert r.json() == {"ok": True, "suppressed": "blocked"}
    fixed_clock.advance(days=40)
    r = await _post(client, _event("hello again", "b2", sender=OTHER))
    assert r.json() == {"ok": True, "suppressed": "blocked"}
    assert ctx.sms.sent == [] and ctx.llm.calls == []
    assert await _user_texts(sf, OTHER) == ["hello", "hello again"]
    assert len(await _blocks(sf)) == 1 and (await _blocks(sf))[0].until is None


# ----- the whole tenant ------------------------------------------------------------------


async def test_the_tenant_daily_ceiling_pauses_the_assistant_with_one_fixed_text_per_sender(
    flood, sf, registry, fixed_clock
):
    client, ctx = flood
    cfg = await _guard(registry, tenant_daily_replies=3)
    for i in range(3):
        await _post(client, _event(f"q {i}", f"c{i}"))
        fixed_clock.advance(minutes=1)
    assert len(ctx.sms.sent) == 3

    r = await _post(client, _event("anyone there?", "c3", sender=OTHER))
    assert r.json()["suppressed"] == "capped"
    assert len(ctx.sms.sent) == 4 and ctx.sms.sent[-1][1] == OTHER
    paused = ctx.sms.sent[-1][2]
    assert "paused" in paused and cfg.public_phone in paused and "will reply" not in paused

    r = await _post(client, _event("hello??", "c4", sender=OTHER))
    assert r.json()["suppressed"] == "capped" and len(ctx.sms.sent) == 4
    r = await _post(client, _event("hi", "c5", sender=THIRD))
    assert r.json()["suppressed"] == "capped" and len(ctx.sms.sent) == 5
    assert len(ctx.llm.calls) == 3, "a capped text reached the model"
    assert [k for k in await _alert_keys(sf) if k.startswith("sms.daily_cap:")] == [
        "sms.daily_cap:skincentrix:2026-09-01"
    ]
    assert (await _user_texts(sf, OTHER)) == ["anyone there?", "hello??"]

    fixed_clock.advance(hours=11)                              # 05:00 UTC = 01:00 Toronto, a new day
    r = await _post(client, _event("morning", "c6"))
    assert "conversation_id" in r.json() and len(ctx.sms.sent) == 6


async def test_staff_numbers_are_never_muted_or_capped(flood, sf, registry, fixed_clock):
    client, ctx = flood
    await _guard(registry, burst_limit=1, tenant_daily_replies=1)
    for i in range(5):
        r = await _post(client, _event("list", f"s{i}", sender=STAFF))
        assert r.json()["handled"] == "staff_list"
    assert await _blocks(sf) == [] and ctx.llm.calls == []
