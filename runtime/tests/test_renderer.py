from datetime import datetime, timezone, timedelta
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
NOW = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)   # Tue 14:00 Toronto


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def test_render_captured_uses_template_and_due_wording():
    from spatalk.brain.outcomes import Captured
    from spatalk.brain.renderer import render
    out = Captured(item_id=7, urgency="normal", confirm_by=NOW + timedelta(hours=3), item_type="callback")
    assert render(out, _cfg(), NOW) == "I've sent that to the team as a request. Someone will confirm with you by 5:00 p.m. today."


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
    assert "within 15 minutes" in text and "911" in text


def test_refusals_never_claim_anything_was_filed():
    """If the ledger is down, nothing was sent. The wording must say so and give the clinic's number."""
    from spatalk.brain.outcomes import Refused
    from spatalk.brain.renderer import render
    for reason in ("out_of_scope", "unavailable"):
        text = render(Refused(reason=reason), _cfg(), NOW).lower()
        assert "905-703-7546" in text
        assert "sent" not in text and "passed" not in text and "confirm with you" not in text
