"""The web chat adapter: the widget, its socket, and the form that catches a broken socket.

Chat is the same brain as voice and SMS, reached over a WebSocket instead of a carrier. The
only things that live here are the ones the socket owns: the Turnstile challenge, per-IP
rate limits, frame plumbing, and the fallback form that files a callback when the socket
cannot be made to work at all.

Data minimisation (spec §4.4, plan B4): the fallback form's free text is stored as a message
on the conversation, never copied onto the tracked item. The item carries the contact only.
"""

from __future__ import annotations

import hmac
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel

from spatalk.brain.ports import ItemDraft
from spatalk.brain.renderer import render_script
from spatalk.brain.requests import ContactInfo, ConversationRef
from spatalk.conversations import append_message
from spatalk.text import takeover
from spatalk.text.service import TextConversationService, make_text_llm

router = APIRouter()

WIDGET_JS = Path(__file__).resolve().parents[1] / "static" / "widget.js"
WIDGET_MAX_AGE = 3600
# The widget's default colour. Not tenant config: docs/reference/tenant-config.md has no
# accent field, so the install snippet overrides it with data-accent (see the runbook).
DEFAULT_ACCENT = "#0f766e"

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Per-IP limits (plan B4 step 3) and the close codes that carry the reason to the widget.
NEW_SESSIONS_PER_MINUTE = 5
MESSAGES_PER_MINUTE = 30
RATE_WINDOW = timedelta(minutes=1)
CLOSE_BAD_REQUEST = 4400
CLOSE_TURNSTILE = 4401
CLOSE_UNKNOWN_TENANT = 4404
CLOSE_RATE_LIMITED = 4429
CLOSE_UNAVAILABLE = 4503


class FallbackForm(BaseModel):
    tenant_id: str
    name: str = ""
    contact: str = ""
    message: str = ""
    session: str = ""
    turnstile: str = ""


class RateLimiter:
    """A fixed-window-per-key counter. Small, in-process, and enough for one runtime node."""

    def __init__(self, limit: int, window: timedelta = RATE_WINDOW):
        self._limit, self._window = limit, window
        self._hits: dict[str, deque[datetime]] = defaultdict(deque)

    def allow(self, key: str, now: datetime) -> bool:
        hits = self._hits[key]
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True


async def verify_turnstile(token: str, secret: str, remote_ip: str | None = None) -> bool:
    """Ask Cloudflare whether this token is good. Any failure is a refusal, never a pass."""
    # No secret means there is nothing to verify against: refuse without opening a socket to
    # Cloudflare. Callers that mean "do not challenge at all" test the secret themselves
    # before calling (see ``chat_ws`` and ``chat_fallback``). QA gate B, finding 1.
    if not secret:
        return False
    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(TURNSTILE_VERIFY_URL, data=data)
        return bool(resp.json().get("success"))
    except Exception as e:  # noqa: BLE001  network, JSON or Cloudflare failure: refuse
        logger.warning("turnstile verification failed: {}", e)
        return False


def _verifier(app):
    """The Turnstile checker. Tests inject a fake through ``app.state.turnstile_verifier``."""
    return getattr(app.state, "turnstile_verifier", verify_turnstile)


def _limiters(app) -> tuple[RateLimiter, RateLimiter]:
    limiters = getattr(app.state, "chat_limiters", None)
    if limiters is None:
        limiters = (
            RateLimiter(NEW_SESSIONS_PER_MINUTE),
            RateLimiter(MESSAGES_PER_MINUTE),
        )
        app.state.chat_limiters = limiters
    return limiters


def _client_ip(scope_client, headers) -> str:
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return scope_client[0] if scope_client else "unknown"


def _service(ctx) -> TextConversationService:
    if getattr(ctx, "llm", None) is None:
        ctx.llm = make_text_llm(ctx.settings)
        if ctx.llm is None:
            raise HTTPException(status_code=503, detail="no llm configured")
    return TextConversationService(ctx, ctx.llm)


# ----- the widget itself ----------------------------------------------------------------


@router.get("/widget.js")
async def widget_js() -> Response:
    return Response(
        content=WIDGET_JS.read_text(encoding="utf-8"),
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": f"public, max-age={WIDGET_MAX_AGE}"},
    )


@router.get("/widget/{tenant_id}/config")
async def widget_config(request: Request, tenant_id: str) -> dict:
    ctx = request.app.state.ctx
    try:
        cfg = await ctx.registry.get(tenant_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown tenant")
    return {
        "name": cfg.name,
        "greeting": render_script("chat_greeting", cfg, ctx.clock.now(), urgent=False),
        "accent": DEFAULT_ACCENT,
        "turnstile_site_key": ctx.settings.turnstile_site_key,
    }


# ----- the socket -----------------------------------------------------------------------


@router.websocket("/chat/ws")
async def chat_ws(websocket: WebSocket) -> None:
    ctx = websocket.app.state.ctx
    tenant_id = websocket.query_params.get("tenant", "")
    session = websocket.query_params.get("session", "")
    token = websocket.query_params.get("turnstile", "")
    ip = _client_ip(websocket.scope.get("client"), websocket.headers)
    sessions, messages = _limiters(websocket.app)

    if not session:
        await websocket.close(code=CLOSE_BAD_REQUEST)
        return
    try:
        await ctx.registry.get(tenant_id)
    except KeyError:
        await websocket.close(code=CLOSE_UNKNOWN_TENANT)
        return
    if not sessions.allow(ip, ctx.clock.now()):
        logger.warning("chat: too many sessions from {}", ip)
        await websocket.close(code=CLOSE_RATE_LIMITED)
        return
    secret = ctx.settings.turnstile_secret_key
    if secret and not await _verifier(websocket.app)(token, secret, ip):
        logger.warning("chat: turnstile rejected a connection from {}", ip)
        await websocket.close(code=CLOSE_TURNSTILE)
        return

    try:
        service = _service(ctx)
    except HTTPException:
        # No model is configured. Close before accepting so the widget falls through to its
        # form rather than sitting in front of a socket that can never answer.
        logger.error("chat: no llm configured; socket refused")
        await websocket.close(code=CLOSE_UNAVAILABLE)
        return

    await websocket.accept()

    async def send_staff(text: str) -> None:
        await websocket.send_text(json.dumps({"type": "staff", "text": text}))

    # A person may be answering this visitor (Task B5): take the socket so staff replies
    # arrive live, and deliver anything said while the widget was away.
    takeover.register_chat_socket(tenant_id, session, send_staff)
    try:
        for waiting in takeover.take_pending_staff(tenant_id, session):
            await send_staff(waiting)
        await _chat_loop(websocket, ctx, service, tenant_id, session, ip, messages)
    finally:
        takeover.unregister_chat_socket(tenant_id, session)


async def _chat_loop(websocket, ctx, service, tenant_id, session, ip, messages) -> None:
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return
        try:
            frame = json.loads(raw)
        except ValueError:
            continue
        if frame.get("type") != "message":
            continue
        text = (frame.get("text") or "").strip()
        if not text:
            continue
        if not messages.allow(ip, ctx.clock.now()):
            logger.warning("chat: too many messages from {}", ip)
            await websocket.close(code=CLOSE_RATE_LIMITED)
            return
        await websocket.send_text(json.dumps({"type": "typing"}))
        result = await service.handle_inbound(
            tenant_id=tenant_id,
            channel="chat",
            external_id=session,
            sender=None,
            text=text,
            provider_message_id=None,
        )
        for reply in result.replies:
            await websocket.send_text(json.dumps({"type": "reply", "text": reply}))
        if result.turn is not None and result.turn.ended:
            await websocket.send_text(json.dumps({"type": "ended"}))
            await websocket.close()
            return


# ----- the fallback form ----------------------------------------------------------------


def _fallback_authorized(request: Request, form: FallbackForm, settings) -> bool:
    """The Worker presents the edge key; a direct post is checked by Turnstile if configured."""
    presented = request.headers.get("X-Edge-Key")
    if presented is not None or settings.edge_shared_key:
        return bool(settings.edge_shared_key) and hmac.compare_digest(
            presented or "", settings.edge_shared_key
        )
    return True


@router.post("/chat/fallback")
async def chat_fallback(request: Request, form: FallbackForm) -> dict:
    """The socket could not be made to work. File a callback and keep the words in the
    transcript, where free text belongs; the item carries only the contact."""
    ctx = request.app.state.ctx
    if not _fallback_authorized(request, form, ctx.settings):
        raise HTTPException(status_code=401)
    try:
        cfg = await ctx.registry.get(form.tenant_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown tenant")
    secret = ctx.settings.turnstile_secret_key
    if secret and request.headers.get("X-Edge-Key") is None:
        ip = _client_ip(request.scope.get("client"), request.headers)
        if not await _verifier(request.app)(form.turnstile, secret, ip):
            raise HTTPException(status_code=401)

    service = TextConversationService(ctx, ctx.llm)
    conv = await service.find_or_create_conversation(
        cfg.id, "chat", form.session or str(request.headers.get("x-request-id") or ""), None
    )
    if form.message.strip():
        await append_message(ctx.sf, conv.id, "user", form.message)
    contact = form.contact.strip()
    await ctx.ledger.create_item(
        ConversationRef(conversation_id=conv.id, tenant=cfg, channel="chat"),
        ItemDraft(
            type="callback",
            urgency="normal",
            contact=ContactInfo(
                name=form.name.strip() or None,
                email=contact if "@" in contact else None,
                phone=None if "@" in contact else (contact or None),
            ),
        ),
    )
    return {"ok": True}
