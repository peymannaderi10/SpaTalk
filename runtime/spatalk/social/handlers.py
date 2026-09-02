"""What happens after a Meta webhook returns 200: the jobs that answer an event.

The webhook's only job is to be fast and to be sure (signature, dedup, enqueue). Everything
that can be slow or can fail — the model, the ledger, the Graph send — happens here, in a job
that can be retried.

Three rules shape this module:

* Nothing is sent outside Meta's 24-hour messaging window. Outside it the conversation is
  closed and a tracked item is filed instead, so a person answers from the Instagram or Page
  inbox. The assistant never quietly drops a customer.
* Public comment replies are fixed tenant wording (``scripts.comment_public_reply``). Only the
  private reply goes through the brain, the guard and the ledger, like every other channel.
* A retryable Graph failure (429, 5xx) comes back later; any other 4xx is a dead letter with
  the response body, because retrying it would only repeat the same refusal.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from spatalk import jobs
from spatalk.brain.ports import ItemDraft
from spatalk.brain.renderer import render_script
from spatalk.brain.requests import ContactInfo, ConversationRef
from spatalk.conversations import append_message, record_usage
from spatalk.models import Conversation, Item, Message
from spatalk.social.events import ACTIONABLE, SocialEvent
from spatalk.social.graph import GraphClient, GraphError, HttpGraphClient
from spatalk.social.meta_oauth import (
    FACEBOOK_GRAPH_BASE,
    INSTAGRAM_GRAPH_BASE,
    access_token,
    integration_by_external_id,
    integration_for,
)
from spatalk.social.models import MetaEvent, MetaWindow
from spatalk.text.service import (
    USAGE_UNITS,
    TextConversationService,
    make_text_llm,
    record_inbound,
)

IG_EVENT_JOB = "social.ig_event"
FB_EVENT_JOB = "social.fb_event"

# Meta lets a business answer a person for 24 hours after that person's last message.
MESSAGING_WINDOW = timedelta(hours=24)

# The channel each provider's conversations use, and the provider each channel sends through.
PROVIDER_FOR_CHANNEL = {"instagram": "instagram", "messenger": "messenger"}

# Instagram and a Facebook Page are the same product with two hosts and two comment edges.
GRAPH_BASE_FOR_CHANNEL = {
    "instagram": INSTAGRAM_GRAPH_BASE,
    "messenger": FACEBOOK_GRAPH_BASE,
}


# ----- from the webhook to the queue -------------------------------------------------------


async def claim_event(sf, event: SocialEvent, tenant_id: str, provider: str) -> bool:
    """Record this event id once. False means Meta has already delivered it."""
    async with sf() as s, s.begin():
        result = await s.execute(
            insert(MetaEvent)
            .values(
                event_id=event.event_id,
                tenant_id=tenant_id,
                provider=provider,
                kind=event.kind,
            )
            .on_conflict_do_nothing(index_elements=[MetaEvent.event_id])
        )
        return result.rowcount == 1


async def ingest_events(ctx, provider: str, events: list[SocialEvent], job_kind: str) -> int:
    """Resolve, deduplicate and queue. Returns how many jobs were enqueued.

    Every event is recorded, including the ones nobody answers (echoes of our own sends,
    postbacks, read receipts): that record is the dedup key and the audit trail. Only the
    kinds an adapter acts on become jobs.
    """
    queued = 0
    for event in events:
        integration = await integration_by_external_id(
            ctx.sf, provider, event.tenant_external_id
        )
        if integration is None:
            logger.warning(
                "{} event for account {} which no tenant has connected",
                provider,
                event.tenant_external_id,
            )
            continue
        if not await claim_event(ctx.sf, event, integration.tenant_id, provider):
            logger.info("duplicate {} event {} ignored", provider, event.event_id)
            continue
        if event.kind not in ACTIONABLE:
            continue
        if event.sender_id == integration.external_id:
            # Our own comment on our own post, or an event the account raised about itself.
            logger.info("{} event from the account itself ignored", provider)
            continue
        await jobs.enqueue(ctx.sf, job_kind, {"event": event.to_payload()})
        queued += 1
    return queued


# ----- the 24-hour window ----------------------------------------------------------------


async def record_window(sf, tenant_id: str, provider: str, sender_id: str, at: datetime) -> None:
    """Remember when this person last wrote to us. Never moves backwards."""
    column = MetaWindow.__table__.c.last_inbound_at
    async with sf() as s, s.begin():
        await s.execute(
            insert(MetaWindow)
            .values(
                tenant_id=tenant_id,
                provider=provider,
                sender_id=sender_id,
                last_inbound_at=at,
            )
            .on_conflict_do_update(
                index_elements=[
                    MetaWindow.tenant_id,
                    MetaWindow.provider,
                    MetaWindow.sender_id,
                ],
                set_={"last_inbound_at": func.greatest(column, at)},
            )
        )


async def window_open(
    sf, tenant_id: str, provider: str, sender_id: str, now: datetime
) -> bool:
    """True when a message may still be sent to this person."""
    async with sf() as s:
        row = await s.get(
            MetaWindow,
            {"tenant_id": tenant_id, "provider": provider, "sender_id": sender_id},
        )
    return row is not None and now - row.last_inbound_at <= MESSAGING_WINDOW


# ----- talking to Meta -------------------------------------------------------------------


def _client(ctx, integration, channel: str) -> GraphClient:
    """The Graph client for a send. Tests inject a fake through ``ctx.graph``."""
    injected = getattr(ctx, "graph", None)
    if injected is not None:
        return injected
    token = access_token(integration, ctx.settings)
    return HttpGraphClient(GRAPH_BASE_FOR_CHANNEL[channel], lambda: token)


def _path(ctx, *parts: str) -> str:
    return "/" + "/".join((ctx.settings.meta_graph_version, *parts))


def _reply_call(ctx, integration, channel: str, recipient: dict, text: str) -> tuple[str, dict]:
    """Where one reply goes on this channel, and what the body looks like.

    Instagram answers both a direct message and a comment on the account's ``messages``
    edge, distinguished by the recipient (``id`` or ``comment_id``). A Page has two separate
    edges instead: ``messages`` for a conversation, ``private_replies`` on the comment
    itself. This is the only place that difference exists.
    """
    comment_id = recipient.get("comment_id")
    if channel == "messenger":
        if comment_id:
            return _path(ctx, str(comment_id), "private_replies"), {"message": text}
        return (
            _path(ctx, integration.external_id, "messages"),
            {
                "recipient": recipient,
                "message": {"text": text},
                # A Page must say why it is writing; this is always an answer to a person.
                "messaging_type": "RESPONSE",
            },
        )
    return (
        _path(ctx, integration.external_id, "messages"),
        {"recipient": recipient, "message": {"text": text}},
    )


async def send_message(ctx, integration, channel: str, recipient: dict, text: str) -> None:
    """One Graph send: a direct message, or a private reply to a comment."""
    path, body = _reply_call(ctx, integration, channel, recipient, text)
    await _client(ctx, integration, channel).post(path, json=body)


async def send_public_reply(ctx, integration, channel: str, comment_id: str, text: str) -> None:
    """The one public sentence, which is fixed tenant wording and never the model's."""
    edge = "comments" if channel == "messenger" else "replies"
    await _client(ctx, integration, channel).post(
        _path(ctx, comment_id, edge), json={"message": text}
    )


# ----- conversation helpers ---------------------------------------------------------------


def _service(ctx) -> TextConversationService:
    llm = getattr(ctx, "llm", None)
    if llm is None:
        llm = ctx.llm = make_text_llm(ctx.settings)
    if llm is None:
        raise RuntimeError("no llm configured; the instagram event cannot be answered")
    return TextConversationService(ctx, llm)


def _conversations(ctx) -> TextConversationService:
    """The same service, for the paths that only need its conversation bookkeeping.

    Filing a callback because the window closed must work on a runtime with no model key:
    the customer's words still have to land somewhere a person can read them.
    """
    return TextConversationService(ctx, getattr(ctx, "llm", None))


def matches_keyword(text: str, keywords: list[str]) -> bool:
    """Case-insensitive, word-bounded, and multi-word keywords are allowed."""
    terms = [k.strip() for k in keywords if k and k.strip()]
    if not terms:
        return False
    alts = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
    return re.search(rf"(?<![\w-])(?:{alts})(?![\w-])", text or "", re.IGNORECASE) is not None


async def _first_contact(ctx, conversation_id) -> bool:
    """True when nobody on our side has said anything in this conversation yet."""
    async with ctx.sf() as s:
        seen = await s.scalar(
            select(Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_(("assistant", "staff")),
            )
            .limit(1)
        )
    return seen is None


async def open_greeting(ctx, cfg, conv) -> str:
    """Put this channel's one-sentence AI disclosure on the record, once per conversation.

    It is stored as the conversation's first assistant message, ahead of the customer's first
    message, so a transcript shows the disclosure was given. It is never sent on its own: the
    caller prefixes it onto the first reply, so the customer gets one message, not two.
    """
    greeting = render_script("dm_greeting", cfg, ctx.clock.now(), urgent=False)
    if conv.controller == "ai" and await _first_contact(ctx, conv.id):
        await append_message(ctx.sf, conv.id, "assistant", greeting)
    return greeting


async def greeting_due(ctx, conversation_id, greeting: str, reply_count: int) -> bool:
    """True when the replies about to go out are the first ones this person will receive.

    Read from the transcript rather than from a flag, so a job retried after a failed send
    still carries the disclosure: the customer must hear it once, and exactly once.
    """
    async with ctx.sf() as s:
        ours = list(
            (
                await s.scalars(
                    select(Message.text)
                    .where(
                        Message.conversation_id == conversation_id,
                        Message.role.in_(("assistant", "staff")),
                    )
                    .order_by(Message.id)
                )
            ).all()
        )
    return len(ours) == reply_count + 1 and ours[0] == greeting


async def _replies_to_send(ctx, result) -> list[str]:
    """What this job should put on the wire.

    Normally the replies the turn just produced. When the turn was deduplicated, this job is
    a retry of one whose send failed: the reply is already on the record, so it is sent from
    there rather than asking the model a second time.
    """
    if not result.suppressed:
        return list(result.replies)
    if result.reason != "duplicate":
        return []
    async with ctx.sf() as s:
        rows = list(
            (
                await s.scalars(
                    select(Message)
                    .where(Message.conversation_id == result.conversation_id)
                    .order_by(Message.id.desc())
                    .limit(4)
                )
            ).all()
        )
    trailing: list[str] = []
    for message in rows:
        if message.role != "assistant":
            break
        trailing.append(message.text)
    return list(reversed(trailing))


async def _conversation_for_sender(ctx, cfg, provider_channel: str, sender_id: str):
    """The latest conversation with this person, open or closed."""
    async with ctx.sf() as s:
        return await s.scalar(
            select(Conversation)
            .where(
                Conversation.tenant_id == cfg.id,
                Conversation.channel == provider_channel,
                Conversation.external_ref == sender_id,
            )
            .order_by(Conversation.started_at.desc())
            .limit(1)
        )


async def close_and_capture(ctx, cfg, channel: str, event: SocialEvent) -> None:
    """Outside the window: say nothing, keep the message, and put a person on it.

    The only contact Meta gives us is a username (Instagram) or a display name (a Page), so
    that is what the item carries. The words stay in the transcript, where free text belongs
    (there is no free text on an item).
    """
    now = ctx.clock.now()
    conv = await _conversation_for_sender(ctx, cfg, channel, event.sender_id)
    if conv is None:
        conv = await _conversations(ctx).find_or_create_conversation(
            cfg.id, channel, event.sender_id, None
        )
    if event.event_id and not await record_inbound(ctx.sf, event.event_id, cfg.id, channel):
        logger.info("duplicate {} event {} ignored", channel, event.event_id)
        return
    await append_message(ctx.sf, conv.id, "user", event.text)
    await record_usage(
        ctx.sf, cfg.id, conv.id, channel, USAGE_UNITS[channel][2], USAGE_UNITS[channel][0], 1
    )
    async with ctx.sf() as s, s.begin():
        await s.execute(
            update(Conversation)
            .where(Conversation.id == conv.id, Conversation.closed_at.is_(None))
            .values(closed_at=now, ended_at=now)
        )
    async with ctx.sf() as s:
        already = await s.scalar(
            select(Item.id)
            .join(Conversation, Item.conversation_id == Conversation.id)
            .where(
                Conversation.tenant_id == cfg.id,
                Conversation.channel == channel,
                Conversation.external_ref == event.sender_id,
                Item.state.in_(("open", "acknowledged")),
            )
            .limit(1)
        )
    if already:
        logger.info("a person is already on {}'s {} conversation", event.sender_id, channel)
        return
    await ctx.ledger.create_item(
        ConversationRef(conversation_id=conv.id, tenant=cfg, channel=channel),
        ItemDraft(
            type="callback",
            urgency="normal",
            contact=ContactInfo(name=event.username or event.sender_id),
        ),
    )
    logger.info("{} window closed for {}; a callback was filed", channel, event.sender_id)


# ----- one inbound message, answered ---------------------------------------------------------


async def answer_inbound(ctx, cfg, integration, event: SocialEvent, channel: str,
                         recipient: dict) -> bool:
    """The path a direct message and a comment-triggered private reply both take.

    Returns True when something was actually put on the wire. Everything a channel does
    differently — who the recipient is, what policy let the message through — is decided by
    the caller; what happens to the words is the same here as on SMS and web chat.
    """
    now = ctx.clock.now()
    provider = PROVIDER_FOR_CHANNEL[channel]
    await record_window(ctx.sf, cfg.id, provider, event.sender_id, event.timestamp or now)
    if not await window_open(ctx.sf, cfg.id, provider, event.sender_id, now):
        await close_and_capture(ctx, cfg, channel, event)
        return False

    service = _service(ctx)
    conv = await service.find_or_create_conversation(cfg.id, channel, event.sender_id, None)
    greeting = await open_greeting(ctx, cfg, conv)
    result = await service.handle_inbound(
        tenant_id=cfg.id,
        channel=channel,
        external_id=event.sender_id,
        sender=None,
        text=event.text,
        provider_message_id=event.event_id,
    )
    replies = await _replies_to_send(ctx, result)
    if not replies:
        return False
    if await greeting_due(ctx, conv.id, greeting, len(replies)):
        replies[0] = f"{greeting} {replies[0]}"
    for part in replies:
        await send_message(ctx, integration, channel, recipient, part)
    return True


# ----- the two event kinds, on either channel ----------------------------------------------


async def _handle_message(ctx, cfg, integration, event: SocialEvent, channel: str) -> None:
    await answer_inbound(ctx, cfg, integration, event, channel, {"id": event.sender_id})


async def _handle_comment(ctx, cfg, integration, event: SocialEvent, channel: str) -> None:
    """A comment the tenant's policy says to answer: reply privately, then optionally in public."""
    policy = cfg.social
    if policy.comment_mode == "off":
        return
    if policy.comment_mode == "keyword" and not matches_keyword(
        event.text, policy.comment_keywords
    ):
        logger.info("comment {} matched no keyword; nothing sent", event.event_id)
        return

    replied = await answer_inbound(
        ctx, cfg, integration, event, channel, {"comment_id": event.comment_id}
    )
    if replied and policy.public_reply_enabled and event.comment_id:
        try:
            await send_public_reply(
                ctx,
                integration,
                channel,
                event.comment_id,
                render_script("comment_public_reply", cfg, ctx.clock.now(), urgent=False),
            )
        except GraphError as e:
            # The private reply is already delivered. Failing the job now would retry it and
            # send the customer a second copy, so the public courtesy is dropped instead.
            logger.warning("public reply to comment {} failed: {}", event.comment_id, e)


async def _social_event(payload: dict, ctx, channel: str) -> None:
    """One Meta event on either channel: a message, or a comment the policy answers."""
    event = SocialEvent.from_payload(payload["event"])
    provider = PROVIDER_FOR_CHANNEL[channel]
    integration = await integration_by_external_id(ctx.sf, provider, event.tenant_external_id)
    if integration is None:
        logger.warning(
            "{} event for account {} which no tenant has connected",
            provider,
            event.tenant_external_id,
        )
        return
    cfg = await ctx.registry.get(integration.tenant_id)
    try:
        if event.kind == "message":
            await _handle_message(ctx, cfg, integration, event, channel)
        elif event.kind == "comment":
            await _handle_comment(ctx, cfg, integration, event, channel)
    except GraphError as e:
        if e.retryable:
            raise
        # Meta refused this call and will refuse it again: stop, and keep the reason.
        raise jobs.DeadLetter(f"graph {e.status_code}: {e.body}") from e


@jobs.register_handler(IG_EVENT_JOB)
async def ig_event(payload: dict, ctx) -> None:
    """One Instagram event: a direct message, or a comment the tenant's policy answers."""
    await _social_event(payload, ctx, "instagram")


@jobs.register_handler(FB_EVENT_JOB)
async def fb_event(payload: dict, ctx) -> None:
    """One Facebook Page event: a message, or a feed comment the tenant's policy answers."""
    await _social_event(payload, ctx, "messenger")


# ----- human takeover ----------------------------------------------------------------------


async def relay_social(ctx, conv, text: str) -> str | None:
    """Send a staff member's words out through Graph. Returns why it could not go, or None.

    Called by :mod:`spatalk.text.takeover`, which posts the reason in the Slack thread so the
    team is never left believing a message went out that did not.
    """
    provider = PROVIDER_FOR_CHANNEL.get(conv.channel)
    if provider is None:
        return f"{conv.channel} replies are not connected yet"
    integration = await integration_for(ctx.sf, conv.tenant_id, provider)
    if integration is None:
        return f"this tenant has no {provider} account connected"
    sender_id = conv.external_ref or ""
    if not await window_open(ctx.sf, conv.tenant_id, provider, sender_id, ctx.clock.now()):
        return f"the 24-hour {provider} messaging window has closed"
    await send_message(ctx, integration, conv.channel, {"id": sender_id}, text)
    await record_usage(
        ctx.sf,
        conv.tenant_id,
        conv.id,
        conv.channel,
        USAGE_UNITS[conv.channel][2],
        USAGE_UNITS[conv.channel][1],
        1,
    )
    return None
