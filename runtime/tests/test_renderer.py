from datetime import datetime, timezone, timedelta
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
NOW = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)   # Tue 14:00 Toronto


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def test_render_captured_uses_template_and_says_when_to_expect_contact():
    """Founder decision 2026-09-03: no clock time is spoken to the caller (\"by 7:29 p.m.\" sounded
    like a deadline the clinic might miss); the caller hears \"as soon as they're free\". The
    promised time is still on the item and in the team's own alert."""
    from spatalk.brain.outcomes import Captured
    from spatalk.brain.renderer import render
    out = Captured(item_id=7, urgency="normal", confirm_by=NOW + timedelta(hours=3), item_type="callback")
    assert render(out, _cfg(), NOW) == "I've sent that to the team as a request. Someone will confirm with you as soon as they're free. Is there anything else I can help with?"
    assert "p.m." not in render(out, _cfg(), NOW) and "a.m." not in render(out, _cfg(), NOW)


def test_render_link_sent_names_service():
    from spatalk.brain.outcomes import LinkSent
    from spatalk.brain.renderer import render
    assert "Facial" in render(LinkSent(service_id="facial", url="https://x"), _cfg(), NOW)
    shown = render(LinkSent(service_id="facial", url="https://x"), _cfg(), NOW, channel="chat")
    assert "https://x" in shown and "texted" not in shown


def test_render_refused_never_claims_action():
    from spatalk.brain.outcomes import Refused
    from spatalk.brain.renderer import render
    text = render(Refused(reason="no_contact"), _cfg(), NOW).lower()
    assert "booked" not in text and "confirmed" not in text


def test_render_completed_only_from_completed_outcome():
    from spatalk.brain.outcomes import Completed
    from spatalk.brain.renderer import render
    text = render(Completed(platform_ref="J-1", verb="booked", when="Thursday at 2 p.m."), _cfg(), NOW)
    assert "booked" in text and "J-1" in text


def test_render_script_clinical_urgent():
    from spatalk.brain.renderer import render_script
    text = render_script("clinical", _cfg(), NOW, urgent=True)
    assert "as soon as possible" in text and "911" in text


def test_refusals_never_claim_anything_was_filed():
    """If the ledger is down, nothing was sent. The wording must say so and give the clinic's number."""
    from spatalk.brain.outcomes import Refused
    from spatalk.brain.renderer import render
    for reason in ("out_of_scope", "unavailable"):
        text = render(Refused(reason=reason), _cfg(), NOW).lower()
        assert "905-703-7546" in text
        assert "sent" not in text and "passed" not in text and "confirm with you" not in text


def test_clinical_escalation_on_a_text_channel_drops_the_phone_wording():
    from spatalk.brain.outcomes import Captured
    from spatalk.brain.renderer import render
    out = Captured(item_id=9, urgency="urgent", confirm_by=NOW + timedelta(minutes=15), item_type="escalation_clinical")
    voice = render(out, _cfg(), NOW)
    text = render(out, _cfg(), NOW, channel="sms")
    assert "hang up" in voice and "911" in voice
    assert "hang up" not in text and "at this number" not in text
    assert "911" in text and "urgent request" in text
