"""Task D4: the portal's view of a tenant's Meta integrations, over `/internal/*`.

The portal owns no social data and never speaks to Meta itself (CLAUDE.md non-negotiable 7);
the Integrations page is drawn from these three endpoints and nothing else. Every test here
is named after a behaviour in the task's Behaviour list. No test reaches Meta: the
unsubscribe goes through `FakeGraphClient`, which records what was asked for.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

INTERNAL_KEY = "test-internal-key"
ACTOR = "owner@skincentrix.test"
IG_USER_ID = "17841400000000000"
PAGE_ID = "1234567890"
RETURN_TO = "https://portal.example.com/app/skincentrix/settings"

IG_UNSUBSCRIBE_PATH = f"/v21.0/{IG_USER_ID}/subscribed_apps"
PAGE_UNSUBSCRIBE_PATH = f"/v21.0/{PAGE_ID}/subscribed_apps"


def _settings(**overrides):
    from cryptography.fernet import Fernet

    from spatalk.settings import Settings

    values = dict(
        secret_key="s3cret",
        public_base_url="https://api.example.com",
        internal_api_key=INTERNAL_KEY,
        instagram_app_id="IG_APP_ID",
        instagram_app_secret="ig-app-secret",
        facebook_app_id="FB_APP_ID",
        facebook_app_secret="fb-app-secret",
        meta_token_encryption_key=Fernet.generate_key().decode(),
    )
    values.update(overrides)
    return Settings(**values)


async def _build(sf, registry, fixed_clock, *, settings=None, graph_responses=None):
    from spatalk import jobs
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.social.graph import FakeGraphClient

    settings = settings or _settings()
    responses = {IG_UNSUBSCRIBE_PATH: {"success": True}, PAGE_UNSUBSCRIBE_PATH: {"success": True}}
    responses.update(graph_responses or {})
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=settings,
        graph=FakeGraphClient(responses),
    )
    return create_app(ctx, start_background=False), ctx


async def _connect(ctx, sf, fixed_clock, provider="instagram", **overrides):
    from spatalk.social.meta_oauth import store_integration

    fields = dict(
        tenant_id="skincentrix",
        provider=provider,
        external_id=IG_USER_ID if provider == "instagram" else PAGE_ID,
        display_name="skincentrix" if provider == "instagram" else "Skincentrix Medspa",
        access_token="a-long-lived-token",
        token_expires_at=fixed_clock.now().replace(microsecond=0),
        scopes=["instagram_business_basic"],
        connected_by="owner@skincentrix.test",
    )
    fields.update(overrides)
    return await store_integration(sf, ctx.settings, fixed_clock, **fields)


@pytest_asyncio.fixture
async def app_ctx(sf, registry, fixed_clock):
    return await _build(sf, registry, fixed_clock)


@pytest_asyncio.fixture
async def client(app_ctx):
    app, _ = app_ctx
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as c:
        yield c


# ----- status ------------------------------------------------------------------------------


async def test_both_providers_are_listed_as_not_connected_before_anyone_connects(client):
    body = (await client.get("/internal/tenants/skincentrix/integrations")).json()

    assert [row["provider"] for row in body] == ["instagram", "messenger"]
    assert all(row["connected"] is False for row in body)
    assert all(row["display_name"] is None for row in body)
    assert all(row["configured"] is True for row in body)


async def test_a_connected_account_is_reported_with_its_name_expiry_and_scopes(
    client, app_ctx, sf, fixed_clock
):
    _, ctx = app_ctx
    await _connect(ctx, sf, fixed_clock)

    body = (await client.get("/internal/tenants/skincentrix/integrations")).json()
    instagram = next(row for row in body if row["provider"] == "instagram")

    assert instagram["connected"] is True
    assert instagram["external_id"] == IG_USER_ID
    assert instagram["display_name"] == "skincentrix"
    assert instagram["token_expires_at"].startswith("2026-09-01")
    assert instagram["scopes"] == ["instagram_business_basic"]
    assert instagram["needs_reconnect"] is False
    assert instagram["connected_by"] == "owner@skincentrix.test"
    assert next(row for row in body if row["provider"] == "messenger")["connected"] is False


async def test_the_status_never_carries_the_token_in_any_form(client, app_ctx, sf, fixed_clock):
    _, ctx = app_ctx
    row = await _connect(ctx, sf, fixed_clock)
    ciphertext = row.access_token_enc

    response = await client.get("/internal/tenants/skincentrix/integrations")

    assert "access_token" not in response.text
    assert ciphertext not in response.text
    assert "a-long-lived-token" not in response.text


async def test_a_token_the_refresh_job_could_not_renew_is_reported_as_needing_a_reconnect(
    client, app_ctx, sf, fixed_clock
):
    _, ctx = app_ctx
    await _connect(ctx, sf, fixed_clock, needs_reconnect=True)

    body = (await client.get("/internal/tenants/skincentrix/integrations")).json()

    assert next(row for row in body if row["provider"] == "instagram")["needs_reconnect"] is True


async def test_a_provider_this_runtime_has_no_app_for_is_reported_as_unconfigured(
    sf, registry, fixed_clock
):
    app, _ = await _build(
        sf, registry, fixed_clock, settings=_settings(facebook_app_id="", facebook_app_secret="")
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as client:
        body = (await client.get("/internal/tenants/skincentrix/integrations")).json()

    assert next(row for row in body if row["provider"] == "messenger")["configured"] is False
    assert next(row for row in body if row["provider"] == "instagram")["configured"] is True


async def test_the_integrations_of_an_unknown_tenant_are_a_404(client):
    assert (await client.get("/internal/tenants/nobody/integrations")).status_code == 404


# ----- the connect url ---------------------------------------------------------------------


async def test_the_connect_url_is_the_instagram_authorize_url_with_the_scopes_and_a_state(client):
    from urllib.parse import parse_qs, urlparse

    body = (
        await client.get(
            "/internal/tenants/skincentrix/integrations/instagram/connect-url",
            params={"return_to": RETURN_TO},
        )
    ).json()

    parsed = urlparse(body["url"])
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://www.instagram.com/oauth/authorize"
    )
    assert query["client_id"] == ["IG_APP_ID"]
    assert query["redirect_uri"] == ["https://api.example.com/instagram/callback"]
    assert "instagram_business_manage_messages" in query["scope"][0]
    assert body["expires_in"] == 15 * 60


async def test_the_signed_state_carries_the_tenant_and_the_return_to_back(client, app_ctx):
    from urllib.parse import parse_qs, urlparse

    from spatalk.social.meta_oauth import verify_state

    _, ctx = app_ctx
    body = (
        await client.get(
            "/internal/tenants/skincentrix/integrations/instagram/connect-url",
            params={"return_to": RETURN_TO},
        )
    ).json()

    state = parse_qs(urlparse(body["url"]).query)["state"][0]
    verified = verify_state(ctx.settings.secret_key, state)

    assert verified.tenant_id == "skincentrix"
    assert verified.return_to == RETURN_TO


async def test_the_page_connect_url_is_the_facebook_dialog_with_the_page_scopes(client):
    from urllib.parse import parse_qs, urlparse

    body = (
        await client.get(
            "/internal/tenants/skincentrix/integrations/messenger/connect-url",
            params={"return_to": RETURN_TO},
        )
    ).json()

    parsed = urlparse(body["url"])
    assert parsed.netloc == "www.facebook.com"
    assert parsed.path == "/v21.0/dialog/oauth"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["FB_APP_ID"]
    assert "pages_messaging" in query["scope"][0]
    assert query["redirect_uri"] == ["https://api.example.com/messenger/callback"]


async def test_a_connect_url_is_refused_when_this_runtime_has_no_app_for_the_provider(
    sf, registry, fixed_clock
):
    app, _ = await _build(
        sf, registry, fixed_clock, settings=_settings(instagram_app_id="", instagram_app_secret="")
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as client:
        response = await client.get(
            "/internal/tenants/skincentrix/integrations/instagram/connect-url"
        )

    assert response.status_code == 409
    assert "not configured" in response.json()["detail"]


async def test_a_return_to_that_is_not_an_http_url_is_refused(client):
    response = await client.get(
        "/internal/tenants/skincentrix/integrations/instagram/connect-url",
        params={"return_to": "javascript:alert(1)"},
    )

    assert response.status_code == 400


async def test_an_unknown_provider_is_a_404(client):
    response = await client.get("/internal/tenants/skincentrix/integrations/tiktok/connect-url")

    assert response.status_code == 404


async def test_asking_for_a_connect_url_is_audited_against_the_portal_user(client, sf):
    from spatalk.models import AuditLog

    await client.get("/internal/tenants/skincentrix/integrations/instagram/connect-url")

    async with sf() as s:
        rows = (
            await s.scalars(select(AuditLog).where(AuditLog.record_type == "tenant"))
        ).all()
    assert [(r.actor, r.action) for r in rows] == [
        (f"portal:{ACTOR}", "integration_connect_started")
    ]


# ----- disconnect --------------------------------------------------------------------------


async def test_disconnect_deletes_the_integration_and_unsubscribes_the_app_from_meta(
    client, app_ctx, sf, fixed_clock
):
    from spatalk.social.models import TenantIntegration

    _, ctx = app_ctx
    await _connect(ctx, sf, fixed_clock)

    body = (await client.delete("/internal/tenants/skincentrix/integrations/instagram")).json()

    assert body == {"provider": "instagram", "disconnected": True, "unsubscribed": True}
    call = ctx.graph.calls[-1]
    assert (call.method, call.path) == ("DELETE", IG_UNSUBSCRIBE_PATH)
    assert call.params["access_token"] == "a-long-lived-token"
    async with sf() as s:
        assert (await s.scalars(select(TenantIntegration))).all() == []


async def test_disconnecting_a_page_unsubscribes_it_through_the_facebook_host(
    client, app_ctx, sf, fixed_clock
):
    _, ctx = app_ctx
    await _connect(ctx, sf, fixed_clock, provider="messenger")

    body = (await client.delete("/internal/tenants/skincentrix/integrations/messenger")).json()

    assert body["disconnected"] is True
    assert ctx.graph.calls[-1].path == PAGE_UNSUBSCRIBE_PATH


async def test_disconnect_still_removes_the_row_when_meta_refuses_the_unsubscribe(
    sf, registry, fixed_clock
):
    from spatalk.social.graph import GraphError
    from spatalk.social.models import TenantIntegration

    app, ctx = await _build(
        sf,
        registry,
        fixed_clock,
        graph_responses={IG_UNSUBSCRIBE_PATH: GraphError(400, "token has been revoked")},
    )
    await _connect(ctx, sf, fixed_clock)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as client:
        body = (await client.delete("/internal/tenants/skincentrix/integrations/instagram")).json()

    assert body == {"provider": "instagram", "disconnected": True, "unsubscribed": False}
    async with sf() as s:
        assert (await s.scalars(select(TenantIntegration))).all() == []


async def test_disconnect_is_audited_against_the_portal_user(client, app_ctx, sf, fixed_clock):
    from spatalk.models import AuditLog

    _, ctx = app_ctx
    await _connect(ctx, sf, fixed_clock)

    await client.delete("/internal/tenants/skincentrix/integrations/instagram")

    async with sf() as s:
        rows = (
            await s.scalars(select(AuditLog).where(AuditLog.record_type == "tenant"))
        ).all()
    assert [(r.actor, r.action, r.record_id) for r in rows] == [
        (f"portal:{ACTOR}", "integration_disconnect", "skincentrix")
    ]


async def test_disconnecting_something_that_is_not_connected_is_a_404(client):
    response = await client.delete("/internal/tenants/skincentrix/integrations/instagram")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/internal/tenants/skincentrix/integrations"),
        ("GET", "/internal/tenants/skincentrix/integrations/instagram/connect-url"),
        ("DELETE", "/internal/tenants/skincentrix/integrations/instagram"),
    ],
)
async def test_every_integration_endpoint_needs_the_internal_key(app_ctx, method, path):
    app, _ = app_ctx
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://runtime") as c:
        assert (await c.request(method, path)).status_code == 401
