from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def _walk(slots, cfg, channel, answers):
    """Apply a dict of slot values one step at a time and return the steps visited."""
    from spatalk.brain.flow import Step, next_step

    seen = []
    for _ in range(20):
        step = next_step(slots, cfg, channel)
        seen.append(step)
        # COMPLETE is where the record files itself; QA after a route answer is the reset.
        if step in (Step.COMPLETE, Step.QA):
            break
        slots = answers[step](slots)
    return seen


def test_new_client_booking_order_on_a_call():
    from spatalk.brain.flow import Slots, Step
    from spatalk.brain.requests import PreferredWindow

    cfg = _cfg()
    answers = {
        Step.RETURNING: lambda s: s.with_(returning_client=False),
        Step.OFFERS: lambda s: s.with_(offers_done=True),
        Step.SERVICE: lambda s: s.with_(service_id="hydrabrasion_facial"),
        Step.PRACTITIONER: lambda s: s.with_(practitioner="any"),
        Step.NAME: lambda s: s.with_(first_name="Dana"),
        Step.PHONE: lambda s: s.with_(phone="+19055550101", phone_confirmed=True),
        Step.WINDOW: lambda s: s.with_(preferred_window=PreferredWindow()),
        Step.TEAM_NOTE: lambda s: s.with_(team_note_asked=True),
        Step.ROUTE: lambda s: s.with_(ended_flow=True),
    }
    seen = _walk(Slots(flow="new_booking"), cfg, "voice", answers)
    assert seen == [
        Step.RETURNING, Step.OFFERS, Step.SERVICE, Step.PRACTITIONER, Step.NAME,
        Step.PHONE, Step.WINDOW, Step.TEAM_NOTE, Step.ROUTE, Step.QA,
    ]


def test_returning_client_asks_practitioner_first_and_no_offers():
    from spatalk.brain.flow import Slots, Step, next_step

    cfg = _cfg()
    s = Slots(flow="new_booking", returning_client=True)
    assert next_step(s, cfg, "voice") == Step.PRACTITIONER
    s = s.with_(practitioner="Helen Courbetis")
    assert next_step(s, cfg, "voice") == Step.SERVICE


def test_sms_skips_the_phone_step_and_chat_asks_it():
    from spatalk.brain.flow import Slots, Step, next_step

    cfg = _cfg()
    s = Slots(
        flow="callback", returning_client=True, practitioner="any",
        service_id="hydrabrasion_facial", first_name="Dana",
    )
    assert next_step(s, cfg, "sms") == Step.WINDOW
    assert next_step(s, cfg, "chat") == Step.PHONE
    assert next_step(s, cfg, "voice") == Step.PHONE


def test_callback_files_without_the_route_step_and_question_needs_only_name_and_phone():
    from spatalk.brain.flow import Slots, Step, next_step
    from spatalk.brain.requests import PreferredWindow

    cfg = _cfg()
    s = Slots(
        flow="callback", returning_client=False, offers_done=True, practitioner="any",
        service_id="hydrabrasion_facial", first_name="Dana", phone="+1", phone_confirmed=True,
        preferred_window=PreferredWindow(), team_note_asked=True,
    )
    assert next_step(s, cfg, "voice") == Step.COMPLETE
    q = Slots(flow="question", first_name="Dana", phone="+1", phone_confirmed=True)
    assert next_step(q, cfg, "voice") == Step.COMPLETE
    assert next_step(Slots(flow="question"), cfg, "voice") == Step.NAME


def test_step_question_keys_and_fills():
    from spatalk.brain.flow import Pending, Slots, Step, step_question

    cfg = _cfg()
    assert step_question(Step.NAME, Slots(flow="callback"), cfg, "voice") == ("ask_name", {})
    assert step_question(Step.QA, Slots(), cfg, "voice") is None
    pending = Slots(
        flow="new_booking",
        pending=Pending(kind="match", slot="practitioner", value="Helen Courbetis"),
    )
    assert step_question(Step.PRACTITIONER, pending, cfg, "voice") == (
        "confirm_match", {"value": "Helen"},
    )
    kind_q = step_question(
        Step.SERVICE,
        Slots(flow="new_booking", pending=Pending(kind="offers", slot="service_kind")),
        cfg, "voice",
    )
    assert kind_q[0] == "ask_service_kind" and "consultation" in kind_q[1]["consultation"].lower()
