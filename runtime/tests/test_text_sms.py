import base64
import json
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

SMS_FROM = "+18885550100"
CALLER = "+19055550101"
EDGE_KEY = "edge-shared-key"


def _event(text="What time do you open today?", msg_id="msg-1", to=SMS_FROM, sender=CALLER,
           event_type="message.received"):
    return {
        "data": {
            "event_type": event_type,
            "id": "evt-1",
            "occurred_at": "2026-09-01T18:00:00.000Z",
            "payload": {
                "id": msg_id,
                "direction": "inbound",
                "type": "SMS",
                "text": text,
                "from": {"phone_number": sender, "carrier": "Rogers", "line_type": "Wireless"},
                "to": [{"phone_number": to, "status": "webhook_delivered"}],
                "received_at": "2026-09-01T18:00:00.000Z",
            },
        }
    }


def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return private, base64.b64encode(raw).decode()


async def _build(sf, registry, fixed_clock, llm, **setting_overrides):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    cfg = await registry.get("skincentrix")
    await registry.import_config(cfg.model_copy(update={"sms_from_number": SMS_FROM}), "test")
    registry.invalidate("skincentrix")
    settings = Settings(secret_key="s3cret", **setting_overrides)
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=settings,
        sms=MemorySms(),
        llm=llm,
    )
    app = create_app(ctx, start_background=False)
    return app, ctx


def _llm(*texts: str):
    from spatalk.brain.driver import FakeLLM, LLMResponse
    return FakeLLM([LLMResponse(text=t, tool_calls=[]) for t in texts])


@pytest.fixture
async def client(sf, registry, fixed_clock):
    app, ctx = await _build(sf, registry, fixed_clock, _llm("We open at ten today."),
                            edge_shared_key=EDGE_KEY)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        yield c, ctx


async def _post(c, body: dict, headers: dict | None = None):
    return await c.post(
        "/telnyx/sms",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", **(headers or {})},
    )


def test_the_sms_route_is_on_the_app():
    from spatalk.http.app import create_app
    app = create_app(None, start_background=False)
    assert "/telnyx/sms" in {r.path for r in app.routes}


async def test_the_edge_key_is_accepted_and_the_reply_is_sent(client):
    c, ctx = client
    r = await _post(c, _event(), {"X-Edge-Key": EDGE_KEY})
    assert r.status_code == 200
    assert ctx.sms.sent == [(SMS_FROM, CALLER, "We open at ten today.")]


async def test_a_wrong_edge_key_is_401(client):
    c, ctx = client
    r = await _post(c, _event(), {"X-Edge-Key": "not-the-key"})
    assert r.status_code == 401
    assert ctx.sms.sent == []


async def test_a_missing_edge_key_is_401(client):
    c, _ = client
    assert (await _post(c, _event())).status_code == 401


async def test_a_telnyx_signature_is_accepted_when_no_edge_key_is_configured(
    sf, registry, fixed_clock
):
    private, public_b64 = _keypair()
    app, ctx = await _build(sf, registry, fixed_clock, _llm("We open at ten today."),
                            telnyx_public_key=public_b64)
    body = json.dumps(_event())
    ts = str(int(time.time()))
    sig = base64.b64encode(private.sign(f"{ts}|{body}".encode())).decode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        good = await c.post(
            "/telnyx/sms",
            content=body,
            headers={
                "Content-Type": "application/json",
                "telnyx-signature-ed25519": sig,
                "telnyx-timestamp": ts,
            },
        )
        bad = await c.post(
            "/telnyx/sms",
            content=body,
            headers={
                "Content-Type": "application/json",
                "telnyx-signature-ed25519": base64.b64encode(b"x" * 64).decode(),
                "telnyx-timestamp": ts,
            },
        )
    assert good.status_code == 200 and len(ctx.sms.sent) == 1
    assert bad.status_code == 401


async def test_a_stale_telnyx_timestamp_is_rejected(sf, registry, fixed_clock):
    private, public_b64 = _keypair()
    app, ctx = await _build(sf, registry, fixed_clock, _llm("We open at ten today."),
                            telnyx_public_key=public_b64)
    body = json.dumps(_event())
    ts = str(int(time.time()) - 400)
    sig = base64.b64encode(private.sign(f"{ts}|{body}".encode())).decode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        r = await c.post(
            "/telnyx/sms",
            content=body,
            headers={
                "Content-Type": "application/json",
                "telnyx-signature-ed25519": sig,
                "telnyx-timestamp": ts,
            },
        )
    assert r.status_code == 401 and ctx.sms.sent == []


async def test_a_non_message_received_event_is_ignored(client):
    c, ctx = client
    r = await _post(c, _event(event_type="message.sent"), {"X-Edge-Key": EDGE_KEY})
    assert r.status_code == 200 and ctx.sms.sent == []


async def test_an_unknown_destination_number_is_ignored(client):
    c, ctx = client
    r = await _post(c, _event(to="+15550009999"), {"X-Edge-Key": EDGE_KEY})
    assert r.status_code == 200 and ctx.sms.sent == []


async def test_a_duplicate_message_id_is_ignored(client):
    c, ctx = client
    await _post(c, _event(), {"X-Edge-Key": EDGE_KEY})
    r = await _post(c, _event(), {"X-Edge-Key": EDGE_KEY})
    assert r.status_code == 200 and len(ctx.sms.sent) == 1


async def test_stop_writes_an_optout_and_confirms(client, sf):
    from spatalk.models import SmsOptout
    c, ctx = client
    r = await _post(c, _event(text=" StOp "), {"X-Edge-Key": EDGE_KEY})
    assert r.status_code == 200
    assert ctx.sms.sent == [
        (SMS_FROM, CALLER,
         "You've been unsubscribed from Skincentrix texts. Reply START to opt back in.")
    ]
    async with sf() as s:
        rows = list((await s.scalars(select(SmsOptout))).all())
    assert [(x.tenant_id, x.phone) for x in rows] == [("skincentrix", CALLER)]


async def test_an_opted_out_sender_gets_no_reply(client, sf):
    c, ctx = client
    await _post(c, _event(text="STOP", msg_id="m-stop"), {"X-Edge-Key": EDGE_KEY})
    ctx.sms.sent.clear()
    r = await _post(c, _event(msg_id="m-2"), {"X-Edge-Key": EDGE_KEY})
    assert r.status_code == 200 and ctx.sms.sent == []


async def test_start_removes_the_optout_and_replies_with_help(client, sf):
    from spatalk.models import SmsOptout
    c, ctx = client
    await _post(c, _event(text="STOP", msg_id="m-stop"), {"X-Edge-Key": EDGE_KEY})
    ctx.sms.sent.clear()
    r = await _post(c, _event(text="start", msg_id="m-start"), {"X-Edge-Key": EDGE_KEY})
    assert r.status_code == 200
    assert ctx.sms.sent[0][2].startswith("Skincentrix: reply with your question")
    async with sf() as s:
        assert (await s.scalars(select(SmsOptout))).all() == []


async def test_help_replies_with_the_help_script(client):
    c, ctx = client
    r = await _post(c, _event(text="HELP"), {"X-Edge-Key": EDGE_KEY})
    assert r.status_code == 200
    assert ctx.sms.sent[0][2].startswith("Skincentrix: reply with your question")


async def test_a_long_reply_is_sent_as_two_messages(sf, registry, fixed_clock):
    sentence = "Our team can help you with that today and tomorrow."
    app, ctx = await _build(sf, registry, fixed_clock, _llm(" ".join([sentence] * 9)),
                            edge_shared_key=EDGE_KEY)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        r = await _post(c, _event(), {"X-Edge-Key": EDGE_KEY})
    assert r.status_code == 200
    assert len(ctx.sms.sent) == 2
    assert all(len(body) <= 300 for _, _, body in ctx.sms.sent)
