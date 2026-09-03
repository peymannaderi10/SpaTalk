"""One turn of a text conversation, shared by every text channel.

SMS uses it today, web chat next (B4), Instagram and Messenger after that. The service owns
the parts that are the same everywhere: find or create the conversation inside a 24-hour
window, load the history the model may see, run :class:`~spatalk.brain.driver.Brain`, persist
both sides, meter the usage, and schedule the single follow-up. It owns none of the parts that
differ: signature checks, keyword handling and socket plumbing live in the adapters.

Two rules are enforced here rather than in the adapters, because an adapter can forget them:
an opted-out number is never sent anything, and a conversation under human control never
reaches the model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk import jobs
from spatalk.brain.audio_tags import strip_audio_tags
from spatalk.brain.capabilities import load_capabilities
from spatalk.brain.driver import Brain, LLMClient, TurnResult
from spatalk.brain.hours import BusinessCalendar
from spatalk.brain.renderer import render_script
from spatalk.brain.requests import ConversationRef
from spatalk.conversations import append_message, queue_call_notes, record_usage
from spatalk.models import Conversation, InboundMessage, Item, Job, Message, SmsOptout
from spatalk.text import takeover
from spatalk.text.segments import split_sms

Channel = Literal["sms", "chat", "instagram", "messenger"]

# How long a text conversation stays open to a new message before a new one is started.
WINDOW = timedelta(hours=24)
# How long after a question the single follow-up is sent, and the local hours it may land in.
FOLLOWUP_DELAY = timedelta(hours=2)
QUIET_FROM_HOUR = 21
QUIET_UNTIL_HOUR = 9
# What the model is told in place of staff wording: never the words themselves, so the model
# cannot repeat a person's promise back to the customer as its own.
STAFF_NOTE = "(A member of the team replied to this conversation directly.)"

# Per-channel segment limits and the usage units each channel meters.
SEGMENT_LIMIT = {"sms": 300}
USAGE_UNITS = {
    "sms": ("sms_in", "sms_out", "telnyx"),
    "chat": ("chat_in", "chat_out", "web"),
    "instagram": ("ig_in", "ig_out", "meta"),
    "messenger": ("fb_in", "fb_out", "meta"),
}


@dataclass
class InboundResult:
    conversation_id: uuid.UUID
    replies: list[str] = field(default_factory=list)
    turn: TurnResult | None = None
    suppressed: bool = False
    reason: str | None = None


async def record_inbound(
    sf: async_sessionmaker, provider_message_id: str, tenant_id: str, channel: str
) -> bool:
    """Claim a provider message id. False means the provider already delivered this one."""
    async with sf() as s, s.begin():
        result = await s.execute(
            insert(InboundMessage)
            .values(
                provider_message_id=provider_message_id, tenant_id=tenant_id, channel=channel
            )
            .on_conflict_do_nothing(index_elements=[InboundMessage.provider_message_id])
        )
        return result.rowcount == 1


async def is_opted_out(sf: async_sessionmaker, tenant_id: str, phone: str) -> bool:
    async with sf() as s:
        return (
            await s.get(SmsOptout, {"tenant_id": tenant_id, "phone": phone})
        ) is not None


async def add_optout(sf: async_sessionmaker, tenant_id: str, phone: str) -> None:
    async with sf() as s, s.begin():
        await s.execute(
            insert(SmsOptout)
            .values(tenant_id=tenant_id, phone=phone)
            .on_conflict_do_nothing(index_elements=[SmsOptout.tenant_id, SmsOptout.phone])
        )


async def remove_optout(sf: async_sessionmaker, tenant_id: str, phone: str) -> None:
    async with sf() as s, s.begin():
        await s.execute(
            delete(SmsOptout).where(
                SmsOptout.tenant_id == tenant_id, SmsOptout.phone == phone
            )
        )


class TextConversationService:
    def __init__(self, ctx: jobs.JobContext, llm: LLMClient):
        self._ctx, self._llm = ctx, llm

    # ----- conversation state -------------------------------------------------------

    async def find_or_create_conversation(
        self, tenant_id: str, channel: str, external_id: str, sender: str | None
    ) -> Conversation:
        """Reuse the conversation this sender is already in, or start a new one.

        Reuse needs an open conversation whose last message is inside the 24-hour window.
        A conversation the assistant ended (``closed_at``) is never reopened.
        """
        now = self._ctx.clock.now()
        async with self._ctx.sf() as s, s.begin():
            existing = await s.scalar(
                select(Conversation)
                .where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.channel == channel,
                    Conversation.external_ref == external_id,
                    Conversation.closed_at.is_(None),
                    Conversation.last_message_at.is_not(None),
                    Conversation.last_message_at >= now - WINDOW,
                )
                .order_by(Conversation.last_message_at.desc())
                .limit(1)
            )
            if existing is not None:
                return existing
            conv = Conversation(
                tenant_id=tenant_id,
                channel=channel,
                external_ref=external_id,
                caller=sender,
                last_message_at=now,
            )
            s.add(conv)
            await s.flush()
            await s.refresh(conv)
            return conv

    async def history(self, conversation_id: uuid.UUID, limit: int = 20) -> list[dict]:
        """The last ``limit`` messages as the model may see them.

        Staff wording never enters the model's context: a run of staff messages collapses to
        one neutral note that a person replied, so the model can neither repeat a promise a
        person made nor treat it as something it said itself.
        """
        async with self._ctx.sf() as s:
            rows = list(
                (
                    await s.scalars(
                        select(Message)
                        .where(Message.conversation_id == conversation_id)
                        .order_by(Message.id.desc())
                        .limit(limit)
                    )
                ).all()
            )
        out: list[dict] = []
        for m in reversed(rows):
            if m.role == "user":
                out.append({"role": "user", "content": m.text})
            elif m.role == "assistant":
                out.append({"role": "assistant", "content": m.text})
            elif m.role == "staff":
                note = {"role": "assistant", "content": STAFF_NOTE}
                if not out or out[-1] != note:
                    out.append(note)
        return out

    # ----- one inbound message ------------------------------------------------------

    async def handle_inbound(
        self,
        tenant_id: str,
        channel: Channel,
        external_id: str,
        sender: str | None,
        text: str,
        provider_message_id: str | None,
        suppressed_reason: str | None = None,
    ) -> InboundResult:
        """Take one customer message and produce what the channel should send back.

        ``provider_message_id`` is the dedup key. Pass ``None`` when the adapter has already
        claimed it (the SMS router does, because it must dedup before the STOP keywords).
        ``suppressed_reason`` (plan F: ``blocked``, ``muted``, ``capped``) stores the message
        and stops there: no model call, no reply, no follow-up.
        """
        ctx = self._ctx
        cfg = await ctx.registry.get(tenant_id)
        conv = await self.find_or_create_conversation(tenant_id, channel, external_id, sender)
        if provider_message_id is not None and not await record_inbound(
            ctx.sf, provider_message_id, tenant_id, channel
        ):
            logger.info("duplicate {} message {} ignored", channel, provider_message_id)
            return InboundResult(conv.id, suppressed=True, reason="duplicate")
        await append_message(ctx.sf, conv.id, "user", text, at=ctx.clock.now())
        # Staff read the conversation in Slack, whoever is answering it (Task B5).
        await takeover.mirror_to_thread(ctx, conv.id, text, "customer")
        await self._touch(conv.id)
        await self._meter(cfg.id, conv.id, channel, USAGE_UNITS[channel][0], 1)
        if suppressed_reason is not None:
            logger.info("{} text from {} stored and not answered: {}", channel, sender, suppressed_reason)
            return InboundResult(conv.id, suppressed=True, reason=suppressed_reason)

        if channel == "sms" and sender and await is_opted_out(ctx.sf, tenant_id, sender):
            logger.info("sender opted out of {} texts; nothing sent", tenant_id)
            return InboundResult(conv.id, suppressed=True, reason="optout")
        if conv.controller == "human":
            logger.info("conversation {} is under human control; brain not called", conv.id)
            return InboundResult(conv.id, suppressed=True, reason="human")

        caps = load_capabilities(cfg, ctx.ledger, ctx.sms, ctx.clock)
        ref = ConversationRef(
            conversation_id=conv.id,
            tenant=cfg,
            channel=channel,
            caller_phone=conv.caller,
            health_context=conv.health_context,
        )
        turn = await Brain(self._llm, caps, ctx.clock).turn(
            ref, await self.history(conv.id), text
        )
        # A tag meant for a voice is never something a customer reads.
        replies = self._segments(strip_audio_tags(turn.reply), channel)
        for part in replies:
            await append_message(ctx.sf, conv.id, "assistant", part, at=ctx.clock.now())
            await takeover.mirror_to_thread(ctx, conv.id, part, "assistant")
        await self._finish_turn(cfg, conv, turn)
        if replies:
            await self._meter(
                cfg.id, conv.id, channel, USAGE_UNITS[channel][1], len(replies)
            )
            await self._deliver(cfg, conv, channel, replies)
        if turn.reply.rstrip().endswith("?"):
            await self.schedule_followup(conv)
        return InboundResult(conv.id, replies=replies, turn=turn)

    def _segments(self, reply: str, channel: str) -> list[str]:
        if not reply.strip():
            return []
        limit = SEGMENT_LIMIT.get(channel)
        if limit is None:
            return [" ".join(reply.split())]
        return split_sms(reply, limit)

    async def _deliver(self, cfg, conv: Conversation, channel: str, replies: list[str]) -> None:
        """Send the parts on the channels this service can reach directly.

        SMS goes out through the ``SmsPort`` here. Chat and the social channels are delivered
        by their own adapters, which hold the socket or the Graph token.
        """
        if channel != "sms":
            return
        if not cfg.sms_from_number or not conv.caller:
            logger.warning("tenant {} has no sms_from_number; reply not sent", cfg.id)
            return
        if await is_opted_out(self._ctx.sf, cfg.id, conv.caller):
            return
        for part in replies:
            await self._ctx.sms.send(cfg.sms_from_number, conv.caller, part)

    async def _finish_turn(self, cfg, conv: Conversation, turn: TurnResult) -> None:
        now = self._ctx.clock.now()
        values: dict = {"last_message_at": now}
        if turn.health_context:
            values["health_context"] = True
        if turn.band is not None:
            # A conversation keeps the highest band it ever reached: a later routine turn
            # must not erase the fact that an earlier one went to a human.
            values["band"] = func.greatest(func.coalesce(Conversation.band, 0), turn.band)
        if turn.ended:
            values["closed_at"] = now
            values["ended_at"] = now
        async with self._ctx.sf() as s, s.begin():
            await s.execute(
                update(Conversation).where(Conversation.id == conv.id).values(**values)
            )
        # Call-notes plan, Task N1: the close is where a text conversation gets its notes,
        # for the same reason the end of a call is. The handler is idempotent per
        # conversation, so a second close cannot draft twice.
        if turn.ended and cfg.call_notes:
            await queue_call_notes(self._ctx.sf, conv.id)

    async def _touch(self, conversation_id: uuid.UUID) -> None:
        async with self._ctx.sf() as s, s.begin():
            await s.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(last_message_at=self._ctx.clock.now())
            )

    async def _meter(
        self, tenant_id: str, conversation_id: uuid.UUID, channel: str, unit: str, qty: float
    ) -> None:
        await record_usage(
            self._ctx.sf,
            tenant_id,
            conversation_id,
            channel,
            USAGE_UNITS[channel][2],
            unit,
            qty,
        )

    # ----- the single follow-up -----------------------------------------------------

    async def schedule_followup(self, conversation: Conversation) -> int | None:
        """Queue the one follow-up, if this conversation is still owed one.

        Nothing is scheduled when a tracked item already exists (the team is on it), when the
        follow-up has already gone out, or when one is already queued.
        """
        ctx, conv = self._ctx, conversation
        if conv.channel != "sms" or not conv.caller:
            return None
        cfg = await ctx.registry.get(conv.tenant_id)
        async with ctx.sf() as s:
            fresh = await s.get(Conversation, conv.id)
            if fresh is None or fresh.followup_sent_at is not None or fresh.closed_at is not None:
                return None
            if await s.scalar(
                select(Item.id).where(Item.conversation_id == conv.id).limit(1)
            ):
                return None
            queued = await s.scalar(
                select(Job.id)
                .where(
                    Job.kind == "text.followup",
                    Job.state == "queued",
                    Job.payload["conversation_id"].astext == str(conv.id),
                )
                .limit(1)
            )
        if queued:
            return None
        # The follow-up is owed to *this* moment in the conversation. If any message lands
        # after it, the conversation moved on and the check-in would be noise.
        async with ctx.sf() as s:
            after = await s.scalar(
                select(func.max(Message.id)).where(Message.conversation_id == conv.id)
            )
        run_at = self._followup_time(cfg, ctx.clock.now())
        return await jobs.enqueue(
            ctx.sf,
            "text.followup",
            {
                "conversation_id": str(conv.id),
                "tenant_id": conv.tenant_id,
                "after_message_id": after or 0,
            },
            run_at=run_at,
        )

    @staticmethod
    def _followup_time(cfg, now: datetime) -> datetime:
        candidate = now + FOLLOWUP_DELAY
        local = candidate.astimezone(ZoneInfo(cfg.timezone))
        if QUIET_UNTIL_HOUR <= local.hour < QUIET_FROM_HOUR:
            return candidate
        return BusinessCalendar(cfg).next_open(candidate)


@jobs.register_handler("text.followup")
async def _send_followup(payload: dict, ctx: jobs.JobContext) -> None:
    """Send the one check-in, but only if the customer never came back."""
    conversation_id = uuid.UUID(payload["conversation_id"])
    async with ctx.sf() as s:
        conv = await s.get(Conversation, conversation_id)
        latest = await s.scalar(
            select(func.max(Message.id)).where(Message.conversation_id == conversation_id)
        )
    if conv is None or conv.followup_sent_at is not None or conv.closed_at is not None:
        return
    if conv.controller != "ai" or (latest or 0) > payload.get("after_message_id", 0):
        logger.info("follow-up for {} skipped: the conversation moved on", conversation_id)
        return
    if not conv.caller:
        return
    cfg = await ctx.registry.get(conv.tenant_id)
    if not cfg.sms_from_number or await is_opted_out(ctx.sf, cfg.id, conv.caller):
        return
    text = render_script("followup", cfg, ctx.clock.now(), urgent=False)
    await ctx.sms.send(cfg.sms_from_number, conv.caller, text)
    await append_message(ctx.sf, conversation_id, "assistant", text)
    await record_usage(ctx.sf, cfg.id, conversation_id, conv.channel, "telnyx", "sms_out", 1)
    async with ctx.sf() as s, s.begin():
        await s.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(followup_sent_at=ctx.clock.now())
        )


def make_text_llm(settings) -> LLMClient | None:
    """The production LLM client for text channels, or None when no key is configured.

    `LLM_MODEL` names the vendor as well as the model (operations plan, Task E6), and it is
    read here exactly as `voice.pipeline.make_llm` reads it, so one environment change
    swaps every channel at once rather than leaving text on the retired vendor.
    """
    from spatalk.brain.driver import OPENAI, GeminiClient, OpenAIClient, provider_for

    if provider_for(settings.llm_model) == OPENAI:
        key = getattr(settings, "openai_api_key", "")
        return OpenAIClient(key, settings.llm_model) if key else None
    if not settings.google_api_key:
        return None
    return GeminiClient(settings.google_api_key, settings.llm_model)
