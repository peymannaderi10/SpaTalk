from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from slack_sdk.signature import SignatureVerifier

from spatalk.ledger.delivery import build_links, build_slack_blocks

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
    item_id = int(action["value"])
    if action["action_id"] == "ack":
        item = await ctx.ledger.acknowledge(item_id, actor)
    elif action["action_id"] == "resolve":
        item = await ctx.ledger.resolve(item_id, actor)
    else:
        raise HTTPException(status_code=400)
    if item is None:
        raise HTTPException(status_code=404)
    cfg = await ctx.registry.get(item.tenant_id)
    blocks = build_slack_blocks(item, cfg, build_links(ctx.settings, item), ctx.clock.now())
    blocks[-1] = {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"*{item.state}* by {actor}"}],
    }
    return JSONResponse({"replace_original": True, "blocks": blocks})
