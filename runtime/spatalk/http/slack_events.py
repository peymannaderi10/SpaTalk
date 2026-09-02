"""POST /slack/events: the door a staff reply comes in through.

Slack posts every message in every channel the bot is in. Almost all of it is not ours: only
a human's reply inside a thread whose root we posted for a conversation is a takeover, and
that is the only event this route acts on. Everything else is acknowledged and dropped, which
is what Slack needs (an unacknowledged event is retried, and a retry must never send a second
message to a customer).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from slack_sdk.signature import SignatureVerifier

from spatalk.text import takeover
from spatalk.text.service import record_inbound

router = APIRouter()

# Events Slack sends for edits, deletions, joins and the bot's own posts. None is a person
# typing a reply, and the first two carry someone else's text under a "message" type.
IGNORED_SUBTYPES = {
    "bot_message",
    "message_changed",
    "message_deleted",
    "channel_join",
    "channel_leave",
    "thread_broadcast",
}


@router.post("/slack/events")
async def events(request: Request):
    ctx = request.app.state.ctx
    raw = await request.body()
    verifier = SignatureVerifier(ctx.settings.slack_signing_secret)
    if not verifier.is_valid_request(raw, dict(request.headers)):
        raise HTTPException(status_code=401)
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400)

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}
    # A retry means our first answer was slow, not that anything new happened.
    if request.headers.get("X-Slack-Retry-Num"):
        logger.info("slack retry {} acknowledged without reprocessing", body.get("event_id"))
        return {"ok": True, "ignored": "retry"}
    if body.get("type") != "event_callback":
        return {"ok": True, "ignored": "type"}

    event = body.get("event") or {}
    if event.get("type") != "message":
        return {"ok": True, "ignored": "event_type"}
    if event.get("bot_id") or event.get("app_id") or event.get("subtype") in IGNORED_SUBTYPES:
        return {"ok": True, "ignored": "bot"}

    thread_ts = event.get("thread_ts")
    channel = event.get("channel", "")
    if not thread_ts or thread_ts == event.get("ts"):
        return {"ok": True, "ignored": "not_a_thread_reply"}

    conv = await takeover.conversation_for_thread(ctx.sf, channel, thread_ts)
    if conv is None:
        logger.info("slack message in thread {} matches no conversation", thread_ts)
        return {"ok": True, "ignored": "unknown_thread"}

    event_id = body.get("event_id") or event.get("ts") or ""
    if event_id and not await record_inbound(ctx.sf, event_id, conv.tenant_id, "slack"):
        logger.info("duplicate slack event {} ignored", event_id)
        return {"ok": True, "ignored": "duplicate"}

    await takeover.relay_from_staff(
        ctx, conv.id, event.get("text") or "", staff_id=event.get("user") or "slack"
    )
    return {"ok": True, "relayed": str(conv.id)}
