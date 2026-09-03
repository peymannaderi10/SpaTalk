"""Call notes (call-notes plan, Task N1).

The person who picks up a request card should know why the caller rang before they dial.
Today the card carries a sentence composed from closed columns; nothing says what the caller
was hoping for in their own terms. So the assistant asks once, and a post-conversation job
drafts a few sentences from the stored transcript.

Everything the notes are allowed to be is enforced here rather than trusted:

* they are grounded in what the caller actually said (:func:`ground`), so an invented
  sentence is dropped rather than shown to staff as if the caller had said it;
* any sentence that touches health is replaced by the tenant's fixed line
  (:func:`scrub_health`), so the notes can say "wants help with dark spots before a wedding"
  and can never say "is on a medication";
* they live on the conversation, next to the transcript they came from, never on an item;
* they are drafted once per conversation and never fed back to a model.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

NOW = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
RUNTIME = Path(__file__).resolve().parents[1]


def _cfg():
    from spatalk.tenants.bundle import load_bundle

    return load_bundle(RUNTIME / "tenants" / "skincentrix")


def _settings():
    from spatalk.settings import Settings

    return Settings(_env_file=None, public_base_url="https://api.test", secret_key="s")


def _fake_llm(*texts):
    from spatalk.brain.driver import FakeLLM, LLMResponse

    return FakeLLM([LLMResponse(text=t, tool_calls=[]) for t in texts])


def _msgs(*pairs):
    """A transcript as the ledger stores it: unattached ORM rows, role and text."""
    from spatalk.models import Message

    return [Message(role=role, text=text) for role, text in pairs]


TRANSCRIPT = _msgs(
    ("assistant", "Hi there, thanks for calling Skincentrix. How can I help?"),
    ("user", "I've got dark spots on my cheeks and I've got a wedding in November."),
    ("assistant", "The Mirapeel facial is what I'd suggest for pigmentation."),
    ("user", "That sounds good. My name is Dana and this number is fine."),
)

# Every sentence here is grounded in what the *caller* said, which is the only thing
# `ground` accepts: what the assistant offered is not something the caller told us.
GROUNDED = (
    "Caller has dark spots on the cheeks and a wedding in November. "
    "Gave the name Dana and said this number is fine."
)


# =============================================================================================
# 1. The question: asked once, on every channel, and never about a condition
# =============================================================================================


def test_the_prompt_asks_once_whether_there_is_anything_the_team_should_know():
    from spatalk.brain.prompt import build_system_prompt

    for channel in ("voice", "sms", "chat", "instagram", "messenger"):
        p = build_system_prompt(_cfg(), channel, NOW).lower()
        assert "anything they would like the team to know before they call" in p, channel
        assert "what they are hoping to get out of the visit" in p, channel
        assert "do not repeat their answer back" in p, channel


def test_the_question_is_asked_once_and_takes_no_for_an_answer():
    from spatalk.brain.prompt import build_system_prompt

    booking = build_system_prompt(_cfg(), "voice", NOW).lower().split("when they want to book", 1)[1]
    step = next(
        line for line in booking.splitlines() if "would like the team to know" in line
    )
    assert step.lstrip().startswith("- ask once whether")
    assert "take no for an answer" in step


def test_the_question_never_invites_a_medical_history():
    """The booking block may name a condition or a medication only to forbid asking about it."""
    import re

    from spatalk.brain.prompt import build_system_prompt

    instructions = build_system_prompt(_cfg(), "voice", NOW).split("HOURS:")[0]
    booking = instructions.lower().split("when they want to book", 1)[1]
    for word in ("condition", "medication", "history"):
        for sentence in re.split(r"(?<=[.;])\s+", booking):
            if word in sentence:
                assert "never ask about" in sentence, (
                    f"{word!r} appears in the booking block outside the never-ask clause: "
                    f"{sentence!r}"
                )


def test_the_question_is_asked_after_the_name_and_number_and_before_the_tool_call():
    from spatalk.brain.prompt import build_system_prompt

    booking = build_system_prompt(_cfg(), "voice", NOW).lower().split("when they want to book", 1)[1]
    assert booking.index("first name") < booking.index("would like the team to know")
    assert booking.index("would like the team to know") < booking.index("on the tool call")


# =============================================================================================
# 2. Grounding: a sentence the caller did not say does not survive
# =============================================================================================


def test_ground_keeps_a_grounded_sentence_and_drops_an_invented_one():
    from spatalk.ledger.notes import ground

    user_turns = [m.text for m in TRANSCRIPT if m.role == "user"]
    kept = ground(
        "Caller has dark spots on the cheeks and a wedding in November. "
        "She is anxious about ageing and would like a discount.",
        user_turns,
    )
    assert kept is not None
    assert "dark spots" in kept
    assert "discount" not in kept and "anxious" not in kept


def test_ground_returns_none_when_nothing_survives():
    from spatalk.ledger.notes import ground

    assert ground("She would like a discount on her next visit.", ["Hello there."]) is None
    assert ground("", ["anything"]) is None


def test_ground_needs_three_content_words_not_one():
    """One shared word is a coincidence; the rule is three (call-notes plan, Global Constraints)."""
    from spatalk.ledger.notes import ground

    assert ground("Caller asked about pigmentation.", ["I have pigmentation."]) is None


# =============================================================================================
# 3. The health line: the notes can say what they want, never what they have
# =============================================================================================


def test_scrub_health_replaces_the_first_health_sentence_and_drops_the_rest():
    from spatalk.ledger.notes import scrub_health

    cfg = _cfg()
    out = scrub_health(
        "Caller wants help with dark spots before a wedding. "
        "She takes a medication for her skin. "
        "She has had eczema since last year. "
        "She is hoping to look her best on the day.",
        cfg,
    )
    assert cfg.scripts.notes_health_line in out
    assert out.count(cfg.scripts.notes_health_line) == 1
    assert "medication" not in out and "eczema" not in out
    assert "dark spots" in out and "look her best" in out


def test_scrub_health_replaces_a_clinical_sentence_too():
    from spatalk.ledger.notes import scrub_health

    cfg = _cfg()
    out = scrub_health("Caller has a rash on her arm. Wants a facial.", cfg)
    assert out.startswith(cfg.scripts.notes_health_line)
    assert "rash" not in out


def test_scrub_health_leaves_a_cosmetic_note_alone():
    from spatalk.ledger.notes import scrub_health

    text = "Caller wants help with dark spots on the cheeks before a wedding in November."
    assert scrub_health(text, _cfg()) == text


# =============================================================================================
# 4. draft_notes: nothing to draft from, nothing stored
# =============================================================================================


async def test_draft_notes_returns_none_for_a_transcript_with_no_user_turns():
    from spatalk.ledger.notes import draft_notes

    llm = _fake_llm("Caller wanted a facial.")
    assert await draft_notes(_msgs(("assistant", "Hello?")), _cfg(), llm) is None
    assert llm.calls == [], "the model must not be called when there is nothing to draft from"


async def test_draft_notes_returns_none_when_the_model_says_nothing():
    from spatalk.ledger.notes import draft_notes

    assert await draft_notes(TRANSCRIPT, _cfg(), _fake_llm("")) is None
    assert await draft_notes(TRANSCRIPT, _cfg(), _fake_llm(None)) is None


async def test_draft_notes_returns_a_grounded_scrubbed_string():
    from spatalk.ledger.notes import draft_notes

    out = await draft_notes(
        TRANSCRIPT,
        _cfg(),
        # The health sentence is grounded, so it survives `ground` and reaches the scrub;
        # the invented one does not survive either.
        _fake_llm(
            GROUNDED
            + " The dark spots on her cheeks are a reaction to something."
            + " She wants a discount."
        ),
    )
    assert out is not None
    assert "dark spots" in out and "Dana" in out
    assert "discount" not in out
    assert "reaction" not in out
    assert _cfg().scripts.notes_health_line in out


async def test_draft_notes_drops_everything_the_model_invented():
    from spatalk.ledger.notes import draft_notes

    out = await draft_notes(
        TRANSCRIPT, _cfg(), _fake_llm("She would like a discount and a free consultation.")
    )
    assert out is None


async def test_draft_notes_keeps_at_most_four_sentences():
    """The instruction asks for four; this is the enforcement, because asking is not a limit."""
    import re

    from spatalk.ledger.notes import draft_notes

    five = " ".join(
        [
            "Caller has dark spots on the cheeks.",
            "There is a wedding in November and dark spots to sort out.",
            "Gave the name Dana and said the number is fine.",
            "The spots on the cheeks are dark.",
            "Sounds good about the wedding in November.",
        ]
    )
    assert await draft_notes(TRANSCRIPT, _cfg(), _fake_llm(five)) is not None
    out = await draft_notes(TRANSCRIPT, _cfg(), _fake_llm(five))
    assert len(re.split(r"(?<=[.!?])\s+", out.strip())) == 4


async def test_the_drafting_prompt_is_an_instruction_and_carries_no_tenant_script():
    from spatalk.ledger.notes import DRAFTING_SYSTEM, draft_notes

    cfg = _cfg()
    llm = _fake_llm(GROUNDED)
    await draft_notes(TRANSCRIPT, cfg, llm)
    system, history = llm.calls[0]
    assert system == DRAFTING_SYSTEM
    for script in (cfg.scripts.captured, cfg.scripts.clinical, cfg.scripts.goodbye):
        assert script not in system
    assert "at most four" in DRAFTING_SYSTEM.lower()
    # The transcript is what the model sees, and nothing else.
    assert history and all(m["role"] in ("user", "assistant") for m in history)


# =============================================================================================
# 5. The job: once per conversation, one attempt, and the usage it cost
# =============================================================================================


def _ctx(sf, registry, clock, llm=None):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger

    return jobs.JobContext(
        sf=sf,
        clock=clock,
        registry=registry,
        ledger=PgLedger(sf, clock),
        delivery=MemoryDelivery(),
        settings=_settings(),
        llm=llm,
    )


async def _conversation(sf, *, channel="voice", turns=TRANSCRIPT):
    from spatalk.conversations import append_message, start_conversation

    cid = await start_conversation(sf, "skincentrix", channel, "ref", "+19055550101")
    for m in turns:
        await append_message(sf, cid, m.role, m.text)
    return cid


async def test_the_job_stores_the_notes_once_and_is_a_no_op_the_second_time(
    sf, registry, fixed_clock
):
    from sqlalchemy import select

    from spatalk import jobs
    from spatalk.models import Conversation

    cid = await _conversation(sf)
    llm = _fake_llm(GROUNDED, "Caller wanted something else entirely.")
    ctx = _ctx(sf, registry, fixed_clock, llm)

    await jobs.enqueue(sf, "call_notes", {"conversation_id": str(cid)})
    await jobs.run_once(sf, ctx)

    async with sf() as s:
        conv = await s.get(Conversation, cid)
    assert conv.notes is not None and "dark spots" in conv.notes
    assert conv.notes_model == ctx.settings.llm_model
    assert conv.notes_at == fixed_clock.now()
    first = conv.notes

    await jobs.enqueue(sf, "call_notes", {"conversation_id": str(cid)})
    await jobs.run_once(sf, ctx)

    async with sf() as s:
        conv = await s.get(Conversation, cid)
        states = list((await s.scalars(select(jobs.Job.state))).all())
    assert conv.notes == first, "a second run must not redraft"
    assert len(llm.calls) == 1, "a second run must not call the model again"
    assert states == ["done", "done"]


async def test_the_job_records_what_the_drafting_cost(sf, registry, fixed_clock):
    from sqlalchemy import select

    from spatalk import jobs
    from spatalk.models import UsageEvent

    cid = await _conversation(sf)
    ctx = _ctx(sf, registry, fixed_clock, _fake_llm(GROUNDED))
    await jobs.enqueue(sf, "call_notes", {"conversation_id": str(cid)})
    await jobs.run_once(sf, ctx)

    async with sf() as s:
        rows = (await s.scalars(select(UsageEvent).order_by(UsageEvent.id))).all()
    units = {r.unit: r for r in rows}
    assert "llm_input_tokens" in units and "llm_output_tokens" in units
    assert all(r.channel == "voice" and r.conversation_id == cid for r in rows)
    assert all(r.qty > 0 for r in rows)


async def test_the_job_dead_letters_rather_than_retrying(sf, registry, fixed_clock):
    from sqlalchemy import select

    from spatalk import jobs
    from spatalk.models import Job

    class Broken:
        async def complete(self, system, history, tools):
            raise RuntimeError("provider is down")

    cid = await _conversation(sf)
    await jobs.enqueue(sf, "call_notes", {"conversation_id": str(cid)})
    await jobs.run_once(sf, _ctx(sf, registry, fixed_clock, Broken()))

    async with sf() as s:
        job = (await s.scalars(select(Job))).one()
    assert job.state == "dead" and job.attempts == 1
    assert "provider is down" in job.last_error


async def test_an_empty_draft_stores_null_and_still_marks_the_conversation_drafted(
    sf, registry, fixed_clock
):
    from spatalk import jobs
    from spatalk.models import Conversation

    cid = await _conversation(sf)
    llm = _fake_llm("She would like a discount and a free consultation.")
    await jobs.enqueue(sf, "call_notes", {"conversation_id": str(cid)})
    await jobs.run_once(sf, _ctx(sf, registry, fixed_clock, llm))

    async with sf() as s:
        conv = await s.get(Conversation, cid)
    assert conv.notes is None, "an empty result stores NULL, never a placeholder"
    assert conv.notes_at is not None, "the drafting still happened, and happens only once"


# ----- queueing -------------------------------------------------------------------------


async def _queued(sf, kind="call_notes"):
    from sqlalchemy import select

    from spatalk.models import Job

    async with sf() as s:
        return list((await s.scalars(select(Job).where(Job.kind == kind))).all())


async def test_end_conversation_queues_the_job_for_a_voice_call(sf, registry, fixed_clock):
    from spatalk.conversations import end_conversation

    cid = await _conversation(sf)
    await end_conversation(sf, cid, band=1, latency_ms=[600], call_notes=True)

    jobs_queued = await _queued(sf)
    assert len(jobs_queued) == 1
    assert jobs_queued[0].payload == {"conversation_id": str(cid)}


async def test_end_conversation_queues_nothing_when_the_tenant_turned_notes_off(
    sf, registry, fixed_clock
):
    from spatalk.conversations import end_conversation

    cid = await _conversation(sf)
    await end_conversation(sf, cid, band=1, latency_ms=[600], call_notes=False)
    assert await _queued(sf) == []


async def test_the_default_is_on_and_a_tenant_can_switch_it_off():
    cfg = _cfg()
    assert cfg.call_notes is True
    assert cfg.model_copy(update={"call_notes": False}).call_notes is False


async def test_the_text_channel_close_queues_the_job(sf, registry, fixed_clock):
    """SMS, chat, Instagram and Messenger all end through the same close."""
    from spatalk.text.service import TextConversationService

    cfg = await registry.get("skincentrix")
    cid = await _conversation(sf, channel="sms")
    service = TextConversationService(_ctx(sf, registry, fixed_clock), _fake_llm())
    async with sf() as s:
        from spatalk.models import Conversation

        conv = await s.get(Conversation, cid)
    await service._finish_turn(cfg, conv, _ended_turn())

    assert len(await _queued(sf)) == 1


async def test_the_text_channel_close_queues_nothing_when_notes_are_off(
    sf, registry, fixed_clock
):
    from spatalk.models import Conversation
    from spatalk.text.service import TextConversationService

    cfg = (await registry.get("skincentrix")).model_copy(update={"call_notes": False})
    await registry.import_config(cfg, created_by="test")
    cid = await _conversation(sf, channel="sms")
    service = TextConversationService(_ctx(sf, registry, fixed_clock), _fake_llm())
    async with sf() as s:
        conv = await s.get(Conversation, cid)
    await service._finish_turn(cfg, conv, _ended_turn())

    assert await _queued(sf) == []


def _ended_turn():
    from spatalk.brain.driver import TurnResult

    return TurnResult(reply="", band=1, gate_reason=None, ended=True)


# =============================================================================================
# 6. Delivery: the block appears only when there are notes, and only on email and Slack
# =============================================================================================


def _links():
    from spatalk.ledger.delivery import ActionLinks
    from spatalk.ledger.links import sign_action

    ack = sign_action("s", 7, "ack", "skincentrix")
    res = sign_action("s", 7, "resolve", "skincentrix")
    return ActionLinks("https://a/ack", "https://a/res", "https://api.test/a/t", ack, res)


def _item():
    from spatalk.models import Item

    return Item(
        id=7,
        tenant_id="skincentrix",
        type="new_booking",
        urgency="normal",
        service_id=None,
        contact_name="Dana",
        contact_phone="+19055550101",
        preferred_window={},
        channel="voice",
        state="open",
        due_at=NOW + timedelta(hours=3),
        owner="owner@example.test",
    )


def test_the_email_carries_the_notes_block_only_when_notes_exist():
    from spatalk.ledger.delivery import build_email

    cfg = _cfg()
    _, without = build_email(_item(), cfg, _links(), NOW)
    assert cfg.scripts.notes_label not in without

    _, with_notes = build_email(_item(), cfg, _links(), NOW, notes=GROUNDED)
    assert cfg.scripts.notes_label in with_notes
    assert GROUNDED in with_notes
    assert with_notes.index(cfg.scripts.notes_label) > with_notes.index("Due:")


def test_the_slack_card_carries_the_notes_block_only_when_notes_exist():
    from spatalk.ledger.delivery import build_slack_blocks

    cfg = _cfg()
    without = build_slack_blocks(_item(), cfg, _links(), NOW)
    assert cfg.scripts.notes_label not in str(without)

    with_notes = build_slack_blocks(_item(), cfg, _links(), NOW, notes=GROUNDED)
    assert cfg.scripts.notes_label in str(with_notes)
    assert GROUNDED in str(with_notes)


def test_the_staff_sms_and_the_whatsapp_text_are_unchanged():
    """Segment budget: a staff text says the same thing it said before the notes existed."""
    from spatalk.ledger.delivery import build_sms_text, build_whatsapp_text

    cfg = _cfg()
    sms = build_sms_text(_item(), cfg, _links(), NOW)
    wa = build_whatsapp_text(_item(), cfg, _links(), NOW)
    assert cfg.scripts.notes_label not in sms
    assert cfg.scripts.notes_label not in wa


async def test_the_delivered_email_carries_the_notes_the_conversation_holds(
    sf, registry, fixed_clock
):
    from spatalk import jobs
    from spatalk.conversations import set_notes
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.models import Item

    cfg = await registry.get("skincentrix")
    cid = await _conversation(sf)
    await set_notes(sf, cid, GROUNDED, "gemini-2.5-flash", fixed_clock.now())
    async with sf() as s, s.begin():
        item = Item(
            tenant_id="skincentrix",
            conversation_id=cid,
            type="new_booking",
            urgency="normal",
            preferred_window={},
            channel="voice",
            state="open",
            due_at=fixed_clock.now(),
            owner="owner@example.test",
        )
        s.add(item)
        await s.flush()
        item_id = item.id

    delivery = MemoryDelivery()
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=delivery,
        settings=_settings(),
    )
    await jobs.enqueue(
        sf, "deliver.email", {"item_id": item_id, "tenant_id": cfg.id, "to": "owner@x.test"}
    )
    await jobs.run_once(sf, ctx)

    assert delivery.emails, "no email was sent"
    body = delivery.emails[-1][2]
    assert cfg.scripts.notes_label in body and GROUNDED in body


# =============================================================================================
# 7. The internal API: the card needs one call
# =============================================================================================


async def test_item_out_serialises_the_notes_from_the_items_conversation(
    sf, registry, fixed_clock
):
    import httpx

    from spatalk.conversations import set_notes
    from spatalk.http.app import create_app
    from spatalk.ledger.items import PgLedger
    from spatalk.models import Item

    cid = await _conversation(sf)
    await set_notes(sf, cid, GROUNDED, "gemini-2.5-flash", fixed_clock.now())
    async with sf() as s, s.begin():
        s.add(
            Item(
                tenant_id="skincentrix",
                conversation_id=cid,
                type="new_booking",
                urgency="normal",
                preferred_window={},
                channel="voice",
                state="open",
                due_at=fixed_clock.now(),
                owner="owner@example.test",
            )
        )

    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.settings import Settings

    settings = Settings(_env_file=None, secret_key="s", internal_api_key="k")
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=settings,
    )
    app = create_app(ctx, start_background=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        items = await client.get(
            "/internal/tenants/skincentrix/items", headers={"X-Internal-Key": "k"}
        )
        detail = await client.get(
            f"/internal/conversations/{cid}", headers={"X-Internal-Key": "k"}
        )
    assert items.status_code == 200, items.text
    assert items.json()[0]["notes"] == GROUNDED
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["conversation"]["notes"] == GROUNDED
    assert body["conversation"]["notes_at"] is not None
    assert body["items"][0]["notes"] == GROUNDED


def test_the_committed_contract_carries_the_three_new_fields():
    import json

    contract = json.loads(
        (RUNTIME.parent / "docs" / "contracts" / "runtime-internal.openapi.json").read_text(
            encoding="utf-8"
        )
    )
    schemas = contract["components"]["schemas"]
    assert "notes" in schemas["ItemOut"]["properties"]
    assert "notes" in schemas["ConversationFull"]["properties"]
    assert "notes_at" in schemas["ConversationFull"]["properties"]
    # The list view stays light: notes are read on the card and on the conversation page.
    assert "notes" not in schemas["ConversationRow"]["properties"]


# =============================================================================================
# 8. The line that must not move
# =============================================================================================


def test_the_item_table_gained_no_column():
    from spatalk.models import Item

    assert "notes" not in Item.__table__.columns


def test_the_notes_are_config_wording_and_a_code_instruction_only():
    """CLAUDE.md 3: the health line and the label are scripts; the drafting prompt is code."""
    from spatalk.ledger import notes as notes_module

    cfg = _cfg()
    assert cfg.scripts.notes_health_line
    assert cfg.scripts.notes_label
    source = (RUNTIME / "spatalk" / "ledger" / "notes.py").read_text(encoding="utf-8")
    assert cfg.scripts.notes_health_line not in source
    assert cfg.scripts.notes_label not in source
    assert notes_module.DRAFTING_SYSTEM


def test_the_bundle_carries_both_scripts():
    import yaml

    raw = yaml.safe_load(
        (RUNTIME / "tenants" / "skincentrix" / "scripts.yaml").read_text(encoding="utf-8")
    )
    assert raw["notes_health_line"]
    assert raw["notes_label"]


@pytest.mark.parametrize("word", ["booked", "confirmed", "scheduled"])
def test_neither_script_promises_an_action(word):
    cfg = _cfg()
    assert word not in cfg.scripts.notes_health_line.lower()
    assert word not in cfg.scripts.notes_label.lower()
