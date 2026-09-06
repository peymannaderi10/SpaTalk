"""Slack one-click connect: the Add to Slack flow, and what the runtime keeps of it.

Shape copied from :mod:`spatalk.social.meta_oauth` (onboarding roadmap, section 3): the
owner leaves for Slack with a signed state, comes back with a code, the code becomes a bot
token and an incoming webhook for the channel the workspace chose, and both are stored as
Fernet ciphertext against the tenant. One Slack app (client id, client secret, signing
secret) serves every tenant; what differs per tenant is the row.

Two rules hold throughout:

* A token or a webhook URL is never returned to a caller, logged, or put in a response. What
  leaves this module is a team id, a display name and a channel id.
* Every Slack call goes through the :class:`~spatalk.social.graph.GraphClient` seam, so a
  test injects :class:`~spatalk.social.graph.FakeGraphClient` and nothing reaches the network.

The routes live in :mod:`spatalk.http.slack_connect`; delivery reads the row through
:func:`slack_bot_token` and :func:`slack_webhook_url`; the thread posts in
:mod:`spatalk.text.takeover` ask :func:`bot_token_for_tenant` which token to speak with.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk.social.crypto import decrypt_token
from spatalk.social.graph import GraphClient, HttpGraphClient
from spatalk.social.meta_oauth import ConnectResult, integration_for, store_integration, verify_state
from spatalk.social.models import TenantIntegration

PROVIDER = "slack"
SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
SLACK_API_BASE = "https://slack.com/api"
# The manifest's bot scopes (docs/runbooks/accounts-and-env.md, section 8): the webhook to
# post with, chat:write for the thread per conversation, channels:history for the staff
# replies typed in it, channels:read and users:read for channel and people names.
SLACK_SCOPES = (
    "incoming-webhook",
    "chat:write",
    "channels:history",
    "channels:read",
    "users:read",
)


# ----- the start url -----------------------------------------------------------------------


def slack_redirect_uri(settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}/slack/callback"


def build_slack_start_url(settings, state: str) -> str:
    """Where the Connect button sends the owner: Slack's install page for the app."""
    query = urlencode(
        {
            "client_id": settings.slack_client_id,
            "scope": ",".join(SLACK_SCOPES),
            "redirect_uri": slack_redirect_uri(settings),
            "state": state,
        }
    )
    return f"{SLACK_AUTHORIZE_URL}?{query}"


# ----- the exchange ------------------------------------------------------------------------


@dataclass(frozen=True)
class SlackInstall:
    """What ``oauth.v2.access`` answered. Lives in a local for the length of the callback."""

    access_token: str
    team_id: str
    team_name: str
    channel: str
    channel_id: str | None
    webhook_url: str | None
    bot_user_id: str
    scopes: tuple[str, ...]


def _api(client: GraphClient | None) -> GraphClient:
    return client or HttpGraphClient(SLACK_API_BASE)


async def exchange_code(settings, code: str, client: GraphClient | None = None) -> SlackInstall:
    """The code from the callback becomes the workspace's bot token and webhook.

    Slack answers 200 with ``ok: false`` and an error word on a refusal (a used or stale
    code, a redirect that does not match the app's); that is a 400 here naming the word and
    nothing else. The client secret is in the request and nowhere in any answer.
    """
    data = await _api(client).post(
        "/oauth.v2.access",
        data={
            "client_id": settings.slack_client_id,
            "client_secret": settings.slack_client_secret,
            "code": code,
            "redirect_uri": slack_redirect_uri(settings),
        },
    )
    if not data.get("ok"):
        error = str(data.get("error") or "unknown_error")
        logger.warning("slack refused the oauth exchange: {}", error)
        raise HTTPException(status_code=400, detail=f"slack refused the connection: {error}")
    team = data.get("team") or {}
    webhook = data.get("incoming_webhook") or {}
    token = str(data.get("access_token") or "")
    if not token or not team.get("id"):
        raise HTTPException(status_code=400, detail="slack answered without a bot token or a team")
    return SlackInstall(
        access_token=token,
        team_id=str(team["id"]),
        team_name=str(team.get("name") or team["id"]),
        channel=str(webhook.get("channel") or ""),
        channel_id=str(webhook["channel_id"]) if webhook.get("channel_id") else None,
        webhook_url=str(webhook["url"]) if webhook.get("url") else None,
        bot_user_id=str(data.get("bot_user_id") or ""),
        scopes=tuple(s.strip() for s in str(data.get("scope") or "").split(",") if s.strip()),
    )


def display_name(install: SlackInstall) -> str:
    """``Workspace · #channel``, or the workspace alone when the install chose no channel."""
    return f"{install.team_name} · {install.channel}" if install.channel else install.team_name


async def complete_slack_connect(
    sf: async_sessionmaker,
    settings,
    clock,
    *,
    code: str,
    state: str,
    connected_by: str,
    client: GraphClient | None = None,
) -> ConnectResult:
    """Code to stored workspace: verify the state, exchange, store encrypted.

    A bot token does not expire on its own (it is revoked, or the app is reinstalled), so
    ``token_expires_at`` stays null and the Meta refresh job leaves the row alone.
    """
    claim = verify_state(settings.secret_key, state)
    install = await exchange_code(settings, code, client)
    row = await store_integration(
        sf,
        settings,
        clock,
        tenant_id=claim.tenant_id,
        provider=PROVIDER,
        external_id=install.team_id,
        display_name=display_name(install),
        access_token=install.access_token,
        token_expires_at=None,
        scopes=list(install.scopes) or list(SLACK_SCOPES),
        connected_by=connected_by,
        channel_id=install.channel_id,
        webhook_url=install.webhook_url,
    )
    logger.info("slack connected for {} as {}", claim.tenant_id, row.display_name)
    return ConnectResult(
        integration_id=row.id,
        tenant_id=claim.tenant_id,
        provider=PROVIDER,
        external_id=install.team_id,
        display_name=row.display_name,
        return_to=claim.return_to,
    )


# ----- what delivery and the thread need -----------------------------------------------------


def slack_bot_token(integration: TenantIntegration, settings=None) -> str:
    """The workspace's bot token, in the clear. Hold it in a local; never log or store it."""
    key = settings.meta_token_encryption_key if settings is not None else None
    return decrypt_token(integration.access_token_enc, key)


def slack_webhook_url(integration: TenantIntegration, settings=None) -> str | None:
    """The incoming-webhook URL, in the clear, or None when the install chose no channel."""
    if not integration.webhook_url_enc:
        return None
    key = settings.meta_token_encryption_key if settings is not None else None
    return decrypt_token(integration.webhook_url_enc, key)


async def bot_token_for_tenant(sf: async_sessionmaker, settings, tenant_id: str) -> str | None:
    """The connected workspace's bot token for this tenant, or None: speak with the global one.

    A row whose token cannot be read (a rotated key) answers None with a warning, so a thread
    post tries the global token rather than failing on a decrypt; the tenant reconnects.
    """
    row = await integration_for(sf, tenant_id, PROVIDER)
    if row is None:
        return None
    try:
        return slack_bot_token(row, settings)
    except Exception as e:  # a rotated key, a corrupted column: nothing to speak with
        logger.warning("cannot read the slack token for {}: {}", tenant_id, type(e).__name__)
        return None


# ----- disconnecting -------------------------------------------------------------------------


async def revoke_integration(
    settings, integration: TenantIntegration, client: GraphClient | None = None
) -> bool:
    """Ask Slack to revoke the workspace's bot token, before the row goes.

    Best effort, exactly like the Meta unsubscribe: disconnect is the tenant's decision and
    succeeds even when Slack cannot be reached, when the app was already removed from the
    workspace, or when the stored token can no longer be read. It never raises, and the
    token is never in a log line. Answers whether Slack confirmed the revoke.
    """
    try:
        token = slack_bot_token(integration, settings)
    except Exception as e:  # a rotated key, a corrupted column: nothing left to revoke with
        logger.warning(
            "cannot read the slack token for {} to revoke it: {}",
            integration.tenant_id,
            type(e).__name__,
        )
        return False
    try:
        answer = await _api(client).post("/auth.revoke", data={"token": token})
    except Exception as e:
        logger.warning("slack could not be asked to revoke {}'s token: {}", integration.tenant_id, e)
        return False
    if not answer.get("ok"):
        logger.warning(
            "slack did not revoke {}'s token: {}", integration.tenant_id, answer.get("error")
        )
        return False
    return True
