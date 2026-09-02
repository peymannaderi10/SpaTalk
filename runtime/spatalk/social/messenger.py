"""The Facebook Page door: connect, choose a Page, and the webhook Meta delivers events to.

This is Task D2's Instagram adapter with Page semantics. The webhook is the same shape — HMAC
over the raw body against either app secret, one `meta_events` row per event, one job per
event an adapter answers — and the job that follows is literally the same code
(:mod:`spatalk.social.handlers`), so a Page conversation gets the same brain, the same guard,
the same tracked items and the same human takeover as SMS, web chat and Instagram.

Connecting is where the two differ. A person may administer several Pages, and the OAuth code
that produced their user token is single use, so the flow cannot simply be restarted once
they have chosen. When Meta answers with more than one Page, the choice is held here for
fifteen minutes under an opaque handle and the browser is sent back to the portal with the
Page names only; the portal posts the handle and the chosen id to
``POST /internal/tenants/{id}/integrations/messenger/select``, which subscribes and stores
that one Page. The Page access tokens never leave this process: not in a URL, not in the
database until one is chosen, never in a log.
"""

from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from loguru import logger

from spatalk.social.events import (
    SIGNATURE_HEADER,
    parse_messenger_payload,
    verify_meta_signature,
)
from spatalk.social.handlers import FB_EVENT_JOB, ingest_events
from spatalk.social.meta_oauth import (
    PAGE_SCOPES,
    ConnectResult,
    PageChoices,
    build_page_start_url,
    complete_page_connect,
    sign_state,
    store_integration,
    subscribe_page,
)

router = APIRouter()

PROVIDER = "messenger"
# Who the audit trail credits a connection to. The connect link is opened by a signed-in
# portal owner, but the runtime sees only the signed state, so it records the door used.
CONNECTED_BY = "messenger connect link"

# How long a person has to pick a Page after Meta hands us the list. The same fifteen minutes
# the OAuth state itself is good for.
PENDING_TTL = timedelta(minutes=15)


def _app_secrets(settings) -> tuple[str, str]:
    """Both app secrets: one runtime can front the Instagram app and the Facebook app."""
    return (settings.instagram_app_secret, settings.facebook_app_secret)


def _verify_token(settings) -> str:
    """The webhook verify token, shared by both Meta apps (`INSTAGRAM_WEBHOOK_VERIFY_TOKEN`).

    One value is configured for the deployment and typed into both apps' webhook screens;
    `api-surface.md` lists no second variable, and a second one would only be another secret
    to keep in step.
    """
    return settings.instagram_webhook_verify_token


# ----- the Pages a person is still choosing between -----------------------------------------


@dataclass(frozen=True)
class PendingPages:
    """A finished OAuth exchange waiting for a person to say which Page to connect."""

    tenant_id: str
    pages: tuple[dict, ...]
    return_to: str | None
    expires_at: datetime


# Held in memory on purpose: these dicts carry Page access tokens, and the alternative is
# writing a token to a row nobody has chosen yet or putting it through a browser. A restart
# loses the pending choice, and the honest answer to that is a 400 that says "start again".
_PENDING: dict[str, PendingPages] = {}


def _prune(now: datetime) -> None:
    for handle in [h for h, p in _PENDING.items() if p.expires_at <= now]:
        _PENDING.pop(handle, None)


def remember_pages(choices: PageChoices, now: datetime) -> str:
    """Hold a Page list for fifteen minutes and return the opaque handle for it."""
    _prune(now)
    handle = secrets.token_urlsafe(24)
    _PENDING[handle] = PendingPages(
        tenant_id=choices.tenant_id,
        pages=tuple(dict(p) for p in choices.pages),
        return_to=choices.return_to,
        expires_at=now + PENDING_TTL,
    )
    return handle


def take_pending(handle: str, tenant_id: str, now: datetime) -> PendingPages:
    """Consume a handle. Unknown, expired, already used or another tenant's is a 400."""
    _prune(now)
    pending = _PENDING.pop(handle, None)
    if pending is None or pending.tenant_id != tenant_id:
        raise HTTPException(
            status_code=400,
            detail="this page selection has expired; start the connection again",
        )
    return pending


def offered_pages(pages) -> list[dict]:
    """What a person is allowed to see: the id and the name, never the token."""
    return [{"id": str(p["id"]), "name": str(p.get("name") or p["id"])} for p in pages]


async def select_page(ctx, tenant_id: str, handle: str, page_id: str) -> ConnectResult:
    """Subscribe and store the Page a person chose. Called by the portal's internal API."""
    pending = take_pending(handle, tenant_id, ctx.clock.now())
    chosen = next((p for p in pending.pages if str(p["id"]) == str(page_id)), None)
    if chosen is None:
        raise HTTPException(status_code=400, detail="that page was not one of the choices")
    await subscribe_page(
        ctx.settings, chosen["id"], chosen["access_token"], getattr(ctx, "graph", None)
    )
    row = await store_integration(
        ctx.sf,
        ctx.settings,
        ctx.clock,
        tenant_id=tenant_id,
        provider=PROVIDER,
        external_id=str(chosen["id"]),
        display_name=str(chosen.get("name") or chosen["id"]),
        access_token=chosen["access_token"],
        token_expires_at=None,
        scopes=list(PAGE_SCOPES),
        connected_by=CONNECTED_BY,
    )
    logger.info("facebook page {} connected for {}", row.external_id, tenant_id)
    return ConnectResult(
        integration_id=row.id,
        tenant_id=tenant_id,
        provider=PROVIDER,
        external_id=row.external_id,
        display_name=row.display_name,
        return_to=pending.return_to,
    )


# ----- connecting a page ---------------------------------------------------------------------


@router.get("/messenger/connect")
async def connect(request: Request, tenant: str, return_to: str | None = None):
    """Send the tenant to Facebook Login with a 15-minute signed state."""
    ctx = request.app.state.ctx
    state = sign_state(ctx.settings.secret_key, tenant, return_to)
    return RedirectResponse(build_page_start_url(ctx.settings, state), status_code=302)


def _with_query(url: str, params: dict) -> str:
    return f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"


@router.get("/messenger/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    """Meta sends the person back here with a code. A bad state is a 400 and stores nothing."""
    ctx = request.app.state.ctx
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    result = await complete_page_connect(
        ctx.sf,
        ctx.settings,
        ctx.clock,
        code=code,
        state=state,
        connected_by=CONNECTED_BY,
        client=getattr(ctx, "graph", None),
    )
    if isinstance(result, PageChoices):
        handle = remember_pages(result, ctx.clock.now())
        offered = offered_pages(result.pages)
        logger.info("{} manages {} pages; asking which one", result.tenant_id, len(offered))
        choice = {"messenger_pending": handle, "messenger_pages": json.dumps(offered)}
        if result.return_to:
            return RedirectResponse(_with_query(result.return_to, choice), status_code=302)
        return {"pending": handle, "pages": offered}
    if result.return_to:
        return RedirectResponse(result.return_to, status_code=302)
    return {"ok": True, "connected_as": result.display_name}


# ----- the webhook -----------------------------------------------------------------------------


@router.get("/messenger/webhook")
async def verify(
    request: Request,
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    """Meta's subscription handshake: echo the challenge, but only for our verify token."""
    expected = _verify_token(request.app.state.ctx.settings)
    if mode != "subscribe" or not expected or not hmac.compare_digest(token, expected):
        logger.warning("messenger webhook verification refused (mode={})", mode)
        raise HTTPException(status_code=403, detail="verification failed")
    return PlainTextResponse(challenge)


@router.post("/messenger/webhook")
async def inbound(request: Request):
    """Prove it came from Meta, record each event once, queue the work, answer immediately."""
    ctx = request.app.state.ctx
    raw = await request.body()
    if not verify_meta_signature(
        raw, request.headers.get(SIGNATURE_HEADER, ""), _app_secrets(ctx.settings)
    ):
        logger.warning("messenger webhook rejected: bad signature")
        raise HTTPException(status_code=401)
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400)
    queued = await ingest_events(ctx, PROVIDER, parse_messenger_payload(body), FB_EVENT_JOB)
    return {"ok": True, "queued": queued}
