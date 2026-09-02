from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature
from slack_sdk.signature import SignatureVerifier

from spatalk.ledger.delivery import build_links, build_slack_blocks
from spatalk.ledger.links import verify_action

router = APIRouter()


@router.post("/slack/interactions")
async def interactions(request: Request):
    ctx = request.app.state.ctx
    raw = await request.body()
    verifier = SignatureVerifier(ctx.settings.slack_signing_secret)
    if not verifier.is_valid_request(raw, dict(request.headers)):
        raise HTTPException(status_code=401)
    form = await request.form()
    payload = json.loads(form["payload"])
    action = payload["actions"][0]
    actor = payload.get("user", {}).get("username") or payload.get("user", {}).get("id", "slack")
    # The button value is the only thing that authorises the click: a signed claim naming the
    # item, the action and the tenant. action_id is presentation only and is never trusted.
    try:
        claim = verify_action(ctx.settings.secret_key, str(action.get("value", "")))
    except BadSignature:
        raise HTTPException(status_code=401)
    if claim.action not in ("ack", "resolve"):
        raise HTTPException(status_code=400)
    item = await ctx.ledger.get(claim.item_id)
    if item is None:
        raise HTTPException(status_code=404)
    if item.tenant_id != claim.tenant_id:
        raise HTTPException(status_code=403)
    if claim.action == "ack":
        item = await ctx.ledger.acknowledge(claim.item_id, actor)
    else:
        item = await ctx.ledger.resolve(claim.item_id, actor)
    if item is None:
        raise HTTPException(status_code=404)
    cfg = await ctx.registry.get(item.tenant_id)
    blocks = build_slack_blocks(item, cfg, build_links(ctx.settings, item), ctx.clock.now())
    blocks[-1] = {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"*{item.state}* by {actor}"}],
    }
    return JSONResponse({"replace_original": True, "blocks": blocks})
