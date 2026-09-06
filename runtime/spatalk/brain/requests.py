from __future__ import annotations

from datetime import date as date_type
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from spatalk.tenants.schema import TenantConfig

# The weekday names a caller may name instead of a date, as the model is asked to write
# them. Compared case-insensitively and stored in this capitalisation.
WEEKDAY_NAMES: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class ContactInfo(BaseModel, frozen=True):
    name: str | None = None
    phone: str | None = None
    email: str | None = None


class PreferredWindow(BaseModel, frozen=True):
    date: str = "any"                                   # ISO date, a weekday name, or "any"
    part_of_day: Literal["morning", "afternoon", "evening", "any"] = "any"

    @field_validator("date", mode="before")
    @classmethod
    def _closed_date(cls, v) -> str:
        """A closed vocabulary: an ISO date, a weekday name, or "any" (CLAUDE.md 2).

        This is the last gate before the ledger writes the window into JSONB, so anything
        else — a sentence the model wrote in the caller's words, a mangled date — becomes
        "any" rather than free text on an item. It never raises: the model is told what
        the field takes, and a rejected value must cost the preference, never the request.
        """
        if v is None:
            return "any"
        text = str(v).strip()
        if not text or text.lower() == "any":
            return "any"
        try:
            return date_type.fromisoformat(text).isoformat()
        except ValueError:
            pass
        for day in WEEKDAY_NAMES:
            if text.lower() == day.lower():
                return day
        return "any"


EscalateReason = Literal[
    "emergency", "human_request", "clinical", "complaint", "payment", "legal", "unsure"
]


class BookingLinkRequest(BaseModel, frozen=True):
    """Text the caller the booking link for one service (the slot engine's route step)."""

    service_id: str
    contact: ContactInfo = ContactInfo()


class EscalateRequest(BaseModel, frozen=True):
    reason: EscalateReason
    contact: ContactInfo = ContactInfo()


class TransferRequest(BaseModel, frozen=True):
    """Ask to be put through to a person (operations plan, Task E10).

    There is nothing to say about the request itself: the destination is the tenant's
    `transfer_number` and the caller is the conversation. The contact exists only so a
    tier that cannot transfer has something to file the fallback callback against.
    """

    contact: ContactInfo = ContactInfo()


class ConversationRef(BaseModel, frozen=True):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    conversation_id: UUID
    tenant: TenantConfig
    channel: Literal["voice", "sms", "chat", "instagram", "messenger"]
    caller_phone: str | None = None
    # Set for the rest of the conversation once the caller volunteers health context.
    health_context: bool = False
