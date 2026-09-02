"""The Telnyx SMS adapter: authenticate, dedup, honour the keywords, then hand to the brain.

Two things happen here that must happen before anything else, and therefore cannot live in
:mod:`spatalk.text.service`: the request is authenticated (edge key or Telnyx signature), and
the compliance keywords STOP, START and HELP are answered from fixed tenant wording without
the model ever seeing the message.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import time

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from spatalk.brain.renderer import render_script
from spatalk.text.service import (
    TextConversationService,
    add_optout,
    make_text_llm,
    record_inbound,
    remove_optout,
)

router = APIRouter()

SIGNATURE_TOLERANCE_SECONDS = 300
STOP_WORDS = {"stop", "unsubscribe", "cancel", "end", "quit", "stopall"}
START_WORDS = {"start", "unstop", "yes"}
HELP_WORDS = {"help", "info"}


def verify_telnyx_signature(
    raw_body: bytes,
    signature_b64: str,
    timestamp: str,
    public_key_b64: str,
    tolerance_seconds: int = SIGNATURE_TOLERANCE_SECONDS,
) -> bool:
    """Ed25519 over ``"{timestamp}|{raw_body}"`` against the account public key."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        if abs(time.time() - int(timestamp)) > tolerance_seconds:
            return False
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        key.verify(base64.b64decode(signature_b64), f"{timestamp}|".encode() + raw_body)
        return True
    except (InvalidSignature, ValueError, TypeError, binascii.Error):
        return False


def _authorized(request: Request, raw: bytes, settings) -> bool:
    if settings.edge_shared_key:
        presented = request.headers.get("X-Edge-Key", "")
        return hmac.compare_digest(presented, settings.edge_shared_key)
    if settings.telnyx_public_key:
        return verify_telnyx_signature(
            raw,
            request.headers.get("telnyx-signature-ed25519", ""),
            request.headers.get("telnyx-timestamp", "0"),
            settings.telnyx_public_key,
        )
    return False


def _service(ctx) -> TextConversationService:
    if getattr(ctx, "llm", None) is None:
        ctx.llm = make_text_llm(ctx.settings)
        if ctx.llm is None:
            raise HTTPException(status_code=503, detail="no llm configured")
    return TextConversationService(ctx, ctx.llm)


async def _send(ctx, cfg, to: str, text: str) -> None:
    if not cfg.sms_from_number:
        logger.warning("tenant {} has no sms_from_number; nothing sent", cfg.id)
        return
    await ctx.sms.send(cfg.sms_from_number, to, text)


async def _keyword_reply(ctx, cfg, sender: str, word: str) -> bool:
    """Answer STOP, START and HELP from fixed wording. True when the message was a keyword.

    These three replies are the carrier-required confirmations, so they go out even to a
    number that is opted out; nothing else ever does.
    """
    now = ctx.clock.now()
    if word in STOP_WORDS:
        await add_optout(ctx.sf, cfg.id, sender)
        await _send(ctx, cfg, sender, render_script("optout_confirm", cfg, now, urgent=False))
        return True
    if word in START_WORDS:
        await remove_optout(ctx.sf, cfg.id, sender)
        await _send(ctx, cfg, sender, render_script("help_text", cfg, now, urgent=False))
        return True
    if word in HELP_WORDS:
        await _send(ctx, cfg, sender, render_script("help_text", cfg, now, urgent=False))
        return True
    return False


@router.post("/telnyx/sms")
async def inbound_sms(request: Request):
    ctx = request.app.state.ctx
    raw = await request.body()
    if not _authorized(request, raw, ctx.settings):
        raise HTTPException(status_code=401)
    try:
        data = json.loads(raw)["data"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400)
    if data.get("event_type") != "message.received":
        return {"ok": True, "ignored": "event_type"}

    payload = data.get("payload") or {}
    to_numbers = payload.get("to") or [{}]
    to = to_numbers[0].get("phone_number", "")
    sender = (payload.get("from") or {}).get("phone_number", "")
    message_id = payload.get("id") or ""
    text = payload.get("text") or ""

    tenant_id = await ctx.registry.resolve_number(to)
    if tenant_id is None:
        logger.warning("inbound sms to unconfigured number {}", to)
        return {"ok": True, "ignored": "unknown_number"}
    if message_id and not await record_inbound(ctx.sf, message_id, tenant_id, "sms"):
        logger.info("duplicate sms {} ignored", message_id)
        return {"ok": True, "ignored": "duplicate"}

    cfg = await ctx.registry.get(tenant_id)
    word = text.strip().lower()
    if sender and await _keyword_reply(ctx, cfg, sender, word):
        return {"ok": True, "handled": "keyword"}

    # An opted-out sender is filtered inside the service, which still stores the message.
    result = await _service(ctx).handle_inbound(
        tenant_id=tenant_id,
        channel="sms",
        external_id=sender,
        sender=sender,
        text=text,
        provider_message_id=None,
    )
    return {"ok": True, "conversation_id": str(result.conversation_id)}
