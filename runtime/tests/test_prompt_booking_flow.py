"""Booking flow after the founder's calls of 2026-09-03 at 15:56 and 16:09.

Ava suggested a treatment for the caller's concern and, in the same breath, asked for their
first name as if the suggestion were their choice; and she recited the new-client offers to a
new caller without asking whether they wanted to hear them, leaving the fifty-dollar credit
out on the second call. The prompt now asks before it offers, treats a suggestion as a
suggestion, and the knowledge file lists the offers in one place with the credit first.
"""

from datetime import datetime, timezone
from pathlib import Path

NOW = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(Path(__file__).resolve().parents[1] / "tenants" / "skincentrix")


def test_the_knowledge_file_lists_the_new_client_offers_with_the_credit_first():
    cfg = _cfg()
    assert "## New-client offers" in cfg.knowledge
    section = cfg.knowledge.split("## New-client offers", 1)[1].split("\n## ", 1)[0]
    bullets = [line for line in section.splitlines() if line.startswith("- ")]
    assert len(bullets) >= 2
    assert "$50 credit" in bullets[0]
    assert any("free virtual consultation" in b for b in bullets)


def test_the_offer_wording_stays_out_of_the_prompt():
    from spatalk.brain.prompt import build_system_prompt

    instructions = build_system_prompt(_cfg(), "voice", NOW).split("HOURS:")[0].lower()
    for word in ("$50", "credit", "consultation", "underarm", "free "):
        assert word not in instructions, word


# --- after the call from the 437 number, 2026-09-03 20:38 ----------------------------------


def test_the_preferred_day_is_never_when_the_team_will_call():
    """"I'm looking to come on Tuesday" became "have our team call you on Tuesday"."""
    from spatalk.brain.prompt import build_system_prompt

    for channel in ("voice", "sms"):
        p = build_system_prompt(_cfg(), channel, NOW).lower()
        assert "never when the team will call" in p
        assert "never say when the team will call, text or reach out" in p


def test_the_voice_is_calm():
    """Feedback from the caller: a little too high energy."""
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    p = build_system_prompt(cfg, "voice", NOW)
    assert "At most one exclamation mark" in p
    assert "[cheerful] at most once per call" in p
    assert "calm" in cfg.persona.tone and "upbeat" not in cfg.persona.tone
    assert cfg.scripts.disclosure.startswith("[warm]")
    assert "!" not in cfg.scripts.disclosure


def test_every_booking_link_is_the_plain_jane_address():
    """The link texted on that call did not work: every service pointed at a /locations path."""
    cfg = _cfg()
    assert cfg.booking_url_default == "https://skincentrix.janeapp.com/"
    for service in cfg.services:
        assert service.booking_url == "https://skincentrix.janeapp.com/", service.id


def test_the_static_prompt_no_longer_carries_the_booking_order():
    """The order and the questions belong to the slot engine (slot engine design, §6.6)."""
    from spatalk.brain.prompt import build_system_prompt

    for channel in ("voice", "sms", "chat"):
        # The instructions only: the facts section keeps its "New-client offers" heading.
        p = build_system_prompt(_cfg(), channel, NOW).split("HOURS:")[0].lower()
        assert "when they want to book" not in p
        assert "ask for their first name" not in p
        assert "new-client offers" not in p
        assert "the system asks the questions" in p
        assert "never ask for a name or a number yourself" in p


def test_the_faq_is_rendered_ahead_of_the_facts_and_only_when_there_is_one():
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    p = build_system_prompt(cfg, "voice", NOW)
    assert "FREQUENTLY ASKED" in p
    assert p.index("FREQUENTLY ASKED") < p.index("FACTS ABOUT")
    assert "Q: What is the cancellation policy?" in p and "A: Rescheduling and cancellations need 48 hours" in p
    assert "in your own words, and add nothing the clinic did not say" in p
    bare = build_system_prompt(cfg.model_copy(update={"faq": []}), "voice", NOW)
    assert "FREQUENTLY ASKED" not in bare
