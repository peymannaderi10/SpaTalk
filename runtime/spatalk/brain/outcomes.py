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


class Transferred(BaseModel, frozen=True):
    """The carrier accepted a live transfer to the tenant's staffed back-line (E10).

    Only the voice adapter may construct this: it is the one place that has a call leg and
    has heard the carrier say yes. Tier C has no leg to hand over, so its `transfer`
    returns :class:`Captured` instead and the caller is told about a callback, not a
    connection. The number is masked because an outcome ends up in logs and scenario
    output, and a staffed back-line is not a fact those need to carry in full.
    """

    kind: Literal["transferred"] = "transferred"
    number_masked: str


class Completed(BaseModel, frozen=True):
    """Only a Tier A platform adapter may construct this. Tier C never imports it."""

    kind: Literal["completed"] = "completed"
    platform_ref: str
    verb: Literal["booked", "rescheduled", "cancelled"]
    when: str


Outcome = Union[Captured, LinkSent, Refused, Transferred, Completed]
