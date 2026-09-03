"""Adversarial verification of SMS staff delivery (plan S, tasks S1 and S2).

These tests were written against the shipped code, not with it, and they try to break the four
promises the plan makes about a text that lands on the owner's own mobile:

* nothing a model produced is ever in it;
* only a configured number can work the ledger, and only its own tenant's items;
* an opt-out and a missing messaging number are honoured out loud, never silently;
* the transcript link survives every cut.

Three of them began as ``xfail(strict=True)`` descriptions of gaps found during verification;
the gaps were closed in the commit that followed the review and the markers removed.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
SMS_FROM = "+18885550100"
STAFF = "+15195550123"
CALLER = "+19055550101"
EDGE_KEY = "edge-shared-key"
TRANSCRIPT = "https://api.test/a/tok7"


# ----- helpers -----------------------------------------------------------------------------


def _links():
    from spatalk.ledger.delivery import ActionLinks
    from spatalk.ledger.links import sign_action

    ack = sign_action("s", 7, "ack", "skincentrix")
    res = sign_action("s", 7, "resolve", "skincentrix")
    return ActionLinks("https://a/ack", "https://a/res", TRANSCRIPT, ack, res)


def _settings(**over):
    from spatalk.settings import Settings

    return Settings(_env_file=None, public_base_url="https://api.test", secret_key="s", **over)


def _fake_item(clock, **over):
    """An item shaped like the row, for the pure builders."""
    base = dict(
        id=7,
        tenant_id="skincentrix",
        type="callback",
        urgency="normal",
        channel="voice",
        state="open",
        contact_name="Dana",
        contact_phone=CALLER,
        contact_email=None,
        due_at=clock.now(),
        health_context=False,
        conversation_id=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


async def _tenant(registry, number=SMS_FROM):
    cfg = await registry.get("skincentrix")
    await registry.import_config(cfg.model_copy(update={"sms_from_number": number}), "test")
    registry.invalidate("skincentrix")
    return await registry.get("skincentrix")


async def _item_for(sf, registry, fixed_clock, tenant_id="skincentrix", **draft):
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.items import PgLedger

    cfg = await registry.get(tenant_id)
    cid = await start_conversation(sf, tenant_id, "voice", f"c-{tenant_id}", CALLER)
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice", caller_phone=CALLER)
    rec = await ledger.create_item(
        ref,
        ItemDraft(type="callback", urgency="normal", contact=ContactInfo(name="Dana", phone=CALLER), **draft),
    )
    return ledger, rec


def _ctx(sf, registry, ledger, fixed_clock, **over):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryDelivery

    kwargs = dict(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=ledger,
        delivery=MemoryDelivery(),
        settings=_settings(),
        sms=MemorySms(),
    )
    kwargs.update(over)
    return jobs.JobContext(**kwargs)


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


async def _audit_rows(sf):
    from spatalk.models import AuditLog

    async with sf() as s:
        return list((await s.scalars(select(AuditLog))).all())


@pytest.fixture
async def staff_client(sf, registry, fixed_clock, monkeypatch):
    from spatalk import jobs
    from spatalk.brain.driver import FakeLLM, LLMResponse
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    await _tenant(registry)
    await registry.add_number(SMS_FROM, "skincentrix", "sms")
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=_settings(edge_shared_key=EDGE_KEY),
        sms=MemorySms(),
        llm=FakeLLM([LLMResponse(text="We open at ten.", tool_calls=[])] * 6),
    )
    app = create_app(ctx, start_background=False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        yield client, ctx


# ----- 1. nothing generated reaches a staff phone -------------------------------------------


async def test_the_staff_text_is_the_pure_builder_output_and_carries_no_conversation_words(
    sf, registry, fixed_clock, monkeypatch
):
    """What went down the wire is exactly what the deterministic builder produced.

    The conversation behind the item holds an assistant turn; none of it may appear, and the
    body must be reproducible character for character from the item's columns alone.
    """
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.conversations import append_message
    from spatalk.ledger.delivery import build_links, build_sms_text

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    cfg = await _tenant(registry)
    ledger, rec = await _item_for(sf, registry, fixed_clock)
    item = await ledger.get(rec.id)
    await append_message(
        sf, item.conversation_id, "assistant", "I have booked you in for Thursday at four."
    )

    sms = MemorySms()
    await jobs.enqueue(
        sf,
        "deliver.sms",
        {
            "item_id": rec.id,
            "tenant_id": "skincentrix",
            "to_env": "SKINCENTRIX_STAFF_SMS",
            "escalation": False,
        },
    )
    ctx = _ctx(sf, registry, ledger, fixed_clock, sms=sms)
    assert await jobs.run_once(sf, ctx) == 1

    text = sms.sent[0][2]
    # The action token is signed with the clock, so the body is compared up to the link and the
    # link itself is checked for its shape: everything before it must be reproducible.
    head, sep, link = text.partition("Transcript: ")
    expected = build_sms_text(item, cfg, build_links(ctx.settings, item), fixed_clock.now())
    assert sep and head == expected.partition("Transcript: ")[0]
    assert link.startswith("https://api.test/a/") and " " not in link
    assert "booked" not in text and "Thursday" not in text


# ----- 2. only a configured number, and only its own tenant ---------------------------------


async def test_a_customer_number_cannot_acknowledge_a_real_open_item(
    staff_client, sf, registry, fixed_clock
):
    client, ctx = staff_client
    _, rec = await _item_for(sf, registry, fixed_clock)

    r = await _post(client, _event(f"ACK {rec.id}", sender=CALLER))
    assert r.status_code == 200 and "conversation_id" in r.json()

    item = await ctx.ledger.get(rec.id)
    assert item.state == "open" and item.acknowledged_at is None and item.acknowledged_by is None
    assert await _audit_rows(sf) == []
    assert all("acknowledged" not in text for _, _, text in ctx.sms.sent)


async def test_a_staff_number_cannot_acknowledge_another_tenants_item(
    staff_client, sf, registry, fixed_clock
):
    client, ctx = staff_client
    other = (await registry.get("skincentrix")).model_copy(
        update={
            "id": "otherclinic",
            "name": "Other Clinic",
            "sms_from_number": None,
            "voice_numbers": [],
        }
    )
    await registry.import_config(other, "test")
    _, mine = await _item_for(sf, registry, fixed_clock)
    _, theirs = await _item_for(sf, registry, fixed_clock, tenant_id="otherclinic")
    # The refusal must be about the tenant, not about the id being absent or already closed.
    assert theirs.id != mine.id
    assert (await ctx.ledger.get(theirs.id)).state == "open"

    r = await _post(client, _event(f"ack {theirs.id}"))
    assert r.json()["handled"] == "staff_unknown_item"
    assert ctx.sms.sent == [(SMS_FROM, STAFF, f"No open item #{theirs.id}.")]
    item = await ctx.ledger.get(theirs.id)
    assert item.state == "open" and item.acknowledged_by is None
    assert await _audit_rows(sf) == []


async def test_the_list_reply_never_names_another_tenants_open_item(
    staff_client, sf, registry, fixed_clock
):
    client, ctx = staff_client
    other = (await registry.get("skincentrix")).model_copy(
        update={
            "id": "otherclinic",
            "name": "Other Clinic",
            "sms_from_number": None,
            "voice_numbers": [],
        }
    )
    await registry.import_config(other, "test")
    _, theirs = await _item_for(sf, registry, fixed_clock, tenant_id="otherclinic")
    _, mine = await _item_for(sf, registry, fixed_clock)

    r = await _post(client, _event("LIST"))
    assert r.json()["handled"] == "staff_list"
    text = ctx.sms.sent[0][2]
    assert text.startswith("Skincentrix front desk: 1 open item(s).")
    assert f"#{mine.id}" in text
    assert f"#{theirs.id}" not in text and "Other Clinic" not in text


async def test_a_number_whose_variable_is_gone_is_no_longer_staff(
    staff_client, sf, registry, fixed_clock, monkeypatch
):
    """Authorisation is resolved per request: unset the variable and the number is a caller."""
    client, ctx = staff_client
    _, rec = await _item_for(sf, registry, fixed_clock)
    monkeypatch.delenv("SKINCENTRIX_STAFF_SMS", raising=False)

    r = await _post(client, _event(f"DONE {rec.id}"))
    assert "conversation_id" in r.json()
    item = await ctx.ledger.get(rec.id)
    assert item.state == "open"
    assert await _audit_rows(sf) == []


@pytest.mark.parametrize(
    "text,handled",
    [
        ("ack {id}", "staff_ack"),
        ("done {id}", "staff_resolve"),
        ("LIST", "staff_list"),
        ("#{id} on my way", "staff_relay"),
        ("#{id}", "staff_help"),
        ("done 999999", "staff_unknown_item"),
        ("can you call Dana back", "staff_help"),
        ("", "staff_help"),
    ],
)
async def test_no_staff_branch_ever_reaches_the_brain(
    staff_client, sf, registry, fixed_clock, text, handled
):
    client, ctx = staff_client
    _, rec = await _item_for(sf, registry, fixed_clock)

    r = await _post(client, _event(text.format(id=rec.id)))
    assert r.status_code == 200 and r.json()["handled"] == handled
    assert ctx.llm.calls == []


# ----- 3. opt-outs and a missing messaging number --------------------------------------------


async def test_a_staff_number_that_texted_stop_gets_no_digest_either(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.text.service import add_optout

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    monkeypatch.setenv("SKINCENTRIX_WHATSAPP_STAFF", "")
    await _tenant(registry)
    ledger, _ = await _item_for(sf, registry, fixed_clock)
    await add_optout(sf, "skincentrix", STAFF)

    sms, delivery = MemorySms(), MemoryDelivery()
    await jobs.enqueue(sf, "digest.email", {"tenant_id": "skincentrix"})
    await jobs.run_once(sf, _ctx(sf, registry, ledger, fixed_clock, sms=sms, delivery=delivery))

    assert sms.sent == []
    assert len(delivery.emails) == 1          # the email destination is untouched by the opt-out


async def test_a_tenant_with_no_messaging_number_claims_nothing_on_the_reply_path(
    sf, registry, fixed_clock, monkeypatch
):
    """Without a from-number the ledger still moves, but nothing is sent and nothing claimed."""
    from spatalk import jobs
    from spatalk.brain.driver import FakeLLM, LLMResponse
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    await _tenant(registry, number=None)
    await registry.add_number(SMS_FROM, "skincentrix", "sms")
    _, rec = await _item_for(sf, registry, fixed_clock)
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
        r = await _post(client, _event(f"done {rec.id}"))

    assert r.json()["handled"] == "staff_resolve"
    assert ctx.sms.sent == []                  # no confirmation invented for a text never sent
    assert ctx.llm.calls == []


# ----- 4. the 459-character rule and the link ------------------------------------------------


@pytest.mark.parametrize(
    "over,name",
    [
        ({}, "ordinary"),
        ({"contact_name": "D" * 200}, "a name at the column limit"),
        ({"contact_email": "d" * 180 + "@e.test"}, "a very long email"),
        ({"contact_name": "D" * 200, "health_context": True, "urgency": "urgent"},
         "flagged, urgent and long"),
        ({"contact_name": "D" * 200, "contact_email": "d" * 180 + "@e.test",
          "health_context": True, "urgency": "urgent"}, "every field at once"),
    ],
)
async def test_the_transcript_link_survives_every_shape_of_item(fixed_clock, registry, over, name):
    from spatalk.ledger.delivery import SMS_STAFF_LIMIT, build_sms_text

    cfg = await registry.get("skincentrix")
    text = build_sms_text(_fake_item(fixed_clock, **over), cfg, _links(), fixed_clock.now(), True)

    assert len(text) <= SMS_STAFF_LIMIT, name
    assert text.endswith(TRANSCRIPT), name
    assert text.count(TRANSCRIPT) == 1, name


async def test_an_absurd_tenant_name_cuts_the_head_and_still_ends_in_the_whole_link(
    fixed_clock, registry
):
    """The last resort truncates the front. The link is appended whole and exactly once."""
    from spatalk.ledger.delivery import SMS_STAFF_LIMIT, build_sms_text

    cfg = (await registry.get("skincentrix")).model_copy(update={"name": "N" * 600})
    text = build_sms_text(_fake_item(fixed_clock), cfg, _links(), fixed_clock.now())

    assert len(text) <= SMS_STAFF_LIMIT
    assert text.endswith(TRANSCRIPT) and text.count("Transcript:") == 1


async def test_a_staff_text_is_three_segments_even_when_a_name_is_not_gsm7(fixed_clock, registry):
    from spatalk.ledger.delivery import build_sms_text, sms_segments

    cfg = await registry.get("skincentrix")
    # A curly apostrophe is what a phone keyboard and most CRMs produce, and the column holds
    # 200 characters, so this item is one a real ledger can carry.
    item = _fake_item(fixed_clock, contact_name="Dana O’Brien " + "a" * 187)
    text = build_sms_text(item, cfg, _links(), fixed_clock.now())

    assert sms_segments(text) <= 3


async def test_a_name_in_another_script_still_leaves_three_segments_and_the_link(
    fixed_clock, registry
):
    """Nothing here folds into GSM-7, so the body stays UCS-2 and the front gives way."""
    from spatalk.ledger.delivery import build_sms_text, sms_segments

    cfg = (await registry.get("skincentrix")).model_copy(update={"name": "\u7f8e\u5bb9" * 150})
    item = _fake_item(fixed_clock, contact_name="\u738b\u79c0\u82f1")
    text = build_sms_text(item, cfg, _links(), fixed_clock.now())

    assert sms_segments(text) <= 3
    assert text.endswith(TRANSCRIPT) and text.count("Transcript:") == 1


async def test_a_caller_name_cannot_forge_an_item_line_in_the_list_reply(fixed_clock, registry):
    from spatalk.ledger.delivery import build_list_sms

    cfg = await registry.get("skincentrix")
    forged = "Dana\n#9999 Callback requested, Mallory, due now"
    text = build_list_sms([_fake_item(fixed_clock, contact_name=forged)], cfg, fixed_clock.now())

    assert len(text.splitlines()) == 2          # the header and one real item


async def test_an_opted_out_staff_number_is_answered_with_nothing(
    staff_client, sf, registry, fixed_clock
):
    from spatalk.text.service import add_optout

    client, ctx = staff_client
    _, rec = await _item_for(sf, registry, fixed_clock)
    await add_optout(sf, "skincentrix", STAFF)
    ctx.sms.sent.clear()

    await _post(client, _event(f"ack {rec.id}"))
    assert ctx.sms.sent == []


# ----- 5. the bundle names personal numbers, it never writes them ----------------------------


async def test_the_bundle_writes_no_number_but_the_tenants_own(registry):
    """Every destination that reaches a person names an environment variable."""
    import re

    cfg = await registry.get("skincentrix")
    for dest in cfg.delivery.destinations:
        if dest.kind in ("sms", "whatsapp"):
            assert dest.address_env and not dest.address, dest.kind

    found = set()
    for path in sorted(BUNDLE.iterdir()):
        if path.is_file():
            found |= set(re.findall(r"\+\d{10,15}", path.read_text("utf-8")))
    assert found == {"+12899170079"}            # the tenant's own messaging number, nothing else
