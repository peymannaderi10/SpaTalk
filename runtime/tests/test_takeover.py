"""Task B5: a human joins the conversation, and the assistant steps aside.

The behaviours under test are the plan's: the first item of a conversation opens a Slack
thread, every later item and every message is mirrored into it, a staff reply pauses the
brain and is relayed verbatim, the hand-back button and twelve hours of silence resume the
assistant, and staff can relay by SMS with `#<item>`.
"""

import asyncio
import contextlib
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

SMS_FROM = "+18885550100"
CALLER = "+19055550101"
STAFF_PHONE = "+19051112222"
CHANNEL = "C0TEST0001"
SESSION = "11111111-2222-3333-4444-555555555555"


# ----- world building -------------------------------------------------------------------


async def _configure(registry):
    """Give the tenant a toll-free number, a Slack channel id and one staff phone."""
    cfg = await registry.get("skincentrix")
    dests = [
        d.model_copy(update={"channel_id": CHANNEL}) if d.kind == "slack" else d
        for d in cfg.delivery.destinations
    ]
    delivery = cfg.delivery.model_copy(
        update={"destinations": dests, "staff_phone_numbers": [STAFF_PHONE]}
    )
    cfg = cfg.model_copy(update={"sms_from_number": SMS_FROM, "delivery": delivery})
    await registry.import_config(cfg, "test")
    registry.invalidate("skincentrix")
    return cfg


def _llm(*texts: str):
    from spatalk.brain.driver import FakeLLM, LLMResponse

    return FakeLLM([LLMResponse(text=t, tool_calls=[]) for t in texts])


async def _ctx(sf, registry, fixed_clock, bot: bool = True, llm=None):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryBotDelivery, MemoryDelivery, schedule_item_delivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings

    await _configure(registry)

    async def on_created(item, cfg):
        await schedule_item_delivery(sf, item, cfg)

    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock, on_created=on_created),
        delivery=MemoryBotDelivery() if bot else MemoryDelivery(),
        settings=Settings(
            secret_key="s3cret",
            slack_signing_secret="slacksecret",
            slack_bot_token="xoxb-test" if bot else "",
        ),
        sms=MemorySms(),
        llm=llm,
    )


@pytest.fixture
async def ctx(sf, registry, fixed_clock):
    return await _ctx(sf, registry, fixed_clock)


def _service(ctx, llm):
    from spatalk.text.service import TextConversationService

    return TextConversationService(ctx, llm)


async def _sms_conversation(ctx, sender: str = CALLER):
    return await _service(ctx, None).find_or_create_conversation(
        "skincentrix", "sms", sender, sender
    )


async def _item(ctx, conversation_id, item_type: str = "callback"):
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef

    cfg = await ctx.registry.get("skincentrix")
    ref = ConversationRef(
        conversation_id=conversation_id, tenant=cfg, channel="sms", caller_phone=CALLER
    )
    return await ctx.ledger.create_item(
        ref,
        ItemDraft(
            type=item_type,
            urgency="normal",
            contact=ContactInfo(name="Dana", phone=CALLER),
        ),
    )


async def _conversation(sf, conversation_id):
    from spatalk.models import Conversation

    async with sf() as s:
        return await s.get(Conversation, conversation_id)


async def _roles(sf, conversation_id):
    from spatalk.conversations import get_transcript

    return [(m.role, m.text) for m in await get_transcript(sf, conversation_id)]


# ----- the thread root ------------------------------------------------------------------


async def test_the_first_item_of_a_conversation_opens_a_slack_thread(ctx, sf):
    from spatalk import jobs

    conv = await _sms_conversation(ctx)
    rec = await _item(ctx, conv.id)
    await jobs.run_once(sf, ctx)

    assert len(ctx.delivery.roots) == 1
    channel, blocks, text = ctx.delivery.roots[0]
    assert channel == CHANNEL
    assert f"#{rec.id}" in text
    assert ctx.delivery.slack == [], "a bot token means no webhook post"
    assert any("Dana" in str(b) for b in blocks)
    fresh = await _conversation(sf, conv.id)
    assert fresh.slack_channel == CHANNEL
    assert fresh.slack_ts and fresh.slack_ts in ctx.delivery.posted_ts


async def test_the_thread_root_carries_a_hand_back_button(ctx, sf):
    from spatalk import jobs
    from spatalk.ledger.links import verify_action

    conv = await _sms_conversation(ctx)
    rec = await _item(ctx, conv.id)
    await jobs.run_once(sf, ctx)

    _, blocks, _ = ctx.delivery.roots[0]
    buttons = {
        e["action_id"]: e["value"] for b in blocks if b["type"] == "actions" for e in b["elements"]
    }
    assert set(buttons) == {"ack", "resolve", "handback"}
    claim = verify_action(ctx.settings.secret_key, buttons["handback"])
    assert (claim.item_id, claim.action, claim.tenant_id) == (rec.id, "handback", "skincentrix")


async def test_a_later_item_is_posted_in_the_thread_not_as_a_second_root(ctx, sf):
    from spatalk import jobs

    conv = await _sms_conversation(ctx)
    await _item(ctx, conv.id)
    await jobs.run_once(sf, ctx)
    second = await _item(ctx, conv.id, "question")
    await jobs.run_once(sf, ctx)

    assert len(ctx.delivery.roots) == 1
    root_ts = (await _conversation(sf, conv.id)).slack_ts
    posted = [p for p in ctx.delivery.thread if f"#{second.id}" in p[2]]
    assert posted and posted[0][0] == CHANNEL and posted[0][1] == root_ts


async def test_without_a_bot_token_delivery_still_goes_to_the_webhook(
    sf, registry, fixed_clock, monkeypatch
):
    from spatalk import jobs

    monkeypatch.setenv("SKINCENTRIX_SLACK_WEBHOOK", "https://hooks.slack.com/services/T/B/x")
    ctx = await _ctx(sf, registry, fixed_clock, bot=False)
    conv = await _sms_conversation(ctx)
    rec = await _item(ctx, conv.id)
    await jobs.run_once(sf, ctx)

    assert len(ctx.delivery.slack) == 1
    assert ctx.delivery.slack[0][0].startswith("https://hooks.slack.com")
    assert f"#{rec.id}" in ctx.delivery.slack[0][2]
    assert (await _conversation(sf, conv.id)).slack_ts is None


class _FakeSlackClient:
    """Stands in for slack_sdk's AsyncWebClient: records calls, returns a ts."""

    def __init__(self):
        self.calls: list[dict] = []

    async def chat_postMessage(self, **kwargs):
        self.calls.append(kwargs)
        return {"ts": "1712.000900", "ok": True}


class _FakeHttp:
    def __init__(self):
        self.posts: list[tuple[str, dict]] = []

    async def post(self, url, json=None):
        self.posts.append((url, json))

        class _R:
            @staticmethod
            def raise_for_status():
                return None

        return _R()


async def test_the_real_bot_delivery_posts_roots_replies_and_webhooks():
    from spatalk.ledger.delivery import SlackBotDelivery, make_delivery
    from spatalk.settings import Settings

    client, http = _FakeSlackClient(), _FakeHttp()
    delivery = SlackBotDelivery(
        Settings(slack_bot_token="xoxb-test"), http=http, client=client
    )
    ts = await delivery.post_thread_root(CHANNEL, [{"type": "divider"}], "#1 Callback requested")
    assert ts == "1712.000900"
    await delivery.post_in_thread(CHANNEL, ts, "Customer: hello")
    await delivery.send_slack(CHANNEL, [], "as the bot")
    await delivery.send_slack("https://hooks.slack.com/services/T/B/x", [], "as the webhook")

    assert [c["channel"] for c in client.calls] == [CHANNEL] * 3
    assert client.calls[1]["thread_ts"] == ts and client.calls[1]["text"] == "Customer: hello"
    assert http.posts and http.posts[0][0].startswith("https://hooks.slack.com")
    assert isinstance(
        make_delivery(Settings(slack_bot_token="xoxb-test")), SlackBotDelivery
    )


# ----- mirroring ------------------------------------------------------------------------


async def test_customer_and_assistant_messages_are_mirrored_into_the_thread(ctx, sf):
    from spatalk import jobs

    conv = await _sms_conversation(ctx)
    await _item(ctx, conv.id)
    await jobs.run_once(sf, ctx)
    ctx.delivery.thread.clear()

    svc = _service(ctx, _llm("We open at ten today."))
    await svc.handle_inbound(
        tenant_id="skincentrix",
        channel="sms",
        external_id=CALLER,
        sender=CALLER,
        text="What time do you open?",
        provider_message_id="m1",
    )
    mirrored = [p[2] for p in ctx.delivery.thread]
    assert any("What time do you open?" in m for m in mirrored)
    assert any("We open at ten today." in m for m in mirrored)
    root_ts = (await _conversation(sf, conv.id)).slack_ts
    assert all(p[1] == root_ts for p in ctx.delivery.thread)


# ----- a staff reply pauses the brain ---------------------------------------------------


async def test_a_staff_relay_is_sent_verbatim_and_stored_as_staff(ctx, sf):
    from spatalk.models import UsageEvent
    from spatalk.text import takeover

    conv = await _sms_conversation(ctx)
    await takeover.relay_from_staff(ctx, conv.id, "On my way, calling her now", "U1")

    assert ctx.sms.sent == [(SMS_FROM, CALLER, "On my way, calling her now")]
    assert ("staff", "On my way, calling her now") in await _roles(sf, conv.id)
    assert (await _conversation(sf, conv.id)).controller == "human"
    async with sf() as s:
        units = list((await s.scalars(select(UsageEvent.unit))).all())
    assert units.count("sms_out") == 1


async def test_a_customer_message_while_a_person_is_replying_is_mirrored_and_unanswered(ctx, sf):
    from spatalk import jobs
    from spatalk.text import takeover

    conv = await _sms_conversation(ctx)
    await _item(ctx, conv.id)
    await jobs.run_once(sf, ctx)
    await takeover.relay_from_staff(ctx, conv.id, "On my way", "U1")
    ctx.sms.sent.clear()
    ctx.delivery.thread.clear()

    svc = _service(ctx, _llm("The assistant must never say this."))
    result = await svc.handle_inbound(
        tenant_id="skincentrix",
        channel="sms",
        external_id=CALLER,
        sender=CALLER,
        text="Thanks, see you then",
        provider_message_id="m2",
    )
    assert result.suppressed and result.reason == "human"
    assert ctx.sms.sent == []
    assert any("Thanks, see you then" in p[2] for p in ctx.delivery.thread)
    assert ("user", "Thanks, see you then") in await _roles(sf, conv.id)


async def test_staff_wording_never_reaches_the_model_as_its_own(ctx, sf):
    from spatalk.text import takeover
    from spatalk.text.service import STAFF_NOTE

    conv = await _sms_conversation(ctx)
    await takeover.relay_from_staff(ctx, conv.id, "I have booked you for Thursday", "U1")
    history = await _service(ctx, None).history(conv.id)
    assert history == [{"role": "assistant", "content": STAFF_NOTE}]


async def test_a_reply_to_an_opted_out_number_is_not_sent_and_the_thread_says_so(ctx, sf):
    from spatalk import jobs
    from spatalk.text import takeover
    from spatalk.text.service import add_optout

    conv = await _sms_conversation(ctx)
    await _item(ctx, conv.id)
    await jobs.run_once(sf, ctx)
    await add_optout(sf, "skincentrix", CALLER)
    ctx.delivery.thread.clear()

    await takeover.relay_from_staff(ctx, conv.id, "On my way", "U1")
    assert ctx.sms.sent == []
    assert len(ctx.delivery.thread) == 1
    assert "NOT DELIVERED" in ctx.delivery.thread[0][2]
    assert ("staff", "On my way") in await _roles(sf, conv.id)


# ----- coming back ----------------------------------------------------------------------


async def test_the_hand_back_button_resumes_the_assistant(sf, registry, fixed_clock):
    import hashlib
    import hmac
    import time
    from urllib.parse import urlencode

    from httpx import ASGITransport, AsyncClient

    from spatalk import jobs
    from spatalk.http.app import create_app
    from spatalk.ledger.links import sign_action
    from spatalk.text import takeover

    ctx = await _ctx(sf, registry, fixed_clock)
    conv = await _sms_conversation(ctx)
    rec = await _item(ctx, conv.id)
    await jobs.run_once(sf, ctx)
    await takeover.relay_from_staff(ctx, conv.id, "On my way", "U1")
    ctx.delivery.thread.clear()

    token = sign_action(ctx.settings.secret_key, rec.id, "handback", "skincentrix")
    payload = json.dumps(
        {
            "type": "block_actions",
            "user": {"username": "dana"},
            "channel": {"id": CHANNEL},
            "actions": [{"action_id": "handback", "value": token}],
        }
    )
    body = urlencode({"payload": payload})
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(b"slacksecret", f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    app = create_app(ctx, start_background=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        r = await c.post(
            "/slack/interactions",
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
            },
        )
    assert r.status_code == 200
    assert (await _conversation(sf, conv.id)).controller == "ai"
    assert ctx.delivery.thread, "the thread says the assistant is answering again"


async def test_twelve_hours_of_staff_silence_hands_back_and_says_so_in_the_thread(ctx, sf):
    from spatalk import jobs
    from spatalk.models import Message
    from spatalk.text import takeover

    conv = await _sms_conversation(ctx)
    await _item(ctx, conv.id)
    await jobs.run_once(sf, ctx)
    await takeover.relay_from_staff(ctx, conv.id, "On my way", "U1")
    ctx.delivery.thread.clear()

    async with sf() as s, s.begin():
        await s.execute(
            Message.__table__.update()
            .where(Message.conversation_id == conv.id, Message.role == "staff")
            .values(created_at=ctx.clock.now() - timedelta(hours=13))
        )
    assert await takeover.hand_back_stale(ctx) == 1
    assert (await _conversation(sf, conv.id)).controller == "ai"
    assert len(ctx.delivery.thread) == 1
    assert await takeover.hand_back_stale(ctx) == 0


async def test_a_recent_staff_reply_keeps_the_conversation_with_the_person(ctx, sf):
    from spatalk.models import Message
    from spatalk.text import takeover

    conv = await _sms_conversation(ctx)
    await takeover.relay_from_staff(ctx, conv.id, "On my way", "U1")
    async with sf() as s, s.begin():
        await s.execute(
            Message.__table__.update()
            .where(Message.conversation_id == conv.id, Message.role == "staff")
            .values(created_at=ctx.clock.now() - timedelta(hours=11))
        )
    assert await takeover.hand_back_stale(ctx) == 0
    assert (await _conversation(sf, conv.id)).controller == "human"


# ----- staff SMS relay ------------------------------------------------------------------


async def _staff_sms(ctx, text: str, sender: str = STAFF_PHONE):
    from httpx import ASGITransport, AsyncClient

    from spatalk.http.app import create_app

    body = {
        "data": {
            "event_type": "message.received",
            "id": "evt-staff",
            "payload": {
                "id": f"msg-{abs(hash(text)) % 10000}",
                "text": text,
                "from": {"phone_number": sender},
                "to": [{"phone_number": SMS_FROM}],
            },
        }
    }
    app = create_app(ctx, start_background=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        return await c.post(
            "/telnyx/sms",
            content=json.dumps(body),
            headers={"Content-Type": "application/json", "X-Edge-Key": "edge-key"},
        )


@pytest.fixture
async def staff_ctx(sf, registry, fixed_clock):
    ctx = await _ctx(sf, registry, fixed_clock, llm=_llm("The brain should not answer staff."))
    ctx.settings = ctx.settings.model_copy(update={"edge_shared_key": "edge-key"})
    await registry.add_number(SMS_FROM, "skincentrix", "sms")
    return ctx


async def test_a_staff_sms_naming_an_item_relays_to_that_conversation(staff_ctx, sf):
    ctx = staff_ctx
    conv = await _sms_conversation(ctx)
    rec = await _item(ctx, conv.id)
    ctx.sms.sent.clear()

    r = await _staff_sms(ctx, f"#{rec.id} on my way, calling at 3")
    assert r.status_code == 200
    assert ctx.sms.sent == [(SMS_FROM, CALLER, "on my way, calling at 3")]
    assert (await _conversation(sf, conv.id)).controller == "human"
    assert ("staff", "on my way, calling at 3") in await _roles(sf, conv.id)


async def test_a_staff_sms_in_any_other_shape_gets_the_help_text(staff_ctx):
    ctx = staff_ctx
    r = await _staff_sms(ctx, "who is on the desk today?")
    assert r.status_code == 200
    assert len(ctx.sms.sent) == 1
    assert "Reply STOP to unsubscribe" in ctx.sms.sent[0][2]


async def test_a_staff_sms_naming_an_unknown_item_gets_the_help_text(staff_ctx):
    ctx = staff_ctx
    r = await _staff_sms(ctx, "#9999 on my way")
    assert r.status_code == 200
    assert len(ctx.sms.sent) == 1
    assert "Reply STOP to unsubscribe" in ctx.sms.sent[0][2]


async def test_a_customer_number_writing_a_hash_is_not_a_staff_relay(staff_ctx, sf):
    ctx = staff_ctx
    conv = await _sms_conversation(ctx)
    rec = await _item(ctx, conv.id)
    ctx.sms.sent.clear()

    r = await _staff_sms(ctx, f"#{rec.id} let me in", sender=CALLER)
    assert r.status_code == 200
    assert ctx.sms.sent == [(SMS_FROM, CALLER, "The brain should not answer staff.")]
    assert (await _conversation(sf, conv.id)).controller == "ai"


# ----- chat relay -----------------------------------------------------------------------


async def test_a_staff_relay_to_a_chat_visitor_reaches_the_open_socket(ctx, sf):
    from spatalk.text import takeover

    conv = await _service(ctx, None).find_or_create_conversation(
        "skincentrix", "chat", SESSION, None
    )
    got: list[str] = []

    async def send(text: str) -> None:
        got.append(text)

    takeover.register_chat_socket("skincentrix", SESSION, send)
    try:
        await takeover.relay_from_staff(ctx, conv.id, "Hi, this is Dana from the desk", "U1")
    finally:
        takeover.unregister_chat_socket("skincentrix", SESSION)
    assert got == ["Hi, this is Dana from the desk"]
    assert ("staff", "Hi, this is Dana from the desk") in await _roles(sf, conv.id)


async def test_a_staff_relay_with_no_socket_waits_for_the_next_connect(ctx, sf):
    from spatalk.text import takeover

    conv = await _service(ctx, None).find_or_create_conversation(
        "skincentrix", "chat", SESSION, None
    )
    await takeover.relay_from_staff(ctx, conv.id, "Sorry for the wait", "U1")
    assert takeover.take_pending_staff("skincentrix", SESSION) == ["Sorry for the wait"]
    assert takeover.take_pending_staff("skincentrix", SESSION) == []


class WS:
    """A minimal ASGI websocket client, as in tests/test_widget.py."""

    def __init__(self, app, query: str, client: tuple[str, int] = ("203.0.113.9", 5555)):
        self._app, self._query, self._client = app, query, client
        self._to_app: asyncio.Queue = asyncio.Queue()
        self._from_app: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "WS":
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "server": ("api.test", 443),
            "client": self._client,
            "root_path": "",
            "path": "/chat/ws",
            "raw_path": b"/chat/ws",
            "query_string": self._query.encode(),
            "headers": [(b"host", b"api.test")],
            "subprotocols": [],
            "state": {},
        }
        self._task = asyncio.create_task(self._app(scope, self._to_app.get, self._from_app.put))
        await self._to_app.put({"type": "websocket.connect"})
        return self

    async def __aexit__(self, *exc) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5)
            if not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

    async def receive(self, timeout: float = 5.0) -> dict:
        message = await asyncio.wait_for(self._from_app.get(), timeout)
        if message["type"] == "websocket.send":
            return json.loads(message["text"])
        return message


async def test_a_staff_message_left_waiting_is_delivered_when_the_widget_reconnects(ctx, sf):
    from spatalk.http.app import create_app
    from spatalk.text import takeover

    ctx.llm = _llm("unused")
    conv = await _service(ctx, None).find_or_create_conversation(
        "skincentrix", "chat", SESSION, None
    )
    await takeover.relay_from_staff(ctx, conv.id, "Dana here, one moment", "U1")

    app = create_app(ctx, start_background=False)
    async with WS(app, f"tenant=skincentrix&session={SESSION}&turnstile=tok") as ws:
        assert (await ws.receive())["type"] == "websocket.accept"
        assert await ws.receive() == {"type": "staff", "text": "Dana here, one moment"}
