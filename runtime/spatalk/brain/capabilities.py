from __future__ import annotations

from typing import Protocol

from spatalk.brain.outcomes import Captured, LinkSent, Outcome, Refused, Transferred
from spatalk.brain.ports import LedgerPort, SmsPort
from spatalk.brain.requests import (
    AppointmentChangeRequest,
    BookingLinkRequest,
    CaptureRequest,
    ConversationRef,
    EscalateRequest,
    TransferRequest,
)
from spatalk.clock import Clock
from spatalk.tenants.schema import TenantConfig


class Capabilities(Protocol):
    """What the assistant may attempt. The tier decides what each one can actually achieve."""

    async def capture(self, ref: ConversationRef, req: CaptureRequest) -> Outcome: ...

    async def request_appointment_change(
        self, ref: ConversationRef, req: AppointmentChangeRequest
    ) -> Outcome: ...

    async def send_booking_link(
        self, ref: ConversationRef, req: BookingLinkRequest
    ) -> LinkSent | Captured | Refused: ...

    async def escalate(self, ref: ConversationRef, req: EscalateRequest) -> Captured: ...

    # --- live transfer (operations plan, Task E10) ---
    # A tier with a call leg and a staffed back-line can hand the caller over and return
    # `Transferred`. A tier without one returns `Captured`: an urgent callback the team
    # actually has to work, never a claim that anybody was connected.
    async def transfer(
        self, ref: ConversationRef, req: TransferRequest
    ) -> Transferred | Captured: ...


def load_capabilities(
    cfg: TenantConfig, ledger: LedgerPort, sms: SmsPort, clock: Clock
) -> Capabilities:
    if cfg.fulfilment == "tier_c":
        from spatalk.brain.tier_c import TierCCapabilities

        return TierCCapabilities(ledger=ledger, sms=sms, clock=clock)
    raise ValueError(f"unknown fulfilment {cfg.fulfilment}")
