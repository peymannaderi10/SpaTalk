from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from spatalk.brain.hours import BusinessCalendar
from spatalk.brain.requests import ContactInfo, ConversationRef, PreferredWindow
from spatalk.clock import Clock

Urgency = str  # "normal" | "urgent"


class ItemDraft(BaseModel, frozen=True):
    """Everything a tracked item may carry. There is no free-text field and there never will be."""

    # callback, new_booking, question, training_enquiry, reschedule, cancel, send_link,
    # escalation_<reason>
    type: str
    urgency: str
    service_id: str | None = None
    contact: ContactInfo = ContactInfo()
    preferred_window: PreferredWindow = PreferredWindow()
    # Caller volunteered a condition or medication; staff read the transcript. No free text.
    health_context: bool = False


class ItemRecord(BaseModel, frozen=True):
    id: int
    type: str
    urgency: str
    due_at: datetime
    contact: ContactInfo
    service_id: str | None = None
    health_context: bool = False


class LedgerPort(Protocol):
    async def create_item(self, ref: ConversationRef, draft: ItemDraft) -> ItemRecord: ...


class SmsPort(Protocol):
    async def send(self, from_number: str, to: str, text: str) -> None: ...


class MemoryLedger:
    """In-memory LedgerPort for tests; due times use the same business calendar as Postgres."""

    def __init__(self, clock: Clock):
        self._clock = clock
        self.items: list[ItemRecord] = []

    async def create_item(self, ref: ConversationRef, draft: ItemDraft) -> ItemRecord:
        due = BusinessCalendar(ref.tenant).due_for(draft.urgency, self._clock.now())
        rec = ItemRecord(
            id=len(self.items) + 1,
            type=draft.type,
            urgency=draft.urgency,
            due_at=due,
            contact=draft.contact,
            service_id=draft.service_id,
            health_context=draft.health_context,
        )
        self.items.append(rec)
        return rec


class MemorySms:
    """In-memory SmsPort for tests; records (from_number, to, text) tuples."""

    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, from_number: str, to: str, text: str) -> None:
        self.sent.append((from_number, to, text))
