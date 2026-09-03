"""The SMS staff destination, its delivery job and the digest (sms staff plan, Task S1).

Nothing here reaches Telnyx: every send goes through :class:`MemorySms`, so the from/to
pair, the wording and the segment count are asserted rather than a network trace.
"""

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from loguru import logger
from sqlalchemy import select

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
SMS_FROM = "+18885550100"
STAFF = "+15195550123"
CALLER = "+19055550101"
EDGE_KEY = "edge-shared-key"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def _item(clock, **over):
    base = dict(
        id=7,
        type="callback",
        urgency="normal",
        service_id="facial",
        contact_name="Dana",
        contact_phone=CALLER,
        contact_email=None,
        preferred_window={"date": "any", "part_of_day": "morning"},
        channel="voice",
        due_at=clock.now() + timedelta(hours=3),
        state="open",
        conversation_id=None,
        health_context=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _links():
    from spatalk.ledger.delivery import ActionLinks
    from spatalk.ledger.links import sign_action

    ack = sign_action("s", 7, "ack", "skincentrix")
    res = sign_action("s", 7, "resolve", "skincentrix")
    return ActionLinks("https://a/ack", "https://a/res", "https://api.test/a/tok7", ack, res)


def _settings(**over):
    from spatalk.settings import Settings

    return Settings(
        _env_file=None, public_base_url="https://api.test", secret_key="s", **over
    )


# ----- the destination ---------------------------------------------------------------------


def test_an_sms_destination_needs_an_env_name_never_a_literal_number():
    from spatalk.tenants.schema import Destination

    dest = Destination(kind="sms", address_env="SKINCENTRIX_STAFF_SMS")
    assert dest.address_env == "SKINCENTRIX_STAFF_SMS" and dest.address is None

    with pytest.raises(ValueError):
        Destination(kind="sms")
    with pytest.raises(ValueError):
        Destination(kind="sms", address=STAFF)


def test_the_bundle_carries_an_sms_destination_and_a_messaging_number():
    cfg = _cfg()
    sms = [d for d in cfg.delivery.destinations if d.kind == "sms"]
    assert sms, "skincentrix has no sms destination"
    assert sms[0].address_env == "SKINCENTRIX_STAFF_SMS" and sms[0].address is None
    assert not any(c.isdigit() for c in sms[0].address_env)
    assert cfg.sms_from_number and cfg.sms_from_number.startswith("+1")
    # The whatsapp destination from the earlier plan stays in the bundle, dormant.
    assert [d.kind for d in cfg.delivery.destinations].count("whatsapp") == 1


# ----- the message body --------------------------------------------------------------------


def test_the_staff_sms_carries_the_item_fields_and_the_reply_instruction(fixed_clock):
    from spatalk.ledger.delivery import SMS_STAFF_LIMIT, build_sms_text

    cfg, links = _cfg(), _links()
    text = build_sms_text(_item(fixed_clock), cfg, links, fixed_clock.now())
    assert len(text) <= SMS_STAFF_LIMIT == 459
    assert text.startswith("Skincentrix front desk #7:")
    assert "Callback requested" in text          # the label, never the raw enum
    assert "via voice" in text
    assert "Who: Dana +19055550101" in text
    assert "Due by " in text
    assert "Reply ACK 7 or DONE 7." in text
    assert text.endswith("Transcript: https://api.test/a/tok7")
    assert "health condition" not in text


def test_a_flagged_item_adds_the_health_line_and_an_urgent_one_says_so(fixed_clock):
    from spatalk.ledger.delivery import build_sms_text

    cfg, links = _cfg(), _links()
    flagged = build_sms_text(
        _item(fixed_clock, health_context=True), cfg, links, fixed_clock.now()
    )
    assert "Caller mentioned a health condition; read the transcript first." in flagged

    urgent = build_sms_text(
        _item(fixed_clock, urgency="urgent", due_at=fixed_clock.now() + timedelta(minutes=15)),
        cfg,
        links,
        fixed_clock.now(),
    )
    assert "URGENT" in urgent and "within 15 minutes" in urgent


def test_the_message_drops_the_summary_then_the_health_line_then_the_who_line(fixed_clock):
    """The drop order, re-ordered on 2026-09-03: summary, then health line, then who line.

    It used to be health, who, summary, which made the 154-character sentence outrank both
    the warning that tells the owner how to read the call and the number they call back on.
    Every word of the sentence is on the portal card and in the transcript; neither of the
    other two lines is recoverable from a phone.
    """
    from spatalk.ledger.delivery import SMS_STAFF_LIMIT, build_sms_text

    cfg, links = _cfg(), _links()
    long_name = "Dana " + "Wollaston" * 60
    text = build_sms_text(
        _item(fixed_clock, contact_name=long_name, health_context=True),
        cfg,
        links,
        fixed_clock.now(),
    )
    assert len(text) <= SMS_STAFF_LIMIT
    # Nothing survives a 545-character name but the head, the due line and the link.
    assert "health condition" not in text
    assert "Wollaston" not in text
    assert text.endswith("Transcript: https://api.test/a/tok7")
    assert "Reply ACK 7 or DONE 7." in text

    # A name that fits once the summary and the health line are gone keeps the who line. The
    # padding is measured rather than guessed: a name ten characters short of the limit
    # leaves room for neither the 62-character health line nor anything else.
    bare = build_sms_text(_item(fixed_clock, contact_name="D"), cfg, links, fixed_clock.now())
    padded = "D" * (SMS_STAFF_LIMIT - len(bare) - 10)
    middling = build_sms_text(
        _item(fixed_clock, contact_name=padded, health_context=True),
        cfg,
        links,
        fixed_clock.now(),
    )
    assert len(middling) <= SMS_STAFF_LIMIT
    assert "health condition" not in middling and padded in middling


def test_segment_counting_follows_the_gsm7_and_ucs2_rules():
    from spatalk.ledger.delivery import sms_segments

    assert sms_segments("hello") == 1
    assert sms_segments("a" * 160) == 1
    assert sms_segments("a" * 161) == 2
    assert sms_segments("a" * 306) == 2
    assert sms_segments("a" * 307) == 3
    assert sms_segments("a" * 459) == 3
    # A non-GSM character forces UCS-2, where a segment is 70 then 67 characters.
    assert sms_segments("é" * 70) == 1          # é is in the GSM-7 basic set
    assert sms_segments("—" * 70) == 1     # an em dash is not
    assert sms_segments("—" * 71) == 2


# ----- scheduling --------------------------------------------------------------------------


async def _queued(sf):
    from spatalk.models import Job

    async with sf() as s:
        return [(j.kind, j.payload) for j in (await s.scalars(select(Job).order_by(Job.id))).all()]


def _two_sms_config(cfg):
    from spatalk.tenants.schema import Delivery, Destination

    return cfg.model_copy(
        update={
            "delivery": Delivery(
                destinations=[
                    Destination(kind="sms", address_env="SMS_ONE"),
                    Destination(kind="sms", address_env="SMS_TWO", urgent_only=True),
                ]
            )
        }
    )


async def test_scheduling_enqueues_one_job_per_sms_destination(sf, registry, fixed_clock):
    from spatalk.ledger.delivery import schedule_item_delivery

    cfg = _two_sms_config(await registry.get("skincentrix"))
    await schedule_item_delivery(sf, _item(fixed_clock), cfg)
    queued = await _queued(sf)
    assert [k for k, _ in queued] == ["deliver.sms"]
    assert queued[0][1] == {
        "item_id": 7,
        "tenant_id": "skincentrix",
        "to_env": "SMS_ONE",
        "escalation": False,
    }


async def test_urgent_and_escalated_items_reach_every_sms_destination(sf, registry, fixed_clock):
    from spatalk.ledger.delivery import schedule_item_delivery

    cfg = _two_sms_config(await registry.get("skincentrix"))
    await schedule_item_delivery(sf, _item(fixed_clock, urgency="urgent"), cfg)
    assert [p["to_env"] for k, p in await _queued(sf) if k == "deliver.sms"] == [
        "SMS_ONE",
        "SMS_TWO",
    ]

    await schedule_item_delivery(sf, _item(fixed_clock, id=8), cfg, escalation=True)
    escalated = [p for k, p in await _queued(sf) if k == "deliver.sms" and p["item_id"] == 8]
    assert [p["to_env"] for p in escalated] == ["SMS_ONE", "SMS_TWO"]
    assert all(p["escalation"] for p in escalated)


# ----- the job -----------------------------------------------------------------------------


async def _real_item(sf, registry, fixed_clock, urgency="normal", **draft):
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.items import PgLedger

    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c-sms", CALLER)
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice", caller_phone=CALLER)
    rec = await ledger.create_item(
        ref,
        ItemDraft(
            type="callback",
            urgency=urgency,
            contact=ContactInfo(name="Dana", phone=CALLER),
            **draft,
        ),
    )
    return ledger, rec


def _ctx(sf, registry, ledger, fixed_clock, sms=None, delivery=None):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryDelivery

    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=ledger,
        delivery=delivery or MemoryDelivery(),
        settings=_settings(),
        sms=sms or MemorySms(),
    )


async def _with_sms_number(registry, number=SMS_FROM):
    cfg = await registry.get("skincentrix")
    await registry.import_config(cfg.model_copy(update={"sms_from_number": number}), "test")
    registry.invalidate("skincentrix")
    return await registry.get("skincentrix")


async def _enqueue_sms(sf, item_id, escalation=False, to_env="SKINCENTRIX_STAFF_SMS"):
    from spatalk import jobs

    return await jobs.enqueue(
        sf,
        "deliver.sms",
        {
            "item_id": item_id,
            "tenant_id": "skincentrix",
            "to_env": to_env,
            "escalation": escalation,
        },
    )


async def test_the_job_texts_the_staff_number_from_the_tenant_number(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.models import UsageEvent

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    await _with_sms_number(registry)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    sms = MemorySms()
    await _enqueue_sms(sf, rec.id)
    assert await jobs.run_once(sf, _ctx(sf, registry, ledger, fixed_clock, sms=sms)) == 1

    assert len(sms.sent) == 1
    from_number, to, text = sms.sent[0]
    assert (from_number, to) == (SMS_FROM, STAFF)
    assert f"#{rec.id}" in text and "Dana" in text
    assert f"Reply ACK {rec.id} or DONE {rec.id}." in text
    assert "https://api.test/a/" in text

    async with sf() as s:
        rows = list((await s.scalars(select(UsageEvent).where(UsageEvent.unit == "sms_out"))).all())
    assert len(rows) == 1
    assert rows[0].tenant_id == "skincentrix" and rows[0].channel == "sms"
    from spatalk.ledger.delivery import sms_segments

    assert float(rows[0].qty) == float(sms_segments(text)) > 1.0


async def test_an_escalated_item_says_so_at_the_front_of_the_message(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    await _with_sms_number(registry)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    sms = MemorySms()
    await _enqueue_sms(sf, rec.id, escalation=True)
    await jobs.run_once(sf, _ctx(sf, registry, ledger, fixed_clock, sms=sms))
    assert sms.sent[0][2].startswith("ESCALATED, past due: ")


async def test_an_unset_number_env_warns_and_sends_nothing(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.models import Job

    monkeypatch.delenv("SKINCENTRIX_STAFF_SMS", raising=False)
    await _with_sms_number(registry)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    sms = MemorySms()
    job_id = await _enqueue_sms(sf, rec.id)
    warnings: list[str] = []
    handle = logger.add(warnings.append, level="WARNING")
    try:
        assert await jobs.run_once(sf, _ctx(sf, registry, ledger, fixed_clock, sms=sms)) == 1
    finally:
        logger.remove(handle)

    assert sms.sent == []
    assert any("SKINCENTRIX_STAFF_SMS" in line for line in warnings)
    async with sf() as s:
        assert (await s.get(Job, job_id)).state == "done"


async def test_an_opted_out_staff_number_is_skipped_and_the_email_still_goes(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryDelivery, schedule_item_delivery
    from spatalk.tenants.schema import Delivery, Destination
    from spatalk.text.service import add_optout

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    cfg = await _with_sms_number(registry)
    cfg = cfg.model_copy(
        update={
            "delivery": Delivery(
                destinations=[
                    Destination(kind="email", address="info@skincentrix.com"),
                    Destination(kind="sms", address_env="SKINCENTRIX_STAFF_SMS"),
                ]
            )
        }
    )
    await add_optout(sf, "skincentrix", STAFF)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    await schedule_item_delivery(sf, rec, cfg)

    sms, delivery = MemorySms(), MemoryDelivery()
    warnings: list[str] = []
    handle = logger.add(warnings.append, level="WARNING")
    try:
        assert await jobs.run_once(
            sf, _ctx(sf, registry, ledger, fixed_clock, sms=sms, delivery=delivery)
        ) == 2
    finally:
        logger.remove(handle)

    assert sms.sent == []
    assert any("opted out" in line for line in warnings)
    assert len(delivery.emails) == 1 and delivery.emails[0][0] == "info@skincentrix.com"


async def test_a_tenant_without_a_messaging_number_fails_loudly_and_dead_letters(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.models import Job

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    await _with_sms_number(registry, number=None)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    sms = MemorySms()
    job_id = await _enqueue_sms(sf, rec.id)

    # First attempt: the job fails and is queued again, so the failure is visible.
    await jobs.run_once(sf, _ctx(sf, registry, ledger, fixed_clock, sms=sms))
    async with sf() as s:
        job = await s.get(Job, job_id)
        assert job.state == "queued" and job.attempts == 1
        assert "sms_from_number" in job.last_error

    # It never silently succeeds: with the attempts spent it lands in the dead letters.
    async with sf() as s, s.begin():
        job = await s.get(Job, job_id)
        job.max_attempts, job.run_at = 2, fixed_clock.now()
    await jobs.run_once(sf, _ctx(sf, registry, ledger, fixed_clock, sms=sms))
    async with sf() as s:
        assert (await s.get(Job, job_id)).state == "dead"
    assert sms.sent == []


# ----- the digest --------------------------------------------------------------------------


async def test_the_digest_texts_a_count_and_the_list_invitation(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryDelivery

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    monkeypatch.setenv("SKINCENTRIX_WHATSAPP_STAFF", "")
    await _with_sms_number(registry)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    sms, delivery = MemorySms(), MemoryDelivery()
    await jobs.enqueue(sf, "digest.email", {"tenant_id": "skincentrix"})
    await jobs.run_once(sf, _ctx(sf, registry, ledger, fixed_clock, sms=sms, delivery=delivery))

    assert len(delivery.emails) == 1
    assert len(sms.sent) == 1
    from_number, to, text = sms.sent[0]
    assert (from_number, to) == (SMS_FROM, STAFF)
    assert text == "Skincentrix front desk: 1 open item(s). Reply LIST for details."
    assert rec.id == 1


async def test_the_open_item_list_is_five_lines_of_ids_at_most(sf, registry, fixed_clock):
    from spatalk.ledger.delivery import SMS_STAFF_LIMIT, build_list_sms

    cfg = await registry.get("skincentrix")
    ledger, _ = await _real_item(sf, registry, fixed_clock)
    for _ in range(6):
        await _real_item(sf, registry, fixed_clock)
    items = await ledger.list_open("skincentrix")
    assert len(items) == 7

    text = build_list_sms(items, cfg, fixed_clock.now())
    assert len(text) <= SMS_STAFF_LIMIT
    body = text.splitlines()
    assert body[0] == "Skincentrix front desk: 7 open item(s)."
    assert len(body) == 6                       # the header and five items
    assert all(line.startswith("#") for line in body[1:])
    assert "Callback requested" in body[1] and "Dana" in body[1]

    assert build_list_sms([], cfg, fixed_clock.now()) == (
        "Skincentrix front desk: 0 open item(s)."
    )


# ----- the LIST reply through the real route ------------------------------------------------


def _event(text, msg_id="msg-1", to=SMS_FROM, sender=STAFF):
    return {
        "data": {
            "event_type": "message.received",
            "id": "evt-1",
            "occurred_at": "2026-09-01T18:00:00.000Z",
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


@pytest.fixture
async def staff_client(sf, registry, fixed_clock, monkeypatch):
    from spatalk import jobs
    from spatalk.brain.driver import FakeLLM, LLMResponse
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    await _with_sms_number(registry)
    await registry.add_number(SMS_FROM, "skincentrix", "sms")
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=_settings(edge_shared_key=EDGE_KEY),
        sms=MemorySms(),
        llm=FakeLLM([LLMResponse(text="We open at ten.", tool_calls=[])]),
    )
    app = create_app(ctx, start_background=False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        yield client, ctx


async def _post(client, body):
    return await client.post(
        "/telnyx/sms",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "X-Edge-Key": EDGE_KEY},
    )


async def test_a_staff_number_replying_list_gets_the_open_items(
    staff_client, sf, registry, fixed_clock
):
    client, ctx = staff_client
    _, rec = await _real_item(sf, registry, fixed_clock)

    r = await _post(client, _event("LIST"))
    assert r.status_code == 200 and r.json()["handled"] == "staff_list"
    assert len(ctx.sms.sent) == 1
    from_number, to, text = ctx.sms.sent[0]
    assert (from_number, to) == (SMS_FROM, STAFF)
    assert text.startswith("Skincentrix front desk: 1 open item(s).")
    assert f"#{rec.id}" in text


async def test_list_from_an_unknown_number_is_an_ordinary_customer_message(
    staff_client, sf, registry, fixed_clock
):
    from spatalk.models import Conversation

    client, ctx = staff_client
    await _real_item(sf, registry, fixed_clock)

    r = await _post(client, _event("list", sender=CALLER))
    assert r.status_code == 200 and "conversation_id" in r.json()
    async with sf() as s:
        rows = list((await s.scalars(select(Conversation).where(Conversation.caller == CALLER))).all())
    assert any(c.channel == "sms" for c in rows)
    assert all("open item(s)" not in text for _, _, text in ctx.sms.sent)
