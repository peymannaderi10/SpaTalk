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
    # --- lead context (plan L, Task L1) -----------------------------------------------
    # Three more closed values, so a request reads as a lead instead of a type label. None
    # means the caller was not asked or did not say; nothing here is ever guessed.
    returning_client: bool | None = None
    # A `team[].name` or "any" (no preference). The ledger nulls anything else: validating
    # here would reject the whole draft and lose the request over a hallucinated name.
    practitioner: str | None = None
    # One of the tenant's `concerns`; cosmetic only. Health still goes to the transcript.
    concern: str | None = None


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
        # The drafts as filed, so a test can read the closed lead fields an ItemRecord omits.
        self.drafts: list[ItemDraft] = []

    async def create_item(self, ref: ConversationRef, draft: ItemDraft) -> ItemRecord:
        self.drafts.append(draft)
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
