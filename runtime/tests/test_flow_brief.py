"""The brief becomes a readiness report (OSS §8.2; LIT R1).

It used to end "Do not ask a question yourself; one short acknowledgement at most", which is
the prompt half of the answering machine the founder heard. It becomes Parlant's two
sections — what is known, and what is missing with its legal choices — and it *invites* the
question instead of forbidding it. What the runtime keeps is which slot is open and what may
be stored; what it gives up is choosing the words.
"""

from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg_link():
    """A tenant that offers the booking link after a filed booking (off by default since 2026-09-12)."""
    return _cfg().model_copy(update={"offer_booking_link": True})


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def test_the_brief_names_what_is_known_and_what_is_missing_and_asks_for_the_question():
    from spatalk.brain.flow import STEP_MARKER, Slots, Step, step_message

    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=True, practitioner="Helen Courbetis")
    brief = step_message(Step.SERVICE, s, cfg, "voice")
    assert brief.startswith(STEP_MARKER)
    assert "Known:" in brief and "returning client" in brief and "Helen" in brief
    assert "which treatment they want" in brief
    assert "in your own words" in brief and "choose_service" in brief
    assert "do not ask a question" not in brief.lower()
    assert "one short acknowledgement at most" not in brief


def test_the_brief_never_licenses_a_claim():
    from spatalk.brain.flow import Slots, Step, step_message

    cfg = _cfg()
    for step in Step:
        brief = step_message(step, Slots(flow="new_booking"), cfg, "voice")
        assert "answer_question" in brief or step in (Step.QA, Step.COMPLETE), step
        assert "the system speaks every outcome" in brief or step in (Step.QA, Step.COMPLETE), step


def test_the_name_and_number_steps_forbid_autocorrecting():
    """Vapi's anti-autocorrect rule, verbatim in effect: a recogniser's "payment" for Peyman
    is a transcription problem, and a model that tidies it up hides it (V1 open item 2)."""
    from spatalk.brain.flow import Slots, Step, step_message

    cfg = _cfg()
    name = step_message(Step.NAME, Slots(flow="callback", returning_client=True), cfg, "voice")
    assert "never modify" in name and "never autocorrect" in name and "never guess" in name
    phone = step_message(
        Step.PHONE, Slots(flow="callback", returning_client=True, first_name="Dana"), cfg, "voice"
    )
    assert "never modify, autocorrect or guess" in phone


def test_the_brief_asks_for_the_answer_and_the_next_question_in_one_reply():
    """The orchestrator's amendment of 2026-09-11: one model call per caller turn. The model
    records the answer and asks what comes next in the same response, so the runtime never
    has to buy a second round trip to get a question worded."""
    from spatalk.brain.flow import Slots, Step, step_message

    cfg = _cfg()
    brief = step_message(Step.SERVICE, Slots(flow="new_booking", returning_client=True,
                                             practitioner="any"), cfg, "voice")
    assert "ask the next question in the same reply" in brief


def test_a_pending_confirmation_is_the_runtimes_words_and_a_plain_step_question_is_not():
    """Phase A's split. A confirmation of a value the resolver is unsure of is wording the
    runtime still owns (candidates-not-verdicts is phase B); a plain step question is not."""
    from spatalk.brain.flow import Pending, Slots, open_question

    cfg = _cfg()
    plain = open_question(Slots(flow="new_booking", returning_client=True), cfg, "voice")
    assert plain.key == "ask_practitioner" and plain.fixed is False
    pending = Slots(
        flow="new_booking", returning_client=True,
        pending=Pending(kind="match", slot="practitioner", value="Helen Courbetis"),
    )
    confirm = open_question(pending, cfg, "voice")
    assert confirm.key == "confirm_match" and confirm.fixed is True
    assert confirm.fills == {"value": "Helen"}
    # And the brief tells the model the runtime has this one.
    from spatalk.brain.flow import Step, step_message

    brief = step_message(Step.PRACTITIONER, pending, cfg, "voice")
    assert "read something back" in brief and "say nothing else" in brief


def test_the_link_offer_brief_says_the_request_is_already_filed():
    """Founder call 14ea2579, 2026-09-11 15:56. The old route brief let the model put the
    link first ("I can text you the booking link now, or…"), which is the branch that wrote
    nothing to the ledger at all. The step's brief now says the filing already happened."""
    from spatalk.brain.flow import Slots, Step, step_message

    cfg = _cfg()
    filed = Slots(
        flow="new_booking", returning_client=False, offers_done=True, practitioner="any",
        service_id="mesojet_facial", first_name="Payman", phone="+19055550101",
        phone_confirmed=True, team_note_asked=True, filed=True,
    )
    brief = step_message(Step.LINK_OFFER, filed, cfg, "voice")
    assert "already said so" in brief
    assert "never lead with the link" in brief
    assert "answer with yes or no" in brief
    assert "never say a request has been sent, filed, passed on or booked" in brief
    assert "file_request" not in brief


def test_no_flow_no_open_question():
    from spatalk.brain.flow import Slots, open_question

    cfg = _cfg()
    assert open_question(Slots(), cfg, "voice") is None
    assert open_question(Slots(flow="question", ended_flow=True), cfg, "voice") is None


def test_the_brief_says_a_change_needs_the_callers_words():
    """Defect 7. The brief used to read "If instead they change an earlier answer, call
    change_answer with that slot", which invites the bare call that cleared a filled window on
    "Oh, actually, you know." (founder call 14ea2579, 15:56:05). The runtime now refuses a
    change the caller's words do not ask for, so the model is told the precondition it is
    being judged on."""
    from spatalk.brain.flow import Slots, Step, step_message

    brief = step_message(Step.SERVICE, Slots(flow="new_booking", returning_client=True,
                                             practitioner="any"), _cfg(), "voice")
    assert "change_answer" in brief
    assert "their own words" in brief
    assert "name that answer or give the new one" in brief


def test_the_offers_brief_does_not_order_a_price_recital():
    """Defect 8, the turn-level half. The static prompt now says a treatment question opens a
    conversation and that a price answers a question about price — and then the offers brief,
    which rides at the END of the same system message and is turn-specific, ordered "name two
    or three from the facts with prices in one breath". The caller who says "a facial" lands on
    this brief one turn later: `match_service("a facial")` is a category, so the runtime asks
    whether they want options, and the brief for their "yes" is the recital the founder
    complained about."""
    from spatalk.brain.flow import Pending, Slots, next_step, step_message

    cfg = _cfg()
    s = Slots(
        flow="new_booking", returning_client=False, offers_done=True,
        pending=Pending(kind="offers", slot="service_kind", value="facial"),
    )
    brief = step_message(next_step(s, cfg, "voice"), s, cfg, "voice")
    assert "with prices" not in brief and "prices in one breath" not in brief
    assert "what it does" in brief
    assert "choose_service" in brief


def test_the_service_brief_honours_an_offer_to_say_more_before_a_choice():
    """Founder call dc229ede (2026-09-11 22:50): "hear more about any of those?" — "the MesoJet
    one" — and the practitioner question came straight back."""
    from spatalk.brain.flow import Slots, Step, step_message

    cfg = _cfg()
    brief = step_message(Step.SERVICE, Slots(flow="new_booking", returning_client=False, offers_done=True), cfg, "voice")
    assert "offered to say more" in brief and "describe it" in brief
    assert "call choose_service only once they say they want it" in brief
