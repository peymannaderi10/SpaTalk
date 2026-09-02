"""Task D1: the Meta OAuth flows, encrypted token storage and the daily refresh job.

Every test names a behaviour the plan lists. No test touches the network: every Graph call
goes through :class:`spatalk.social.graph.FakeGraphClient`, which records what was asked for
and answers from a fixture table.
"""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select

IG_USER_ID = "17841400000000000"
PAGE_ID = "1234567890"
SECOND_PAGE_ID = "9876543210"
SHORT_TOKEN = "IGQVJshort-code-token"
LONG_TOKEN = "IGQVJlong-lived-token"
PAGE_TOKEN = "EAAGpage-token"
USER_TOKEN = "EAAGuser-token"


@pytest.fixture
def settings():
    from spatalk.settings import Settings

    return Settings(
        secret_key="s3cret",
        public_base_url="https://api.example.com",
        instagram_app_id="IG_APP_ID",
        instagram_app_secret="ig-app-secret",
        facebook_app_id="FB_APP_ID",
        facebook_app_secret="fb-app-secret",
        meta_token_encryption_key=Fernet.generate_key().decode(),
    )


def _instagram_client(**overrides):
    from spatalk.social.graph import FakeGraphClient

    responses = {
        "POST /oauth/access_token": {
            "access_token": SHORT_TOKEN,
            "user_id": IG_USER_ID,
            "permissions": ["instagram_business_basic", "instagram_business_manage_messages"],
        },
        "GET /access_token": {
            "access_token": LONG_TOKEN,
            "token_type": "bearer",
            "expires_in": 5_183_944,
        },
        "GET /v21.0/me": {"id": IG_USER_ID, "username": "skincentrix"},
        f"POST /v21.0/{IG_USER_ID}/subscribed_apps": {"success": True},
    }
    responses.update(overrides)
    return FakeGraphClient(responses)


def _page_client(pages=None, **overrides):
    from spatalk.social.graph import FakeGraphClient

    pages = pages if pages is not None else [
        {"id": PAGE_ID, "name": "Skincentrix", "access_token": PAGE_TOKEN}
    ]
    responses = {
        "GET /v21.0/oauth/access_token": {
            "access_token": USER_TOKEN,
            "token_type": "bearer",
            "expires_in": 5_184_000,
        },
        "GET /v21.0/me/accounts": {"data": pages},
        f"POST /v21.0/{PAGE_ID}/subscribed_apps": {"success": True},
        f"POST /v21.0/{SECOND_PAGE_ID}/subscribed_apps": {"success": True},
    }
    responses.update(overrides)
    return FakeGraphClient(responses)


async def _ctx(sf, registry, fixed_clock, settings, graph=None):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger

    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=settings,
        graph=graph,
    )


async def _stored(sf, provider="instagram"):
    from spatalk.social.models import TenantIntegration

    async with sf() as s:
        return (
            await s.scalars(
                select(TenantIntegration).where(TenantIntegration.provider == provider)
            )
        ).first()


# ----- signed state ----------------------------------------------------------------------


def test_the_instagram_start_url_carries_the_scopes_and_a_signed_state(settings):
    from spatalk.social import meta_oauth

    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", "https://portal/settings")
    url = meta_oauth.build_instagram_start_url(settings, state)

    parsed = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert parsed.netloc == "www.instagram.com" and parsed.path == "/oauth/authorize"
    assert q["client_id"] == "IG_APP_ID"
    assert q["redirect_uri"] == "https://api.example.com/instagram/callback"
    assert q["response_type"] == "code"
    assert set(q["scope"].split(",")) == {
        "instagram_business_basic",
        "instagram_business_manage_messages",
        "instagram_business_manage_comments",
        "instagram_business_manage_insights",
    }
    assert meta_oauth.verify_state(settings.secret_key, q["state"]).tenant_id == "skincentrix"


def test_the_page_start_url_carries_the_page_scopes_and_a_signed_state(settings):
    from spatalk.social import meta_oauth

    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", None)
    url = meta_oauth.build_page_start_url(settings, state)

    parsed = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert parsed.netloc == "www.facebook.com"
    assert q["client_id"] == "FB_APP_ID"
    assert q["redirect_uri"] == "https://api.example.com/messenger/callback"
    assert set(q["scope"].split(",")) == {
        "pages_messaging",
        "pages_manage_metadata",
        "pages_read_engagement",
        "pages_show_list",
    }
    assert meta_oauth.verify_state(settings.secret_key, q["state"]).return_to is None


def test_the_state_round_trips_the_tenant_and_the_return_url(settings):
    from spatalk.social import meta_oauth

    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", "https://portal/x")
    claim = meta_oauth.verify_state(settings.secret_key, state)
    assert claim.tenant_id == "skincentrix"
    assert claim.return_to == "https://portal/x"


def test_a_tampered_state_is_rejected_with_400(settings):
    from spatalk.social import meta_oauth

    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", None)
    with pytest.raises(HTTPException) as exc:
        meta_oauth.verify_state(settings.secret_key, state[:-2] + "xy")
    assert exc.value.status_code == 400


def test_a_state_older_than_fifteen_minutes_is_rejected_with_400(settings):
    from spatalk.social import meta_oauth

    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", None)
    with pytest.raises(HTTPException) as exc:
        meta_oauth.verify_state(settings.secret_key, state, max_age_seconds=-1)
    assert exc.value.status_code == 400


# ----- the Instagram callback ------------------------------------------------------------


async def test_the_instagram_callback_stores_an_encrypted_token_and_the_ig_user_id(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth
    from spatalk.social.crypto import decrypt_token

    client = _instagram_client()
    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", "https://portal/settings")
    result = await meta_oauth.complete_instagram_connect(
        sf,
        settings,
        fixed_clock,
        code="AQB-authorization-code",
        state=state,
        connected_by="owner@example.com",
        client=client,
    )

    assert result.tenant_id == "skincentrix"
    assert result.external_id == IG_USER_ID
    assert result.display_name == "skincentrix"
    assert result.return_to == "https://portal/settings"

    row = await _stored(sf)
    assert row.tenant_id == "skincentrix" and row.provider == "instagram"
    assert row.external_id == IG_USER_ID
    assert LONG_TOKEN not in row.access_token_enc
    assert decrypt_token(row.access_token_enc, settings.meta_token_encryption_key) == LONG_TOKEN
    assert row.token_expires_at == fixed_clock.now() + timedelta(seconds=5_183_944)
    assert row.connected_by == "owner@example.com"
    assert row.needs_reconnect is False
    assert "instagram_business_manage_messages" in row.scopes


async def test_the_instagram_callback_exchanges_short_for_long_and_subscribes_the_fields(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth

    client = _instagram_client()
    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", None)
    await meta_oauth.complete_instagram_connect(
        sf,
        settings,
        fixed_clock,
        code="AQB-authorization-code",
        state=state,
        connected_by="owner@example.com",
        client=client,
    )

    paths = [f"{c.method} {c.path}" for c in client.calls]
    assert paths == [
        "POST /oauth/access_token",
        "GET /access_token",
        "GET /v21.0/me",
        f"POST /v21.0/{IG_USER_ID}/subscribed_apps",
    ]
    exchange = client.calls[0]
    assert exchange.data["code"] == "AQB-authorization-code"
    assert exchange.data["grant_type"] == "authorization_code"
    assert exchange.data["client_secret"] == "ig-app-secret"
    assert exchange.data["redirect_uri"] == "https://api.example.com/instagram/callback"
    long_lived = client.calls[1]
    assert long_lived.params["grant_type"] == "ig_exchange_token"
    assert long_lived.params["access_token"] == SHORT_TOKEN
    subscribe = client.calls[3]
    assert set(subscribe.params["subscribed_fields"].split(",")) == {"comments", "messages"}
    assert subscribe.params["access_token"] == LONG_TOKEN


async def test_a_tampered_callback_state_stores_nothing(sf, registry, fixed_clock, settings):
    from spatalk.social import meta_oauth

    client = _instagram_client()
    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", None)
    with pytest.raises(HTTPException) as exc:
        await meta_oauth.complete_instagram_connect(
            sf,
            settings,
            fixed_clock,
            code="AQB-authorization-code",
            state=state[:-2] + "xy",
            connected_by="owner@example.com",
            client=client,
        )
    assert exc.value.status_code == 400
    assert client.calls == []
    assert await _stored(sf) is None


async def test_reconnecting_replaces_the_stored_token_and_clears_needs_reconnect(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth
    from spatalk.social.crypto import decrypt_token

    await meta_oauth.store_integration(
        sf,
        settings,
        fixed_clock,
        tenant_id="skincentrix",
        provider="instagram",
        external_id=IG_USER_ID,
        display_name="skincentrix",
        access_token="stale-token",
        token_expires_at=fixed_clock.now() - timedelta(days=1),
        scopes=["instagram_business_basic"],
        connected_by="owner@example.com",
        needs_reconnect=True,
    )

    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", None)
    await meta_oauth.complete_instagram_connect(
        sf,
        settings,
        fixed_clock,
        code="AQB-authorization-code",
        state=state,
        connected_by="owner2@example.com",
        client=_instagram_client(),
    )

    from spatalk.social.models import TenantIntegration

    async with sf() as s:
        rows = list((await s.scalars(select(TenantIntegration))).all())
    assert len(rows) == 1, "one integration per (tenant, provider)"
    assert decrypt_token(rows[0].access_token_enc, settings.meta_token_encryption_key) == (
        LONG_TOKEN
    )
    assert rows[0].needs_reconnect is False
    assert rows[0].connected_by == "owner2@example.com"


# ----- the Facebook Page callback ---------------------------------------------------------


async def test_a_single_page_is_stored_and_subscribed_to_messages_and_feed(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth
    from spatalk.social.crypto import decrypt_token

    client = _page_client()
    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", None)
    result = await meta_oauth.complete_page_connect(
        sf,
        settings,
        fixed_clock,
        code="AQB-page-code",
        state=state,
        connected_by="owner@example.com",
        client=client,
    )

    assert result.external_id == PAGE_ID
    assert result.display_name == "Skincentrix"
    row = await _stored(sf, provider="messenger")
    assert decrypt_token(row.access_token_enc, settings.meta_token_encryption_key) == PAGE_TOKEN
    subscribe = client.calls[-1]
    assert subscribe.path == f"/v21.0/{PAGE_ID}/subscribed_apps"
    assert set(subscribe.params["subscribed_fields"].split(",")) == {"messages", "feed"}
    assert subscribe.params["access_token"] == PAGE_TOKEN


async def test_several_pages_return_the_choices_and_store_nothing(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth

    client = _page_client(
        pages=[
            {"id": PAGE_ID, "name": "Skincentrix", "access_token": PAGE_TOKEN},
            {"id": SECOND_PAGE_ID, "name": "Skincentrix Training", "access_token": "EAAG2"},
        ]
    )
    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", "https://portal/settings")
    result = await meta_oauth.complete_page_connect(
        sf,
        settings,
        fixed_clock,
        code="AQB-page-code",
        state=state,
        connected_by="owner@example.com",
        client=client,
    )

    assert [p["id"] for p in result.pages] == [PAGE_ID, SECOND_PAGE_ID]
    assert result.return_to == "https://portal/settings"
    assert await _stored(sf, provider="messenger") is None
    assert not any("subscribed_apps" in c.path for c in client.calls)


async def test_choosing_one_of_several_pages_stores_that_page(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth

    client = _page_client(
        pages=[
            {"id": PAGE_ID, "name": "Skincentrix", "access_token": PAGE_TOKEN},
            {"id": SECOND_PAGE_ID, "name": "Skincentrix Training", "access_token": "EAAG2"},
        ]
    )
    state = meta_oauth.sign_state(settings.secret_key, "skincentrix", None)
    result = await meta_oauth.complete_page_connect(
        sf,
        settings,
        fixed_clock,
        code="AQB-page-code",
        state=state,
        connected_by="owner@example.com",
        page_id=SECOND_PAGE_ID,
        client=client,
    )

    assert result.external_id == SECOND_PAGE_ID
    row = await _stored(sf, provider="messenger")
    assert row.external_id == SECOND_PAGE_ID and row.display_name == "Skincentrix Training"


# ----- the daily refresh job ---------------------------------------------------------------


async def _integration(sf, settings, clock, *, provider="instagram", days, token="LONG-LIVED"):
    from spatalk.social import meta_oauth

    return await meta_oauth.store_integration(
        sf,
        settings,
        clock,
        tenant_id="skincentrix",
        provider=provider,
        external_id=IG_USER_ID if provider == "instagram" else PAGE_ID,
        display_name="skincentrix",
        access_token=token,
        token_expires_at=clock.now() + timedelta(days=days),
        scopes=["instagram_business_basic"],
        connected_by="owner@example.com",
    )


async def test_the_refresh_job_refreshes_only_near_expiry_tokens(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth
    from spatalk.social.crypto import decrypt_token
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.models import TenantIntegration

    near = await _integration(sf, settings, fixed_clock, days=10, token="NEAR-TOKEN")
    # (tenant, provider) is unique, so the far-from-expiry one is the tenant's page.
    far = await _integration(
        sf, settings, fixed_clock, provider="messenger", days=90, token="FAR-TOKEN"
    )
    client = FakeGraphClient(
        {
            "GET /refresh_access_token": {
                "access_token": "REFRESHED-TOKEN",
                "token_type": "bearer",
                "expires_in": 5_183_944,
            }
        }
    )
    ctx = await _ctx(sf, registry, fixed_clock, settings, graph=client)

    await meta_oauth.refresh_tokens({}, ctx)

    assert [f"{c.method} {c.path}" for c in client.calls] == ["GET /refresh_access_token"]
    assert client.calls[0].params["grant_type"] == "ig_refresh_token"
    assert client.calls[0].params["access_token"] == "NEAR-TOKEN"
    async with sf() as s:
        refreshed = await s.get(TenantIntegration, near.id)
        untouched = await s.get(TenantIntegration, far.id)
    key = settings.meta_token_encryption_key
    assert decrypt_token(refreshed.access_token_enc, key) == "REFRESHED-TOKEN"
    assert refreshed.token_expires_at == fixed_clock.now() + timedelta(seconds=5_183_944)
    assert refreshed.needs_reconnect is False
    assert decrypt_token(untouched.access_token_enc, key) == "FAR-TOKEN"


async def test_a_refresh_failure_marks_needs_reconnect_and_emails_the_owner(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth
    from spatalk.social.crypto import decrypt_token
    from spatalk.social.graph import FakeGraphClient, GraphError
    from spatalk.social.models import TenantIntegration

    near = await _integration(sf, settings, fixed_clock, days=3, token="NEAR-TOKEN")
    client = FakeGraphClient(
        {"GET /refresh_access_token": GraphError(400, '{"error": {"message": "expired"}}')}
    )
    ctx = await _ctx(sf, registry, fixed_clock, settings, graph=client)

    await meta_oauth.refresh_tokens({}, ctx)

    async with sf() as s:
        row = await s.get(TenantIntegration, near.id)
    assert row.needs_reconnect is True
    assert decrypt_token(row.access_token_enc, settings.meta_token_encryption_key) == "NEAR-TOKEN"
    assert len(ctx.delivery.emails) == 1
    to, subject, body = ctx.delivery.emails[0]
    assert to == "info@skincentrix.com"
    assert "instagram" in subject.lower() or "instagram" in body.lower()
    assert "NEAR-TOKEN" not in body, "a token never appears in an email"


async def test_a_page_token_near_expiry_asks_for_a_reconnect_instead_of_refreshing(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.models import TenantIntegration

    row = await _integration(sf, settings, fixed_clock, provider="messenger", days=5)
    client = FakeGraphClient({})
    ctx = await _ctx(sf, registry, fixed_clock, settings, graph=client)

    await meta_oauth.refresh_tokens({}, ctx)

    assert client.calls == [], "a page token cannot be refreshed with ig_refresh_token"
    async with sf() as s:
        stored = await s.get(TenantIntegration, row.id)
    assert stored.needs_reconnect is True
    assert len(ctx.delivery.emails) == 1


async def test_an_integration_already_needing_a_reconnect_is_not_retried(
    sf, registry, fixed_clock, settings
):
    from spatalk.social import meta_oauth
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.models import TenantIntegration

    row = await _integration(sf, settings, fixed_clock, days=2)
    async with sf() as s, s.begin():
        stored = await s.get(TenantIntegration, row.id)
        stored.needs_reconnect = True
    client = FakeGraphClient({})
    ctx = await _ctx(sf, registry, fixed_clock, settings, graph=client)

    await meta_oauth.refresh_tokens({}, ctx)

    assert client.calls == []
    assert ctx.delivery.emails == []


async def test_the_refresh_job_is_scheduled_once_a_day(sf, registry, fixed_clock, settings):
    from spatalk.models import Job
    from spatalk.social import meta_oauth

    assert await meta_oauth.ensure_daily_refresh_scheduled(sf, fixed_clock) is True
    assert await meta_oauth.ensure_daily_refresh_scheduled(sf, fixed_clock) is False

    async with sf() as s:
        kinds = list((await s.scalars(select(Job.kind))).all())
    assert kinds == ["social.refresh_tokens"]


# ----- the real Graph client ----------------------------------------------------------------


async def test_the_http_client_sends_the_bearer_token_and_returns_the_json():
    import httpx

    from spatalk.social.graph import HttpGraphClient

    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": IG_USER_ID})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = HttpGraphClient(
            "https://graph.instagram.com", lambda: "LONG-LIVED", client=http
        )
        assert await client.get("/v21.0/me", params={"fields": "id"}) == {"id": IG_USER_ID}
    assert seen["url"] == "https://graph.instagram.com/v21.0/me?fields=id"
    assert seen["auth"] == "Bearer LONG-LIVED"


async def test_a_rate_limited_graph_call_is_retryable_and_a_4xx_is_not():
    import httpx

    from spatalk.social.graph import GraphError, HttpGraphClient

    for status, retryable in ((429, True), (500, True), (400, False)):
        transport = httpx.MockTransport(
            lambda request, status=status: httpx.Response(status, text='{"error": "no"}')
        )
        async with httpx.AsyncClient(transport=transport) as http:
            client = HttpGraphClient("https://graph.instagram.com", client=http)
            with pytest.raises(GraphError) as exc:
                await client.post("/v21.0/1/messages", json={"message": {"text": "hi"}})
        assert exc.value.status_code == status
        assert exc.value.retryable is retryable
        assert '{"error": "no"}' in exc.value.body


async def test_the_fake_client_refuses_a_call_nobody_stubbed():
    from spatalk.social.graph import FakeGraphClient, GraphError

    client = FakeGraphClient({})
    with pytest.raises(GraphError):
        await client.get("/v21.0/me")
