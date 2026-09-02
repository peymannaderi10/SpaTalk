from __future__ import annotations

from datetime import datetime
from typing import Literal, Union

from pydantic import BaseModel

Urgency = Literal["normal", "urgent"]


class Captured(BaseModel, frozen=True):
    kind: Literal["captured"] = "captured"
    item_id: int
    urgency: Urgency
    confirm_by: datetime
    item_type: str


class LinkSent(BaseModel, frozen=True):
    kind: Literal["link_sent"] = "link_sent"
    service_id: str
    url: str


class Refused(BaseModel, frozen=True):
    kind: Literal["refused"] = "refused"
    reason: Literal["out_of_scope", "payment", "no_contact", "unknown_service", "unavailable"]


class Completed(BaseModel, frozen=True):
    """Only a Tier A platform adapter may construct this. Tier C never imports it."""

    kind: Literal["completed"] = "completed"
    platform_ref: str
    verb: Literal["booked", "rescheduled", "cancelled"]
    when: str


Outcome = Union[Captured, LinkSent, Refused, Completed]
