from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from spatalk.tenants.schema import TenantConfig


class ContactInfo(BaseModel, frozen=True):
    name: str | None = None
    phone: str | None = None
    email: str | None = None


class PreferredWindow(BaseModel, frozen=True):
    date: str = "any"                                   # ISO date or "any"
    part_of_day: Literal["morning", "afternoon", "evening", "any"] = "any"


CaptureKind = Literal["new_booking", "callback", "question", "training_enquiry"]
ChangeKind = Literal["reschedule", "cancel"]
EscalateReason = Literal["human_request", "clinical", "complaint", "payment", "legal", "unsure"]


class CaptureRequest(BaseModel, frozen=True):
    kind: CaptureKind
    service_id: str | None = None
    contact: ContactInfo = ContactInfo()
    preferred_window: PreferredWindow = PreferredWindow()


class AppointmentChangeRequest(BaseModel, frozen=True):
    kind: ChangeKind
    contact: ContactInfo = ContactInfo()
    preferred_window: PreferredWindow = PreferredWindow()


class BookingLinkRequest(BaseModel, frozen=True):
    service_id: str
    contact: ContactInfo = ContactInfo()


class EscalateRequest(BaseModel, frozen=True):
    reason: EscalateReason
    contact: ContactInfo = ContactInfo()


class ConversationRef(BaseModel, frozen=True):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    conversation_id: UUID
    tenant: TenantConfig
    channel: Literal["voice", "sms", "chat", "instagram", "messenger"]
    caller_phone: str | None = None
    # Set for the rest of the conversation once the caller volunteers health context.
    health_context: bool = False
