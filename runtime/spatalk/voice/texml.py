"""The Telnyx TeXML front door: answer a call by connecting it to our media socket."""

from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import Response
from loguru import logger

from spatalk.brain.renderer import render_script
from spatalk.conversations import start_conversation
from spatalk.ops.loop_guard import is_own_number, log_loop_guard_alert
from spatalk.tenants.schema import TenantConfig
from spatalk.voice.tokens import sign_stream_token

router = APIRouter()
XML = '<?xml version="1.0" encoding="UTF-8"?>'


def say_and_hangup(sentence: str) -> str:
    """A complete TeXML document that speaks one fixed sentence and ends the call."""
    return f"{XML}<Response><Say>{escape(sentence)}</Say><Hangup/></Response>"


def failover_bin(cfg: TenantConfig, now: datetime) -> str:
    """The body of the carrier-hosted TeXML Bin for this tenant (operations plan, E1).

    Telnyx plays this when it cannot reach us at all, so no part of it may depend on this
    process being alive: it is static text the founder pastes into a bin, printed by
    `spatalk texml failover-bin <tenant>`. There is no XML prolog because the bin editor
    stores the document only, and no `<Record>`: a carrier-side recording is a new place
    patient audio lives, so it stays opt-in per tenant (see docs/runbooks/failover.md).
    """
    sentence = escape(render_script("failover", cfg, now, urgent=False))
    return f'<Response><Say voice="female" language="en-CA">{sentence}</Say><Hangup/></Response>'


@router.post("/telnyx/texml")
async def texml(request: Request):
    ctx = request.app.state.ctx
    form = await request.form()
    caller, to = form.get("From"), form.get("To")
    call_sid = form.get("CallSid") or form.get("CallControlId")
    tenant_id = await ctx.registry.resolve_number(to or "")
    if tenant_id is None:
        return Response(
            content=say_and_hangup("This number is not configured."),
            media_type="application/xml",
        )
    cfg = await ctx.registry.get(tenant_id)
    # Loop guard (operations plan, Task E1): a call from one of this tenant's own lines is
    # a forwarding mistake, not a customer. Say so and hang up before any conversation
    # exists, so nothing downstream ever sees the call.
    if await is_own_number(cfg, ctx.registry, caller):
        logger.warning("loop guard: {} refused a call from its own number {}", tenant_id, caller)
        await log_loop_guard_alert(ctx, tenant_id, caller or "")
        return Response(
            content=say_and_hangup(render_script("loop_guard", cfg, ctx.clock.now(), urgent=False)),
            media_type="application/xml",
        )
    cid = await start_conversation(ctx.sf, tenant_id, "voice", call_sid, caller)
    token = sign_stream_token(ctx.settings.secret_key, cid, tenant_id, caller)
    url = f"wss://{ctx.settings.media_ws_host}/ws/{token}"
    body = f'{XML}<Response><Connect><Stream url="{url}" bidirectionalMode="rtp" /></Connect></Response>'
    return Response(content=body, media_type="application/xml")
