"""The consultation the assistant should have had, from founder call 14ea2579, 2026-09-11.

At 15:53:11 the caller asked "That's the facial one, right? What, what, what facials do you
have?". `resolve.is_question` is True on those words, so the slot engine refused them as
question-shaped and the model answered — correctly — with `answer_question`. What came back at
15:53:14 was three TTS frames in one breath: 409 characters, seven treatment names, three price
points, no question about what the caller wanted to work on, and the bot still speaking 23.5
seconds later.

Three things produced that recital and all three are fixed here:

* the prompt asked for it twice — `VOICE_STYLE` said to lead with "two or three concrete
  options with their prices", and HOW YOU SOUND said "when someone asks about a treatment, give
  the price and one or two concrete details";
* `tenants/skincentrix/services.yaml` handed it over pre-formed — the `facial` category row's
  description was itself a 208-character price recital, and the spoken answer matched it name
  for name and grouping for grouping, down to the adjacent "$215" pair;
* `_services_text` rendered price before purpose, under a heading that said `SERVICES (name:
  price)`.

The rule that was already there — "Never name more than three treatments or three people in one
breath", prompt.py:135 — was overridden, not missing, which is why adding a rule without taking
the two price-first clauses out would have changed nothing. The descriptions already work: the
repair turn at 15:54:05 used `mesojet_facial.description` verbatim.
"""

from datetime import datetime, timezone
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
NOW = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)
CHANNELS = ("voice", "sms", "chat", "instagram")


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(BUNDLE)


def test_the_prompt_asks_the_goal_before_it_names_anything():
    """A price list is no better on SMS than on the phone, so the rule is not voice-only."""
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    for channel in CHANNELS:
        p = build_system_prompt(cfg, channel, NOW)
        assert "WHAT WE OFFER, WHEN THEY ASK" in p, channel
        assert "opens a conversation, not a list" in p, channel
        assert "what they would like to work on" in p, channel
        assert "their skin goal" in p, channel
        assert "Never read a category out" in p, channel


def test_the_price_waits_for_the_question_or_the_choice():
    """The regression that let seven names and three prices out at 15:53:14.

    Both price-first clauses are gone; the licence to answer a price that was asked for is
    explicit, so removing them cannot make the assistant coy about a price question.
    """
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    for channel in CHANNELS:
        p = build_system_prompt(cfg, channel, NOW)
        assert (
            "A price answers a question about price, or a treatment they have already chosen"
            in p
        ), channel
        assert "Do not attach one to a name they have not picked" in p, channel
        assert "with their prices" not in p, channel
        assert "give the price and one or two concrete details" not in p, channel


def test_the_callers_own_word_for_a_treatment_comes_back():
    """"That's the facial one, right?" is answered about facials, not about a renamed row."""
    from spatalk.brain.prompt import build_system_prompt

    p = build_system_prompt(_cfg(), "voice", NOW)
    assert "Call a treatment what the caller called it" in p
    assert "do not rename it" in p


def test_the_consultation_wording_still_stays_out_of_the_prompt():
    """The consultative offer wording lives in `scripts.ask_service_kind` and knowledge.md.

    This duplicates the guarantee of
    `tests/test_prompt_booking_flow.py::test_the_offer_wording_stays_out_of_the_prompt` so that
    an edit to the new section fails in the file that owns the new section.
    """
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    for channel in CHANNELS:
        instructions = build_system_prompt(cfg, channel, NOW).split("HOURS:")[0].lower()
        for word in ("$50", "credit", "consultation", "underarm", "free "):
            assert word not in instructions, f"{channel}: {word}"


def test_three_in_a_breath_is_still_the_ceiling():
    """The new section reinforces the old rule; it does not replace it."""
    from spatalk.brain.prompt import build_system_prompt

    p = build_system_prompt(_cfg(), "voice", NOW).lower()
    assert "more than three" in p
    assert "treatments or three people" in p


# --- defect 5, the prompt half (task P2) --------------------------------------------------


def test_the_question_is_answered_before_the_answer_is_recorded():
    """15:55:00 "How much does it cost?" was recorded as the answer to the treatment slot and
    never answered: `choose_service{'said': 'MesoJet and Sound Therapy facial'}` at 15:55:02,
    and 11 milliseconds later "Is there someone in particular you'd like to see". The caller
    said "I said how much" twice more; the price arrived at 15:55:09, three turns and 8.4
    seconds after it was asked, out of facts the prompt already carried.
    """
    from spatalk.brain.prompt import build_system_prompt

    p = build_system_prompt(_cfg(), "voice", NOW)
    assert "ask the next question in the same reply" in p
    assert "If the same words also asked you something, answer that first" in p
    assert "a question the caller has to repeat is one you did not answer" in p


def test_no_step_brief_contradicts_the_consultative_rule():
    """The whole system message, not half of it. `voice/steps.py` and `driver.py` both build
    the request as `build_system_prompt(...) + "\n\n" + step_message(...)`, so a turn brief is
    the LAST thing the model reads and outranks the static section by position. Every step and
    every pending kind is checked, because the one that broke this was reachable from the word
    "facial" (defect 8, founder call 14ea2579, 15:53:14)."""
    from spatalk.brain.flow import Pending, Slots, Step, step_message
    from spatalk.brain.prompt import build_system_prompt

    cfg = _cfg()
    head = build_system_prompt(cfg, "voice", NOW)
    records = [Slots(flow="new_booking", returning_client=False, offers_done=True)]
    for kind in ("match", "which", "name_staff", "phone", "not_service", "offers"):
        records.append(records[0].with_(pending=Pending(kind=kind, slot="service", value="x")))
    for slots in records:
        for step in Step:
            whole = head + "\n\n" + step_message(step, slots, cfg, "voice")
            for banned in ("with prices", "prices in one breath", "with their prices"):
                assert banned not in whole, (step, slots.pending, banned)
