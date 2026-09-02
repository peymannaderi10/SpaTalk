from __future__ import annotations

from html import escape

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from itsdangerous import BadSignature

from spatalk.conversations import get_transcript
from spatalk.ledger.links import verify_action
from spatalk.models import AuditLog

router = APIRouter()
PAGE = (
    "<!doctype html><meta name=viewport content='width=device-width'>"
    "<body style='font:16px system-ui;max-width:40rem;margin:3rem auto;padding:0 1rem'>"
    "{body}</body>"
)


def _claim(request: Request, token: str):
    try:
        return verify_action(request.app.state.ctx.settings.secret_key, token)
    except BadSignature:
        raise HTTPException(status_code=404)


async def _audit(ctx, actor: str, action: str, record_type: str, record_id: str) -> None:
    async with ctx.sf() as s, s.begin():
        s.add(AuditLog(actor=actor, action=action, record_type=record_type, record_id=record_id))


@router.get("/a/{token}", response_class=HTMLResponse)
async def confirm(request: Request, token: str):
    ctx = request.app.state.ctx
    claim = _claim(request, token)
    item = await ctx.ledger.get(claim.item_id)
    if item is None:
        raise HTTPException(status_code=404)
    if claim.action == "transcript":
        await _audit(ctx, "link", "read_transcript", "conversation", str(item.conversation_id))
        msgs = await get_transcript(ctx.sf, item.conversation_id) if item.conversation_id else []
        rows = (
            "".join(f"<p><b>{escape(m.role)}:</b> {escape(m.text)}</p>" for m in msgs)
            or "<p>No transcript.</p>"
        )
        return PAGE.format(body=f"<h2>Item #{item.id} transcript</h2>{rows}")
    verb = "Acknowledge" if claim.action == "ack" else "Resolve"
    body = (
        f"<h2>{verb} item #{item.id}?</h2>"
        f"<p>Type: {escape(item.type)} &middot; State: {escape(item.state)}</p>"
        f"<form method=post><label>Your name or email <input name=actor required></label> "
        f"<button type=submit>{verb}</button></form>"
    )
    return PAGE.format(body=body)


@router.post("/a/{token}", response_class=HTMLResponse)
async def act(request: Request, token: str, actor: str = Form(...)):
    ctx = request.app.state.ctx
    claim = _claim(request, token)
    if claim.action == "ack":
        item = await ctx.ledger.acknowledge(claim.item_id, actor)
    elif claim.action == "resolve":
        item = await ctx.ledger.resolve(claim.item_id, actor)
    else:
        raise HTTPException(status_code=404)
    if item is None:
        raise HTTPException(status_code=404)
    await _audit(ctx, actor, claim.action, "item", str(item.id))
    return PAGE.format(
        body=f"<h2>Done</h2><p>Item #{item.id} is now <b>{escape(item.state)}</b>. "
        f"You can close this tab.</p>"
    )
