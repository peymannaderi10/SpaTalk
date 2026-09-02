"""WhatsApp destination, delivery and reply buttons (whatsapp plan, Task W1).

Nothing here touches Meta: the transport is either :class:`MemoryDelivery` or a
:class:`FakeGraphClient`, so the payload shape is asserted, never a network trace.
"""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger
from sqlalchemy import select

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
PHONE_ID = "1099999999"
STAFF = "+15195550123"


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
        contact_phone="+19055550101",
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
    return ActionLinks("https://a/ack", "https://a/res", "https://a/t/7", ack, res)


def _settings(**over):
    from spatalk.settings import Settings

    return Settings(
        _env_file=None,
        public_base_url="https://api.test",
        secret_key="s",
        whatsapp_phone_number_id=PHONE_ID,
        whatsapp_access_token="tok",
        **over,
    )


# ----- the destination ---------------------------------------------------------------------


def test_whatsapp_destination_needs_an_env_name_and_email_takes_either():
    from spatalk.tenants.schema import Destination

    dest = Destination(kind="whatsapp", address_env="SKINCENTRIX_WHATSAPP_STAFF")
    assert dest.address_env == "SKINCENTRIX_WHATSAPP_STAFF" and dest.address is None

    with pytest.raises(ValueError):
        Destination(kind="whatsapp")
    with pytest.raises(ValueError):
        Destination(kind="whatsapp", address="+15195550123")

    assert Destination(kind="email", address="info@x.test").address == "info@x.test"
    assert Destination(kind="email", address_env="OWNER_EMAIL").address_env == "OWNER_EMAIL"
    with pytest.raises(ValueError):
        Destination(kind="email")


# ----- the message body --------------------------------------------------------------------


def test_whatsapp_text_carries_the_item_fields_and_stays_under_the_limit(fixed_clock):
    from spatalk.ledger.delivery import WHATSAPP_BODY_LIMIT, build_whatsapp_text

    cfg, links = _cfg(), _links()
    text = build_whatsapp_text(_item(fixed_clock), cfg, links, fixed_clock.now())
    assert len(text) <= WHATSAPP_BODY_LIMIT == 1024
    assert "#7" in text
    assert "Callback requested" in text          # the type label, not the raw enum
    assert "Dana" in text and "+19055550101" in text
    assert "by " in text                          # due wording from humanize_due
    assert "https://a/t/7" in text
    assert "health condition" not in text

    flagged = build_whatsapp_text(
        _item(fixed_clock, health_context=True), cfg, links, fixed_clock.now()
    )
    assert "health condition" in flagged and "read the transcript" in flagged


def test_whatsapp_text_is_truncated_rather_than_overflowing(fixed_clock):
    from spatalk.ledger.delivery import WHATSAPP_BODY_LIMIT, build_whatsapp_text

    item = _item(fixed_clock, contact_name="D" * 4000)
    text = build_whatsapp_text(item, _cfg(), _links(), fixed_clock.now())
    assert len(text) == WHATSAPP_BODY_LIMIT


def test_urgent_text_says_so_and_uses_the_urgent_due_wording(fixed_clock):
    from spatalk.ledger.delivery import build_whatsapp_text

    item = _item(fixed_clock, urgency="urgent", due_at=fixed_clock.now() + timedelta(minutes=15))
    text = build_whatsapp_text(item, _cfg(), _links(), fixed_clock.now())
    assert "URGENT" in text and "within 15 minutes" in text


# ----- the buttons -------------------------------------------------------------------------


def test_buttons_carry_signed_tokens_and_titles_whatsapp_accepts(fixed_clock):
    from spatalk.ledger.delivery import build_whatsapp_buttons
    from spatalk.ledger.links import verify_action

    links = _links()
    buttons = build_whatsapp_buttons(_item(fixed_clock), links)
    assert [title for _, title in buttons] == ["Acknowledge", "Resolve"]
    ids = [bid for bid, _ in buttons]
    assert ids == [f"ack:{links.ack_token}", f"resolve:{links.resolve_token}"]
    assert all(len(title) <= 20 for _, title in buttons)
    assert all(len(bid) <= 256 for bid in ids)

    claims = [verify_action("s", bid.split(":", 1)[1]) for bid in ids]
    assert [c.action for c in claims] == ["ack", "resolve"]
    assert {c.item_id for c in claims} == {7}
    assert {c.tenant_id for c in claims} == {"skincentrix"}


# ----- the transport -----------------------------------------------------------------------


async def test_whatsapp_delivery_posts_the_cloud_api_payloads():
    from spatalk.ledger.delivery import WhatsAppDelivery
    from spatalk.social.graph import FakeGraphClient

    graph = FakeGraphClient({f"POST /{PHONE_ID}/messages": [
        {"messages": [{"id": "wamid.1"}]},
        {"messages": [{"id": "wamid.2"}]},
        {"messages": [{"id": "wamid.3"}]},
    ]})
    wa = WhatsAppDelivery(_settings(), graph)

    assert await wa.send_text(STAFF, "hello") == "wamid.1"
    body = graph.calls[0].json
    assert body["messaging_product"] == "whatsapp" and body["to"] == STAFF
    assert body["type"] == "text" and body["text"]["body"] == "hello"

    assert await wa.send_buttons(STAFF, "pick", [("ack:t1", "Acknowledge")]) == "wamid.2"
    body = graph.calls[1].json
    assert body["type"] == "interactive"
    assert body["interactive"]["type"] == "button"
    assert body["interactive"]["body"]["text"] == "pick"
    assert body["interactive"]["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "ack:t1", "title": "Acknowledge"}}
    ]

    assert await wa.send_template(STAFF, "front_desk_item", "en", ["a", "b"], ["p0"]) == "wamid.3"
    body = graph.calls[2].json
    assert body["type"] == "template"
    assert body["template"]["name"] == "front_desk_item"
    assert body["template"]["language"] == {"code": "en"}
    components = body["template"]["components"]
    assert components[0] == {
        "type": "body",
        "parameters": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
    }
    assert components[1] == {
        "type": "button",
        "sub_type": "quick_reply",
        "index": "0",
        "parameters": [{"type": "payload", "payload": "p0"}],
    }
    assert graph.calls[0].path == f"/{PHONE_ID}/messages"


async def test_whatsapp_delivery_refuses_more_than_three_buttons_or_a_long_title():
    from spatalk.ledger.delivery import WhatsAppDelivery
    from spatalk.social.graph import FakeGraphClient

    wa = WhatsAppDelivery(_settings(), FakeGraphClient())
    with pytest.raises(ValueError):
        await wa.send_buttons(STAFF, "x", [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")])
    with pytest.raises(ValueError):
        await wa.send_buttons(STAFF, "x", [("a", "A" * 21)])


# ----- scheduling --------------------------------------------------------------------------


async def _queued(sf):
    from spatalk.models import Job

    async with sf() as s:
        return [(j.kind, j.payload) for j in (await s.scalars(select(Job).order_by(Job.id))).all()]


def _two_whatsapp_config(cfg):
    from spatalk.tenants.schema import Delivery, Destination

    return cfg.model_copy(
        update={
            "delivery": Delivery(
                destinations=[
                    Destination(kind="whatsapp", address_env="WA_ONE"),
                    Destination(kind="whatsapp", address_env="WA_TWO", urgent_only=True),
                ]
            )
        }
    )


async def test_scheduling_enqueues_one_job_per_whatsapp_destination(sf, registry, fixed_clock):
    from spatalk.ledger.delivery import schedule_item_delivery

    cfg = _two_whatsapp_config(await registry.get("skincentrix"))
    await schedule_item_delivery(sf, _item(fixed_clock), cfg)
    queued = await _queued(sf)
    assert [k for k, _ in queued] == ["deliver.whatsapp"]
    assert queued[0][1] == {
        "item_id": 7,
        "tenant_id": "skincentrix",
        "to_env": "WA_ONE",
        "escalation": False,
    }


async def test_urgent_and_escalated_items_reach_every_whatsapp_destination(
    sf, registry, fixed_clock
):
    from spatalk.ledger.delivery import schedule_item_delivery

    cfg = _two_whatsapp_config(await registry.get("skincentrix"))
    await schedule_item_delivery(sf, _item(fixed_clock, urgency="urgent"), cfg)
    urgent = [p["to_env"] for k, p in await _queued(sf) if k == "deliver.whatsapp"]
    assert urgent == ["WA_ONE", "WA_TWO"]

    await schedule_item_delivery(sf, _item(fixed_clock, id=8), cfg, escalation=True)
    escalated = [
        p["to_env"] for k, p in await _queued(sf) if k == "deliver.whatsapp" and p["item_id"] == 8
    ]
    assert escalated == ["WA_ONE", "WA_TWO"]
    assert all(
        p["escalation"] for k, p in await _queued(sf)
        if k == "deliver.whatsapp" and p["item_id"] == 8
    )


# ----- the job -----------------------------------------------------------------------------


async def _real_item(sf, registry, fixed_clock, urgency="normal"):
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.items import PgLedger

    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c-wa", "+19055550101")
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(
        conversation_id=cid, tenant=cfg, channel="voice", caller_phone="+19055550101"
    )
    rec = await ledger.create_item(
        ref,
        ItemDraft(
            type="callback",
            urgency=urgency,
            contact=ContactInfo(name="Dana", phone="+19055550101"),
        ),
    )
    return ledger, rec


def _ctx(sf, registry, ledger, delivery, fixed_clock, settings=None):
    from spatalk import jobs

    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=ledger,
        delivery=delivery,
        settings=settings or _settings(),
    )


async def _open_the_window(sf, fixed_clock, phone, hours_ago=1):
    from spatalk.models import WhatsAppWindow

    async with sf() as s, s.begin():
        s.add(
            WhatsAppWindow(
                tenant_id="skincentrix",
                phone=phone,
                last_inbound_at=fixed_clock.now() - timedelta(hours=hours_ago),
            )
        )


async def test_the_job_sends_buttons_while_the_window_is_open(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.links import verify_action

    monkeypatch.setenv("SKINCENTRIX_WHATSAPP_STAFF", STAFF)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    await _open_the_window(sf, fixed_clock, STAFF)
    delivery = MemoryDelivery()
    await jobs.enqueue(
        sf,
        "deliver.whatsapp",
        {
            "item_id": rec.id,
            "tenant_id": "skincentrix",
            "to_env": "SKINCENTRIX_WHATSAPP_STAFF",
            "escalation": False,
        },
    )
    ctx = _ctx(sf, registry, ledger, delivery, fixed_clock)
    assert await jobs.run_once(sf, ctx) == 1

    assert delivery.whatsapp_templates == []
    assert len(delivery.whatsapp) == 1
    to, body, buttons = delivery.whatsapp[0]
    assert to == STAFF
    assert "Dana" in body and f"#{rec.id}" in body and "https://api.test/a/" in body
    assert [title for _, title in buttons] == ["Acknowledge", "Resolve"]
    claim = verify_action("s", buttons[0][0].split(":", 1)[1])
    assert (claim.item_id, claim.action, claim.tenant_id) == (rec.id, "ack", "skincentrix")


async def test_the_job_sends_the_template_when_the_window_is_shut(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery

    monkeypatch.setenv("SKINCENTRIX_WHATSAPP_STAFF", STAFF)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    await _open_the_window(sf, fixed_clock, STAFF, hours_ago=30)  # stale: outside 24 h
    delivery = MemoryDelivery()
    await jobs.enqueue(
        sf,
        "deliver.whatsapp",
        {
            "item_id": rec.id,
            "tenant_id": "skincentrix",
            "to_env": "SKINCENTRIX_WHATSAPP_STAFF",
            "escalation": False,
        },
    )
    ctx = _ctx(sf, registry, ledger, delivery, fixed_clock)
    assert await jobs.run_once(sf, ctx) == 1

    assert len(delivery.whatsapp_templates) == 1
    sent = delivery.whatsapp_templates[0]
    assert sent["to"] == STAFF
    assert sent["template"] == "front_desk_item" and sent["lang"] == "en"
    assert len(sent["body_params"]) == 5
    assert sent["body_params"][0] == "Callback requested"
    assert sent["body_params"][1] == "voice"
    assert "Dana" in sent["body_params"][2]
    assert sent["body_params"][4].startswith("https://api.test/a/")
    assert all("\n" not in p and "\t" not in p for p in sent["body_params"])
    assert [p.split(":", 1)[0] for p in sent["button_params"]] == ["ack", "resolve"]


async def test_the_job_records_a_wa_out_usage_row(sf, registry, fixed_clock, monkeypatch):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.models import UsageEvent

    monkeypatch.setenv("SKINCENTRIX_WHATSAPP_STAFF", STAFF)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    await _open_the_window(sf, fixed_clock, STAFF)
    await jobs.enqueue(
        sf,
        "deliver.whatsapp",
        {
            "item_id": rec.id,
            "tenant_id": "skincentrix",
            "to_env": "SKINCENTRIX_WHATSAPP_STAFF",
            "escalation": False,
        },
    )
    await jobs.run_once(sf, _ctx(sf, registry, ledger, MemoryDelivery(), fixed_clock))

    async with sf() as s:
        rows = list((await s.scalars(select(UsageEvent).where(UsageEvent.unit == "wa_out"))).all())
    assert len(rows) == 1
    assert rows[0].tenant_id == "skincentrix" and rows[0].channel == "whatsapp"
    assert float(rows[0].qty) == 1.0


async def test_a_missing_number_env_warns_and_sends_nothing(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.models import Job

    monkeypatch.delenv("SKINCENTRIX_WHATSAPP_STAFF", raising=False)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    delivery = MemoryDelivery()
    job_id = await jobs.enqueue(
        sf,
        "deliver.whatsapp",
        {
            "item_id": rec.id,
            "tenant_id": "skincentrix",
            "to_env": "SKINCENTRIX_WHATSAPP_STAFF",
            "escalation": False,
        },
    )
    warnings: list[str] = []
    handle = logger.add(warnings.append, level="WARNING")
    try:
        assert await jobs.run_once(sf, _ctx(sf, registry, ledger, delivery, fixed_clock)) == 1
    finally:
        logger.remove(handle)

    assert delivery.whatsapp == [] and delivery.whatsapp_templates == []
    assert any("SKINCENTRIX_WHATSAPP_STAFF" in line for line in warnings)
    async with sf() as s:
        assert (await s.get(Job, job_id)).state == "done"


async def test_an_escalated_item_says_so_in_the_whatsapp_message(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery

    monkeypatch.setenv("SKINCENTRIX_WHATSAPP_STAFF", STAFF)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    await _open_the_window(sf, fixed_clock, STAFF)
    delivery = MemoryDelivery()
    await jobs.enqueue(
        sf,
        "deliver.whatsapp",
        {
            "item_id": rec.id,
            "tenant_id": "skincentrix",
            "to_env": "SKINCENTRIX_WHATSAPP_STAFF",
            "escalation": True,
        },
    )
    await jobs.run_once(sf, _ctx(sf, registry, ledger, delivery, fixed_clock))
    assert "ESCALATED, past due" in delivery.whatsapp[0][1]


# ----- the digest --------------------------------------------------------------------------


async def test_the_digest_also_goes_to_whatsapp(sf, registry, fixed_clock, monkeypatch):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery

    monkeypatch.setenv("SKINCENTRIX_WHATSAPP_STAFF", STAFF)
    ledger, rec = await _real_item(sf, registry, fixed_clock)
    await _open_the_window(sf, fixed_clock, STAFF)
    delivery = MemoryDelivery()
    await jobs.enqueue(sf, "digest.email", {"tenant_id": "skincentrix"})
    await jobs.run_once(sf, _ctx(sf, registry, ledger, delivery, fixed_clock))

    assert len(delivery.emails) == 1
    assert len(delivery.whatsapp) == 1
    to, body, buttons = delivery.whatsapp[0]
    assert to == STAFF and buttons == []
    assert f"#{rec.id}" in body and "open front-desk item" in body


async def test_the_digest_uses_its_template_outside_the_window(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery

    monkeypatch.setenv("SKINCENTRIX_WHATSAPP_STAFF", STAFF)
    ledger, _ = await _real_item(sf, registry, fixed_clock)
    delivery = MemoryDelivery()
    await jobs.enqueue(sf, "digest.email", {"tenant_id": "skincentrix"})
    await jobs.run_once(sf, _ctx(sf, registry, ledger, delivery, fixed_clock))

    assert delivery.whatsapp_templates[0]["template"] == "front_desk_digest"
    params = delivery.whatsapp_templates[0]["body_params"]
    assert len(params) == 1 and "\n" not in params[0] and len(params[0]) <= 1024
