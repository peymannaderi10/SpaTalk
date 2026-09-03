from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk.models import Conversation, Message, UsageEvent


async def start_conversation(
    sf: async_sessionmaker,
    tenant_id: str,
    channel: str,
    external_ref: str | None,
    caller: str | None,
) -> uuid.UUID:
    async with sf() as s, s.begin():
        c = Conversation(
            tenant_id=tenant_id, channel=channel, external_ref=external_ref, caller=caller
        )
        s.add(c)
        await s.flush()
        return c.id


async def append_message(
    sf: async_sessionmaker,
    conversation_id: uuid.UUID,
    role: str,
    text: str,
    at: datetime | None = None,
) -> None:
    """Store one message. `at` stamps it with the application clock (the text service does
    this so the SMS flood guard can count messages in business time); the database default
    applies otherwise."""
    if not text.strip():
        return
    extra = {"created_at": at} if at is not None else {}
    async with sf() as s, s.begin():
        s.add(Message(conversation_id=conversation_id, role=role, text=text, **extra))


async def end_conversation(
    sf: async_sessionmaker,
    conversation_id: uuid.UUID,
    band: int | None,
    latency_ms: list[int],
    health_context: bool = False,
    # Operations plan, Task E5: the call's per-stage p95, {stt, llm, tts}. Optional, because
    # only a voice call has stages; a text conversation ends with nothing to say here.
    stage_ms: dict | None = None,
    # Call-notes plan, Task N1: the tenant's `call_notes` switch, passed by the caller
    # because this function has the session factory and not the config. True queues one
    # drafting job for this conversation; the handler is the thing that is idempotent.
    call_notes: bool = False,
) -> None:
    async with sf() as s, s.begin():
        await s.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                ended_at=datetime.now(timezone.utc),
                band=band,
                latency_ms=latency_ms,
                health_context=health_context,
                stage_ms=stage_ms,
            )
        )
    if call_notes:
        await queue_call_notes(sf, conversation_id)


async def queue_call_notes(sf: async_sessionmaker, conversation_id: uuid.UUID) -> int:
    """Queue the one drafting job for this conversation (call-notes plan, Task N1).

    Queued by :func:`end_conversation` for a voice call and by the text channels' close. The
    import is local because `spatalk.jobs` is imported by everything that registers a
    handler, and this module is one of the things those handlers read.
    """
    from spatalk import jobs

    return await jobs.enqueue(sf, "call_notes", {"conversation_id": str(conversation_id)})


async def set_notes(
    sf: async_sessionmaker,
    conversation_id: uuid.UUID,
    notes: str | None,
    model: str,
    at: datetime,
) -> None:
    """Store the drafted notes on the conversation, or record that there were none.

    `notes_at` is stamped either way: it is the mark that the drafting happened, which is
    what stops a second job redrafting. An empty draft leaves `notes` null; there is never a
    placeholder sentence, because staff would read one as something the caller said.
    """
    async with sf() as s, s.begin():
        await s.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(notes=notes, notes_model=model, notes_at=at)
        )


async def get_notes(sf: async_sessionmaker, conversation_id: uuid.UUID | None) -> str | None:
    """The notes drafted for one conversation, if it has any."""
    if conversation_id is None:
        return None
    async with sf() as s:
        return await s.scalar(
            select(Conversation.notes).where(Conversation.id == conversation_id)
        )


async def record_usage(
    sf: async_sessionmaker,
    tenant_id: str,
    conversation_id: uuid.UUID | None,
    channel: str,
    provider: str,
    unit: str,
    qty: float,
) -> None:
    async with sf() as s, s.begin():
        s.add(
            UsageEvent(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                channel=channel,
                provider=provider,
                unit=unit,
                qty=qty,
            )
        )


async def get_transcript(sf: async_sessionmaker, conversation_id: uuid.UUID) -> list[Message]:
    async with sf() as s:
        return list(
            (
                await s.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.id)
                )
            ).all()
        )
