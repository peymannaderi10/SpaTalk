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
import re
import time

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from spatalk.brain.renderer import render_script
# --- sms staff delivery (plan S) ---
from spatalk.ledger.delivery import build_list_sms, sms_destination_numbers
from spatalk.text import takeover
from spatalk.text.service import (
    TextConversationService,
    add_optout,
    make_text_llm,
    record_inbound,
    remove_optout,
)

router = APIRouter()

SIGNATURE_TOLERANCE_SECONDS = 300
# The CTIA opt-out set, matched on the first word of the normalised message so that "STOP.",
# "STOP ALL" and "stop texting me" all unsubscribe the sender.
STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
# A short message that merely *contains* one of these is an opt-out too ("please stop",
# "unsubscribe me"). A longer sentence is not: "can you stop by the clinic" is a question
# for the front desk, and silencing that person would be the worse failure of the two.
SHORT_STOP_WORDS = {"stop", "unsubscribe"}
SHORT_STOP_MAX_WORDS = 3
START_WORDS = {"start", "unstop", "yes"}
HELP_WORDS = {"help", "info"}
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalise_keyword(text: str) -> list[str]:
    """Lowercase, drop punctuation, collapse whitespace: the words a keyword match sees.

    A phone keyboard capitalises and adds a full stop on its own, so the raw string is never
    what the carrier rule is about.
    """
    return _NON_WORD.sub(" ", text.lower()).split()


def is_optout(words: list[str]) -> bool:
    """True when these normalised words are an unsubscribe request."""
    if not words:
        return False
    if words[0] in STOP_WORDS:
        return True
    return len(words) <= SHORT_STOP_MAX_WORDS and not SHORT_STOP_WORDS.isdisjoint(words)


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


async def _keyword_reply(ctx, cfg, sender: str, text: str) -> bool:
    """Answer STOP, START and HELP from fixed wording. True when the message was a keyword.

    These three replies are the carrier-required confirmations, so they go out even to a
    number that is opted out; nothing else ever does.
    """
    now = ctx.clock.now()
    words = normalise_keyword(text)
    if is_optout(words):
        await add_optout(ctx.sf, cfg.id, sender)
        await _send(ctx, cfg, sender, render_script("optout_confirm", cfg, now, urgent=False))
        return True
    # START and HELP are opt-in and informational, so they stay a whole-message match: only
    # the punctuation and the casing are forgiven, never a sentence that contains the word.
    single = words[0] if len(words) == 1 else ""
    if single in START_WORDS:
        await remove_optout(ctx.sf, cfg.id, sender)
        await _send(ctx, cfg, sender, render_script("help_text", cfg, now, urgent=False))
        return True
    if single in HELP_WORDS:
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
    if sender and await _keyword_reply(ctx, cfg, sender, text):
        return {"ok": True, "handled": "keyword"}

    # A staff phone is not a customer: `#4821 on my way` relays to that item's conversation
    # and hands it to the person; anything else from that number gets the help text (B5).
    # --- sms staff delivery (plan S) ---
    # An `sms` destination's number is staff as well: the digest that goes to it says
    # "Reply LIST for details", so the number the digest reached must be recognised here.
    # Task S2 replaces both lookups with spatalk.text.staff.staff_numbers(cfg) and adds the
    # ACK and DONE keywords beside LIST.
    if sender and (
        sender in cfg.delivery.staff_phone_numbers or sender in sms_destination_numbers(cfg)
    ):
        if normalise_keyword(text) == ["list"]:
            open_items = await ctx.ledger.list_open(cfg.id)
            await _send(ctx, cfg, sender, build_list_sms(open_items, cfg, ctx.clock.now()))
            return {"ok": True, "handled": "staff_list"}
        if await takeover.relay_staff_sms(ctx, cfg, sender, text):
            return {"ok": True, "handled": "staff_relay"}
        help_text = render_script("help_text", cfg, ctx.clock.now(), urgent=False)
        await _send(ctx, cfg, sender, help_text)
        return {"ok": True, "handled": "staff_help"}

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
