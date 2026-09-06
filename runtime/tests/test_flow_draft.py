from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def test_draft_carries_only_list_values_and_the_slots_contact():
    from spatalk.brain.flow import Slots, draft_from
    from spatalk.brain.requests import PreferredWindow

    s = Slots(
        flow="new_booking", returning_client=True, practitioner="Helen Courbetis",
        service_id="hydrabrasion_facial", first_name="Dana", phone="+14165550199",
        phone_confirmed=True, preferred_window=PreferredWindow(date="Thursday"),
    )
    d = draft_from(s, _cfg())
    assert d.type == "new_booking" and d.urgency == "normal"
    assert d.contact.name == "Dana" and d.contact.phone == "+14165550199" and d.contact.email is None
    assert d.practitioner == "Helen Courbetis" and d.returning_client is True
    assert d.preferred_window.date == "Thursday" and d.service_id == "hydrabrasion_facial"
    c = draft_from(Slots(flow="clinical", first_name="Dana", phone="+1", phone_confirmed=True), _cfg())
    assert c.type == "escalation_clinical" and c.urgency == "urgent"


def test_step_message_names_what_is_known_and_the_tool_to_use():
    from spatalk.brain.flow import STEP_MARKER, Slots, Step, step_message

    s = Slots(flow="new_booking", returning_client=True, practitioner="Helen Courbetis")
    m = step_message(Step.SERVICE, s, _cfg(), "voice")
    assert m.startswith(STEP_MARKER) and "choose_service" in m and "Helen" in m
    assert len(m.split(". ")) <= 5
    qa = step_message(Step.QA, Slots(), _cfg(), "voice")
    assert qa.startswith(STEP_MARKER) and "start_request" in qa
    done = step_message(Step.COMPLETE, s.with_(first_name="Dana"), _cfg(), "voice")
    assert "file_request" in done
