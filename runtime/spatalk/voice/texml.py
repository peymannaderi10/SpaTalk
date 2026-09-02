"""The Telnyx TeXML front door: answer a call by connecting it to our media socket."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from spatalk.conversations import start_conversation
from spatalk.voice.tokens import sign_stream_token

router = APIRouter()
XML = '<?xml version="1.0" encoding="UTF-8"?>'


@router.post("/telnyx/texml")
async def texml(request: Request):
    ctx = request.app.state.ctx
    form = await request.form()
    caller, to = form.get("From"), form.get("To")
    call_sid = form.get("CallSid") or form.get("CallControlId")
    tenant_id = await ctx.registry.resolve_number(to or "")
    if tenant_id is None:
        body = f"{XML}<Response><Say>This number is not configured.</Say><Hangup/></Response>"
        return Response(content=body, media_type="application/xml")
    cid = await start_conversation(ctx.sf, tenant_id, "voice", call_sid, caller)
    token = sign_stream_token(ctx.settings.secret_key, cid, tenant_id, caller)
    url = f"wss://{ctx.settings.media_ws_host}/ws/{token}"
    body = f'{XML}<Response><Connect><Stream url="{url}" bidirectionalMode="rtp" /></Connect></Response>'
    return Response(content=body, media_type="application/xml")
