"""Tier C fulfilment: capture only. This module must never construct a completion outcome."""
from __future__ import annotations

from spatalk.brain.outcomes import Captured, LinkSent, Refused
from spatalk.brain.ports import ItemDraft, LedgerPort, SmsPort
from spatalk.brain.requests import (
    AppointmentChangeRequest,
    BookingLinkRequest,
    CaptureRequest,
    ContactInfo,
    ConversationRef,
    EscalateRequest,
)
from spatalk.clock import Clock

# Channels where the customer can read and tap a link in the conversation, so the booking
# link is shown inline instead of being texted to a phone number (renderer: scripts.link_shown).
INLINE_LINK_CHANNELS = ("chat", "instagram", "messenger")


def _with_caller(ref: ConversationRef, contact: ContactInfo) -> ContactInfo:
    if contact.phone is None and ref.caller_phone:
        return contact.model_copy(update={"phone": ref.caller_phone})
    return contact


class TierCCapabilities:
    """No booking platform behind this tenant, so every request becomes a tracked item."""

    def __init__(self, ledger: LedgerPort, sms: SmsPort, clock: Clock):
        self._ledger, self._sms, self._clock = ledger, sms, clock

    async def _capture(self, ref: ConversationRef, draft: ItemDraft) -> Captured:
        if ref.health_context and not draft.health_context:
            draft = draft.model_copy(update={"health_context": True})
        rec = await self._ledger.create_item(ref, draft)
        return Captured(
            item_id=rec.id, urgency=rec.urgency, confirm_by=rec.due_at, item_type=rec.type
        )

    async def capture(self, ref: ConversationRef, req: CaptureRequest) -> Captured:
        return await self._capture(
            ref,
            ItemDraft(
                type=req.kind,
                urgency="normal",
                service_id=req.service_id,
                contact=_with_caller(ref, req.contact),
                preferred_window=req.preferred_window,
            ),
        )

    async def request_appointment_change(
        self, ref: ConversationRef, req: AppointmentChangeRequest
    ) -> Captured:
        return await self._capture(
            ref,
            ItemDraft(
                type=req.kind,
                urgency="normal",
                contact=_with_caller(ref, req.contact),
                preferred_window=req.preferred_window,
            ),
        )

    async def send_booking_link(
        self, ref: ConversationRef, req: BookingLinkRequest
    ) -> LinkSent | Captured | Refused:
        service = ref.tenant.service(req.service_id)
        if service is None:
            return Refused(reason="unknown_service")
        # Text channels (Task B4): the customer is reading a screen, so the link is shown in
        # the conversation itself. Nothing is sent anywhere, and no contact is needed.
        if ref.channel in INLINE_LINK_CHANNELS:
            return LinkSent(service_id=service.id, url=service.booking_url)
        contact = _with_caller(ref, req.contact)
        if ref.tenant.sms_from_number and contact.phone:
            text = (
                f"{ref.tenant.name}: here is the booking link for "
                f"{service.name}: {service.booking_url}"
            )
            await self._sms.send(ref.tenant.sms_from_number, contact.phone, text)
            return LinkSent(service_id=service.id, url=service.booking_url)
        if contact.phone or contact.email:
            return await self._capture(
                ref,
                ItemDraft(
                    type="send_link",
                    urgency="normal",
                    service_id=service.id,
                    contact=contact,
                ),
            )
        return Refused(reason="no_contact")

    async def escalate(self, ref: ConversationRef, req: EscalateRequest) -> Captured:
        return await self._capture(
            ref,
            ItemDraft(
                type=f"escalation_{req.reason}",
                urgency="urgent",
                contact=_with_caller(ref, req.contact),
            ),
        )
