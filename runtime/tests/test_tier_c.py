import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _ref(cfg, channel="voice", caller="+19055550101"):
    from spatalk.brain.requests import ConversationRef
    return ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel=channel, caller_phone=caller)


@pytest.fixture
def world(fixed_clock):
    from spatalk.tenants.bundle import load_bundle
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.tier_c import TierCCapabilities
    cfg = load_bundle(BUNDLE)
    ledger, sms = MemoryLedger(fixed_clock), MemorySms()
    return cfg, ledger, sms, TierCCapabilities(ledger=ledger, sms=sms, clock=fixed_clock)


async def test_capture_creates_item_with_due_time(world):
    cfg, ledger, sms, caps = world
    from spatalk.brain.requests import CaptureRequest, ContactInfo, PreferredWindow
    out = await caps.capture(_ref(cfg), CaptureRequest(kind="callback", service_id="facial",
                              contact=ContactInfo(name="Dana"), preferred_window=PreferredWindow()))
    assert out.kind == "captured" and out.urgency == "normal"
    assert ledger.items[0].contact.phone == "+19055550101"   # caller id fills contact
    assert out.confirm_by > datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


async def test_appointment_change_is_captured_not_completed(world):
    cfg, ledger, sms, caps = world
    from spatalk.brain.requests import AppointmentChangeRequest, ContactInfo, PreferredWindow
    out = await caps.request_appointment_change(_ref(cfg), AppointmentChangeRequest(
        kind="cancel", contact=ContactInfo(name="Dana"), preferred_window=PreferredWindow()))
    assert out.kind == "captured"
    assert ledger.items[0].type == "cancel"


async def test_booking_link_texts_when_sms_number_configured(world):
    cfg, ledger, sms, caps = world
    from spatalk.brain.requests import BookingLinkRequest, ContactInfo
    cfg2 = cfg.model_copy(update={"sms_from_number": "+18885550100"})
    out = await caps.send_booking_link(_ref(cfg2), BookingLinkRequest(service_id="facial", contact=ContactInfo()))
    assert out.kind == "link_sent" and out.url.startswith("https://skincentrix.janeapp.com")
    assert sms.sent[0][1] == "+19055550101" and out.url in sms.sent[0][2]


async def test_booking_link_is_captured_when_no_sms_or_no_phone(world):
    cfg, ledger, sms, caps = world
    from spatalk.brain.requests import BookingLinkRequest, ContactInfo
    # The bundle carries a messaging number since S1, so "no sms" is said here, not assumed.
    cfg = cfg.model_copy(update={"sms_from_number": None})
    out = await caps.send_booking_link(_ref(cfg), BookingLinkRequest(service_id="facial", contact=ContactInfo()))
    assert out.kind == "captured" and ledger.items[0].type == "send_link"
    out2 = await caps.send_booking_link(_ref(cfg, channel="voice", caller=None),
                                        BookingLinkRequest(service_id="facial", contact=ContactInfo()))
    assert out2.kind == "refused" and out2.reason == "no_contact"
    # Task B4: on a screen the link is shown in the conversation, so it needs no contact
    # and nothing is sent anywhere.
    out3 = await caps.send_booking_link(_ref(cfg, channel="chat", caller=None),
                                        BookingLinkRequest(service_id="facial", contact=ContactInfo()))
    assert out3.kind == "link_sent" and sms.sent == []


async def test_escalate_is_urgent(world):
    cfg, ledger, sms, caps = world
    from spatalk.brain.requests import EscalateRequest, ContactInfo
    out = await caps.escalate(_ref(cfg), EscalateRequest(reason="clinical", contact=ContactInfo()))
    assert out.urgency == "urgent" and ledger.items[0].type == "escalation_clinical"


async def test_booking_or_callback_without_a_first_name_is_refused_before_anything_is_written(world):
    cfg, ledger, sms, caps = world
    from spatalk.brain.requests import CaptureRequest, ContactInfo, PreferredWindow
    for contact in (ContactInfo(), ContactInfo(name="  ")):
        for kind in ("new_booking", "callback"):
            out = await caps.capture(_ref(cfg), CaptureRequest(kind=kind, service_id="facial",
                                      contact=contact, preferred_window=PreferredWindow()))
            assert out.kind == "refused" and out.reason == "no_name"
    assert ledger.items == []
    # A question needs no name: the team can answer it either way.
    out = await caps.capture(_ref(cfg), CaptureRequest(kind="question", service_id="facial",
                              contact=ContactInfo(), preferred_window=PreferredWindow()))
    assert out.kind == "captured"


async def test_appointment_change_without_a_first_name_is_refused(world):
    cfg, ledger, sms, caps = world
    from spatalk.brain.requests import AppointmentChangeRequest, ContactInfo, PreferredWindow
    out = await caps.request_appointment_change(_ref(cfg), AppointmentChangeRequest(
        kind="reschedule", contact=ContactInfo(), preferred_window=PreferredWindow()))
    assert out.kind == "refused" and out.reason == "no_name"
    assert ledger.items == []
