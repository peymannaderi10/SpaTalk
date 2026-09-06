"""Meta OAuth: Instagram Business Login, Facebook Login for Pages, and the refresh job.

Shape copied from ``diwenne/openreply`` (``lib/meta/oauth.ts``): the tenant leaves for Meta
with a signed state, comes back with a code, the code becomes a short-lived token, the
short-lived token becomes a long-lived one, the account identifies itself, and the app
subscribes to the webhook fields it will actually handle. Only then is anything stored, and
what is stored is ciphertext (:mod:`spatalk.social.crypto`).

Two rules hold throughout:

* The ``state`` is a 15-minute signed payload carrying the tenant and where to send the
  browser afterwards. An unsigned, tampered or stale state is a 400 and nothing happens.
* A token is never returned to a caller, logged, or put in an email. What leaves this module
  is an id, a display name and an expiry.

The routers that call this live in :mod:`spatalk.social.instagram` and
:mod:`spatalk.social.messenger` (instagram plan, Tasks D2 and D3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import HTTPException
from itsdangerous import BadSignature, URLSafeTimedSerializer
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk import jobs
from spatalk.models import Job
from spatalk.social.crypto import decrypt_token, encrypt_token
from spatalk.social.graph import GraphClient, HttpGraphClient
from spatalk.social.models import TenantIntegration

STATE_SALT = "meta-oauth"
STATE_MAX_AGE = 15 * 60

INSTAGRAM_AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
INSTAGRAM_API_BASE = "https://api.instagram.com"
INSTAGRAM_GRAPH_BASE = "https://graph.instagram.com"
FACEBOOK_AUTHORIZE_URL = "https://www.facebook.com/{version}/dialog/oauth"
FACEBOOK_GRAPH_BASE = "https://graph.facebook.com"

INSTAGRAM_SCOPES = (
    "instagram_business_basic",
    "instagram_business_manage_messages",
    "instagram_business_manage_comments",
    "instagram_business_manage_insights",
)
PAGE_SCOPES = (
    "pages_messaging",
    "pages_manage_metadata",
    "pages_read_engagement",
    "pages_show_list",
)
# The webhook fields each adapter handles. Subscribing to more would deliver events with
# nowhere to go; subscribing to fewer would lose the ones the adapters exist for.
INSTAGRAM_WEBHOOK_FIELDS = "comments,messages"
PAGE_WEBHOOK_FIELDS = "messages,feed"

REFRESH_JOB = "social.refresh_tokens"
# Meta long-lived Instagram tokens last 60 days and may be refreshed after 24 hours. Renewing
# at 30 days leaves a month of failed attempts before anyone loses the ability to reply.
REFRESH_WINDOW = timedelta(days=30)

# Staff-facing operational wording. No customer ever sees it, so it is not a tenant script.
RECONNECT_SUBJECT = "{name}: reconnect the {provider} account"
RECONNECT_BODY = (
    "The {provider} connection for {name} ({display}) could not be renewed automatically and "
    "is now marked as needing a reconnect.\n"
    "Messages still arrive, but the assistant will stop being able to reply when the "
    "connection expires{expiry}.\n"
    "Reconnect it from the portal: Settings, Integrations, Connect.\n"
    "\nWhy it failed: {reason}\n"
)


# ----- the signed state ------------------------------------------------------------------


@dataclass(frozen=True)
class OAuthState:
    tenant_id: str
    return_to: str | None = None


def sign_state(secret: str, tenant_id: str, return_to: str | None = None) -> str:
    return URLSafeTimedSerializer(secret, salt=STATE_SALT).dumps(
        {"t": tenant_id, "r": return_to}
    )


def verify_state(secret: str, state: str, max_age_seconds: int = STATE_MAX_AGE) -> OAuthState:
    """The tenant behind a callback. Anything unsigned, tampered or stale is a 400."""
    try:
        payload = URLSafeTimedSerializer(secret, salt=STATE_SALT).loads(
            state, max_age=max_age_seconds
        )
        tenant_id = str(payload["t"])
    except (BadSignature, KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="invalid oauth state") from e
    return_to = payload.get("r")
    return OAuthState(tenant_id=tenant_id, return_to=str(return_to) if return_to else None)


# ----- start urls ------------------------------------------------------------------------


def instagram_redirect_uri(settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}/instagram/callback"


def page_redirect_uri(settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}/messenger/callback"


def build_instagram_start_url(settings, state: str) -> str:
    """Where the Connect button sends the tenant: Instagram Business Login."""
    query = urlencode(
        {
            "client_id": settings.instagram_app_id,
            "redirect_uri": instagram_redirect_uri(settings),
            "response_type": "code",
            "scope": ",".join(INSTAGRAM_SCOPES),
            "state": state,
        }
    )
    return f"{INSTAGRAM_AUTHORIZE_URL}?{query}"


def build_page_start_url(settings, state: str) -> str:
    """Where the Connect button sends the tenant: Facebook Login for a Page."""
    query = urlencode(
        {
            "client_id": settings.facebook_app_id,
            "redirect_uri": page_redirect_uri(settings),
            "response_type": "code",
            "scope": ",".join(PAGE_SCOPES),
            "state": state,
        }
    )
    return f"{FACEBOOK_AUTHORIZE_URL.format(version=settings.meta_graph_version)}?{query}"


# ----- token exchanges -------------------------------------------------------------------


@dataclass(frozen=True)
class ShortToken:
    access_token: str
    user_id: str | None = None
    expires_in: int | None = None
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class LongToken:
    access_token: str
    expires_in: int | None = None
    token_type: str = "bearer"


def _permissions(raw) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(p.strip() for p in raw.split(",") if p.strip())
    return tuple(str(p) for p in (raw or ()))


def _instagram_api(client: GraphClient | None) -> GraphClient:
    return client or HttpGraphClient(INSTAGRAM_API_BASE)


def _instagram_graph(client: GraphClient | None) -> GraphClient:
    return client or HttpGraphClient(INSTAGRAM_GRAPH_BASE)


def _facebook_graph(client: GraphClient | None) -> GraphClient:
    return client or HttpGraphClient(FACEBOOK_GRAPH_BASE)


async def exchange_instagram_code(
    settings, code: str, client: GraphClient | None = None
) -> ShortToken:
    data = await _instagram_api(client).post(
        "/oauth/access_token",
        data={
            "client_id": settings.instagram_app_id,
            "client_secret": settings.instagram_app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": instagram_redirect_uri(settings),
            "code": code,
        },
    )
    user_id = data.get("user_id")
    return ShortToken(
        access_token=str(data["access_token"]),
        user_id=str(user_id) if user_id is not None else None,
        permissions=_permissions(data.get("permissions")),
    )


async def exchange_long_lived(
    settings, short_token: str, client: GraphClient | None = None
) -> LongToken:
    data = await _instagram_graph(client).get(
        "/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": settings.instagram_app_secret,
            "access_token": short_token,
        },
    )
    return LongToken(
        access_token=str(data["access_token"]),
        expires_in=int(data["expires_in"]) if data.get("expires_in") is not None else None,
        token_type=str(data.get("token_type") or "bearer"),
    )


async def refresh_long_lived(token: str, client: GraphClient | None = None) -> LongToken:
    data = await _instagram_graph(client).get(
        "/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
    )
    return LongToken(
        access_token=str(data["access_token"]),
        expires_in=int(data["expires_in"]) if data.get("expires_in") is not None else None,
        token_type=str(data.get("token_type") or "bearer"),
    )


async def me(settings, token: str, client: GraphClient | None = None) -> dict:
    """``{id, username}`` for the connected Instagram account.

    Instagram Business Login answers ``user_id`` on some versions and ``id`` on others; the
    webhook's ``entry.id`` is that same number, so both are normalised to ``id`` here.
    """
    data = await _instagram_graph(client).get(
        f"/{settings.meta_graph_version}/me",
        params={"fields": "id,username", "access_token": token},
    )
    ident = data.get("id") or data.get("user_id")
    return {
        "id": str(ident) if ident is not None else "",
        "username": str(data.get("username") or ""),
    }


async def subscribe_instagram(
    settings, ig_user_id: str, token: str, client: GraphClient | None = None
) -> dict:
    return await _instagram_graph(client).post(
        f"/{settings.meta_graph_version}/{ig_user_id}/subscribed_apps",
        params={"subscribed_fields": INSTAGRAM_WEBHOOK_FIELDS, "access_token": token},
    )


async def exchange_page_code(settings, code: str, client: GraphClient | None = None) -> ShortToken:
    data = await _facebook_graph(client).get(
        f"/{settings.meta_graph_version}/oauth/access_token",
        params={
            "client_id": settings.facebook_app_id,
            "client_secret": settings.facebook_app_secret,
            "redirect_uri": page_redirect_uri(settings),
            "code": code,
        },
    )
    return ShortToken(
        access_token=str(data["access_token"]),
        expires_in=int(data["expires_in"]) if data.get("expires_in") is not None else None,
    )


async def list_pages(settings, user_token: str, client: GraphClient | None = None) -> list[dict]:
    """The Pages this person can manage: ``[{id, name, access_token}]``."""
    data = await _facebook_graph(client).get(
        f"/{settings.meta_graph_version}/me/accounts",
        params={"fields": "id,name,access_token", "access_token": user_token},
    )
    return [
        {
            "id": str(page["id"]),
            "name": str(page.get("name") or ""),
            "access_token": str(page["access_token"]),
        }
        for page in data.get("data") or []
    ]


async def subscribe_page(
    settings, page_id: str, page_token: str, client: GraphClient | None = None
) -> dict:
    return await _facebook_graph(client).post(
        f"/{settings.meta_graph_version}/{page_id}/subscribed_apps",
        params={"subscribed_fields": PAGE_WEBHOOK_FIELDS, "access_token": page_token},
    )


# ----- storage ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectResult:
    """What a finished connect flow tells its router. No token crosses this boundary."""

    integration_id: int
    tenant_id: str
    provider: str
    external_id: str
    display_name: str
    return_to: str | None = None


@dataclass(frozen=True)
class PageChoices:
    """This person manages several Pages: the portal asks which one, nothing is stored yet."""

    tenant_id: str
    pages: tuple[dict, ...]
    return_to: str | None = None


async def store_integration(
    sf: async_sessionmaker,
    settings,
    clock,
    *,
    tenant_id: str,
    provider: str,
    external_id: str,
    display_name: str,
    access_token: str,
    token_expires_at=None,
    scopes: list[str] | None = None,
    connected_by: str,
    needs_reconnect: bool = False,
    channel_id: str | None = None,
    webhook_url: str | None = None,
) -> TenantIntegration:
    """Upsert the one integration a tenant has per provider, token encrypted.

    Reconnecting replaces the row's token and clears ``needs_reconnect``: a tenant never ends
    up with two Instagram accounts, and a reconnect is the cure for a failed refresh.

    ``channel_id`` and ``webhook_url`` are a Slack workspace's (onboarding roadmap, section
    3): the webhook URL lets anyone holding it post, so it is encrypted exactly as the token.
    """
    key = settings.meta_token_encryption_key
    ciphertext = encrypt_token(access_token, key)
    webhook_ciphertext = encrypt_token(webhook_url, key) if webhook_url else None
    now = clock.now()
    async with sf() as s, s.begin():
        row = (
            await s.scalars(
                select(TenantIntegration).where(
                    TenantIntegration.tenant_id == tenant_id,
                    TenantIntegration.provider == provider,
                )
            )
        ).first()
        if row is None:
            row = TenantIntegration(tenant_id=tenant_id, provider=provider)
            s.add(row)
        row.external_id = external_id
        row.display_name = display_name
        row.access_token_enc = ciphertext
        row.token_expires_at = token_expires_at
        row.scopes = list(scopes or [])
        row.needs_reconnect = needs_reconnect
        row.connected_by = connected_by
        row.channel_id = channel_id
        row.webhook_url_enc = webhook_ciphertext
        row.updated_at = now
        await s.flush()
    return row


async def integration_for(
    sf: async_sessionmaker, tenant_id: str, provider: str
) -> TenantIntegration | None:
    async with sf() as s:
        return (
            await s.scalars(
                select(TenantIntegration).where(
                    TenantIntegration.tenant_id == tenant_id,
                    TenantIntegration.provider == provider,
                )
            )
        ).first()


async def integration_by_external_id(
    sf: async_sessionmaker, provider: str, external_id: str
) -> TenantIntegration | None:
    """How a webhook finds its tenant: ``entry.id`` is the account or Page id."""
    async with sf() as s:
        return (
            await s.scalars(
                select(TenantIntegration).where(
                    TenantIntegration.provider == provider,
                    TenantIntegration.external_id == str(external_id),
                )
            )
        ).first()


def access_token(integration: TenantIntegration, settings=None) -> str:
    """The plaintext token for a Graph call. Hold it in a local, never in a log or a row."""
    key = settings.meta_token_encryption_key if settings is not None else None
    return decrypt_token(integration.access_token_enc, key)


async def delete_integration(sf: async_sessionmaker, tenant_id: str, provider: str) -> bool:
    """Disconnect: the row and its token go. Used by the portal and by deauthorize (D2)."""
    async with sf() as s, s.begin():
        row = (
            await s.scalars(
                select(TenantIntegration).where(
                    TenantIntegration.tenant_id == tenant_id,
                    TenantIntegration.provider == provider,
                )
            )
        ).first()
        if row is None:
            return False
        await s.delete(row)
    return True


# ----- the two connect flows ---------------------------------------------------------------


async def complete_instagram_connect(
    sf: async_sessionmaker,
    settings,
    clock,
    *,
    code: str,
    state: str,
    connected_by: str,
    client: GraphClient | None = None,
) -> ConnectResult:
    """Code to stored integration: exchange, extend, identify, subscribe, store."""
    claim = verify_state(settings.secret_key, state)
    short = await exchange_instagram_code(settings, code, client)
    long_lived = await exchange_long_lived(settings, short.access_token, client)
    profile = await me(settings, long_lived.access_token, client)
    ig_user_id = profile["id"] or (short.user_id or "")
    if not ig_user_id:
        raise HTTPException(status_code=400, detail="instagram account id missing")
    await subscribe_instagram(settings, ig_user_id, long_lived.access_token, client)
    expires_at = (
        clock.now() + timedelta(seconds=long_lived.expires_in) if long_lived.expires_in else None
    )
    row = await store_integration(
        sf,
        settings,
        clock,
        tenant_id=claim.tenant_id,
        provider="instagram",
        external_id=ig_user_id,
        display_name=profile["username"] or ig_user_id,
        access_token=long_lived.access_token,
        token_expires_at=expires_at,
        scopes=list(short.permissions) or list(INSTAGRAM_SCOPES),
        connected_by=connected_by,
    )
    logger.info("instagram connected for {} as {}", claim.tenant_id, row.display_name)
    return ConnectResult(
        integration_id=row.id,
        tenant_id=claim.tenant_id,
        provider="instagram",
        external_id=ig_user_id,
        display_name=row.display_name,
        return_to=claim.return_to,
    )


async def complete_page_connect(
    sf: async_sessionmaker,
    settings,
    clock,
    *,
    code: str,
    state: str,
    connected_by: str,
    page_id: str | None = None,
    client: GraphClient | None = None,
) -> ConnectResult | PageChoices:
    """Code to stored Page, or to the list of Pages when the person manages several.

    A Page access token derived from a user token does not expire, so ``token_expires_at``
    stays null and the refresh job leaves the row alone until Meta invalidates it.
    """
    claim = verify_state(settings.secret_key, state)
    user_token = await exchange_page_code(settings, code, client)
    pages = await list_pages(settings, user_token.access_token, client)
    if not pages:
        raise HTTPException(status_code=400, detail="this account manages no facebook page")
    if page_id is not None:
        chosen = next((p for p in pages if p["id"] == str(page_id)), None)
        if chosen is None:
            raise HTTPException(status_code=400, detail="unknown page for this account")
    elif len(pages) == 1:
        chosen = pages[0]
    else:
        return PageChoices(
            tenant_id=claim.tenant_id,
            pages=tuple(dict(p) for p in pages),
            return_to=claim.return_to,
        )
    await subscribe_page(settings, chosen["id"], chosen["access_token"], client)
    row = await store_integration(
        sf,
        settings,
        clock,
        tenant_id=claim.tenant_id,
        provider="messenger",
        external_id=chosen["id"],
        display_name=chosen["name"] or chosen["id"],
        access_token=chosen["access_token"],
        token_expires_at=None,
        scopes=list(PAGE_SCOPES),
        connected_by=connected_by,
    )
    logger.info("facebook page connected for {} as {}", claim.tenant_id, row.display_name)
    return ConnectResult(
        integration_id=row.id,
        tenant_id=claim.tenant_id,
        provider="messenger",
        external_id=chosen["id"],
        display_name=row.display_name,
        return_to=claim.return_to,
    )


# ----- the daily refresh job ----------------------------------------------------------------


async def _ask_for_a_reconnect(ctx, row: TenantIntegration, reason: str) -> None:
    """Mark the integration and tell the tenant's escalation owner, in staff wording."""
    now = ctx.clock.now()
    async with ctx.sf() as s, s.begin():
        stored = await s.get(TenantIntegration, row.id)
        if stored is None:
            return
        stored.needs_reconnect = True
        stored.updated_at = now
    cfg = await ctx.registry.get(row.tenant_id)
    expiry = f" on {row.token_expires_at:%Y-%m-%d}" if row.token_expires_at else ""
    logger.warning(
        "meta token refresh failed for {} {}: needs reconnect", row.tenant_id, row.provider
    )
    await ctx.delivery.send_email(
        cfg.escalation.owner_email,
        RECONNECT_SUBJECT.format(name=cfg.name, provider=row.provider),
        RECONNECT_BODY.format(
            provider=row.provider,
            name=cfg.name,
            display=row.display_name,
            expiry=expiry,
            reason=reason,
        ),
    )


@jobs.register_handler(REFRESH_JOB)
async def refresh_tokens(payload: dict, ctx) -> None:
    """Renew every Meta token inside 30 days of expiry; ask for a reconnect when one fails.

    A row already flagged ``needs_reconnect`` is left alone: it has had its email, and only a
    person can fix it. A Page token cannot be renewed with ``ig_refresh_token``, so a Page
    row that does carry an expiry is a reconnect, not a retry.
    """
    now = ctx.clock.now()
    async with ctx.sf() as s:
        due = list(
            (
                await s.scalars(
                    select(TenantIntegration).where(
                        TenantIntegration.needs_reconnect.is_(False),
                        TenantIntegration.token_expires_at.is_not(None),
                        TenantIntegration.token_expires_at <= now + REFRESH_WINDOW,
                    )
                )
            ).all()
        )
    for row in due:
        if row.provider != "instagram":
            await _ask_for_a_reconnect(
                ctx, row, "a Facebook Page connection cannot be renewed automatically"
            )
            continue
        try:
            token = access_token(row, ctx.settings)
            fresh = await refresh_long_lived(token, getattr(ctx, "graph", None))
        except Exception as e:  # noqa: BLE001  (any failure is the same answer: reconnect)
            await _ask_for_a_reconnect(ctx, row, f"{type(e).__name__}: {e}"[:300])
            continue
        expires_at = now + timedelta(seconds=fresh.expires_in) if fresh.expires_in else None
        ciphertext = encrypt_token(fresh.access_token, ctx.settings.meta_token_encryption_key)
        async with ctx.sf() as s, s.begin():
            stored = await s.get(TenantIntegration, row.id)
            if stored is None:
                continue
            stored.access_token_enc = ciphertext
            stored.token_expires_at = expires_at
            stored.updated_at = now
        logger.info("refreshed the instagram token for {}", row.tenant_id)


async def ensure_daily_refresh_scheduled(sf: async_sessionmaker, clock) -> bool:
    """Queue the refresh job at most once a day. The scheduler calls this every minute."""
    async with sf() as s:
        recent = await s.scalar(
            select(func.count(Job.id)).where(
                Job.kind == REFRESH_JOB, Job.created_at > clock.now() - timedelta(days=1)
            )
        )
    if recent:
        return False
    await jobs.enqueue(sf, REFRESH_JOB, {})
    return True


# ----- disconnecting (instagram plan, Task D4) ---------------------------------------------


async def unsubscribe_integration(
    settings, integration: TenantIntegration, client: GraphClient | None = None
) -> bool:
    """Tell Meta to stop sending this account's events, before the row goes.

    Best effort by design. Disconnect is the tenant's decision, and it must succeed even
    when Meta cannot be reached, when the token has already been revoked from the Instagram
    app, or when the encryption key has been rotated and the stored token can no longer be
    read: the row is deleted either way and this answers whether the unsubscribe landed. It
    never raises, and it never puts the token in the log line.
    """
    host = INSTAGRAM_GRAPH_BASE if integration.provider == "instagram" else FACEBOOK_GRAPH_BASE
    try:
        token = access_token(integration, settings)
    except Exception as e:  # a rotated key, a corrupted column: nothing left to ask Meta with
        logger.warning(
            "cannot read the {} token for {} to unsubscribe: {}",
            integration.provider,
            integration.tenant_id,
            type(e).__name__,
        )
        return False
    api = client if client is not None else HttpGraphClient(host)
    try:
        await api.delete(
            f"/{settings.meta_graph_version}/{integration.external_id}/subscribed_apps",
            params={"access_token": token},
        )
    except Exception as e:
        logger.warning(
            "meta refused to unsubscribe {} for {}: {}",
            integration.provider,
            integration.tenant_id,
            e,
        )
        return False
    return True
