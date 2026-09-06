import uuid
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"


def _world(fixed_clock, responses, channel="voice", caller="+19055550101"):
    from spatalk.brain.driver import Brain, FakeLLM
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle

    cfg = load_bundle(BUNDLE)
    ledger, sms = MemoryLedger(fixed_clock), MemorySms()
    caps = TierCCapabilities(ledger=ledger, sms=sms, clock=fixed_clock)
    llm = FakeLLM(responses)
    ref = ConversationRef(conversation_id=uuid.uuid4(), tenant=cfg, channel=channel, caller_phone=caller)
    return Brain(llm, caps, fixed_clock), ref, ledger, llm, cfg


def _call(name, **args):
    from spatalk.brain.driver import LLMResponse, ToolCall

    return LLMResponse(text=None, tool_calls=[ToolCall(name, args)])


async def test_a_callback_on_sms_walks_the_order_and_files_with_name_and_number(fixed_clock):
    from spatalk.brain.flow import Slots

    responses = [
        _call("start_request", kind="callback"),
        _call("answer", value="yes"),
        _call("choose_practitioner", said="Helen"),
        _call("choose_service", said="hydrabrasion"),
        _call("give_name", first_name="Dana"),
        _call("choose_window", date="Thursday", part_of_day="any"),
        _call("answer", value="no"),
    ]
    brain, ref, ledger, llm, cfg = _world(fixed_clock, responses, channel="sms", caller="+14165550199")
    slots, history = Slots(), []
    texts = ["I'd like someone to call me", "yes", "Helen", "the hydrabrasion", "Dana", "Thursday", "no"]
    replies = []
    for text in texts:
        r = await brain.turn(ref, history, text, slots)
        slots = r.slots
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": r.reply}]
        replies.append(r.reply)
    assert replies[0] == cfg.scripts.ask_returning
    assert replies[1] == cfg.scripts.ask_practitioner
    assert replies[2] == cfg.scripts.ask_service
    assert replies[3] == cfg.scripts.ask_name
    assert replies[4] == cfg.scripts.ask_window            # sms: no phone step
    assert replies[5] == cfg.scripts.ask_team_note
    assert replies[6].startswith("I've sent that to the team as a request")   # filed itself on the last answer
    item = ledger.items[0]
    assert item.type == "callback" and item.contact.name == "Dana" and item.contact.phone == "+14165550199"
    draft = ledger.drafts[0]
    assert draft.practitioner == "Helen Courbetis" and draft.returning_client is True
    # The model was offered only the step's tools each turn.
    offered = [[t.name for t in tools] for (_, _, tools) in llm.calls_with_tools]
    assert all("file_request" not in names for names in offered)   # never needed: the record filed itself
    assert "choose_practitioner" in offered[2] and "give_name" not in offered[2]


async def test_the_model_cannot_file_early_or_put_a_name_in_the_wrong_slot(fixed_clock):
    from spatalk.brain.flow import Slots

    brain, ref, ledger, llm, cfg = _world(
        fixed_clock, [_call("file_request"), _call("give_name", first_name="Ellen")]
    )
    r1 = await brain.turn(ref, [], "book me in", Slots(flow="new_booking"))
    assert ledger.items == [] and r1.reply == cfg.scripts.ask_returning
    r2 = await brain.turn(ref, [], "Ellen", r1.slots)
    assert r2.slots.first_name is None and r2.reply == cfg.scripts.ask_returning


async def test_a_side_question_is_answered_then_the_open_question_is_asked_again(fixed_clock):
    from spatalk.brain.driver import LLMResponse
    from spatalk.brain.flow import Slots

    brain, ref, ledger, llm, cfg = _world(
        fixed_clock, [LLMResponse(text="The Classic facial is $125.", tool_calls=[])]
    )
    r = await brain.turn(
        ref, [], "how much is the classic facial?", Slots(flow="new_booking", returning_client=True)
    )
    assert r.reply == "The Classic facial is $125. " + cfg.scripts.ask_practitioner


async def test_the_acknowledgement_is_one_sentence_and_the_question_is_the_script(fixed_clock):
    from spatalk.brain.driver import LLMResponse, ToolCall
    from spatalk.brain.flow import Slots

    resp = LLMResponse(
        text="Lovely, welcome back! I'm sure the team will be thrilled to see you again.",
        tool_calls=[ToolCall("answer", {"value": "yes"})],
    )
    brain, ref, ledger, llm, cfg = _world(fixed_clock, [resp])
    r = await brain.turn(ref, [], "yes", Slots(flow="new_booking"))
    assert r.reply == "Lovely, welcome back! " + cfg.scripts.ask_practitioner


async def test_clinical_gate_offers_first_and_files_only_on_yes(fixed_clock):
    from spatalk.brain.flow import Slots

    brain, ref, ledger, llm, cfg = _world(fixed_clock, [
        _call("answer", value="yes"), _call("give_name", first_name="Dana"), _call("answer", value="yes"),
    ])
    r = await brain.turn(ref, [], "I have a rash after my peel", Slots())
    assert r.reply == cfg.scripts.clinical_offer and ledger.items == [] and not r.ended
    assert r.gate_reason == "clinical"
    r = await brain.turn(ref, [], "yes please", r.slots)
    assert r.reply == cfg.scripts.ask_name
    r = await brain.turn(ref, [], "Dana", r.slots)
    assert r.reply == cfg.scripts.ask_phone_same
    r = await brain.turn(ref, [], "yes", r.slots)
    assert r.reply.startswith("I've passed that to our clinical team")
    assert ledger.items[0].type == "escalation_clinical" and ledger.items[0].urgency == "urgent"
    assert ledger.items[0].contact.name == "Dana"


async def test_declining_the_clinical_offer_files_nothing(fixed_clock):
    from spatalk.brain.flow import Slots

    brain, ref, ledger, llm, cfg = _world(fixed_clock, [_call("answer", value="no")])
    r = await brain.turn(ref, [], "I have a rash after my peel", Slots())
    r = await brain.turn(ref, [], "no thanks", r.slots)
    assert r.reply == cfg.scripts.clinical_declined and ledger.items == [] and r.slots.flow is None


async def test_an_emergency_still_files_at_once(fixed_clock):
    from spatalk.brain.driver import LLMResponse
    from spatalk.brain.flow import Slots

    brain, ref, ledger, llm, cfg = _world(fixed_clock, [LLMResponse(text="x", tool_calls=[])])
    r = await brain.turn(ref, [], "I can't breathe", Slots())
    assert "911" in r.reply and ledger.items[0].type == "escalation_emergency" and r.ended
