"""Staff replies by SMS: ACK, DONE, LIST (sms staff plan, Task S2).

Every route test goes through the real ``POST /telnyx/sms`` with the edge key and a
:class:`MemorySms`, because the thing under test is precisely the branch that decides
whether an inbound text is a customer talking to the assistant or the owner working the
ledger. The model must never see a staff message, and a staff message must never be able to
touch another tenant's item.
"""

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
SMS_FROM = "+18885550100"
STAFF = "+15195550123"
RELAY_STAFF = "+15195550199"
CALLER = "+19055550101"
EDGE_KEY = "edge-shared-key"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


# ----- staff_numbers -------------------------------------------------------------------


def test_staff_numbers_is_the_configured_list_plus_every_sms_destination(monkeypatch):
    from spatalk.text.staff import staff_numbers

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    cfg = _cfg()
    cfg = cfg.model_copy(
        update={
            "delivery": cfg.delivery.model_copy(update={"staff_phone_numbers": [RELAY_STAFF]})
        }
    )
    assert staff_numbers(cfg) == {STAFF, RELAY_STAFF}


def test_staff_numbers_ignores_an_sms_destination_whose_env_is_unset(monkeypatch):
    from spatalk.text.staff import staff_numbers

    monkeypatch.delenv("SKINCENTRIX_STAFF_SMS", raising=False)
    assert staff_numbers(_cfg()) == set()


# ----- parse_staff_command -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["ack 4821", "ACK 4821", "ack #4821", "  Ack   4821  ", "ok 4821", "OK #4821",
     "acknowledge #4821", "Acknowledged 4821", "ack 4821."],
)
def test_every_acknowledge_wording_parses_to_the_same_command(text):
    from spatalk.text.staff import parse_staff_command

    assert parse_staff_command(text) == ("ack", 4821, "")


@pytest.mark.parametrize(
    "text",
    ["done 4821", "DONE #4821", "Done 4821!", "resolve 4821", "RESOLVE #4821",
     "resolved 4821", "closed 4821", "close #4821"],
)
def test_every_resolve_wording_parses_to_the_same_command(text):
    from spatalk.text.staff import parse_staff_command

    assert parse_staff_command(text) == ("resolve", 4821, "")


def test_a_hash_prefixed_message_is_still_a_relay():
    from spatalk.text.staff import parse_staff_command

    assert parse_staff_command("#4821 on my way") == ("relay", 4821, "on my way")
    assert parse_staff_command("#4821") == ("relay", 4821, "")


@pytest.mark.parametrize("text", ["list", "LIST", " List. ", "list "])
def test_list_parses_without_an_id(text):
    from spatalk.text.staff import parse_staff_command

    assert parse_staff_command(text) == ("list", None, "")


@pytest.mark.parametrize(
    "text",
    ["done", "ack", "resolve", "who is this", "call Dana back please", "", "   ",
     "ack the last one"],
)
def test_anything_else_is_not_a_command(text):
    from spatalk.text.staff import parse_staff_command

    assert parse_staff_command(text) == (None, None, text)


# ----- through the real route ----------------------------------------------------------


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


async def _post(client, body):
    return await client.post(
        "/telnyx/sms",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "X-Edge-Key": EDGE_KEY},
    )


async def _staff_tenant(registry):
    """Skincentrix with a messaging number and one relay-only staff phone."""
    cfg = await registry.get("skincentrix")
    cfg = cfg.model_copy(
        update={
            "sms_from_number": SMS_FROM,
            "delivery": cfg.delivery.model_copy(
                update={"staff_phone_numbers": [RELAY_STAFF]}
            ),
        }
    )
    await registry.import_config(cfg, "test")
    registry.invalidate("skincentrix")
    await registry.add_number(SMS_FROM, "skincentrix", "sms")
    return await registry.get("skincentrix")


async def _item_for(sf, registry, fixed_clock, tenant_id="skincentrix", urgency="normal"):
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.items import PgLedger

    cfg = await registry.get(tenant_id)
    cid = await start_conversation(sf, tenant_id, "sms", f"c-{tenant_id}", CALLER)
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(
        conversation_id=cid, tenant=cfg, channel="sms", caller_phone=CALLER
    )
    return await ledger.create_item(
        ref,
        ItemDraft(
            type="callback",
            urgency=urgency,
            contact=ContactInfo(name="Dana", phone=CALLER),
        ),
    )


@pytest.fixture
async def staff_client(sf, registry, fixed_clock, monkeypatch):
    from spatalk import jobs
    from spatalk.brain.driver import FakeLLM, LLMResponse
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    await _staff_tenant(registry)
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
        llm=FakeLLM([LLMResponse(text="We open at ten.", tool_calls=[])] * 4),
    )
    app = create_app(ctx, start_background=False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        yield client, ctx


async def _audit_rows(sf):
    from spatalk.models import AuditLog

    async with sf() as s:
        return list((await s.scalars(select(AuditLog))).all())


@pytest.mark.parametrize("wording", ["ACK {id}", "ack #{id}", "ok {id}", "Acknowledge #{id}"])
async def test_a_staff_number_acknowledges_an_item_by_reply(
    staff_client, sf, registry, fixed_clock, wording
):
    client, ctx = staff_client
    rec = await _item_for(sf, registry, fixed_clock)

    r = await _post(client, _event(wording.format(id=rec.id)))
    assert r.status_code == 200 and r.json()["handled"] == "staff_ack"
    assert ctx.llm.calls == [], "a staff message reached the model"
    assert ctx.sms.sent == [(SMS_FROM, STAFF, f"#{rec.id} acknowledged.")]

    item = await ctx.ledger.get(rec.id)
    assert item.state == "acknowledged" and item.acknowledged_by == f"sms:{STAFF}"


@pytest.mark.parametrize("wording", ["DONE {id}", "done #{id}", "resolve {id}", "Resolved #{id}",
                                     "closed {id}"])
async def test_a_staff_number_resolves_an_item_by_reply(
    staff_client, sf, registry, fixed_clock, wording
):
    client, ctx = staff_client
    rec = await _item_for(sf, registry, fixed_clock)

    r = await _post(client, _event(wording.format(id=rec.id)))
    assert r.status_code == 200 and r.json()["handled"] == "staff_resolve"
    assert ctx.llm.calls == []
    assert ctx.sms.sent == [(SMS_FROM, STAFF, f"#{rec.id} resolved.")]

    item = await ctx.ledger.get(rec.id)
    assert item.state == "resolved" and item.resolved_by == f"sms:{STAFF}"


async def test_acknowledging_and_resolving_write_audit_rows(
    staff_client, sf, registry, fixed_clock
):
    client, ctx = staff_client
    rec = await _item_for(sf, registry, fixed_clock)

    await _post(client, _event(f"ack {rec.id}", msg_id="m-ack"))
    await _post(client, _event(f"done {rec.id}", msg_id="m-done"))

    rows = await _audit_rows(sf)
    assert [(a.actor, a.action, a.record_type, a.record_id) for a in rows] == [
        (f"sms:{STAFF}", "ack", "item", str(rec.id)),
        (f"sms:{STAFF}", "resolve", "item", str(rec.id)),
    ]


async def test_an_unknown_item_id_is_said_so_and_nothing_is_claimed(staff_client):
    client, ctx = staff_client

    r = await _post(client, _event("DONE 4821"))
    assert r.status_code == 200 and r.json()["handled"] == "staff_unknown_item"
    assert ctx.sms.sent == [(SMS_FROM, STAFF, "No open item #4821.")]
    assert ctx.llm.calls == []
    assert await _audit_rows(ctx.sf) == []


async def test_an_already_resolved_item_is_not_acknowledged_a_second_time(
    staff_client, sf, registry, fixed_clock
):
    client, ctx = staff_client
    rec = await _item_for(sf, registry, fixed_clock)
    await ctx.ledger.resolve(rec.id, "portal:someone@clinic.test")
    ctx.sms.sent.clear()

    r = await _post(client, _event(f"ack {rec.id}"))
    assert r.json()["handled"] == "staff_unknown_item"
    assert ctx.sms.sent == [(SMS_FROM, STAFF, f"No open item #{rec.id}.")]
    item = await ctx.ledger.get(rec.id)
    assert item.resolved_by == "portal:someone@clinic.test"


async def test_a_customer_number_sending_done_is_an_ordinary_message(
    staff_client, sf, registry, fixed_clock
):
    from spatalk.models import Conversation

    client, ctx = staff_client
    rec = await _item_for(sf, registry, fixed_clock)

    r = await _post(client, _event(f"DONE {rec.id}", sender=CALLER))
    assert r.status_code == 200 and "conversation_id" in r.json()
    assert len(ctx.llm.calls) == 1

    item = await ctx.ledger.get(rec.id)
    assert item.state == "open" and item.acknowledged_at is None
    assert await _audit_rows(sf) == []
    async with sf() as s:
        convs = list(
            (await s.scalars(select(Conversation).where(Conversation.caller == CALLER))).all()
        )
    assert any(c.channel == "sms" for c in convs)


async def test_another_tenants_item_cannot_be_resolved_from_this_tenants_staff_phone(
    staff_client, sf, registry, fixed_clock
):
    client, ctx = staff_client
    mine = await _item_for(sf, registry, fixed_clock)
    other_cfg = (await registry.get("skincentrix")).model_copy(
        update={
            "id": "otherclinic",
            "name": "Other Clinic",
            "sms_from_number": None,
            "voice_numbers": [],
        }
    )
    await registry.import_config(other_cfg, "test")
    theirs = await _item_for(sf, registry, fixed_clock, tenant_id="otherclinic")
    assert theirs.id != mine.id

    r = await _post(client, _event(f"done {theirs.id}"))
    assert r.json()["handled"] == "staff_unknown_item"
    assert ctx.sms.sent == [(SMS_FROM, STAFF, f"No open item #{theirs.id}.")]
    item = await ctx.ledger.get(theirs.id)
    assert item.state == "open"
    assert await _audit_rows(sf) == []


async def test_list_answers_with_the_open_items(staff_client, sf, registry, fixed_clock):
    client, ctx = staff_client
    rec = await _item_for(sf, registry, fixed_clock)

    r = await _post(client, _event("List"))
    assert r.status_code == 200 and r.json()["handled"] == "staff_list"
    _, to, text = ctx.sms.sent[0]
    assert to == STAFF
    assert text.startswith("Skincentrix front desk: 1 open item(s).")
    assert f"#{rec.id}" in text and "Dana" in text


async def test_list_with_nothing_open_says_zero(staff_client):
    client, ctx = staff_client

    await _post(client, _event("LIST"))
    assert ctx.sms.sent == [(SMS_FROM, STAFF, "Skincentrix front desk: 0 open item(s).")]


async def test_the_hash_relay_still_reaches_the_customer(
    staff_client, sf, registry, fixed_clock
):
    from spatalk.models import Conversation

    client, ctx = staff_client
    rec = await _item_for(sf, registry, fixed_clock)

    r = await _post(client, _event(f"#{rec.id} on my way"))
    assert r.status_code == 200 and r.json()["handled"] == "staff_relay"
    assert (SMS_FROM, CALLER, "on my way") in ctx.sms.sent
    item = await ctx.ledger.get(rec.id)
    async with sf() as s:
        conv = await s.get(Conversation, item.conversation_id)
    assert conv.controller == "human"


async def test_a_relay_only_staff_number_can_acknowledge_too(
    staff_client, sf, registry, fixed_clock
):
    """`staff_phone_numbers` and the sms destinations are one authorisation list."""
    client, ctx = staff_client
    rec = await _item_for(sf, registry, fixed_clock)

    r = await _post(client, _event(f"ack {rec.id}", sender=RELAY_STAFF))
    assert r.json()["handled"] == "staff_ack"
    assert ctx.sms.sent == [(SMS_FROM, RELAY_STAFF, f"#{rec.id} acknowledged.")]
    item = await ctx.ledger.get(rec.id)
    assert item.acknowledged_by == f"sms:{RELAY_STAFF}"


async def test_anything_else_from_a_staff_number_gets_the_help_text(staff_client):
    client, ctx = staff_client

    r = await _post(client, _event("who is covering the front desk today"))
    assert r.status_code == 200 and r.json()["handled"] == "staff_help"
    assert ctx.llm.calls == []
    assert ctx.sms.sent[0][2].startswith("Skincentrix: reply with your question")
