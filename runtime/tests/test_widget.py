"""Task B4: the web chat widget, its socket, and the fallback form.

The socket is driven through the ASGI interface directly rather than through a test client:
`httpx` cannot open a WebSocket, and Starlette's `TestClient` runs its own event loop, which
would use this test's asyncpg engine from a second loop. `WS` below speaks the ASGI
websocket protocol over two queues, so the whole test stays in one loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

SMS_FROM = "+18885550100"
SESSION = "11111111-2222-3333-4444-555555555555"
WIDGET_JS = Path(__file__).resolve().parents[1] / "spatalk" / "static" / "widget.js"


def _llm(*texts: str):
    from spatalk.brain.driver import FakeLLM, LLMResponse

    return FakeLLM([LLMResponse(text=t, tool_calls=[]) for t in texts])


def _llm_tool(name: str, arguments: dict):
    from spatalk.brain.driver import FakeLLM, LLMResponse, ToolCall

    return FakeLLM([LLMResponse(text=None, tool_calls=[ToolCall(name, arguments)])])


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
    settings = Settings(_env_file=None, secret_key="s3cret", **setting_overrides)
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
    return create_app(ctx, start_background=False), ctx


class WS:
    """A minimal ASGI websocket client: one connection, JSON frames both ways."""

    def __init__(self, app, query: str, client: tuple[str, int] = ("203.0.113.5", 5555)):
        self._app, self._query, self._client = app, query, client
        self._to_app: asyncio.Queue = asyncio.Queue()
        self._from_app: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> WS:
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
        self._task = asyncio.create_task(
            self._app(scope, self._to_app.get, self._from_app.put)
        )
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

    async def send(self, payload: dict) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": json.dumps(payload)})


def _closed(frame: dict, code: int) -> bool:
    """Starlette's close frame carries a reason as well as the code."""
    return frame["type"] == "websocket.close" and frame["code"] == code


async def _open(app, session: str = SESSION, turnstile: str = "tok", **kw) -> WS:
    ws = WS(app, f"tenant=skincentrix&session={session}&turnstile={turnstile}", **kw)
    await ws.__aenter__()
    return ws


# ----- routes and static assets ---------------------------------------------------------


def test_the_chat_routes_are_on_the_app():
    from spatalk.http.app import create_app

    paths = {r.path for r in create_app(None, start_background=False).routes}
    assert {"/widget.js", "/widget/{tenant_id}/config", "/chat/ws", "/chat/fallback"} <= paths


async def test_widget_js_is_served_as_javascript_and_cached_for_an_hour(sf, registry, fixed_clock):
    app, _ = await _build(sf, registry, fixed_clock, _llm())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        r = await c.get("/widget.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "max-age=3600" in r.headers["cache-control"]
    assert "data-tenant" in r.text


def test_the_widget_carries_no_third_party_assets_and_follows_the_colour_scheme():
    source = WIDGET_JS.read_text(encoding="utf-8")
    for host in ("cdn.", "googleapis", "unpkg", "jsdelivr", "http://"):
        assert host not in source
    assert "prefers-color-scheme" in source
    assert "/chat/fallback" in source
    assert "data-fallback" in source


def test_the_install_runbook_carries_the_snippet_and_the_accent_override():
    runbook = (
        Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "widget-install.md"
    ).read_text(encoding="utf-8")
    assert 'data-tenant="skincentrix"' in runbook
    assert "/widget.js" in runbook and "defer" in runbook
    assert "data-accent" in runbook


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed on this machine")
def test_the_widget_is_syntactically_valid_javascript():
    proc = subprocess.run(
        [shutil.which("node"), "--check", str(WIDGET_JS)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


# ----- config endpoint ------------------------------------------------------------------


async def test_the_config_endpoint_returns_the_name_greeting_accent_and_site_key(
    sf, registry, fixed_clock
):
    app, _ = await _build(sf, registry, fixed_clock, _llm(), turnstile_site_key="0xSITE")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        r = await c.get("/widget/skincentrix/config")
    body = r.json()
    assert r.status_code == 200
    assert body["name"] == "Skincentrix"
    assert body["greeting"].startswith("Hi there! I'm Ava, Skincentrix's AI assistant.")
    assert body["turnstile_site_key"] == "0xSITE"
    assert body["accent"].startswith("#")


async def test_the_config_endpoint_is_404_for_an_unknown_tenant(sf, registry, fixed_clock):
    app, _ = await _build(sf, registry, fixed_clock, _llm())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        r = await c.get("/widget/nobody/config")
    assert r.status_code == 404


# ----- the socket -----------------------------------------------------------------------


async def test_a_chat_message_round_trips_through_the_socket(sf, registry, fixed_clock):
    from spatalk.models import Conversation, Message

    app, ctx = await _build(sf, registry, fixed_clock, _llm("We open at ten today."))
    ws = await _open(app)
    try:
        assert (await ws.receive())["type"] == "websocket.accept"
        await ws.send({"type": "message", "text": "What time do you open?"})
        frames = [await ws.receive(), await ws.receive()]
    finally:
        await ws.__aexit__()
    assert {"type": "typing"} in frames
    assert {"type": "reply", "text": "We open at ten today."} in frames
    assert ctx.sms.sent == []
    async with sf() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.channel == "chat"))
        roles = list((await s.scalars(select(Message.role).order_by(Message.id))).all())
    assert conv is not None and conv.external_ref == SESSION and conv.caller is None
    assert roles == ["user", "assistant"]


async def test_the_second_message_of_a_session_stays_in_the_same_conversation(
    sf, registry, fixed_clock
):
    from spatalk.models import Conversation

    app, _ = await _build(sf, registry, fixed_clock, _llm("Ten to six.", "Yes, we do."))
    ws = await _open(app)
    try:
        await ws.receive()
        await ws.send({"type": "message", "text": "What time do you open?"})
        await ws.receive()
        await ws.receive()
        await ws.send({"type": "message", "text": "Do you do facials?"})
        await ws.receive()
        await ws.receive()
    finally:
        await ws.__aexit__()
    async with sf() as s:
        rows = list((await s.scalars(select(Conversation.id))).all())
    assert len(rows) == 1


async def test_the_socket_closes_after_the_assistant_ends_the_conversation(
    sf, registry, fixed_clock
):
    app, _ = await _build(sf, registry, fixed_clock, _llm_tool("end_conversation", {}))
    ws = await _open(app)
    try:
        await ws.receive()
        await ws.send({"type": "message", "text": "That's all, thanks!"})
        frames = [await ws.receive() for _ in range(4)]
    finally:
        await ws.__aexit__()
    assert {"type": "ended"} in frames
    assert any(f.get("type") == "websocket.close" for f in frames)


async def test_a_bad_turnstile_token_closes_the_socket_with_4401(sf, registry, fixed_clock):
    app, _ = await _build(
        sf, registry, fixed_clock, _llm("never reached"), turnstile_secret_key="0xSECRET"
    )
    seen: list[str] = []

    async def verifier(token, secret, remote_ip=None):
        seen.append(token)
        return False

    app.state.turnstile_verifier = verifier
    ws = await _open(app, turnstile="bad-token")
    try:
        frame = await ws.receive()
    finally:
        await ws.__aexit__()
    assert _closed(frame, 4401)
    assert seen == ["bad-token"]


async def test_a_good_turnstile_token_is_accepted(sf, registry, fixed_clock):
    app, _ = await _build(
        sf, registry, fixed_clock, _llm("Sure."), turnstile_secret_key="0xSECRET"
    )

    async def verifier(token, secret, remote_ip=None):
        return True

    app.state.turnstile_verifier = verifier
    ws = await _open(app)
    try:
        assert (await ws.receive())["type"] == "websocket.accept"
    finally:
        await ws.__aexit__()


async def test_a_sixth_session_from_one_ip_in_a_minute_closes_with_4429(
    sf, registry, fixed_clock
):
    app, _ = await _build(sf, registry, fixed_clock, _llm())
    opened = []
    try:
        for i in range(5):
            ws = await _open(app, session=f"{SESSION[:-1]}{i}")
            opened.append(ws)
            assert (await ws.receive())["type"] == "websocket.accept"
        sixth = await _open(app, session="99999999-9999-9999-9999-999999999999")
        opened.append(sixth)
        assert _closed(await sixth.receive(), 4429)
    finally:
        for ws in opened:
            await ws.__aexit__()


async def test_the_thirty_first_message_in_a_minute_closes_with_4429(sf, registry, fixed_clock):
    app, _ = await _build(sf, registry, fixed_clock, _llm(*["ok"] * 40))
    ws = await _open(app)
    try:
        await ws.receive()
        for _ in range(30):
            await ws.send({"type": "message", "text": "hello"})
            await ws.receive()
            await ws.receive()
        await ws.send({"type": "message", "text": "one too many"})
        assert _closed(await ws.receive(), 4429)
    finally:
        await ws.__aexit__()


async def test_a_runtime_with_no_model_configured_closes_the_socket_instead_of_erroring(
    sf, registry, fixed_clock
):
    app, _ = await _build(sf, registry, fixed_clock, None)
    ws = await _open(app)
    try:
        assert _closed(await ws.receive(), 4503)
    finally:
        await ws.__aexit__()


async def test_a_conversation_under_human_control_gets_no_bot_reply(sf, registry, fixed_clock):
    from sqlalchemy import update

    from spatalk.models import Conversation

    app, ctx = await _build(sf, registry, fixed_clock, _llm("the model must not speak"))
    ws = await _open(app)
    try:
        await ws.receive()
        await ws.send({"type": "message", "text": "hello"})
        await ws.receive()  # typing
        await ws.receive()  # first reply
        async with sf() as s, s.begin():
            await s.execute(update(Conversation).values(controller="human"))
        await ws.send({"type": "message", "text": "are you there?"})
        await ws.receive()  # typing
        with pytest.raises(asyncio.TimeoutError):
            await ws.receive(timeout=0.5)
    finally:
        await ws.__aexit__()


# ----- the fallback form ----------------------------------------------------------------


async def test_the_fallback_form_creates_a_conversation_a_message_and_a_callback_item(
    sf, registry, fixed_clock
):
    from spatalk.models import Conversation, Item, Message

    app, _ = await _build(sf, registry, fixed_clock, _llm())
    body = {
        "tenant_id": "skincentrix",
        "name": "Dana",
        "contact": "+19055550101",
        "message": "My laser session left a red patch and I want someone to call me.",
        "session": SESSION,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        r = await c.post("/chat/fallback", json=body)
    assert r.status_code == 200 and r.json() == {"ok": True}
    async with sf() as s:
        conv = await s.scalar(select(Conversation))
        message = await s.scalar(select(Message))
        item = await s.scalar(select(Item))
    assert conv.channel == "chat" and conv.external_ref == SESSION
    assert message.role == "user" and message.text == body["message"]
    assert item.type == "callback" and item.channel == "chat"
    assert item.contact_name == "Dana" and item.contact_phone == "+19055550101"
    assert item.conversation_id == conv.id


async def test_the_fallback_item_never_carries_the_message_text(sf, registry, fixed_clock):
    from spatalk.models import Item

    app, _ = await _build(sf, registry, fixed_clock, _llm())
    body = {
        "tenant_id": "skincentrix",
        "name": "Dana",
        "contact": "dana@example.com",
        "message": "PLEASE-DO-NOT-COPY-ME",
        "session": SESSION,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        await c.post("/chat/fallback", json=body)
    async with sf() as s:
        item = await s.scalar(select(Item))
    assert item.contact_email == "dana@example.com" and item.contact_phone is None
    values = " ".join(str(v) for v in item.__dict__.values())
    assert "PLEASE-DO-NOT-COPY-ME" not in values


async def test_the_fallback_form_is_rejected_with_a_wrong_edge_key(sf, registry, fixed_clock):
    from spatalk.models import Item

    app, _ = await _build(sf, registry, fixed_clock, _llm(), edge_shared_key="edge-shared-key")
    body = {"tenant_id": "skincentrix", "name": "Dana", "contact": "d@e.com",
            "message": "hi", "session": SESSION}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        bad = await c.post("/chat/fallback", json=body, headers={"X-Edge-Key": "wrong"})
        good = await c.post("/chat/fallback", json=body,
                            headers={"X-Edge-Key": "edge-shared-key"})
    assert bad.status_code == 401 and good.status_code == 200
    async with sf() as s:
        assert len(list((await s.scalars(select(Item.id))).all())) == 1


async def test_the_fallback_form_is_404_for_an_unknown_tenant(sf, registry, fixed_clock):
    app, _ = await _build(sf, registry, fixed_clock, _llm())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        r = await c.post(
            "/chat/fallback",
            json={"tenant_id": "nobody", "name": "D", "contact": "d@e.com",
                  "message": "hi", "session": SESSION},
        )
    assert r.status_code == 404


# ----- booking links on chat ------------------------------------------------------------


async def test_a_booking_link_on_chat_is_shown_inline_and_never_texted(sf, registry, fixed_clock):
    app, ctx = await _build(
        sf,
        registry,
        fixed_clock,
        _llm_tool(
            "send_booking_link",
            {"service_id": "facial", "contact": {"phone": "+19055550101"}},
        ),
    )
    ws = await _open(app)
    try:
        await ws.receive()
        await ws.send({"type": "message", "text": "Can I book a facial?"})
        await ws.receive()  # typing
        reply = await ws.receive()
    finally:
        await ws.__aexit__()
    assert reply["type"] == "reply"
    assert "https://skincentrix.janeapp.com" in reply["text"]
    assert "texted" not in reply["text"]
    assert ctx.sms.sent == []


async def test_a_booking_link_on_sms_is_still_texted(sf, registry, fixed_clock):
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import BookingLinkRequest, ContactInfo, ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities

    cfg = (await registry.get("skincentrix")).model_copy(
        update={"sms_from_number": SMS_FROM}
    )
    sms = MemorySms()
    caps = TierCCapabilities(MemoryLedger(fixed_clock), sms, fixed_clock)
    import uuid

    ref = ConversationRef(
        conversation_id=uuid.uuid4(), tenant=cfg, channel="sms", caller_phone="+19055550101"
    )
    out = await caps.send_booking_link(
        ref, BookingLinkRequest(service_id="facial", contact=ContactInfo())
    )
    assert out.kind == "link_sent" and len(sms.sent) == 1
