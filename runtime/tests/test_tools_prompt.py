from datetime import datetime, timezone
from pathlib import Path
BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
NOW = datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc)   # Tue 19:30 Toronto, closed


def _cfg():
    from spatalk.tenants.bundle import load_bundle
    return load_bundle(BUNDLE)


def test_the_qa_tool_set_is_start_request_and_the_always_tools():
    from spatalk.brain.tools import build_tools
    tools = build_tools(_cfg())
    assert [t.name for t in tools] == ["start_request", "escalate", "end_conversation"]
    for t in tools:
        for pname, spec in t.properties.items():
            if spec.get("type") == "string":
                assert "enum" in spec, f"{t.name}.{pname} is free text"


def test_every_slot_tool_is_closed_or_one_of_the_three_transients():
    """The slot engine's tools carry what the caller said and nothing about the item
    (slot engine design, §3 invariant 2): the transient strings are resolved in code."""
    from spatalk.brain.tools import TOOL_NAMES, slot_tool
    cfg = _cfg()
    # `choose_window.date` is a string the ledger closes itself (an ISO date, a weekday or
    # "any"; `PreferredWindow` turns anything else into "any"), as it always was.
    transient = {("give_name", "first_name"), ("give_phone", "digits"),
                 ("choose_practitioner", "said"), ("choose_service", "said"),
                 ("choose_window", "date")}
    for name in TOOL_NAMES:
        if name in ("escalate", "end_conversation"):
            continue
        t = slot_tool(name, cfg)
        for pname, spec in t.properties.items():
            assert pname not in ("contact", "notes", "service_id"), f"{t.name}.{pname}"
            if spec.get("type") == "string" and "enum" not in spec:
                assert (name, pname) in transient, f"{t.name}.{pname} is free text"


def test_genai_declarations_shape():
    from spatalk.brain.tools import build_tools, to_genai_declarations
    d = to_genai_declarations(build_tools(_cfg()))
    assert d[0]["name"] == "start_request" and d[0]["parameters"]["type"] == "object"


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


def test_the_only_thing_that_changes_between_calls_is_at_the_end_of_the_prompt():
    """The model caches a shared prefix; the clock line must not sit in front of it."""
    from datetime import timedelta

    from spatalk.brain.prompt import build_system_prompt
    cfg = _cfg()
    a = build_system_prompt(cfg, "voice", NOW)
    b = build_system_prompt(cfg, "voice", NOW + timedelta(days=1, hours=3))
    assert a != b
    assert a.split("RIGHT NOW")[0] == b.split("RIGHT NOW")[0]
    assert a.index("RIGHT NOW") > a.index("FACTS ABOUT")
    assert "set up" in a and "not even when offering help" in a


def test_a_greeting_is_not_a_question_and_tools_wait_to_be_asked():
    from spatalk.brain.prompt import build_system_prompt
    p = build_system_prompt(_cfg(), "voice", NOW).lower()
    assert "is a greeting, not a question" in p and "never describe how things are here" in p
    assert "answered in words, never with a tool" in p
    # The booking link is a tool only at the route step, once the caller has been asked
    # (slot engine design, §4.1 step 9): a price question can never reach it.
    from spatalk.brain.flow import Slots, Step, step_tools
    qa = [t.name for t in step_tools(Step.QA, Slots(), _cfg(), "voice")]
    assert "send_link" not in qa and "file_request" not in qa
