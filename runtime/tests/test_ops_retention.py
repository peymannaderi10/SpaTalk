"""Retention with receipts (operations plan, Task E3).

Every delete here is a hard delete that leaves a receipt row behind, because the only
defence against "we deleted it, trust us" is a countable artefact. The suite pins the four
thresholds (`retention_days` for transcripts, 400 days for conversations, items and usage,
two years for the audit log), the conversation stub that survives the transcript purge, the
idempotence of a second run the same night, and the once-a-day scheduling at 03:00 UTC.
"""

from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


def _settings():
    from spatalk.settings import Settings

    return Settings(_env_file=None, public_base_url="https://api.test", secret_key="s")


def _ctx(sf, registry, clock):
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
    )


async def _second_tenant(registry, tenant_id="otherclinic", retention_days=7):
    """A second tenant that differs from Skincentrix only in what it keeps."""
    cfg = await registry.get("skincentrix")
    other = cfg.model_copy(
        update={
            "id": tenant_id,
            "name": "Other Clinic",
            "retention_days": retention_days,
            "voice_numbers": [],
            "sms_from_number": None,
        }
    )
    await registry.import_config(other, created_by="test")
    return other


async def _conversation(
    sf,
    tenant_id,
    *,
    started_at,
    ended_at=None,
    last_message_at=None,
    caller="+19055550101",
    channel="sms",
    band=1,
    messages=0,
    latency_ms=None,
    stage_ms=None,
):
    from spatalk.models import Conversation, Message

    async with sf() as s, s.begin():
        c = Conversation(
            tenant_id=tenant_id,
            channel=channel,
            external_ref="ref",
            caller=caller,
            band=band,
            started_at=started_at,
            ended_at=ended_at,
            last_message_at=last_message_at,
            latency_ms=latency_ms,
            stage_ms=stage_ms,
        )
        s.add(c)
        await s.flush()
        for i in range(messages):
            s.add(
                Message(
                    conversation_id=c.id, role="user", text=f"m{i}", created_at=started_at
                )
            )
        return c.id


async def _item(sf, tenant_id, *, created_at, conversation_id=None):
    from spatalk.models import Item

    async with sf() as s, s.begin():
        it = Item(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            type="callback",
            urgency="normal",
            preferred_window={},
            channel="sms",
            state="open",
            due_at=created_at,
            owner="owner@example.test",
            created_at=created_at,
        )
        s.add(it)
        await s.flush()
        return it.id


async def _usage(sf, tenant_id, *, created_at, conversation_id=None):
    from spatalk.models import UsageEvent

    async with sf() as s, s.begin():
        s.add(
            UsageEvent(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                channel="sms",
                provider="telnyx",
                unit="sms_in",
                qty=1,
                created_at=created_at,
            )
        )


async def _audit(sf, *, created_at):
    from spatalk.models import AuditLog

    async with sf() as s, s.begin():
        s.add(
            AuditLog(
                actor="link",
                action="read_transcript",
                record_type="conversation",
                record_id="x",
                created_at=created_at,
            )
        )


async def _count(sf, model, *where):
    from sqlalchemy import func, select

    async with sf() as s:
        return await s.scalar(select(func.count()).select_from(model).where(*where))


async def _receipts(sf):
    from sqlalchemy import select

    from spatalk.models import DeletionReceipt

    async with sf() as s:
        rows = (await s.scalars(select(DeletionReceipt).order_by(DeletionReceipt.id))).all()
        return [(r.tenant_id, r.kind, r.count, r.cutoff, r.run_at) for r in rows]


async def _seed_the_thresholds(sf, registry):
    """One conversation on each side of every threshold, for two tenants."""
    await _second_tenant(registry)
    ids = {}
    # Skincentrix keeps transcripts 30 days.
    ids["expired"] = await _conversation(
        sf,
        "skincentrix",
        started_at=NOW - timedelta(days=40),
        ended_at=NOW - timedelta(days=40),
        messages=3,
        latency_ms=[800, 900],
        stage_ms={"stt": 120, "llm": 300, "tts": 150},
    )
    ids["fresh"] = await _conversation(
        sf,
        "skincentrix",
        started_at=NOW - timedelta(days=10),
        ended_at=NOW - timedelta(days=10),
        messages=2,
    )
    # Never ended: the customer simply stopped replying.
    ids["dangling"] = await _conversation(
        sf,
        "skincentrix",
        started_at=NOW - timedelta(days=60),
        last_message_at=NOW - timedelta(days=60),
        messages=1,
    )
    # Past the 400-day stub life: the row itself goes, with everything hanging off it.
    ids["ancient"] = await _conversation(
        sf,
        "skincentrix",
        started_at=NOW - timedelta(days=500),
        ended_at=NOW - timedelta(days=500),
        messages=1,
    )
    await _item(sf, "skincentrix", created_at=NOW - timedelta(days=500))
    await _item(sf, "skincentrix", created_at=NOW - timedelta(days=399))
    await _usage(sf, "skincentrix", created_at=NOW - timedelta(days=500))
    await _usage(sf, "skincentrix", created_at=NOW - timedelta(days=399))
    # The other tenant keeps transcripts 7 days, so its 10-day-old call is already past.
    ids["other"] = await _conversation(
        sf,
        "otherclinic",
        started_at=NOW - timedelta(days=10),
        ended_at=NOW - timedelta(days=10),
        messages=2,
    )
    await _audit(sf, created_at=NOW - timedelta(days=800))
    await _audit(sf, created_at=NOW - timedelta(days=100))
    return ids


# --- the thresholds --------------------------------------------------------------------


async def test_retention_deletes_across_the_thresholds_and_counts_match(sf, registry, fixed_clock):
    from spatalk.models import Conversation, Item, Message, UsageEvent
    from spatalk.ops.retention import run_retention

    await _seed_the_thresholds(sf, registry)
    assert await _count(sf, Message) == 9

    summary = await run_retention(_ctx(sf, registry, fixed_clock), NOW)

    # Skincentrix: 3 (expired) + 1 (dangling) + 1 (ancient) transcripts, one conversation
    # past 400 days, one item and one usage event past 400 days.
    assert summary.per_tenant["skincentrix"] == {
        "messages": 5,
        "conversations": 1,
        "items": 1,
        "usage_events": 1,
    }
    assert summary.per_tenant["otherclinic"] == {
        "messages": 2,
        "conversations": 0,
        "items": 0,
        "usage_events": 0,
    }
    # Only the two-day-old transcripts of the fresh conversation survive.
    assert await _count(sf, Message) == 2
    assert await _count(sf, Conversation) == 4
    assert await _count(sf, Item) == 1
    assert await _count(sf, UsageEvent) == 1


async def test_every_delete_leaves_a_receipt_and_a_zero_leaves_none(sf, registry, fixed_clock):
    from spatalk.ops.retention import run_retention

    await _seed_the_thresholds(sf, registry)
    await run_retention(_ctx(sf, registry, fixed_clock), NOW)

    rows = await _receipts(sf)
    assert {(t, k, c) for t, k, c, _, _ in rows} == {
        ("skincentrix", "messages", 5),
        ("skincentrix", "conversations", 1),
        ("skincentrix", "items", 1),
        ("skincentrix", "usage_events", 1),
        ("otherclinic", "messages", 2),
    }
    assert all(c > 0 for _, _, c, _, _ in rows), "a receipt for nothing is noise"
    by_kind = {(t, k): cutoff for t, k, _, cutoff, _ in rows}
    assert by_kind[("skincentrix", "messages")] == NOW - timedelta(days=30)
    assert by_kind[("otherclinic", "messages")] == NOW - timedelta(days=7)
    assert by_kind[("skincentrix", "items")] == NOW - timedelta(days=400)
    assert all(run_at == NOW for _, _, _, _, run_at in rows)


async def test_a_tenants_own_retention_days_is_honoured_independently(sf, registry, fixed_clock):
    """Both tenants have a ten-day-old call. Only the seven-day tenant loses its transcript."""
    from sqlalchemy import select

    from spatalk.models import Message
    from spatalk.ops.retention import run_retention

    ids = await _seed_the_thresholds(sf, registry)
    await run_retention(_ctx(sf, registry, fixed_clock), NOW)

    async with sf() as s:
        left = set(
            (await s.scalars(select(Message.conversation_id).distinct())).all()
        )
    assert left == {ids["fresh"]}


async def test_a_transcript_of_a_conversation_that_never_ended_still_expires(
    sf, registry, fixed_clock
):
    """An SMS thread the customer abandoned has no `ended_at`; it must not be kept forever."""
    from sqlalchemy import select

    from spatalk.models import Message
    from spatalk.ops.retention import run_retention

    cid = await _conversation(
        sf,
        "skincentrix",
        started_at=NOW - timedelta(days=60),
        last_message_at=NOW - timedelta(days=60),
        messages=4,
    )
    summary = await run_retention(_ctx(sf, registry, fixed_clock), NOW)

    assert summary.per_tenant["skincentrix"]["messages"] == 4
    async with sf() as s:
        assert (
            await s.scalars(select(Message).where(Message.conversation_id == cid))
        ).all() == []


async def test_the_audit_log_is_kept_for_two_years(sf, registry, fixed_clock):
    from spatalk.models import AuditLog
    from spatalk.ops.retention import run_retention

    await _audit(sf, created_at=NOW - timedelta(days=800))
    await _audit(sf, created_at=NOW - timedelta(days=729))

    summary = await run_retention(_ctx(sf, registry, fixed_clock), NOW)

    assert summary.audit_log == 1
    assert await _count(sf, AuditLog) == 1


# --- the stub --------------------------------------------------------------------------


async def test_the_conversation_stub_keeps_the_shape_and_drops_the_person(
    sf, registry, fixed_clock
):
    """After the transcript goes, what is left is analytics, not a record of a person."""
    from spatalk.models import Conversation
    from spatalk.ops.retention import run_retention

    cid = await _conversation(
        sf,
        "skincentrix",
        started_at=NOW - timedelta(days=40),
        ended_at=NOW - timedelta(days=40),
        channel="voice",
        band=2,
        messages=3,
        latency_ms=[800, 900],
        stage_ms={"stt": 120, "llm": 300, "tts": 150},
    )
    await run_retention(_ctx(sf, registry, fixed_clock), NOW)

    async with sf() as s:
        c = await s.get(Conversation, cid)
    assert c is not None, "the stub is kept for 400 days"
    assert c.caller is None and c.latency_ms is None and c.stage_ms is None
    assert c.channel == "voice" and c.band == 2
    assert c.started_at == NOW - timedelta(days=40)
    assert c.ended_at == NOW - timedelta(days=40)


# --- idempotence -----------------------------------------------------------------------


async def test_a_second_run_the_same_night_deletes_nothing_and_writes_no_receipts(
    sf, registry, fixed_clock
):
    from spatalk.ops.retention import run_retention

    await _seed_the_thresholds(sf, registry)
    ctx = _ctx(sf, registry, fixed_clock)
    await run_retention(ctx, NOW)
    first = await _receipts(sf)

    again = await run_retention(ctx, NOW)

    assert again.audit_log == 0
    assert all(sum(counts.values()) == 0 for counts in again.per_tenant.values())
    assert await _receipts(sf) == first


# --- the run record --------------------------------------------------------------------


async def test_every_run_records_an_ops_run_row(sf, registry, fixed_clock):
    from sqlalchemy import select

    from spatalk.models import OpsRun
    from spatalk.ops.retention import run_retention

    await _seed_the_thresholds(sf, registry)
    ctx = _ctx(sf, registry, fixed_clock)
    await run_retention(ctx, NOW)
    await run_retention(ctx, NOW)

    async with sf() as s:
        runs = (await s.scalars(select(OpsRun).order_by(OpsRun.id))).all()
    assert len(runs) == 2
    assert all(r.kind == "ops.retention" and r.ok for r in runs)
    assert all(r.finished_at is not None for r in runs)
    assert runs[0].summary["per_tenant"]["skincentrix"]["messages"] == 5
    assert runs[1].summary["per_tenant"]["skincentrix"]["messages"] == 0


async def test_a_failing_run_is_recorded_as_not_ok_and_raises(sf, registry, fixed_clock):
    from sqlalchemy import select

    from spatalk.models import OpsRun
    from spatalk.ops.retention import run_retention

    async def boom(_tenant_id):
        raise RuntimeError("registry down")

    ctx = _ctx(sf, registry, fixed_clock)
    ctx.registry.get = boom
    with pytest.raises(RuntimeError):
        await run_retention(ctx, NOW)

    async with sf() as s:
        runs = (await s.scalars(select(OpsRun))).all()
    assert len(runs) == 1 and runs[0].ok is False
    assert "registry down" in runs[0].summary["error"]


# --- scheduling ------------------------------------------------------------------------


async def test_the_nightly_job_is_queued_once_a_day_from_0300_utc(sf, registry):
    from sqlalchemy import select

    from spatalk.clock import FixedClock
    from spatalk.ledger.scheduler import ensure_nightly_retention_scheduled
    from spatalk.models import Job

    clock = FixedClock(datetime(2026, 9, 1, 2, 59, tzinfo=timezone.utc))
    ctx = _ctx(sf, registry, clock)
    assert await ensure_nightly_retention_scheduled(ctx) is False

    clock.advance(minutes=1)
    assert await ensure_nightly_retention_scheduled(ctx) is True
    clock.advance(hours=6)
    assert await ensure_nightly_retention_scheduled(ctx) is False
    clock.advance(hours=20)  # 04:59 the next day
    assert await ensure_nightly_retention_scheduled(ctx) is True

    async with sf() as s:
        queued = (await s.scalars(select(Job).where(Job.kind == "ops.retention"))).all()
    assert len(queued) == 2


async def test_the_queued_job_runs_the_retention(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.ledger.scheduler import ensure_nightly_retention_scheduled
    from spatalk.models import Message

    await _seed_the_thresholds(sf, registry)
    ctx = _ctx(sf, registry, fixed_clock)
    assert await ensure_nightly_retention_scheduled(ctx) is True

    assert await jobs.run_once(sf, ctx) == 1

    assert await _count(sf, Message) == 2
    assert len(await _receipts(sf)) == 5
