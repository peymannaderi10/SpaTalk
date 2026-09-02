"""Task B5: POST /slack/events, the door a staff reply comes in through.

Only a signed request is read at all; a retry or a repeated event id changes nothing; the
bot's own messages are never mistaken for a person; and a reply in a conversation's thread
reaches the customer and pauses the assistant.
"""

import hashlib
import hmac
import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

SMS_FROM = "+18885550100"
CALLER = "+19055550101"
CHANNEL = "C0TEST0001"
ROOT_TS = "1712.000100"
SECRET = "slacksecret"


async def _configure(registry):
    cfg = await registry.get("skincentrix")
    dests = [
        d.model_copy(update={"channel_id": CHANNEL}) if d.kind == "slack" else d
        for d in cfg.delivery.destinations
    ]
    delivery = cfg.delivery.model_copy(update={"destinations": dests})
    cfg = cfg.model_copy(update={"sms_from_number": SMS_FROM, "delivery": delivery})
    await registry.import_config(cfg, "test")
    registry.invalidate("skincentrix")
    return cfg


@pytest.fixture
async def world(sf, registry, fixed_clock):
    """An app, its context, and one SMS conversation whose Slack thread root is known."""
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryBotDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    from spatalk.text.service import TextConversationService

    await _configure(registry)
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryBotDelivery(),
        settings=Settings(
            secret_key="s3cret", slack_signing_secret=SECRET, slack_bot_token="xoxb-test"
        ),
        sms=MemorySms(),
    )
    conv = await TextConversationService(ctx, None).find_or_create_conversation(
        "skincentrix", "sms", CALLER, CALLER
    )
    from spatalk.text import takeover

    await takeover.store_thread(sf, conv.id, CHANNEL, ROOT_TS)
    app = create_app(ctx, start_background=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        yield c, ctx, conv, app


def _headers(body: str, secret: str = SECRET, **extra) -> dict:
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
        **extra,
    }


def _message_event(
    text: str = "On my way, calling her now",
    event_id: str = "Ev1",
    thread_ts: str = ROOT_TS,
    **event_extra,
) -> dict:
    event = {
        "type": "message",
        "channel": CHANNEL,
        "user": "U1",
        "text": text,
        "ts": "1712.000200",
        "thread_ts": thread_ts,
    }
    event.update(event_extra)
    return {"type": "event_callback", "event_id": event_id, "event": event}


async def _post(c, payload: dict, secret: str = SECRET, **extra):
    body = json.dumps(payload)
    return await c.post("/slack/events", content=body, headers=_headers(body, secret, **extra))


async def test_the_events_route_is_on_the_app(world):
    c, _, _, app = world
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/slack/events" in paths


async def test_url_verification_echoes_the_challenge(world):
    c, _, _, _ = world
    r = await _post(c, {"type": "url_verification", "challenge": "abc123"})
    assert r.status_code == 200 and r.json()["challenge"] == "abc123"


async def test_a_request_with_a_bad_signature_is_refused(world):
    c, ctx, _, _ = world
    r = await _post(c, _message_event(), secret="not-the-secret")
    assert r.status_code == 401 and ctx.sms.sent == []


async def test_a_staff_thread_reply_relays_to_the_customer_and_pauses_the_brain(world, sf):
    from spatalk.models import Conversation

    c, ctx, conv, _ = world
    r = await _post(c, _message_event())
    assert r.status_code == 200
    assert ctx.sms.sent == [(SMS_FROM, CALLER, "On my way, calling her now")]
    async with sf() as s:
        fresh = await s.get(Conversation, conv.id)
    assert fresh.controller == "human"


async def test_the_bots_own_messages_are_ignored(world):
    c, ctx, _, _ = world
    r = await _post(c, _message_event(text="#1 Callback requested", bot_id="B1", user="U0BOT"))
    assert r.status_code == 200 and ctx.sms.sent == []


async def test_a_retry_is_acknowledged_without_reprocessing(world):
    c, ctx, _, _ = world
    assert (await _post(c, _message_event())).status_code == 200
    r = await _post(c, _message_event(event_id="Ev2"), **{"X-Slack-Retry-Num": "1"})
    assert r.status_code == 200
    assert len(ctx.sms.sent) == 1


async def test_the_same_event_id_is_relayed_once(world):
    c, ctx, _, _ = world
    assert (await _post(c, _message_event())).status_code == 200
    assert (await _post(c, _message_event())).status_code == 200
    assert len(ctx.sms.sent) == 1


async def test_a_reply_in_an_unknown_thread_is_ignored(world):
    c, ctx, _, _ = world
    r = await _post(c, _message_event(thread_ts="9999.000001"))
    assert r.status_code == 200 and ctx.sms.sent == []


async def test_a_message_that_is_not_a_thread_reply_is_ignored(world):
    c, ctx, _, _ = world
    payload = _message_event()
    payload["event"].pop("thread_ts")
    r = await _post(c, payload)
    assert r.status_code == 200 and ctx.sms.sent == []
