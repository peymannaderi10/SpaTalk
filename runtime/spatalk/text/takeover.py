"""Human takeover: the assistant steps aside when a person joins the conversation.

The Slack thread is the seam. A conversation's first tracked item posts a root message in
the tenant's channel; its channel and ``ts`` are stored on the conversation, and from then on
every customer and assistant message is mirrored into that thread. A staff reply in the
thread (or an SMS naming the item) hands control to the person: the conversation's
``controller`` becomes ``human``, the brain is not called again, and the staff wording is
relayed to the customer exactly as it was written.

Two rules hold everywhere in this module:

* Nothing is generated. A staff message is the person's own words; the only sentences this
  module produces are the two staff-facing notes posted in Slack, which no customer sees.
* Staff wording is stored with role ``staff`` and never enters the model's context as
  something the assistant said (:data:`spatalk.text.service.STAFF_NOTE` is what the model
  sees instead).
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from typing import Awaitable, Callable, Literal

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk.conversations import append_message, record_usage
from spatalk.models import Conversation, Message

Controller = Literal["ai", "human", "closed"]
Who = Literal["customer", "assistant"]

# How long a conversation waits for the person who took it over before the assistant resumes.
STAFF_SILENCE = timedelta(hours=12)

# Staff-facing notes. These are read in Slack by the team, never sent to a customer, so they
# are not tenant scripts: no customer-facing wording is produced anywhere in this module.
HANDBACK_NOTE = "Handed back to the assistant by {who}."
UNDELIVERED_NOTE = "NOT DELIVERED: your reply was not sent because {why}. It is on the record only."
WAITING_NOTE = (
    "Waiting to deliver: this visitor's chat window is closed. It will arrive if they return."
)
STALE_NOTE = "No staff reply for 12 hours: the assistant is answering this conversation again."

# Live chat sockets, by (tenant_id, session). One runtime node holds the socket a staff
# message must reach, so the registry is in this process; a message with nowhere to go waits
# in _PENDING_STAFF until the widget reconnects (it is in the transcript either way).
_CHAT_SOCKETS: dict[tuple[str, str], Callable[[str], Awaitable[None]]] = {}
_PENDING_STAFF: dict[tuple[str, str], list[str]] = {}


# ----- the Slack thread on a conversation -----------------------------------------------


async def store_thread(
    sf: async_sessionmaker, conversation_id: uuid.UUID, channel: str, ts: str
) -> None:
    """Remember where this conversation's Slack thread is."""
    async with sf() as s, s.begin():
        await s.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(slack_channel=channel, slack_ts=ts)
        )


async def thread_for(
    sf: async_sessionmaker, conversation_id: uuid.UUID | None
) -> tuple[str, str] | None:
    """The (channel, ts) of this conversation's thread root, if it has one."""
    if conversation_id is None:
        return None
    async with sf() as s:
        row = (
            await s.execute(
                select(Conversation.slack_channel, Conversation.slack_ts).where(
                    Conversation.id == conversation_id
                )
            )
        ).first()
    if row is None or not row[0] or not row[1]:
        return None
    return row[0], row[1]


async def conversation_for_thread(
    sf: async_sessionmaker, channel: str, thread_ts: str
) -> Conversation | None:
    async with sf() as s:
        return await s.scalar(
            select(Conversation)
            .where(Conversation.slack_ts == thread_ts, Conversation.slack_channel == channel)
            .limit(1)
        )


async def slack_token_for(ctx, conversation_id: uuid.UUID) -> str | None:
    """The bot token to post in this conversation's thread with.

    A workspace the tenant connected from the portal speaks with its own token (slack
    one-click connect); None means the global ``SLACK_BOT_TOKEN``, exactly as before.
    """
    # Imported here, not at module level, so `social` may import `text` and not the other way.
    from spatalk.social.slack_oauth import bot_token_for_tenant

    async with ctx.sf() as s:
        tenant_id = await s.scalar(
            select(Conversation.tenant_id).where(Conversation.id == conversation_id)
        )
    if tenant_id is None:
        return None
    return await bot_token_for_tenant(ctx.sf, ctx.settings, tenant_id)


async def mirror_to_thread(ctx, conversation_id: uuid.UUID, text: str, who: Who) -> None:
    """Put one side of the conversation into the Slack thread staff are reading.

    A no-op when the conversation has no thread (no bot token, or no item yet).
    """
    post = getattr(ctx.delivery, "post_in_thread", None)
    if post is None or not text.strip():
        return
    thread = await thread_for(ctx.sf, conversation_id)
    if thread is None:
        return
    label = "Customer" if who == "customer" else "Assistant"
    try:
        token = await slack_token_for(ctx, conversation_id)
        await post(thread[0], thread[1], f"{label}: {text}", token=token)
    except Exception as e:  # noqa: BLE001  Slack must never break a customer conversation
        logger.warning("could not mirror {} message to slack: {}", who, e)


# ----- who is answering -----------------------------------------------------------------


async def set_controller(
    sf: async_sessionmaker, conversation_id: uuid.UUID, controller: Controller, by: str
) -> None:
    """Hand the conversation to a person, back to the assistant, or close it."""
    async with sf() as s, s.begin():
        await s.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(controller=controller)
        )
    logger.info(
        "conversation {} is now controlled by {} (set by {})", conversation_id, controller, by
    )


# ----- reaching the customer ------------------------------------------------------------


def register_chat_socket(
    tenant_id: str, session: str, send: Callable[[str], Awaitable[None]]
) -> None:
    _CHAT_SOCKETS[(tenant_id, session)] = send


def unregister_chat_socket(tenant_id: str, session: str) -> None:
    _CHAT_SOCKETS.pop((tenant_id, session), None)


def take_pending_staff(tenant_id: str, session: str) -> list[str]:
    """Staff messages that arrived while this session had no socket. Drains the queue."""
    return _PENDING_STAFF.pop((tenant_id, session), [])


async def deliver_to_chat(tenant_id: str, session: str, text: str) -> bool:
    """Push a staff message down the visitor's socket, or hold it for the next connect."""
    send = _CHAT_SOCKETS.get((tenant_id, session))
    if send is not None:
        try:
            await send(text)
            return True
        except Exception as e:  # noqa: BLE001  a dead socket is a queue, not an error
            logger.warning("chat socket for {} failed: {}", session, e)
    _PENDING_STAFF.setdefault((tenant_id, session), []).append(text)
    return False


async def relay_from_staff(ctx, conversation_id: uuid.UUID, text: str, staff_id: str) -> None:
    """Send a person's words to the customer, verbatim, and pause the assistant.

    The words are stored with role ``staff`` so the model can never repeat them as its own.
    """
    text = text.strip()
    if not text:
        return
    async with ctx.sf() as s:
        conv = await s.get(Conversation, conversation_id)
    if conv is None:
        logger.warning("staff relay for unknown conversation {}", conversation_id)
        return

    await set_controller(ctx.sf, conversation_id, "human", by=staff_id)
    await append_message(ctx.sf, conversation_id, "staff", text)
    async with ctx.sf() as s, s.begin():
        await s.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(last_message_at=ctx.clock.now())
        )

    cfg = await ctx.registry.get(conv.tenant_id)
    if conv.channel == "sms":
        note = await _relay_sms(ctx, cfg, conv, text)
    elif conv.channel == "chat":
        delivered = await deliver_to_chat(conv.tenant_id, conv.external_ref or "", text)
        note = None if delivered else WAITING_NOTE
    elif conv.channel in ("instagram", "messenger"):
        # Meta channels go out through the Graph API (instagram plan, Task D2). Imported
        # here, not at module level, so `social` may import `text` and not the other way.
        from spatalk.social.handlers import relay_social

        why = await relay_social(ctx, conv, text)
        note = None if why is None else UNDELIVERED_NOTE.format(why=why)
    else:
        logger.warning("staff relay on channel {} is not wired yet; stored only", conv.channel)
        note = UNDELIVERED_NOTE.format(why=f"a {conv.channel} conversation cannot be replied to")
    # The team must never be left believing a message went out that did not (spec §5).
    if note:
        await _post_note(ctx, conversation_id, note)


async def _relay_sms(ctx, cfg, conv: Conversation, text: str) -> str | None:
    """Send the staff message as SMS. Returns a note for the thread if it could not go."""
    from spatalk.text.service import is_opted_out

    if not cfg.sms_from_number or not conv.caller:
        logger.warning("tenant {} has no sms_from_number; staff reply not sent", cfg.id)
        return UNDELIVERED_NOTE.format(why="this tenant has no SMS number")
    if await is_opted_out(ctx.sf, cfg.id, conv.caller):
        logger.info("customer opted out of {} texts; staff reply not sent", cfg.id)
        return UNDELIVERED_NOTE.format(why="this number is opted out of texts")
    # Verbatim: a person's words are never split, rewritten or truncated.
    await ctx.sms.send(cfg.sms_from_number, conv.caller, text)
    await record_usage(ctx.sf, cfg.id, conv.id, "sms", "telnyx", "sms_out", 1)
    return None


async def _post_note(ctx, conversation_id: uuid.UUID, note: str) -> None:
    post = getattr(ctx.delivery, "post_in_thread", None)
    thread = await thread_for(ctx.sf, conversation_id)
    if post is None or thread is None:
        return
    try:
        token = await slack_token_for(ctx, conversation_id)
        await post(thread[0], thread[1], note, token=token)
    except Exception as e:  # noqa: BLE001
        logger.warning("could not post a thread note: {}", e)


# ----- coming back to the assistant -----------------------------------------------------


async def hand_back(ctx, conversation_id: uuid.UUID, by: str, note: str) -> None:
    """Return the conversation to the assistant and say so in the thread."""
    await set_controller(ctx.sf, conversation_id, "ai", by=by)
    await _post_note(ctx, conversation_id, note)


async def hand_back_stale(ctx) -> int:
    """Resume the assistant on every conversation a person left silent for 12 hours."""
    cutoff = ctx.clock.now() - STAFF_SILENCE
    async with ctx.sf() as s:
        paused = list(
            (await s.scalars(select(Conversation).where(Conversation.controller == "human"))).all()
        )
    handed = 0
    for conv in paused:
        async with ctx.sf() as s:
            last = await s.scalar(
                select(Message.created_at)
                .where(Message.conversation_id == conv.id, Message.role == "staff")
                .order_by(Message.id.desc())
                .limit(1)
            )
        if last is not None and last > cutoff:
            continue
        await hand_back(ctx, conv.id, by="scheduler", note=STALE_NOTE)
        handed += 1
        logger.info("conversation {} returned to the assistant after 12 h of silence", conv.id)
    return handed


async def relay_staff_sms(ctx, cfg, sender: str, text: str) -> bool:
    """A staff member's SMS: ``#<item> <words>`` relays to that item's conversation.

    Returns True when the message was a relay. Anything else from a staff number is not a
    relay, and the caller answers it with the tenant's help text.
    """
    match = re.match(r"^#\s*(\d+)\s*(.*)$", text.strip(), re.S)
    if not match:
        return False
    item_id, words = int(match.group(1)), match.group(2).strip()
    if not words:
        return False
    item = await ctx.ledger.get(item_id)
    if item is None or item.tenant_id != cfg.id or item.conversation_id is None:
        logger.warning("staff sms named item {} which is not this tenant's", item_id)
        return False
    await relay_from_staff(ctx, item.conversation_id, words, staff_id=sender)
    return True
