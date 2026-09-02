from __future__ import annotations

from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk.brain.hours import BusinessCalendar
from spatalk.brain.ports import ItemDraft, ItemRecord
from spatalk.brain.requests import ContactInfo, ConversationRef
from spatalk.clock import Clock
from spatalk.models import Item
from spatalk.tenants.schema import TenantConfig

OnCreated = Callable[[Item, TenantConfig], Awaitable[None]]


class PgLedger:
    """The tracked-item ledger. Items carry no free text and never will."""

    def __init__(self, sf: async_sessionmaker, clock: Clock, on_created: OnCreated | None = None):
        self._sf, self._clock, self._on_created = sf, clock, on_created

    async def create_item(self, ref: ConversationRef, draft: ItemDraft) -> ItemRecord:
        now = self._clock.now()
        due = BusinessCalendar(ref.tenant).due_for(draft.urgency, now)
        async with self._sf() as s, s.begin():
            item = Item(
                tenant_id=ref.tenant.id,
                conversation_id=ref.conversation_id,
                type=draft.type,
                urgency=draft.urgency,
                service_id=draft.service_id,
                contact_name=draft.contact.name,
                contact_phone=draft.contact.phone,
                contact_email=draft.contact.email,
                preferred_window=draft.preferred_window.model_dump(),
                channel=ref.channel,
                health_context=draft.health_context,
                due_at=due,
                owner=ref.tenant.escalation.owner_email,
            )
            s.add(item)
            await s.flush()
            await s.refresh(item)
        if self._on_created:
            await self._on_created(item, ref.tenant)
        return ItemRecord(
            id=item.id,
            type=item.type,
            urgency=item.urgency,
            due_at=item.due_at,
            contact=ContactInfo(
                name=item.contact_name, phone=item.contact_phone, email=item.contact_email
            ),
            service_id=item.service_id,
            health_context=item.health_context,
        )

    async def get(self, item_id: int) -> Item | None:
        async with self._sf() as s:
            return await s.get(Item, item_id)

    async def _transition(self, item_id: int, actor: str, state: str) -> Item | None:
        async with self._sf() as s, s.begin():
            item = await s.get(Item, item_id)
            if item is None:
                return None
            now = self._clock.now()
            if state == "acknowledged" and item.state == "open":
                item.state, item.acknowledged_at, item.acknowledged_by = "acknowledged", now, actor
            elif state == "resolved" and item.state in ("open", "acknowledged"):
                if item.acknowledged_at is None:
                    item.acknowledged_at, item.acknowledged_by = now, actor
                item.state, item.resolved_at, item.resolved_by = "resolved", now, actor
            await s.flush()
            await s.refresh(item)
            return item

    async def acknowledge(self, item_id: int, actor: str) -> Item | None:
        return await self._transition(item_id, actor, "acknowledged")

    async def resolve(self, item_id: int, actor: str) -> Item | None:
        return await self._transition(item_id, actor, "resolved")

    async def list_open(self, tenant_id: str) -> list[Item]:
        async with self._sf() as s:
            q = (
                select(Item)
                .where(Item.tenant_id == tenant_id, Item.state.in_(("open", "acknowledged")))
                .order_by(Item.due_at)
            )
            return list((await s.scalars(q)).all())

    async def breached(self, now: datetime) -> list[Item]:
        async with self._sf() as s:
            q = (
                select(Item)
                .where(Item.state == "open", Item.due_at < now, Item.escalated_at.is_(None))
                .order_by(Item.due_at)
            )
            return list((await s.scalars(q)).all())

    async def mark_escalated(self, item_id: int, now: datetime) -> None:
        async with self._sf() as s, s.begin():
            item = await s.get(Item, item_id)
            if item is not None:
                item.escalated_at = now
