"""The runtime owns the request conversation (slot engine design, 2026-09-05).

`Slots` is what the runtime knows about the open request. `next_step` is the fixed order.
`step_question` is the script the caller hears next. Nothing here talks to a model, a
database or a phone: the drivers do, with what these functions return.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from spatalk.brain.requests import PreferredWindow
from spatalk.brain.resolve import first_name_of, spoken_digits, typed_digits
from spatalk.tenants.schema import TenantConfig

Flow = Literal["new_booking", "callback", "reschedule", "cancel", "question", "clinical"]
NAME_REQUIRED_FLOWS = ("new_booking", "callback", "reschedule", "cancel", "question", "clinical")
BOOKING_LIKE = ("new_booking", "callback")


class Step(str, Enum):
    QA = "qa"
    RETURNING = "returning"
    OFFERS = "offers"
    PRACTITIONER = "practitioner"
    SERVICE = "service"
    NAME = "name"
    PHONE = "phone"
    WINDOW = "window"
    TEAM_NOTE = "team_note"
    ROUTE = "route"
    COMPLETE = "complete"


class Pending(BaseModel, frozen=True):
    """A confirmation the caller owes an answer to before the slot can be filled."""

    kind: Literal["match", "which", "name_staff", "phone", "not_service", "offers", "route"]
    slot: str
    value: str | None = None
    candidates: tuple[str, ...] = ()


class Slots(BaseModel, frozen=True):
    """What the runtime knows about the open request. Every value is a closed one."""

    flow: Flow | None = None
    returning_client: bool | None = None
    offers_done: bool = False
    practitioner: str | None = None
    service_id: str | None = None
    first_name: str | None = None
    phone: str | None = None
    phone_confirmed: bool = False
    preferred_window: PreferredWindow | None = None
    team_note_asked: bool = False
    pending: Pending | None = None
    misses: dict[str, int] = Field(default_factory=dict)
    ended_flow: bool = False

    def with_(self, **changes) -> Slots:
        return self.model_copy(update=changes)

    def miss(self, slot: str) -> Slots:
        misses = dict(self.misses)
        misses[slot] = misses.get(slot, 0) + 1
        return self.with_(misses=misses)


def _phone_needed(slots: Slots, channel: str) -> bool:
    if channel == "sms":
        return False
    return not (slots.phone and slots.phone_confirmed)


def next_step(slots: Slots, cfg: TenantConfig, channel: str) -> Step:
    """The fixed order (slot engine design, §4). A step already answered is skipped."""
    if slots.flow is None or slots.ended_flow:
        return Step.QA
    if slots.flow in BOOKING_LIKE:
        if slots.returning_client is None:
            return Step.RETURNING
        if slots.returning_client is False and not slots.offers_done:
            return Step.OFFERS
        if slots.returning_client:
            if slots.practitioner is None:
                return Step.PRACTITIONER
            if slots.service_id is None:
                return Step.SERVICE
        else:
            if slots.service_id is None:
                return Step.SERVICE
            if slots.practitioner is None:
                return Step.PRACTITIONER
    if not slots.first_name:
        return Step.NAME
    if _phone_needed(slots, channel):
        return Step.PHONE
    if slots.flow in ("new_booking", "callback", "reschedule") and slots.preferred_window is None:
        return Step.WINDOW
    if slots.flow in BOOKING_LIKE and not slots.team_note_asked:
        return Step.TEAM_NOTE
    if slots.flow == "new_booking" and cfg.sms_from_number and channel == "voice":
        return Step.ROUTE
    return Step.COMPLETE


def _consultation_name(cfg: TenantConfig) -> str:
    consult = next((s for s in cfg.services if s.category == "consultation"), None)
    return f"a {consult.name.lower()}" if consult else "the team can help you pick when they call"


def _service_name(cfg: TenantConfig, service_id: str) -> str:
    s = cfg.service(service_id)
    return s.name if s else service_id


def _initialled(a: str, b: str) -> tuple[str, str]:
    """'Helen' and 'Amanda' when the first names differ; 'Amanda C.' and 'Amanda K.' when not."""
    fa, fb = first_name_of(a), first_name_of(b)
    if fa.lower() != fb.lower():
        return fa, fb
    return f"{fa} {a.split()[-1][0]}.", f"{fb} {b.split()[-1][0]}."


def step_question(
    step: Step, slots: Slots, cfg: TenantConfig, channel: str
) -> tuple[str, dict] | None:
    """The `scripts` key the caller hears next, with its fills; None at QA and COMPLETE."""
    p = slots.pending
    if p is not None:
        if p.kind == "match":
            label = first_name_of(p.value or "") if p.slot == "practitioner" else _service_name(cfg, p.value or "")
            return "confirm_match", {"value": label}
        if p.kind == "which":
            a, b = p.candidates[:2]
            if p.slot == "practitioner":
                a, b = _initialled(a, b)
            else:
                a, b = _service_name(cfg, a), _service_name(cfg, b)
            return "confirm_which", {"first": a, "second": b}
        if p.kind == "name_staff":
            return "confirm_name_staff", {"name": p.value}
        if p.kind == "phone":
            digits = spoken_digits(p.value or "") if channel == "voice" else typed_digits(p.value or "")
            return "confirm_phone", {"digits": digits}
        if p.kind == "not_service":
            return "practitioner_not_service", {
                "practitioner": first_name_of(p.value or ""),
                "service": _service_name(cfg, slots.service_id or ""),
            }
        if p.kind == "offers":
            return "ask_service_kind", {"consultation": _consultation_name(cfg)}
        if p.kind == "route":
            return "ask_route", {}
    if step == Step.RETURNING:
        return "ask_returning", {}
    if step == Step.OFFERS:
        return "ask_offers", {}
    if step == Step.PRACTITIONER:
        key = "ask_practitioner_again" if slots.misses.get("practitioner") else "ask_practitioner"
        return key, {}
    if step == Step.SERVICE:
        return ("ask_service_again" if slots.misses.get("service") else "ask_service"), {}
    if step == Step.NAME:
        return ("ask_name_again" if slots.misses.get("name") else "ask_name"), {}
    if step == Step.PHONE:
        same = channel == "voice" and not slots.misses.get("phone")
        return ("ask_phone_same" if same else "ask_phone"), {}
    if step == Step.WINDOW:
        return "ask_window", {}
    if step == Step.TEAM_NOTE:
        return "ask_team_note", {}
    if step == Step.ROUTE:
        return "ask_route", {}
    return None
