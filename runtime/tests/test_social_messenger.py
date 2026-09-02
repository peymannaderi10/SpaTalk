"""Task D3: the Facebook Page (Messenger) webhook, Page messages and feed comments.

The same matrix as Task D2, replayed against Page payloads. Every test drives the real
router with a real HMAC signature; every Graph call goes through ``FakeGraphClient`` and
every model turn through ``FakeLLM``, so no test reaches Meta.

Test names are the behaviours the plan lists for this task.
"""

import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "meta"

PAGE_ID = "1234567890"
OTHER_PAGE_ID = "1234567891"
PSID = "8000000000001"
COMMENTER_ID = "9990000000001"
COMMENT_ID = "1234567890_111"
IG_SECRET = "ig-app-secret"
FB_SECRET = "fb-app-secret"
VERIFY_TOKEN = "the-verify-token"
INTERNAL_KEY = "internal-key"

MESSAGES_PATH = f"/v21.0/{PAGE_ID}/messages"
PRIVATE_REPLY_PATH = f"/v21.0/{COMMENT_ID}/private_replies"
PUBLIC_REPLY_PATH = f"/v21.0/{COMMENT_ID}/comments"
SUBSCRIBE_PATH = f"/v21.0/{PAGE_ID}/subscribed_apps"
OTHER_SUBSCRIBE_PATH = f"/v21.0/{OTHER_PAGE_ID}/subscribed_apps"
GREETING = "Hi, this is Skincentrix's assistant."


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def sign(raw: bytes, secret: str = FB_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def social(mode="keyword", keywords=("price", "how much", "book"), public=False):
    from spatalk.tenants.schema import SocialSettings

    return SocialSettings(
        comment_mode=mode, comment_keywords=list(keywords), public_reply_enabled=public
    )


async def _build(sf, registry, fixed_clock, *, replies=("We open at ten today.",),
                 social_settings=None, graph_responses=None, integration=True):
    from cryptography.fernet import Fernet

    from spatalk import jobs
    from spatalk.brain.driver import FakeLLM, LLMResponse
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.meta_oauth import store_integration

    settings = Settings(
        secret_key="s3cret",
        public_base_url="https://api.example.com",
        instagram_app_id="IG_APP_ID",
        instagram_app_secret=IG_SECRET,
        facebook_app_id="FB_APP_ID",
        facebook_app_secret=FB_SECRET,
        instagram_webhook_verify_token=VERIFY_TOKEN,
        meta_token_encryption_key=Fernet.generate_key().decode(),
        internal_api_key=INTERNAL_KEY,
    )
    if social_settings is not None:
        cfg = await registry.get("skincentrix")
        await registry.import_config(cfg.model_copy(update={"social": social_settings}), "test")
        registry.invalidate("skincentrix")
    responses = {
        MESSAGES_PATH: {"message_id": "mid-out"},
        PRIVATE_REPLY_PATH: {"id": "private-1"},
        PUBLIC_REPLY_PATH: {"id": "public-1"},
    }
    responses.update(graph_responses or {})
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=settings,
        sms=MemorySms(),
        llm=FakeLLM([LLMResponse(text=t, tool_calls=[]) for t in replies]),
        graph=FakeGraphClient(responses),
    )
    if integration:
        await store_integration(
            sf,
            settings,
            fixed_clock,
            tenant_id="skincentrix",
            provider="messenger",
            external_id=PAGE_ID,
            display_name="Skincentrix",
            access_token="PAGE-token",
            connected_by="test",
        )
    return create_app(ctx, start_background=False), ctx


@pytest.fixture
async def app_ctx(sf, registry, fixed_clock):
    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social())
    yield app, ctx


@pytest.fixture
async def client(app_ctx):
    app, ctx = app_ctx
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        yield c, ctx


async def post_event(c, body: dict, secret: str = FB_SECRET, header: str | None = None):
    raw = json.dumps(body).encode()
    return await c.post(
        "/messenger/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": header if header is not None else sign(raw, secret),
        },
    )


async def run_jobs(ctx) -> int:
    from spatalk import jobs

    return await jobs.run_once(ctx.sf, ctx)


async def deliver(c, ctx, body: dict, secret: str = FB_SECRET):
    """The whole path a real event takes: webhook, then the job the webhook queued."""
    response = await post_event(c, body, secret)
    assert response.status_code == 200, response.text
    await run_jobs(ctx)
    return response


def sends(ctx, path: str = MESSAGES_PATH) -> list:
    return [call for call in ctx.graph.calls if call.path == path]


async def jobs_of(sf, kind="social.fb_event") -> list:
    from spatalk.models import Job

    async with sf() as s:
        return list((await s.scalars(select(Job).where(Job.kind == kind))).all())


async def conversations(sf) -> list:
    from spatalk.models import Conversation

    async with sf() as s:
        return list((await s.scalars(select(Conversation))).all())


async def items(sf) -> list:
    from spatalk.models import Item

    async with sf() as s:
        return list((await s.scalars(select(Item))).all())


async def messages(sf) -> list:
    from spatalk.models import Message

    async with sf() as s:
        return list((await s.scalars(select(Message).order_by(Message.id))).all())


async def integrations(sf) -> list:
    from spatalk.social.models import TenantIntegration

    async with sf() as s:
        return list((await s.scalars(select(TenantIntegration))).all())


# ----- the routes and the handshake ------------------------------------------------------


def test_the_messenger_routes_are_on_the_app():
    from spatalk.http.app import create_app

    paths = {r.path for r in create_app(None, start_background=False).routes}
    assert {
        "/messenger/connect",
        "/messenger/callback",
        "/messenger/webhook",
        "/internal/tenants/{tenant_id}/integrations/messenger/select",
    } <= paths


async def test_the_verification_handshake_echoes_the_challenge(client):
    c, _ = client
    r = await c.get(
        "/messenger/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1158201444",
        },
    )
    assert r.status_code == 200
    assert r.text == "1158201444"
    assert r.headers["content-type"].startswith("text/plain")


async def test_a_wrong_verify_token_is_403(client):
    c, _ = client
    r = await c.get(
        "/messenger/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "x"},
    )
    assert r.status_code == 403


# ----- the signature ---------------------------------------------------------------------


async def test_a_bad_signature_is_401_and_nothing_is_queued(client):
    c, ctx = client
    r = await post_event(c, fixture("page_message"), header="sha256=" + "0" * 64)
    assert r.status_code == 401
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []


async def test_a_signature_from_either_app_secret_is_accepted(client):
    c, ctx = client
    assert (await post_event(c, fixture("page_message"), IG_SECRET)).status_code == 200
    assert len(await jobs_of(ctx.sf)) == 1


# ----- dedup and page resolution ---------------------------------------------------------


async def test_a_duplicate_event_id_is_enqueued_once(client):
    c, ctx = client
    assert (await post_event(c, fixture("page_message"))).status_code == 200
    assert (await post_event(c, fixture("page_message"))).status_code == 200
    assert len(await jobs_of(ctx.sf)) == 1


async def test_an_event_for_an_unconnected_page_is_dropped(sf, registry, fixed_clock):
    app, ctx = await _build(
        sf, registry, fixed_clock, social_settings=social(), integration=False
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        assert (await post_event(c, fixture("page_message"))).status_code == 200
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []


# ----- page messages ---------------------------------------------------------------------


async def test_a_page_message_reaches_the_brain_and_one_send_carries_the_greeting_and_the_reply(
    client,
):
    c, ctx = client
    await deliver(c, ctx, fixture("page_message"))

    calls = sends(ctx)
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].json == {
        "recipient": {"id": PSID},
        "message": {"text": f"{GREETING} We open at ten today."},
        "messaging_type": "RESPONSE",
    }
    texts = [(m.role, m.text) for m in await messages(ctx.sf)]
    assert texts == [
        ("assistant", GREETING),
        ("user", "Are you open Sunday?"),
        ("assistant", "We open at ten today."),
    ]
    convs = await conversations(ctx.sf)
    assert len(convs) == 1
    assert convs[0].channel == "messenger" and convs[0].external_ref == PSID


async def test_an_echo_from_the_page_is_ignored(client):
    c, ctx = client
    await deliver(c, ctx, fixture("page_message_echo"))
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []
    assert await conversations(ctx.sf) == []


async def test_a_read_receipt_is_stored_and_ignored(client):
    c, ctx = client
    from spatalk.social.models import MetaEvent

    await deliver(c, ctx, fixture("page_read"))

    async with ctx.sf() as s:
        rows = list((await s.scalars(select(MetaEvent))).all())
    assert [(r.kind, r.provider) for r in rows] == [("read", "messenger")]
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []


async def test_the_usage_is_metered_as_fb_in_and_fb_out(client):
    c, ctx = client
    from spatalk.models import UsageEvent

    await deliver(c, ctx, fixture("page_message"))
    async with ctx.sf() as s:
        rows = list((await s.scalars(select(UsageEvent))).all())
    assert sorted(r.unit for r in rows) == ["fb_in", "fb_out"]
    assert {r.channel for r in rows} == {"messenger"}


# ----- feed comments ---------------------------------------------------------------------


async def test_a_comment_from_the_page_itself_is_ignored(client):
    c, ctx = client
    await deliver(c, ctx, fixture("page_feed_comment_own_page"))
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []


async def test_a_keyword_comment_gets_a_private_reply(client):
    c, ctx = client
    await deliver(c, ctx, fixture("page_feed_comment"))

    private = sends(ctx, PRIVATE_REPLY_PATH)
    assert len(private) == 1
    assert private[0].json == {"message": f"{GREETING} We open at ten today."}
    assert sends(ctx, PUBLIC_REPLY_PATH) == []
    assert sends(ctx) == []


async def test_a_keyword_comment_also_gets_the_fixed_public_comment_when_enabled(
    sf, registry, fixed_clock
):
    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social(public=True))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("page_feed_comment"))

    public = sends(ctx, PUBLIC_REPLY_PATH)
    assert len(public) == 1
    # Fixed tenant wording, never the model's.
    assert public[0].json == {"message": "Thanks! Check your DMs."}
    assert len(sends(ctx, PRIVATE_REPLY_PATH)) == 1


async def test_a_comment_without_a_keyword_is_ignored_in_keyword_mode(client):
    c, ctx = client
    await deliver(c, ctx, fixture("page_feed_comment_no_keyword"))
    assert ctx.graph.calls == []
    assert await conversations(ctx.sf) == []


async def test_comment_mode_all_replies_to_any_comment(sf, registry, fixed_clock):
    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social(mode="all"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("page_feed_comment_no_keyword"))
    assert len(ctx.graph.calls) == 1


async def test_comment_mode_off_replies_to_nothing(sf, registry, fixed_clock):
    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social(mode="off"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("page_feed_comment"))
    assert ctx.graph.calls == []


async def test_a_feed_change_that_is_not_an_added_comment_is_ignored(client):
    c, ctx = client
    from spatalk.social.models import MetaEvent

    await deliver(c, ctx, fixture("page_feed_like"))
    await deliver(c, ctx, fixture("page_feed_comment_removed"))

    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []
    async with ctx.sf() as s:
        assert list((await s.scalars(select(MetaEvent))).all()) == []


# ----- the 24-hour window ----------------------------------------------------------------


async def test_an_expired_window_sends_nothing_closes_the_conversation_and_captures_a_callback(
    client,
):
    c, ctx = client
    await deliver(c, ctx, fixture("page_message_expired"))

    assert ctx.graph.calls == []
    convs = await conversations(ctx.sf)
    assert len(convs) == 1 and convs[0].closed_at is not None
    filed = await items(ctx.sf)
    assert len(filed) == 1
    assert filed[0].type == "callback"
    assert filed[0].channel == "messenger"
    assert filed[0].contact_phone is None and filed[0].contact_email is None
    assert filed[0].contact_name == PSID
    # The customer's words are on the record even though nothing was sent.
    assert ("user", "Are you open Sunday?") in [(m.role, m.text) for m in await messages(ctx.sf)]


async def test_a_second_expired_message_does_not_capture_a_second_item(client):
    c, ctx = client
    second = fixture("page_message_expired")
    second["entry"][0]["messaging"][0]["message"]["mid"] = "m_page000000010"
    await deliver(c, ctx, fixture("page_message_expired"))
    await deliver(c, ctx, second)

    assert len(await items(ctx.sf)) == 1
    assert ctx.graph.calls == []


async def test_an_expired_comment_captures_the_commenter_name(client):
    c, ctx = client
    stale = fixture("page_feed_comment")
    stale["entry"][0]["time"] = 1788112800
    stale["entry"][0]["changes"][0]["value"]["created_time"] = 1788112800
    await deliver(c, ctx, stale)

    filed = await items(ctx.sf)
    assert len(filed) == 1 and filed[0].contact_name == "Dana W"
    assert ctx.graph.calls == []


# ----- Graph failures --------------------------------------------------------------------


async def test_a_graph_429_requeues_the_job(sf, registry, fixed_clock):
    from spatalk.social.graph import GraphError

    app, ctx = await _build(
        sf,
        registry,
        fixed_clock,
        social_settings=social(),
        graph_responses={MESSAGES_PATH: GraphError(429, "rate limited")},
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("page_message"))

    queued = await jobs_of(sf)
    assert len(queued) == 1
    assert queued[0].state == "queued" and queued[0].attempts == 1
    assert "429" in (queued[0].last_error or "")


async def test_a_graph_400_dead_letters_with_the_response_body(sf, registry, fixed_clock):
    from spatalk.social.graph import GraphError

    app, ctx = await _build(
        sf,
        registry,
        fixed_clock,
        social_settings=social(),
        graph_responses={MESSAGES_PATH: GraphError(400, "(#100) no matching user")},
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("page_message"))

    dead = await jobs_of(sf)
    assert len(dead) == 1 and dead[0].state == "dead"
    assert "no matching user" in (dead[0].last_error or "")


# ----- takeover --------------------------------------------------------------------------


async def test_a_staff_reply_is_relayed_to_the_page_through_graph(client):
    c, ctx = client
    from spatalk.models import Conversation
    from spatalk.text import takeover

    await deliver(c, ctx, fixture("page_message"))
    conv = (await conversations(ctx.sf))[0]
    ctx.graph.calls.clear()

    await takeover.relay_from_staff(ctx, conv.id, "On my way, calling her now", staff_id="U1")

    calls = sends(ctx)
    assert len(calls) == 1
    assert calls[0].json == {
        "recipient": {"id": PSID},
        "message": {"text": "On my way, calling her now"},
        "messaging_type": "RESPONSE",
    }
    async with ctx.sf() as s:
        refreshed = await s.get(Conversation, conv.id)
    assert refreshed.controller == "human"
    assert ("staff", "On my way, calling her now") in [
        (m.role, m.text) for m in await messages(ctx.sf)
    ]


# ----- the channel rule ------------------------------------------------------------------


async def test_the_messenger_prompt_rule_caps_the_length_and_the_emoji(registry, fixed_clock):
    from spatalk.brain.prompt import build_system_prompt

    prompt = build_system_prompt(await registry.get("skincentrix"), "messenger", fixed_clock.now())
    assert "under 500 characters" in prompt
    assert "no emoji unless the customer used one" in prompt


# ----- connecting a page ------------------------------------------------------------------


def _oauth_responses(pages: list[dict]) -> dict:
    return {
        "GET /v21.0/oauth/access_token": {"access_token": "user-token", "expires_in": 5_183_944},
        "GET /v21.0/me/accounts": {"data": pages},
        SUBSCRIBE_PATH: {"success": True},
        OTHER_SUBSCRIBE_PATH: {"success": True},
    }


ONE_PAGE = [{"id": PAGE_ID, "name": "Skincentrix", "access_token": "page-token"}]
TWO_PAGES = ONE_PAGE + [
    {"id": OTHER_PAGE_ID, "name": "Skincentrix Training", "access_token": "other-page-token"}
]


async def test_the_connect_link_redirects_to_facebook_with_a_signed_state(client):
    from spatalk.social.meta_oauth import verify_state

    c, ctx = client
    r = await c.get(
        "/messenger/connect",
        params={"tenant": "skincentrix", "return_to": "https://portal/settings"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert location.startswith("https://www.facebook.com/v21.0/dialog/oauth?")
    state = parse_qs(urlparse(location).query)["state"][0]
    claim = verify_state(ctx.settings.secret_key, state)
    assert claim.tenant_id == "skincentrix"
    assert claim.return_to == "https://portal/settings"


async def test_a_callback_with_one_page_stores_and_subscribes_it(sf, registry, fixed_clock):
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.meta_oauth import sign_state

    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social(), integration=False)
    ctx.graph = FakeGraphClient(_oauth_responses(ONE_PAGE))
    state = sign_state(ctx.settings.secret_key, "skincentrix", "https://portal/settings")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        r = await c.get(
            "/messenger/callback",
            params={"code": "AQB-code", "state": state},
            follow_redirects=False,
        )
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "https://portal/settings"
    rows = await integrations(sf)
    assert len(rows) == 1
    assert rows[0].provider == "messenger" and rows[0].external_id == PAGE_ID
    assert "page-token" not in rows[0].access_token_enc
    subscribed = [call for call in ctx.graph.calls if call.path == SUBSCRIBE_PATH]
    assert len(subscribed) == 1
    assert subscribed[0].params["subscribed_fields"] == "messages,feed"


async def test_a_callback_with_two_pages_stores_nothing_and_offers_the_choices(
    sf, registry, fixed_clock
):
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.meta_oauth import sign_state

    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social(), integration=False)
    ctx.graph = FakeGraphClient(_oauth_responses(TWO_PAGES))
    state = sign_state(ctx.settings.secret_key, "skincentrix", "https://portal/settings")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        r = await c.get(
            "/messenger/callback",
            params={"code": "AQB-code", "state": state},
            follow_redirects=False,
        )
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert location.startswith("https://portal/settings")
    query = parse_qs(urlparse(location).query)
    offered = json.loads(query["messenger_pages"][0])
    assert [p["id"] for p in offered] == [PAGE_ID, OTHER_PAGE_ID]
    assert [p["name"] for p in offered] == ["Skincentrix", "Skincentrix Training"]
    # A page access token never travels through the browser.
    assert "access_token" not in location
    assert all("access_token" not in p for p in offered)
    assert query["messenger_pending"][0]
    # Nothing is connected until a person chooses.
    assert await integrations(sf) == []
    assert [call for call in ctx.graph.calls if "subscribed_apps" in call.path] == []


async def _pending_handle(sf, registry, fixed_clock):
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.meta_oauth import sign_state

    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social(), integration=False)
    ctx.graph = FakeGraphClient(_oauth_responses(TWO_PAGES))
    state = sign_state(ctx.settings.secret_key, "skincentrix", "https://portal/settings")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        r = await c.get(
            "/messenger/callback",
            params={"code": "AQB-code", "state": state},
            follow_redirects=False,
        )
    query = parse_qs(urlparse(r.headers["location"]).query)
    return app, ctx, query["messenger_pending"][0]


async def test_selecting_a_page_stores_and_subscribes_the_chosen_one(sf, registry, fixed_clock):
    app, ctx, handle = await _pending_handle(sf, registry, fixed_clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        r = await c.post(
            "/internal/tenants/skincentrix/integrations/messenger/select",
            json={"pending": handle, "page_id": OTHER_PAGE_ID},
            headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": "owner@example.com"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["external_id"] == OTHER_PAGE_ID
    assert body["display_name"] == "Skincentrix Training"
    assert "access_token" not in json.dumps(body)
    rows = await integrations(sf)
    assert len(rows) == 1 and rows[0].external_id == OTHER_PAGE_ID
    assert "other-page-token" not in rows[0].access_token_enc
    subscribed = [call for call in ctx.graph.calls if call.path == OTHER_SUBSCRIBE_PATH]
    assert len(subscribed) == 1


async def test_a_selection_handle_can_only_be_used_once(sf, registry, fixed_clock):
    app, _, handle = await _pending_handle(sf, registry, fixed_clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        first = await c.post(
            "/internal/tenants/skincentrix/integrations/messenger/select",
            json={"pending": handle, "page_id": PAGE_ID},
            headers={"X-Internal-Key": INTERNAL_KEY},
        )
        second = await c.post(
            "/internal/tenants/skincentrix/integrations/messenger/select",
            json={"pending": handle, "page_id": PAGE_ID},
            headers={"X-Internal-Key": INTERNAL_KEY},
        )
    assert first.status_code == 200
    assert second.status_code == 400


async def test_selecting_with_an_unknown_handle_is_400(client):
    c, _ = client
    r = await c.post(
        "/internal/tenants/skincentrix/integrations/messenger/select",
        json={"pending": "not-a-handle", "page_id": PAGE_ID},
        headers={"X-Internal-Key": INTERNAL_KEY},
    )
    assert r.status_code == 400


async def test_selecting_a_page_that_was_not_offered_is_400(sf, registry, fixed_clock):
    app, _, handle = await _pending_handle(sf, registry, fixed_clock)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        r = await c.post(
            "/internal/tenants/skincentrix/integrations/messenger/select",
            json={"pending": handle, "page_id": "999999"},
            headers={"X-Internal-Key": INTERNAL_KEY},
        )
    assert r.status_code == 400
    assert await integrations(sf) == []


async def test_the_select_endpoint_refuses_a_request_without_the_internal_key(client):
    c, _ = client
    r = await c.post(
        "/internal/tenants/skincentrix/integrations/messenger/select",
        json={"pending": "anything", "page_id": PAGE_ID},
    )
    assert r.status_code == 401


async def test_a_tampered_callback_state_is_400(client):
    c, _ = client
    r = await c.get("/messenger/callback", params={"code": "x", "state": "not-a-state"})
    assert r.status_code == 400
