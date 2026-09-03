from datetime import datetime, timezone
from pathlib import Path
BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
NOW = datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc)   # Tue 19:30 Toronto, closed


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def test_tools_have_no_free_text_parameters():
    from spatalk.brain.tools import build_tools, TOOL_NAMES
    tools = build_tools(_cfg())
    assert [t.name for t in tools] == list(TOOL_NAMES)
    for t in tools:
        for pname, spec in t.properties.items():
            if spec.get("type") == "string":
                assert "enum" in spec, f"{t.name}.{pname} is free text"
            if spec.get("type") == "object":
                for sub in spec["properties"]:
                    assert sub in ("name", "phone", "email", "date", "part_of_day"), f"{t.name}.{pname}.{sub}"


def test_service_ids_are_enumerated():
    from spatalk.brain.tools import build_tools
    t = next(t for t in build_tools(_cfg()) if t.name == "send_booking_link")
    assert "laser_hair_removal" in t.properties["service_id"]["enum"]


def test_genai_declarations_shape():
    from spatalk.brain.tools import build_tools, to_genai_declarations
    d = to_genai_declarations(build_tools(_cfg()))
    assert d[0]["name"] == "send_booking_link" and d[0]["parameters"]["type"] == "object"


def test_prompt_states_closed_now_and_honesty_rules():
    from spatalk.brain.prompt import build_system_prompt
    p = build_system_prompt(_cfg(), "voice", NOW)
    assert "closed" in p.lower() and "7:30 p.m." in p
    assert "never say" in p.lower() and "booked" in p.lower()
    assert "$99" in p and "Britannia" in p
    assert f"at most {_cfg().persona.max_sentences_per_turn} sentences" in p.lower()
    assert "do not ask about it" in p.lower() and "suitable or safe" in p.lower()


def test_prompt_files_questions_about_the_callers_own_appointment():
    """Account-specific questions are never answered from memory and never refused flatly.

    Real-model finding QA-A1 (docs/reports/promptfoo-run-2026-09-02-A.md): the model replied
    "I can't confirm appointments" at band 1 with no item. Brief 7.1 puts an account-specific
    question in band 2: file it and let the system speak the captured wording.
    """
    from spatalk.brain.prompt import build_system_prompt
    p = build_system_prompt(_cfg(), "voice", NOW).lower()
    assert "existing appointment" in p
    assert "no access to the appointment calendar" in p
    assert "never answer from memory" in p
    assert "never say you cannot help" in p
    assert "capture_request (kind question)" in p


def test_prompt_makes_booking_a_short_exchange_that_collects_a_name():
    from spatalk.brain.prompt import build_system_prompt
    p = build_system_prompt(_cfg(), "voice", NOW).lower()
    assert "when they want to book" in p
    assert "stop describing" in p and "first name" in p
    assert "never file a booking, callback or reschedule request without a first name" in p
