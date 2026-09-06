"""Slack one-click connect (onboarding roadmap, section 3): a clinic installs the Front Desk
app in its own workspace from Settings, Integrations, and needs no `.env` line.

The flow is the Instagram one with Slack's names: a signed state leaves with the browser,
comes back with a code, the code becomes a bot token and an incoming webhook, and both are
stored encrypted against the tenant. No test reaches Slack: every call goes through
``FakeGraphClient``, which records what was asked for and answers from a table.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

INTERNAL_KEY = "test-internal-key"
ACTOR = "owner@skincentrix.test"
RETURN_TO = "https://portal.example.com/app/skincentrix/settings?connected=slack"
SIGNING_SECRET = "slacksecret"

TEAM_ID = "T0123ABC"
TEAM_NAME = "Skincentrix"
CHANNEL = "#front-desk"
CHANNEL_ID = "C0FRONTDESK"
BOT_TOKEN = "xoxb-slack-bot-token-for-skincentrix"
WEBHOOK = "https://hooks.slack.com/services/T0123ABC/B0WEBHOOK/s3cretpart"
CALLER = "+19055550101"

EXCHANGE = "POST /oauth.v2.access"
REVOKE = "POST /auth.revoke"


def _settings(**overrides):
    from cryptography.fernet import Fernet

    from spatalk.settings import Settings

    values = dict(
        secret_key="s3cret",
        public_base_url="https://api.example.com",
        internal_api_key=INTERNAL_KEY,
        slack_signing_secret=SIGNING_SECRET,
        slack_client_id="SLACK_CLIENT_ID",
        slack_client_secret="slack-client-secret",
        meta_token_encryption_key=Fernet.generate_key().decode(),
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _exchange_answer(**overrides) -> dict:
    """What ``oauth.v2.access`` answers for a bot install with an incoming webhook."""
    answer = {
        "ok": True,
        "access_token": BOT_TOKEN,
        "token_type": "bot",
        "scope": "incoming-webhook,chat:write,channels:history,channels:read,users:read",
        "bot_user_id": "U0BOT",
        "app_id": "A0APP",
        "team": {"id": TEAM_ID, "name": TEAM_NAME},
        "enterprise": None,
        "authed_user": {"id": "U0OWNER"},
        "incoming_webhook": {
            "channel": CHANNEL,
            "channel_id": CHANNEL_ID,
            "configuration_url": "https://skincentrix.slack.com/services/B0WEBHOOK",
            "url": WEBHOOK,
        },
    }
    answer.update(overrides)
    return answer


async def _build(sf, registry, fixed_clock, *, settings=None, graph_responses=None, bot=False):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryBotDelivery, MemoryDelivery, schedule_item_delivery
    from spatalk.ledger.items import PgLedger
    from spatalk.social.graph import FakeGraphClient

    settings = settings or _settings()
    responses = {EXCHANGE: _exchange_answer(), REVOKE: {"ok": True, "revoked": True}}
    responses.update(graph_responses or {})

    async def on_created(item, cfg):
        await schedule_item_delivery(sf, item, cfg)

    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock, on_created=on_created),
        delivery=MemoryBotDelivery() if bot else MemoryDelivery(),
        settings=settings,
        sms=MemorySms(),
        graph=FakeGraphClient(responses),
    )
    return create_app(ctx, start_background=False), ctx


async def _connect(ctx, sf, fixed_clock, **overrides):
    from spatalk.social.meta_oauth import store_integration

    fields = dict(
        tenant_id="skincentrix",
        provider="slack",
        external_id=TEAM_ID,
        display_name=f"{TEAM_NAME} · {CHANNEL}",
        access_token=BOT_TOKEN,
        scopes=["incoming-webhook", "chat:write"],
        connected_by="slack connect link",
        channel_id=CHANNEL_ID,
        webhook_url=WEBHOOK,
    )
    fields.update(overrides)
    return await store_integration(sf, ctx.settings, fixed_clock, **fields)


async def _stored(sf):
    from spatalk.social.models import TenantIntegration

    async with sf() as s:
        return (
            await s.scalars(select(TenantIntegration).where(TenantIntegration.provider == "slack"))
        ).first()


@pytest_asyncio.fixture
async def app_ctx(sf, registry, fixed_clock):
    return await _build(sf, registry, fixed_clock)


@pytest_asyncio.fixture
async def internal(app_ctx):
    app, _ = app_ctx
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def public(app_ctx):
    app, _ = app_ctx
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.example.com") as c:
        yield c


# ----- the start url and the state ---------------------------------------------------------


def test_the_start_url_is_slacks_authorize_page_with_the_bot_scopes_and_a_signed_state():
    from spatalk.social.meta_oauth import sign_state, verify_state
    from spatalk.social.slack_oauth import build_slack_start_url

    settings = _settings()
    state = sign_state(settings.secret_key, "skincentrix", RETURN_TO)
    url = build_slack_start_url(settings, state)

    parsed = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert parsed.netloc == "slack.com" and parsed.path == "/oauth/v2/authorize"
    assert q["client_id"] == "SLACK_CLIENT_ID"
    assert q["redirect_uri"] == "https://api.example.com/slack/callback"
    assert set(q["scope"].split(",")) == {
        "incoming-webhook",
        "chat:write",
        "channels:history",
        "channels:read",
        "users:read",
    }
    claim = verify_state(settings.secret_key, q["state"])
    assert claim.tenant_id == "skincentrix" and claim.return_to == RETURN_TO
    assert "slack-client-secret" not in url


async def test_get_slack_connect_redirects_to_slack_with_a_state_naming_the_tenant(public, app_ctx):
    from spatalk.social.meta_oauth import verify_state

    _, ctx = app_ctx
    response = await public.get(
        "/slack/connect", params={"tenant": "skincentrix", "return_to": RETURN_TO}
    )

    assert response.status_code == 302
    location = urlparse(response.headers["location"])
    assert location.netloc == "slack.com" and location.path == "/oauth/v2/authorize"
    state = parse_qs(location.query)["state"][0]
    assert verify_state(ctx.settings.secret_key, state).tenant_id == "skincentrix"


# ----- the callback --------------------------------------------------------------------------


async def test_the_callback_exchanges_the_code_and_stores_the_workspace_encrypted(
    public, app_ctx, sf
):
    from spatalk.social.crypto import decrypt_token
    from spatalk.social.meta_oauth import sign_state

    _, ctx = app_ctx
    state = sign_state(ctx.settings.secret_key, "skincentrix", RETURN_TO)

    response = await public.get("/slack/callback", params={"code": "the-code", "state": state})

    assert response.status_code == 302
    assert response.headers["location"] == RETURN_TO

    exchange = ctx.graph.calls[-1]
    assert (exchange.method, exchange.path) == ("POST", "/oauth.v2.access")
    assert exchange.data == {
        "client_id": "SLACK_CLIENT_ID",
        "client_secret": "slack-client-secret",
        "code": "the-code",
        "redirect_uri": "https://api.example.com/slack/callback",
    }

    row = await _stored(sf)
    assert row is not None
    assert row.tenant_id == "skincentrix" and row.provider == "slack"
    assert row.external_id == TEAM_ID
    assert row.display_name == f"{TEAM_NAME} · {CHANNEL}"
    assert row.channel_id == CHANNEL_ID
    assert row.connected_by == "slack connect link"
    assert row.token_expires_at is None and row.needs_reconnect is False
    assert set(row.scopes) == {
        "incoming-webhook",
        "chat:write",
        "channels:history",
        "channels:read",
        "users:read",
    }
    key = ctx.settings.meta_token_encryption_key
    assert BOT_TOKEN not in row.access_token_enc
    assert decrypt_token(row.access_token_enc, key) == BOT_TOKEN
    assert WEBHOOK not in row.webhook_url_enc
    assert decrypt_token(row.webhook_url_enc, key) == WEBHOOK


async def test_the_callback_without_a_return_to_answers_in_plain_words_and_never_the_token(
    public, app_ctx
):
    from spatalk.social.meta_oauth import sign_state

    _, ctx = app_ctx
    state = sign_state(ctx.settings.secret_key, "skincentrix", None)

    response = await public.get("/slack/callback", params={"code": "the-code", "state": state})

    assert response.status_code == 200
    assert "Connected" in response.text and TEAM_NAME in response.text
    assert BOT_TOKEN not in response.text and WEBHOOK not in response.text


async def test_a_refused_exchange_stores_nothing_and_leaks_nothing(sf, registry, fixed_clock):
    from spatalk.social.meta_oauth import sign_state

    app, ctx = await _build(
        sf, registry, fixed_clock, graph_responses={EXCHANGE: {"ok": False, "error": "invalid_code"}}
    )
    state = sign_state(ctx.settings.secret_key, "skincentrix", RETURN_TO)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.example.com") as c:
        response = await c.get("/slack/callback", params={"code": "stale", "state": state})

    assert response.status_code == 400
    assert "invalid_code" in response.json()["detail"]
    assert "slack-client-secret" not in response.text
    assert await _stored(sf) is None


async def test_a_tampered_state_stores_nothing(public, app_ctx, sf):
    from spatalk.social.meta_oauth import sign_state

    _, ctx = app_ctx
    state = sign_state(ctx.settings.secret_key, "skincentrix", RETURN_TO)

    response = await public.get(
        "/slack/callback", params={"code": "the-code", "state": state[:-2] + "xy"}
    )

    assert response.status_code == 400
    assert ctx.graph.calls == []
    assert await _stored(sf) is None


async def test_a_callback_without_a_code_is_a_400(public, app_ctx):
    from spatalk.social.meta_oauth import sign_state

    _, ctx = app_ctx
    state = sign_state(ctx.settings.secret_key, "skincentrix", RETURN_TO)

    response = await public.get("/slack/callback", params={"state": state})

    assert response.status_code == 400
    assert ctx.graph.calls == []


async def test_reconnecting_replaces_the_workspace_rather_than_adding_a_second(
    public, app_ctx, sf, fixed_clock
):
    from spatalk.social.crypto import decrypt_token
    from spatalk.social.meta_oauth import sign_state
    from spatalk.social.models import TenantIntegration

    _, ctx = app_ctx
    await _connect(ctx, sf, fixed_clock, access_token="xoxb-old", channel_id="C0OLD")
    state = sign_state(ctx.settings.secret_key, "skincentrix", None)

    await public.get("/slack/callback", params={"code": "the-code", "state": state})

    async with sf() as s:
        rows = (await s.scalars(select(TenantIntegration))).all()
    assert len(rows) == 1
    assert rows[0].channel_id == CHANNEL_ID
    key = ctx.settings.meta_token_encryption_key
    assert decrypt_token(rows[0].access_token_enc, key) == BOT_TOKEN


# ----- the portal's view: /internal ----------------------------------------------------------


async def test_the_integrations_list_reports_the_workspace_without_the_token_or_the_webhook(
    internal, app_ctx, sf, fixed_clock
):
    _, ctx = app_ctx
    row = await _connect(ctx, sf, fixed_clock)

    response = await internal.get("/internal/tenants/skincentrix/integrations")

    body = response.json()
    assert [entry["provider"] for entry in body] == ["instagram", "messenger", "slack"]
    slack = next(entry for entry in body if entry["provider"] == "slack")
    assert slack["connected"] is True and slack["configured"] is True
    assert slack["external_id"] == TEAM_ID
    assert slack["display_name"] == f"{TEAM_NAME} · {CHANNEL}"
    assert slack["connected_by"] == "slack connect link"
    assert slack["token_expires_at"] is None
    for secret in (BOT_TOKEN, WEBHOOK, row.access_token_enc, row.webhook_url_enc):
        assert secret not in response.text
    # The scope word "incoming-webhook" is fine; the URL, its column and its host are not.
    assert "channel_id" not in response.text
    assert "webhook_url" not in response.text
    assert "hooks.slack.com" not in response.text


async def test_the_connect_url_for_slack_is_the_authorize_page_with_a_signed_state(
    internal, app_ctx
):
    from spatalk.social.meta_oauth import verify_state

    _, ctx = app_ctx
    body = (
        await internal.get(
            "/internal/tenants/skincentrix/integrations/slack/connect-url",
            params={"return_to": RETURN_TO},
        )
    ).json()

    parsed = urlparse(body["url"])
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://slack.com/oauth/v2/authorize"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["SLACK_CLIENT_ID"]
    assert query["redirect_uri"] == ["https://api.example.com/slack/callback"]
    assert "chat:write" in query["scope"][0]
    assert verify_state(ctx.settings.secret_key, query["state"][0]).return_to == RETURN_TO
    assert body["expires_in"] == 15 * 60


async def test_a_connect_url_is_refused_when_the_slack_app_is_not_configured(
    sf, registry, fixed_clock
):
    app, _ = await _build(sf, registry, fixed_clock, settings=_settings(slack_client_secret=""))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as c:
        response = await c.get("/internal/tenants/skincentrix/integrations/slack/connect-url")
        listed = (await c.get("/internal/tenants/skincentrix/integrations")).json()

    assert response.status_code == 409
    assert "not configured" in response.json()["detail"]
    assert next(row for row in listed if row["provider"] == "slack")["configured"] is False


# ----- disconnect ----------------------------------------------------------------------------


async def test_disconnect_revokes_the_token_and_removes_the_row(internal, app_ctx, sf, fixed_clock):
    _, ctx = app_ctx
    await _connect(ctx, sf, fixed_clock)

    body = (await internal.delete("/internal/tenants/skincentrix/integrations/slack")).json()

    assert body == {"provider": "slack", "disconnected": True, "unsubscribed": True}
    revoke = ctx.graph.calls[-1]
    assert (revoke.method, revoke.path) == ("POST", "/auth.revoke")
    assert revoke.data == {"token": BOT_TOKEN}
    assert await _stored(sf) is None


@pytest.mark.parametrize(
    "answer",
    [{"ok": False, "error": "invalid_auth"}, {"ok": False, "error": "token_revoked"}],
)
async def test_disconnect_says_so_when_slack_did_not_revoke_and_still_removes_the_row(
    sf, registry, fixed_clock, answer
):
    app, ctx = await _build(sf, registry, fixed_clock, graph_responses={REVOKE: answer})
    await _connect(ctx, sf, fixed_clock)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as c:
        body = (await c.delete("/internal/tenants/skincentrix/integrations/slack")).json()

    assert body == {"provider": "slack", "disconnected": True, "unsubscribed": False}
    assert await _stored(sf) is None


async def test_disconnect_still_removes_the_row_when_slack_cannot_be_reached(
    sf, registry, fixed_clock
):
    from spatalk.social.graph import GraphError

    app, ctx = await _build(
        sf, registry, fixed_clock, graph_responses={REVOKE: GraphError(503, "down")}
    )
    await _connect(ctx, sf, fixed_clock)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as c:
        body = (await c.delete("/internal/tenants/skincentrix/integrations/slack")).json()

    assert body["disconnected"] is True and body["unsubscribed"] is False
    assert await _stored(sf) is None


# ----- the thread relay in a clinic's own workspace --------------------------------------------


def _signed(body: str, secret: str = SIGNING_SECRET) -> dict:
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
    }


async def _sms_conversation_with_an_item(ctx, sf):
    from spatalk import jobs
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.text.service import TextConversationService

    conv = await TextConversationService(ctx, None).find_or_create_conversation(
        "skincentrix", "sms", CALLER, CALLER
    )
    cfg = await ctx.registry.get("skincentrix")
    ref = ConversationRef(conversation_id=conv.id, tenant=cfg, channel="sms", caller_phone=CALLER)
    item = await ctx.ledger.create_item(
        ref, ItemDraft(type="callback", urgency="normal", contact=ContactInfo(name="Dana", phone=CALLER))
    )
    await jobs.run_once(sf, ctx)
    return conv, item


async def test_a_staff_reply_in_a_per_tenant_thread_still_finds_its_conversation(
    sf, registry, fixed_clock
):
    """The events door keeps the one signing secret; the thread is found by channel and ts."""
    from spatalk.models import Conversation

    app, ctx = await _build(sf, registry, fixed_clock, bot=True)
    assert ctx.settings.slack_bot_token == ""
    await _connect(ctx, sf, fixed_clock)
    conv, item = await _sms_conversation_with_an_item(ctx, sf)

    # The root went to the clinic's channel with the clinic's own token, not a global one.
    assert [root[0] for root in ctx.delivery.roots] == [CHANNEL_ID]
    assert ctx.delivery.root_tokens == [BOT_TOKEN]
    root_ts = ctx.delivery.posted_ts[0]
    async with sf() as s:
        stored = await s.get(Conversation, conv.id)
    assert (stored.slack_channel, stored.slack_ts) == (CHANNEL_ID, root_ts)

    event = {
        "type": "event_callback",
        "event_id": "Ev-tenant-thread",
        "team_id": TEAM_ID,
        "event": {
            "type": "message",
            "channel": CHANNEL_ID,
            "user": "U0STAFF",
            "text": "Calling you now, Dana.",
            "ts": "1712.000900",
            "thread_ts": root_ts,
        },
    }
    body = json.dumps(event)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.example.com") as c:
        response = await c.post("/slack/events", content=body, headers=_signed(body))

    assert response.status_code == 200
    assert response.json() == {"ok": True, "relayed": str(conv.id)}
    assert ctx.sms.sent[-1][1] == CALLER and ctx.sms.sent[-1][2] == "Calling you now, Dana."
    async with sf() as s:
        assert (await s.get(Conversation, conv.id)).controller == "human"


async def test_thread_mirrors_and_notes_go_out_with_the_workspaces_own_token(
    sf, registry, fixed_clock
):
    from spatalk.text import takeover

    _, ctx = await _build(sf, registry, fixed_clock, bot=True)
    await _connect(ctx, sf, fixed_clock)
    conv, _ = await _sms_conversation_with_an_item(ctx, sf)

    await takeover.mirror_to_thread(ctx, conv.id, "Is Thursday open?", "customer")
    await takeover.hand_back(ctx, conv.id, by="U0STAFF", note=takeover.HANDBACK_NOTE.format(who="U0STAFF"))

    assert [entry[2] for entry in ctx.delivery.thread] == [
        "Customer: Is Thursday open?",
        "Handed back to the assistant by U0STAFF.",
    ]
    assert ctx.delivery.thread_tokens == [BOT_TOKEN, BOT_TOKEN]
