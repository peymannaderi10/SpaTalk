"""The Instagram door: connect, disconnect, and the webhook Meta delivers events to.

The webhook is deliberately thin. It proves the request came from Meta (HMAC-SHA256 over the
raw body, against either app secret), claims each event id once, and queues a job. Nothing
that can be slow happens here: Meta retries a webhook that does not answer within a couple of
seconds, and a retry must never produce a second reply to a customer.

The connect and callback routes finish the Instagram Business Login flow that
:mod:`spatalk.social.meta_oauth` implements; the deauthorize and delete routes are Meta's
platform requirement that a person can cut us off and have their data removed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from loguru import logger

from spatalk.social.events import SIGNATURE_HEADER, parse_instagram_payload, verify_meta_signature
from spatalk.social.handlers import IG_EVENT_JOB, ingest_events
from spatalk.social.meta_oauth import (
    build_instagram_start_url,
    complete_instagram_connect,
    delete_integration,
    integration_by_external_id,
    sign_state,
)

router = APIRouter()

PROVIDER = "instagram"
# Who the audit trail credits a connection to. The connect link is opened by a signed-in
# portal owner, but the runtime sees only the signed state, so it records the door used.
CONNECTED_BY = "instagram connect link"


def _app_secrets(settings) -> tuple[str, str]:
    """Both app secrets: one runtime can front the Instagram app and the Facebook app."""
    return (settings.instagram_app_secret, settings.facebook_app_secret)


def _unpad(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def parse_signed_request(signed_request: str, secrets) -> dict | None:
    """Meta's ``signed_request``: ``base64url(signature).base64url(payload)``.

    Returns the payload only when the signature verifies against one of the app secrets;
    anything else is None, and the route answers 401.
    """
    if not signed_request or "." not in signed_request:
        return None
    signature_b64, payload_b64 = signed_request.split(".", 1)
    try:
        signature = _unpad(signature_b64)
        payload = json.loads(_unpad(payload_b64))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    accepted = False
    for secret in secrets:
        if not secret:
            continue
        expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
        accepted |= hmac.compare_digest(expected, signature)
    return payload if accepted and isinstance(payload, dict) else None


# ----- connecting an account ---------------------------------------------------------------


@router.get("/instagram/connect")
async def connect(request: Request, tenant: str, return_to: str | None = None):
    """Send the tenant to Instagram Business Login with a 15-minute signed state."""
    ctx = request.app.state.ctx
    state = sign_state(ctx.settings.secret_key, tenant, return_to)
    return RedirectResponse(build_instagram_start_url(ctx.settings, state), status_code=302)


@router.get("/instagram/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    """Meta sends the person back here with a code. A bad state is a 400 and stores nothing."""
    ctx = request.app.state.ctx
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    result = await complete_instagram_connect(
        ctx.sf,
        ctx.settings,
        ctx.clock,
        code=code,
        state=state,
        connected_by=CONNECTED_BY,
        client=getattr(ctx, "graph", None),
    )
    if result.return_to:
        return RedirectResponse(result.return_to, status_code=302)
    return {"ok": True, "connected_as": result.display_name}


# ----- the webhook ---------------------------------------------------------------------------


@router.get("/instagram/webhook")
async def verify(
    request: Request,
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    """Meta's subscription handshake: echo the challenge, but only for our verify token."""
    expected = request.app.state.ctx.settings.instagram_webhook_verify_token
    if mode != "subscribe" or not expected or not hmac.compare_digest(token, expected):
        logger.warning("instagram webhook verification refused (mode={})", mode)
        raise HTTPException(status_code=403, detail="verification failed")
    return PlainTextResponse(challenge)


@router.post("/instagram/webhook")
async def inbound(request: Request):
    """Prove it came from Meta, record each event once, queue the work, answer immediately."""
    ctx = request.app.state.ctx
    raw = await request.body()
    if not verify_meta_signature(
        raw, request.headers.get(SIGNATURE_HEADER, ""), _app_secrets(ctx.settings)
    ):
        logger.warning("instagram webhook rejected: bad signature")
        raise HTTPException(status_code=401)
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400)
    queued = await ingest_events(ctx, PROVIDER, parse_instagram_payload(body), IG_EVENT_JOB)
    return {"ok": True, "queued": queued}


# ----- Meta's platform requirements ---------------------------------------------------------


async def _forget(ctx, user_id: str) -> bool:
    """Remove the integration for this Instagram account, and with it the stored token."""
    if not user_id:
        return False
    integration = await integration_by_external_id(ctx.sf, PROVIDER, user_id)
    if integration is None:
        return False
    return await delete_integration(ctx.sf, integration.tenant_id, PROVIDER)


async def _signed_payload(request: Request) -> dict:
    ctx = request.app.state.ctx
    form = await request.form()
    payload = parse_signed_request(
        str(form.get("signed_request") or ""), _app_secrets(ctx.settings)
    )
    if payload is None:
        raise HTTPException(status_code=401, detail="bad signed_request")
    return payload


@router.post("/instagram/deauthorize")
async def deauthorize(request: Request):
    """The person removed our app in Instagram: drop the connection and its token."""
    payload = await _signed_payload(request)
    removed = await _forget(request.app.state.ctx, str(payload.get("user_id") or ""))
    logger.info("instagram deauthorize processed (removed={})", removed)
    return {"ok": True, "removed": removed}


@router.post("/instagram/delete")
async def delete_data(request: Request):
    """Meta's data deletion callback: remove the connection and hand back a status URL."""
    ctx = request.app.state.ctx
    payload = await _signed_payload(request)
    user_id = str(payload.get("user_id") or "")
    await _forget(ctx, user_id)
    code = hashlib.sha256(f"{user_id}:{ctx.settings.secret_key}".encode()).hexdigest()[:16]
    base = ctx.settings.public_base_url.rstrip("/")
    return {"url": f"{base}/instagram/delete?code={code}", "confirmation_code": code}


@router.get("/instagram/delete")
async def delete_status(code: str = ""):
    """Where the confirmation code points: what was deleted, in plain words."""
    return PlainTextResponse(
        "The Instagram connection for this request has been deleted, along with the stored "
        f"access token. Reference: {code}"
    )
