"""A call that ended on a complete record files it (founder call 14ea2579, 2026-09-11).

The call of 15:51:55 collected every slot of a new-client MesoJet booking and ended with one
ledger row: an `escalation_clinical` with no name, no treatment and no window. The booking
existed only in `conversations.notes`, which by CLAUDE.md 2 can never become an item.

Two holes close here. A ledger that refused leaves the record *unfiled* rather than marked
filed with nothing behind it, and the end of the call tries once more — silently, because the
caller has gone. A complete request is the team's to work whether or not the caller ever
answered the last question.
"""

import uuid

import pytest
from sqlalchemy import select

CALLER = "+18567451025"


@pytest.fixture
async def ctx(sf, registry, fixed_clock):
    """A JobContext on memory ports, the same shape the pipeline's `_finalize` is given."""
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings

    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=Settings(_env_file=None, secret_key="s3cret"),
        sms=MemorySms(),
    )


class _StubContext:
    """Stands in for the Pipecat LLMContext: `_finalize` reads nothing but `messages`."""

    def __init__(self, messages):
        self.messages = messages


class _Worker:
    """The pipeline's worker double: every frame the end of the call would queue."""

    def __init__(self):
        self.queued = []

    async def queue_frames(self, frames):
        self.queued.extend(frames)


class _DeadLedger:
    """A capabilities double whose ledger is down. Nothing is written; nothing is promised."""

    def __init__(self):
        self.attempts = 0

    async def capture(self, ref, draft):
        self.attempts += 1
        raise RuntimeError("database is down")


async def _session(ctx, sf, caps=None):
    """A finished voice call: a conversation row plus the session the pipeline held."""
    from datetime import datetime, timezone

    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.conversations import start_conversation
    from spatalk.voice.session import VoiceSession

    cfg = await ctx.registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "v3:call-1551", CALLER)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice", caller_phone=CALLER)
    caps = caps or TierCCapabilities(
        ledger=MemoryLedger(ctx.clock), sms=MemorySms(), clock=ctx.clock
    )
    session = VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=ctx.clock)
    session.started_at = datetime.now(timezone.utc)
    session.worker = _Worker()
    return session


def _the_1556_record():
    """The founder's record at 15:56:17, one answered question short of nothing at all.

    `PreferredWindow._closed_date` maps anything that is not an ISO date, a weekday name or
    "any" to "any", so the model's 'Monday or Tuesday' is stored as "any" (requests.py:34-56).
    """
    from spatalk.brain.flow import Slots
    from spatalk.brain.requests import PreferredWindow

    return Slots(
        flow="new_booking",
        returning_client=False,
        offers_done=True,
        service_id="mesojet_facial",
        practitioner="any",
        first_name="Payman",
        phone=CALLER,
        phone_confirmed=True,
        preferred_window=PreferredWindow(date="Monday or Tuesday", part_of_day="afternoon"),
        team_note_asked=True,
    )


async def test_a_call_that_ends_on_a_complete_unfiled_record_files_it(ctx, sf):
    """Conversation 14ea2579-a14e-4be5-9786-8b5354499931, 2026-09-11 15:56:39."""
    from spatalk.voice.pipeline import _finalize

    session = await _session(ctx, sf)
    session.slots = _the_1556_record()
    await _finalize(ctx, session, _StubContext([{"role": "user", "content": "the mesojet one"}]))
    ledger = session.caps._ledger
    assert len(ledger.items) == 1
    item = ledger.items[0]
    assert item.type == "new_booking"
    assert item.contact.name == "Payman" and item.contact.phone == CALLER
    assert item.service_id == "mesojet_facial"
    draft = ledger.drafts[0]
    assert draft.practitioner == "any" and draft.returning_client is False
    assert draft.preferred_window.model_dump() == {"date": "any", "part_of_day": "afternoon"}
    assert session.band >= 2
    assert session.slots.filed is True
    assert session.receipts == [f"item:{item.id}"]


async def test_the_end_of_call_files_nothing_when_there_is_nothing_to_file(ctx, sf):
    from spatalk.brain.flow import Pending, Slots
    from spatalk.voice.pipeline import _finalize

    complete = _the_1556_record()
    cases = {
        "already filed": complete.with_(filed=True),
        "no window yet": complete.with_(preferred_window=None),
        "no request open": Slots(),
        "a confirmation is open": complete.with_(
            pending=Pending(kind="phone", slot="phone", value=CALLER)
        ),
        "the clinical offer was declined": Slots(
            flow="clinical", ended_flow=True, phone=CALLER, phone_confirmed=True
        ),
    }
    for label, slots in cases.items():
        session = await _session(ctx, sf)
        session.slots = slots
        await _finalize(ctx, session, _StubContext([]))
        assert session.caps._ledger.items == [], label


async def test_the_end_of_call_filing_speaks_nothing_and_survives_a_ledger_failure(ctx, sf):
    from pipecat.frames.frames import EndFrame, TTSSpeakFrame
    from spatalk.models import Conversation
    from spatalk.voice.pipeline import _finalize

    dead = _DeadLedger()
    session = await _session(ctx, sf, caps=dead)
    session.slots = _the_1556_record()
    session.signals.record("repeat")
    session.stage_ttfb_ms["llm"].append(900)
    await _finalize(ctx, session, _StubContext([{"role": "assistant", "content": "Hi there."}]))
    assert dead.attempts == 1
    assert session.slots.filed is False
    # The call is still recorded: the rung-0 counts and the stage p95 outlive the transcript.
    async with sf() as s:
        conv = (
            await s.scalars(select(Conversation).where(Conversation.id == session.ref.conversation_id))
        ).one()
    assert conv.ended_at is not None
    assert conv.signals["counts"]["repeat"] == 1
    assert conv.stage_ms and conv.stage_ms["llm"] == 900
    # And the caller has gone, so nothing was said and nothing was queued.
    assert not any(isinstance(f, (TTSSpeakFrame, EndFrame)) for f in session.worker.queued)


async def test_the_1551_call_files_the_booking_alongside_the_clinical_escalation(ctx, sf):
    """The whole defect in one case. Conversation 14ea2579-a14e-4be5-9786-8b5354499931:
    every slot of the booking was on the record, the model called escalate(clinical) at
    15:56:30.765 for a pre-treatment question, and the call ended 9 s later with one item.
    Both requests are real, so both reach the ledger.

    The escalation is filed through the capability directly here, because at this task the
    model's own `escalate` still ends the turn and still collides with the filing in
    `run_tool`'s if/elif chain. The next task takes that apart and this case is tightened to
    drive the whole sequence through `run_tool`."""
    from spatalk.brain.requests import EscalateRequest
    from spatalk.voice.pipeline import _finalize

    session = await _session(ctx, sf)
    session.slots = _the_1556_record()
    await session.caps.escalate(session.ref, EscalateRequest(reason="clinical"))
    await _finalize(ctx, session, _StubContext([{"role": "user", "content": "does it hurt?"}]))
    types = sorted(i.type for i in session.caps._ledger.items)
    assert types == ["escalation_clinical", "new_booking"]
    booking = next(i for i in session.caps._ledger.items if i.type == "new_booking")
    assert booking.contact.name == "Payman" and booking.service_id == "mesojet_facial"
    assert uuid.UUID(str(session.ref.conversation_id)) == session.ref.conversation_id
