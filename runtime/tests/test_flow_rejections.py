"""A refusal the model can read (OSS §8.1(e); Parlant's `ToolInsights`).

Silence was the old answer and it cost the founder's call of 2026-09-10 four identical
questions: the model called a tool the step did not offer, nothing happened, nothing was
said, and it had no way to know why. Every rejection here names the tool, what the record is
waiting on, and what may be called instead — in closed values only. A rejection is a message
to the model. It is never spoken, never sent, and never written anywhere.
"""

from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def test_an_un_offered_tool_names_what_is_missing_and_what_is_legal():
    from spatalk.brain.flow import Slots, rejection_text, tool_rejection

    cfg = _cfg()
    r = tool_rejection(Slots(flow="new_booking"), "give_name", {"first_name": "Ellen"}, cfg, "voice", None)
    assert r is not None and r.reason == "not_offered" and r.tool == "give_name"
    assert r.missing.datum == "returning_client" and r.missing.tool == "answer"
    assert r.missing.choices == ("yes", "no")
    assert "answer_question" in r.offered and "give_name" not in r.offered
    text = rejection_text(r)
    assert "give_name" in text and "answer" in text and "yes" in text
    assert "nothing was recorded" in text.lower()


def test_filing_before_the_slots_are_filled_is_premature_not_merely_un_offered():
    """The distinction is worth the enum value: "not available" tells the model to try
    something else, "not yet, the record still needs X" tells it what to do."""
    from spatalk.brain.flow import Slots, rejection_text, tool_rejection

    cfg = _cfg()
    # The name is what a callback with a practitioner and a treatment is still waiting on.
    open_at_name = Slots(
        flow="callback", returning_client=True, practitioner="any", service_id="classic_facial"
    )
    r = tool_rejection(open_at_name, "file_request", {}, cfg, "voice", None)
    assert r.reason == "premature" and r.missing.datum == "name"
    assert "nothing was filed" in rejection_text(r).lower()


def test_a_malformed_value_says_which_way_it_was_wrong():
    from spatalk.brain.flow import Pending, Slots, tool_rejection

    cfg = _cfg()
    empty = tool_rejection(Slots(flow="new_booking", returning_client=True), "change_answer",
                           {"slot": "service"}, cfg, "voice", None)
    assert empty.reason == "bad_value" and empty.detail == "empty_slot"
    kind = tool_rejection(Slots(), "start_request", {"kind": "haircut"}, cfg, "voice", None)
    assert kind.reason == "bad_value" and kind.detail == "unknown_kind"
    which = Slots(flow="new_booking", returning_client=True,
                  pending=Pending(kind="which", slot="practitioner", candidates=("A B", "C D")))
    named = tool_rejection(which, "answer", {"value": "yes"}, cfg, "voice", None)
    assert named.reason == "bad_value" and named.detail == "name_it_instead"


def test_the_answer_first_message_names_the_next_slot_and_claims_nothing():
    """The function response for a slot recorded on a question turn (founder call 14ea2579,
    15:55:00). Like `rejection_text` it is read by a model and never spoken, never sent,
    never stored — and like every other sentence the model is given, it claims nothing."""
    from spatalk.brain.flow import Slots, answer_first_text

    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=False, offers_done=True,
              service_id="mesojet_facial")
    text = answer_first_text(s, cfg, "voice")
    assert "has not been answered" in text
    assert "choose_practitioner" in text
    assert "who they would like to see" in text
    # Whole words, not substrings: the sentence says "in one or two sentences", and the claim
    # being forbidden is "sent", not the letters of it.
    import re

    low = text.lower()
    for claim in ("sent", "filed", "booked", "passed on", "confirmed"):
        assert re.search(rf"\b{claim}\b", low) is None, claim


def test_a_legal_call_earns_no_rejection():
    from spatalk.brain.flow import Slots, tool_rejection

    cfg = _cfg()
    assert tool_rejection(Slots(flow="new_booking"), "answer", {"value": "yes"}, cfg, "voice", None) is None
    assert tool_rejection(Slots(), "start_request", {"kind": "callback"}, cfg, "voice", None) is None
    assert tool_rejection(Slots(flow="new_booking"), "answer_question", {}, cfg, "voice", None) is None


def test_a_rejection_carries_no_caller_words_anywhere():
    """Structural. The model passed a sentence; nothing of it survives into the rejection."""
    from spatalk.brain.flow import Rejection, Slots, rejection_text, tool_rejection

    cfg = _cfg()
    said = "so what was the fifty dollar one you mentioned earlier"
    r = tool_rejection(Slots(flow="new_booking"), "choose_service", {"said": said}, cfg, "voice", None)
    assert r is not None
    blob = r.model_dump_json() + rejection_text(r)
    for word in ("fifty", "dollar", "mentioned", "earlier"):
        assert word not in blob.lower(), word
    assert set(Rejection.model_fields) == {"reason", "tool", "offered", "missing", "detail"}


def test_the_readiness_report_is_the_one_source_for_both_the_brief_and_the_rejection():
    """One function, two consumers: a rejection that named different choices from the brief
    would be a second policy, which is the thing the runtime exists not to have."""
    from spatalk.brain.flow import Slots, readiness, tool_rejection

    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=True, practitioner="any")
    report = readiness(s, cfg, "voice")
    assert report.missing.datum == "service" and "treatment" in report.missing.description
    assert report.missing.tool == "choose_service" and "choose_service" in report.tools
    assert tool_rejection(s, "give_phone", {"digits": "9055550101"}, cfg, "voice", None).missing == report.missing


def test_a_question_shaped_argument_is_refused_with_the_open_step_named():
    """The narrow fix's five sentences, upgraded: the model is still told it passed a
    question rather than an answer, and now also what the record is waiting on and what it
    may call instead."""
    from spatalk.brain.flow import Slots, rejection_text, tool_rejection

    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=False, offers_done=True)   # open: SERVICE
    r = tool_rejection(s, "choose_service", {"said": "what was the facial one again?"},
                       cfg, "voice", None)
    assert r.reason == "bad_value" and r.detail == "question_shaped"
    text = rejection_text(r)
    assert "question" in text.lower() and "which treatment" in text
    assert "answer_question" in text
