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
    sf: async_sessionmaker, conversation_id: uuid.UUID, role: str, text: str
) -> None:
    if not text.strip():
        return
    async with sf() as s, s.begin():
        s.add(Message(conversation_id=conversation_id, role=role, text=text))


async def end_conversation(
    sf: async_sessionmaker,
    conversation_id: uuid.UUID,
    band: int | None,
    latency_ms: list[int],
    health_context: bool = False,
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
            )
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
