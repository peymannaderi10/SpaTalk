"""Task D2: the Instagram webhook, comment-to-DM and DM conversations.

Every test replays a recorded Meta payload through the real router with a real HMAC
signature. No test reaches Meta: every Graph call goes through ``FakeGraphClient``, which
records what was asked for, and every model turn goes through ``FakeLLM``.

Test names are the behaviours the plan lists for this task.
"""

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "meta"

IG_USER_ID = "17841400000000000"
SENDER_ID = "9000000000000001"
COMMENT_ID = "17900000000000001"
IG_SECRET = "ig-app-secret"
FB_SECRET = "fb-app-secret"
VERIFY_TOKEN = "the-verify-token"

MESSAGES_PATH = f"/v21.0/{IG_USER_ID}/messages"
PUBLIC_REPLY_PATH = f"/v21.0/{COMMENT_ID}/replies"
GREETING = "Hi, this is Skincentrix's assistant."


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def sign(raw: bytes, secret: str = IG_SECRET) -> str:
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
    )
    if social_settings is not None:
        cfg = await registry.get("skincentrix")
        await registry.import_config(cfg.model_copy(update={"social": social_settings}), "test")
        registry.invalidate("skincentrix")
    responses = {MESSAGES_PATH: {"message_id": "mid-out"}, PUBLIC_REPLY_PATH: {"id": "reply-1"}}
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
            provider="instagram",
            external_id=IG_USER_ID,
            display_name="skincentrix",
            access_token="IG-long-lived-token",
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


async def post_event(c, body: dict, secret: str = IG_SECRET, header: str | None = None):
    raw = json.dumps(body).encode()
    return await c.post(
        "/instagram/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": header if header is not None else sign(raw, secret),
        },
    )


async def run_jobs(ctx) -> int:
    from spatalk import jobs

    return await jobs.run_once(ctx.sf, ctx)


async def deliver(c, ctx, body: dict, secret: str = IG_SECRET):
    """The whole path a real event takes: webhook, then the job the webhook queued."""
    response = await post_event(c, body, secret)
    assert response.status_code == 200, response.text
    await run_jobs(ctx)
    return response


def sends(ctx, path: str = MESSAGES_PATH) -> list:
    return [call for call in ctx.graph.calls if call.path == path]


async def jobs_of(sf, kind="social.ig_event") -> list:
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


# ----- the routes and the handshake ------------------------------------------------------


def test_the_instagram_routes_are_on_the_app():
    from spatalk.http.app import create_app

    paths = {r.path for r in create_app(None, start_background=False).routes}
    assert {
        "/instagram/connect",
        "/instagram/callback",
        "/instagram/webhook",
        "/instagram/deauthorize",
        "/instagram/delete",
    } <= paths


async def test_the_verification_handshake_echoes_the_challenge(client):
    c, _ = client
    r = await c.get(
        "/instagram/webhook",
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
        "/instagram/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "x"},
    )
    assert r.status_code == 403


async def test_a_verification_with_the_wrong_mode_is_403(client):
    c, _ = client
    r = await c.get(
        "/instagram/webhook",
        params={"hub.mode": "unsubscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "x"},
    )
    assert r.status_code == 403


# ----- the signature ---------------------------------------------------------------------


async def test_a_bad_signature_is_401_and_nothing_is_queued(client):
    c, ctx = client
    r = await post_event(c, fixture("dm"), header="sha256=" + "0" * 64)
    assert r.status_code == 401
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []


async def test_a_missing_signature_is_401(client):
    c, ctx = client
    raw = json.dumps(fixture("dm")).encode()
    r = await c.post("/instagram/webhook", content=raw)
    assert r.status_code == 401
    assert await jobs_of(ctx.sf) == []


async def test_a_signature_from_either_app_secret_is_accepted(sf, registry, fixed_clock):
    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        assert (await post_event(c, fixture("dm"), FB_SECRET)).status_code == 200
    assert len(await jobs_of(ctx.sf)) == 1


# ----- dedup and tenant resolution -------------------------------------------------------


async def test_a_duplicate_event_id_is_enqueued_once(client):
    c, ctx = client
    assert (await post_event(c, fixture("dm"))).status_code == 200
    assert (await post_event(c, fixture("dm"))).status_code == 200
    assert len(await jobs_of(ctx.sf)) == 1


async def test_an_event_for_an_unknown_account_is_dropped(sf, registry, fixed_clock):
    app, ctx = await _build(
        sf, registry, fixed_clock, social_settings=social(), integration=False
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        assert (await post_event(c, fixture("dm"))).status_code == 200
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []


# ----- direct messages -------------------------------------------------------------------


async def test_a_dm_reaches_the_brain_and_one_send_carries_the_greeting_and_the_reply(client):
    c, ctx = client
    await deliver(c, ctx, fixture("dm"))

    calls = sends(ctx)
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].json == {
        "recipient": {"id": SENDER_ID},
        "message": {"text": f"{GREETING} We open at ten today."},
    }
    # The disclosure is on the record, once, before the customer's first message.
    texts = [(m.role, m.text) for m in await messages(ctx.sf)]
    assert texts == [
        ("assistant", GREETING),
        ("user", "Are you open Sunday?"),
        ("assistant", "We open at ten today."),
    ]


async def test_the_second_reply_in_a_conversation_is_not_prefixed_with_the_greeting(
    sf, registry, fixed_clock
):
    app, ctx = await _build(
        sf,
        registry,
        fixed_clock,
        social_settings=social(),
        replies=("We open at ten today.", "Sundays we open at one."),
    )
    second = fixture("dm")
    second["entry"][0]["messaging"][0]["message"]["mid"] = "aWdfZAG1000000009"
    second["entry"][0]["messaging"][0]["message"]["text"] = "And Sunday?"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("dm"))
        await deliver(c, ctx, second)

    calls = sends(ctx)
    assert len(calls) == 2
    assert calls[0].json["message"]["text"].startswith(GREETING)
    assert calls[1].json["message"]["text"] == "Sundays we open at one."


async def test_an_echo_is_ignored(client):
    c, ctx = client
    await deliver(c, ctx, fixture("dm_echo"))
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []
    assert await conversations(ctx.sf) == []


async def test_a_postback_and_a_read_are_stored_and_ignored(client):
    c, ctx = client
    from spatalk.social.models import MetaEvent

    await deliver(c, ctx, fixture("postback"))
    await deliver(c, ctx, fixture("read"))

    async with ctx.sf() as s:
        kinds = sorted(k for (k,) in (await s.execute(select(MetaEvent.kind))).all())
    assert kinds == ["postback", "read"]
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []


async def test_the_usage_is_metered_as_ig_in_and_ig_out(client):
    c, ctx = client
    from spatalk.models import UsageEvent

    await deliver(c, ctx, fixture("dm"))
    async with ctx.sf() as s:
        rows = list((await s.scalars(select(UsageEvent))).all())
    assert sorted(r.unit for r in rows) == ["ig_in", "ig_out"]
    assert {r.channel for r in rows} == {"instagram"}


# ----- comments --------------------------------------------------------------------------


async def test_a_comment_from_the_account_itself_is_ignored(client):
    c, ctx = client
    await deliver(c, ctx, fixture("comment_own_account"))
    assert await jobs_of(ctx.sf) == []
    assert ctx.graph.calls == []


async def test_a_keyword_comment_gets_a_private_reply(client):
    c, ctx = client
    await deliver(c, ctx, fixture("comment"))

    calls = sends(ctx)
    assert len(calls) == 1
    assert calls[0].json == {
        "recipient": {"comment_id": COMMENT_ID},
        "message": {"text": f"{GREETING} We open at ten today."},
    }
    assert sends(ctx, PUBLIC_REPLY_PATH) == []


async def test_a_keyword_comment_also_gets_the_fixed_public_reply_when_enabled(
    sf, registry, fixed_clock
):
    app, ctx = await _build(
        sf, registry, fixed_clock, social_settings=social(public=True)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("comment"))

    public = sends(ctx, PUBLIC_REPLY_PATH)
    assert len(public) == 1
    # Fixed tenant wording, never the model's.
    assert public[0].json == {"message": "Thanks! Check your DMs."}
    assert len(sends(ctx)) == 1


async def test_a_comment_without_a_keyword_is_ignored_in_keyword_mode(client):
    c, ctx = client
    await deliver(c, ctx, fixture("comment_no_keyword"))
    assert ctx.graph.calls == []
    assert await conversations(ctx.sf) == []


async def test_comment_mode_all_replies_to_any_comment(sf, registry, fixed_clock):
    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social(mode="all"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("comment_no_keyword"))
    assert len(sends(ctx)) == 1


async def test_comment_mode_off_replies_to_nothing(sf, registry, fixed_clock):
    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social(mode="off"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("comment"))
    assert ctx.graph.calls == []


async def test_a_failed_public_reply_does_not_retry_the_private_one(sf, registry, fixed_clock):
    from spatalk.social.graph import GraphError

    app, ctx = await _build(
        sf,
        registry,
        fixed_clock,
        social_settings=social(public=True),
        graph_responses={PUBLIC_REPLY_PATH: GraphError(400, "comment deleted")},
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("comment"))

    assert len(sends(ctx)) == 1
    done = await jobs_of(sf)
    assert len(done) == 1 and done[0].state == "done"


# ----- the 24-hour window ----------------------------------------------------------------


async def test_an_expired_window_sends_nothing_closes_the_conversation_and_captures_a_callback(
    client,
):
    c, ctx = client
    await deliver(c, ctx, fixture("dm_expired"))

    assert ctx.graph.calls == []
    convs = await conversations(ctx.sf)
    assert len(convs) == 1 and convs[0].closed_at is not None
    filed = await items(ctx.sf)
    assert len(filed) == 1
    assert filed[0].type == "callback"
    assert filed[0].channel == "instagram"
    # The username is the only contact Instagram gives us, and it is the only thing captured.
    assert filed[0].contact_phone is None and filed[0].contact_email is None
    assert filed[0].contact_name == SENDER_ID
    # The customer's words are on the record even though nothing was sent.
    assert ("user", "Are you open Sunday?") in [(m.role, m.text) for m in await messages(ctx.sf)]


async def test_a_second_expired_message_does_not_capture_a_second_item(client):
    c, ctx = client
    second = fixture("dm_expired")
    second["entry"][0]["messaging"][0]["message"]["mid"] = "aWdfZAG1000000010"
    await deliver(c, ctx, fixture("dm_expired"))
    await deliver(c, ctx, second)

    assert len(await items(ctx.sf)) == 1
    assert ctx.graph.calls == []


async def test_an_expired_comment_captures_the_commenter_username(client):
    c, ctx = client
    stale = fixture("comment")
    stale["entry"][0]["time"] = 1788112800
    await deliver(c, ctx, stale)

    filed = await items(ctx.sf)
    assert len(filed) == 1 and filed[0].contact_name == "dana.w"
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
        await deliver(c, ctx, fixture("dm"))

    queued = await jobs_of(sf)
    assert len(queued) == 1
    assert queued[0].state == "queued" and queued[0].attempts == 1
    assert "429" in (queued[0].last_error or "")


async def test_the_requeued_job_sends_the_reply_it_already_wrote_without_asking_again(
    sf, registry, fixed_clock
):
    from spatalk.social.graph import GraphError

    app, ctx = await _build(
        sf,
        registry,
        fixed_clock,
        social_settings=social(),
        graph_responses={MESSAGES_PATH: [GraphError(429, "slow down"), {"message_id": "ok"}]},
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        await deliver(c, ctx, fixture("dm"))
        fixed_clock.advance(minutes=5)
        await run_jobs(ctx)

    calls = sends(ctx)
    assert len(calls) == 2
    # The second attempt sent exactly what the first one wrote: the model was asked once.
    assert calls[1].json == calls[0].json
    assert len(ctx.llm.calls) == 1
    assert [m.text for m in await messages(ctx.sf) if m.role == "assistant"] == [
        GREETING,
        "We open at ten today.",
    ]
    assert (await jobs_of(sf))[0].state == "done"


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
        await deliver(c, ctx, fixture("dm"))

    dead = await jobs_of(sf)
    assert len(dead) == 1 and dead[0].state == "dead"
    assert "no matching user" in (dead[0].last_error or "")


# ----- takeover --------------------------------------------------------------------------


async def test_a_staff_reply_is_relayed_to_instagram_through_graph(client):
    c, ctx = client
    from spatalk.models import Conversation
    from spatalk.text import takeover

    await deliver(c, ctx, fixture("dm"))
    conv = (await conversations(ctx.sf))[0]
    ctx.graph.calls.clear()

    await takeover.relay_from_staff(ctx, conv.id, "On my way, calling her now", staff_id="U1")

    calls = sends(ctx)
    assert len(calls) == 1
    assert calls[0].json == {
        "recipient": {"id": SENDER_ID},
        "message": {"text": "On my way, calling her now"},
    }
    async with ctx.sf() as s:
        refreshed = await s.get(Conversation, conv.id)
    assert refreshed.controller == "human"
    assert ("staff", "On my way, calling her now") in [
        (m.role, m.text) for m in await messages(ctx.sf)
    ]


# ----- the channel rule ------------------------------------------------------------------


async def test_the_instagram_prompt_rule_caps_the_length_and_the_emoji(registry, fixed_clock):
    from spatalk.brain.prompt import build_system_prompt

    prompt = build_system_prompt(await registry.get("skincentrix"), "instagram", fixed_clock.now())
    assert "under 500 characters" in prompt
    assert "no emoji unless the customer used one" in prompt


# ----- connect, deauthorize and data deletion --------------------------------------------


async def test_the_connect_link_redirects_to_instagram_with_a_signed_state(client):
    from spatalk.social.meta_oauth import verify_state

    c, ctx = client
    r = await c.get(
        "/instagram/connect",
        params={"tenant": "skincentrix", "return_to": "https://portal/settings"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert location.startswith("https://www.instagram.com/oauth/authorize?")
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(location).query)["state"][0]
    claim = verify_state(ctx.settings.secret_key, state)
    assert claim.tenant_id == "skincentrix"
    assert claim.return_to == "https://portal/settings"


async def test_the_callback_stores_the_integration_and_returns_to_the_portal(
    sf, registry, fixed_clock
):
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.meta_oauth import sign_state
    from spatalk.social.models import TenantIntegration

    app, ctx = await _build(sf, registry, fixed_clock, social_settings=social(), integration=False)
    ctx.graph = FakeGraphClient(
        {
            "POST /oauth/access_token": {"access_token": "short", "user_id": IG_USER_ID},
            "GET /access_token": {"access_token": "long", "expires_in": 5_183_944},
            "GET /v21.0/me": {"id": IG_USER_ID, "username": "skincentrix"},
            f"POST /v21.0/{IG_USER_ID}/subscribed_apps": {"success": True},
        }
    )
    state = sign_state(ctx.settings.secret_key, "skincentrix", "https://portal/settings")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        r = await c.get(
            "/instagram/callback", params={"code": "AQB-code", "state": state},
            follow_redirects=False,
        )
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "https://portal/settings"
    async with sf() as s:
        row = (await s.scalars(select(TenantIntegration))).first()
    assert row is not None and row.external_id == IG_USER_ID
    assert "long" not in row.access_token_enc


async def test_a_tampered_callback_state_is_400(client):
    c, _ = client
    r = await c.get("/instagram/callback", params={"code": "x", "state": "not-a-state"})
    assert r.status_code == 400


async def test_deauthorize_removes_the_integration(client):
    c, ctx = client
    from spatalk.social.models import TenantIntegration

    r = await c.post(
        "/instagram/deauthorize",
        data={"signed_request": _signed_request({"user_id": IG_USER_ID})},
    )
    assert r.status_code == 200
    async with ctx.sf() as s:
        assert (await s.scalars(select(TenantIntegration))).first() is None


async def test_a_deauthorize_with_a_bad_signature_is_401(client):
    c, ctx = client
    from spatalk.social.models import TenantIntegration

    bad = _signed_request({"user_id": IG_USER_ID}, secret="not-the-secret")
    r = await c.post("/instagram/deauthorize", data={"signed_request": bad})
    assert r.status_code == 401
    async with ctx.sf() as s:
        assert (await s.scalars(select(TenantIntegration))).first() is not None


async def test_the_data_deletion_endpoint_returns_a_url_and_a_confirmation_code(client):
    c, ctx = client
    from spatalk.social.models import TenantIntegration

    r = await c.post(
        "/instagram/delete", data={"signed_request": _signed_request({"user_id": IG_USER_ID})}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("https://api.example.com/")
    assert body["confirmation_code"]
    async with ctx.sf() as s:
        assert (await s.scalars(select(TenantIntegration))).first() is None


def _signed_request(payload: dict, secret: str = IG_SECRET) -> str:
    import base64

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    body = b64(json.dumps({"algorithm": "HMAC-SHA256", **payload}).encode())
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{b64(digest)}.{body}"
