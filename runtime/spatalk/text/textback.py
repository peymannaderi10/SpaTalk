"""Missed-call text-back: one text to a caller the assistant never got to help.

A caller who hangs up in the first seconds, or whose call carried no speech at all, gets a
single SMS inviting them to text back or book online. It is the one message this system sends
without being asked, so the guards matter more than the feature:

* nothing is sent to a number that opted out, ever;
* nothing is sent twice to the same caller inside a day;
* nothing is sent to a caller id that is really one of our own numbers or the clinic's own
  line, which is what a lost caller id looks like when the carrier substitutes the main
  number: texting that would have the clinic texting itself, on repeat.

The wording is the tenant's `scripts.missed_call_text` and nothing else; the model is not
involved. The SMS conversation the text starts is linked back to the voice call through
`conversations.external_session`, so the caller's reply lands in a thread staff can read
against the call it followed.
"""

from __future__ import annotations

from datetime import timedelta

from loguru import logger
from sqlalchemy import select, update

from spatalk import jobs
from spatalk.brain.renderer import render_script
from spatalk.conversations import append_message, record_usage
from spatalk.models import Conversation, Job, Textback
from spatalk.text.service import TextConversationService, is_opted_out
from spatalk.voice.session import VoiceSession

# One text-back per caller per day, and a call is "missed" under twenty seconds.
TEXTBACK_WINDOW = timedelta(hours=24)
SHORT_CALL_SECONDS = 20.0


def _digits(number: str | None) -> str:
    return "".join(ch for ch in (number or "") if ch.isdigit())


def _same_number(a: str | None, b: str | None) -> bool:
    """True when two numbers are the same line, however they were written.

    Tenant bundles carry human-written numbers (`905-703-7546`) while a carrier presents
    E.164 (`+19057037546`), so the comparison is on the national ten digits.
    """
    x, y = _digits(a), _digits(b)
    if not x or not y:
        return False
    if len(x) >= 10 and len(y) >= 10:
        return x[-10:] == y[-10:]
    return x == y


async def _is_one_of_ours(ctx, cfg, phone: str) -> bool:
    """True when this caller id is a number the clinic or the platform owns."""
    if _same_number(phone, cfg.public_phone) or _same_number(phone, cfg.sms_from_number):
        return True
    if any(_same_number(phone, n) for n in cfg.voice_numbers):
        return True
    return await ctx.registry.resolve_number(phone) is not None


async def _texted_within_the_window(ctx, tenant_id: str, phone: str) -> bool:
    async with ctx.sf() as s:
        row = await s.scalar(
            select(Textback.id)
            .where(
                Textback.tenant_id == tenant_id,
                Textback.phone == phone,
                Textback.sent_at >= ctx.clock.now() - TEXTBACK_WINDOW,
            )
            .limit(1)
        )
    return row is not None


async def _already_queued(ctx, tenant_id: str, phone: str) -> bool:
    """A text-back queued but not yet sent counts as sent: two calls owe one text."""
    async with ctx.sf() as s:
        row = await s.scalar(
            select(Job.id)
            .where(
                Job.kind == "sms.textback",
                Job.state == "queued",
                Job.payload["tenant_id"].astext == tenant_id,
                Job.payload["to"].astext == phone,
            )
            .limit(1)
        )
    return row is not None


async def schedule_missed_call_textback(
    ctx, session: VoiceSession, had_user_speech: bool, duration_s: float
) -> bool:
    """Queue the one text-back this call may owe. True when a job was enqueued."""
    cfg = session.cfg
    phone = session.ref.caller_phone
    if not phone:
        return False
    if had_user_speech and duration_s >= SHORT_CALL_SECONDS:
        return False
    if not cfg.sms_from_number:
        logger.info("tenant {} has no sms_from_number; no missed-call text-back", cfg.id)
        return False
    if await _is_one_of_ours(ctx, cfg, phone):
        logger.info("caller id {} is one of our own numbers; no missed-call text-back", phone)
        return False
    if await is_opted_out(ctx.sf, cfg.id, phone):
        return False
    if await _texted_within_the_window(ctx, cfg.id, phone) or await _already_queued(
        ctx, cfg.id, phone
    ):
        logger.info("caller {} was already texted back today", phone)
        return False
    await jobs.enqueue(
        ctx.sf,
        "sms.textback",
        {
            "tenant_id": cfg.id,
            "to": phone,
            "conversation_id": str(session.ref.conversation_id),
        },
    )
    return True


@jobs.register_handler("sms.textback")
async def _send_textback(payload: dict, ctx: jobs.JobContext) -> None:
    """Send the missed-call text and start the SMS conversation it may turn into."""
    tenant_id, to = payload["tenant_id"], payload["to"]
    voice_conversation_id = payload.get("conversation_id")
    cfg = await ctx.registry.get(tenant_id)
    if not cfg.sms_from_number:
        return
    # Re-checked here because the job may run minutes after the call ended, and an opt-out
    # in between must win.
    if await is_opted_out(ctx.sf, tenant_id, to):
        logger.info("missed-call text-back to {} dropped: opted out", to)
        return
    if await _texted_within_the_window(ctx, tenant_id, to):
        logger.info("missed-call text-back to {} dropped: already texted today", to)
        return

    now = ctx.clock.now()
    text = render_script("missed_call_text", cfg, now, urgent=False)
    service = TextConversationService(ctx, getattr(ctx, "llm", None))
    conv = await service.find_or_create_conversation(tenant_id, "sms", to, to)
    # Sent before anything is written: a failed send must not leave a transcript saying we
    # texted, and the job retries from a clean state.
    await ctx.sms.send(cfg.sms_from_number, to, text)
    await append_message(ctx.sf, conv.id, "assistant", text)
    await record_usage(ctx.sf, tenant_id, conv.id, "sms", "telnyx", "sms_out", 1)
    async with ctx.sf() as s, s.begin():
        s.add(Textback(tenant_id=tenant_id, phone=to, sent_at=now))
        await s.execute(
            update(Conversation).where(Conversation.id == conv.id).values(last_message_at=now)
        )
        if voice_conversation_id:
            await s.execute(
                update(Conversation)
                .where(
                    Conversation.id == conv.id,
                    Conversation.external_session.is_(None),
                )
                .values(external_session=voice_conversation_id)
            )
