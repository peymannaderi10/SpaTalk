"""Nightly escalation audit (operations plan, Task E4).

Spec §10 weakness 5 is that a deterministic gate cannot see every band-3 intent: a caller
who describes a burn without using a lexicon word slips past it. The answer is not a better
regex but a second look, offline, at everything the day produced — a lexicon scan for terms
the gate should have caught, a stronger model re-judging the band of every transcript, and
the health-context counts that say how often people volunteer a condition.

Three things this suite pins hard:

* the judge is an ``LLMClient``, so every test drives it with ``FakeLLM`` and no test in
  this repository ever reaches Google;
* a judged band 3 that was handled as band 1 or 2 is *blocking*: it raises an alert as well
  as appearing in the report, because it is the failure that ends the business;
* a day with nothing in it still produces a report and still records its run. A nightly job
  that silently stopped looks exactly like one that found nothing, unless it says so.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# 2026-09-01 in America/Toronto (EDT, UTC-4) is 2026-09-01 04:00 UTC to 2026-09-02 04:00 UTC.
DAY = date(2026, 9, 1)
# The 04:00 UTC run that audits the day above.
NOW = datetime(2026, 9, 2, 4, 0, tzinfo=timezone.utc)
# Inside the tenant's local day: 14:00 in Toronto.
MIDDAY = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
# 22:00 in Toronto on the same local day, though the UTC date has already rolled over.
LATE = datetime(2026, 9, 2, 2, 0, tzinfo=timezone.utc)
# 23:00 in Toronto on the day *before*: outside the window.
TOO_EARLY = datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc)

OPS_EMAIL = "ops@example.test"
INTERNAL_KEY = "test-internal-key"


def _settings(**kw):
    from spatalk.settings import Settings

    return Settings(
        _env_file=None,
        public_base_url="https://api.test",
        secret_key="s",
        ops_email=OPS_EMAIL,
        internal_api_key=INTERNAL_KEY,
        **kw,
    )


def _ctx(sf, registry, clock, settings=None):
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger

    return jobs.JobContext(
        sf=sf,
        clock=clock,
        registry=registry,
        ledger=PgLedger(sf, clock),
        delivery=MemoryDelivery(),
        settings=settings or _settings(),
        sms=MemorySms(),
    )


def _clock(at=NOW):
    from spatalk.clock import FixedClock

    return FixedClock(at)


def _judge(*payloads: str):
    """A FakeLLM that answers the judge prompt with the given JSON bodies, in order."""
    from spatalk.brain.driver import FakeLLM, LLMResponse

    return FakeLLM([LLMResponse(text=p, tool_calls=[]) for p in payloads])


def _verdict(band: int, reason: str = "because") -> str:
    import json

    return json.dumps({"band": band, "reason": reason})


async def _second_tenant(registry, tenant_id="otherclinic"):
    cfg = await registry.get("skincentrix")
    other = cfg.model_copy(
        update={
            "id": tenant_id,
            "name": "Other Clinic",
            "voice_numbers": [],
            "sms_from_number": None,
        }
    )
    await registry.import_config(other, created_by="test")
    return other


async def _conversation(
    sf,
    tenant_id="skincentrix",
    *,
    started_at=MIDDAY,
    band=1,
    controller="ai",
    health_context=False,
    channel="voice",
    turns=(),
):
    """One conversation with its transcript. `turns` is a list of (role, text)."""
    from spatalk.models import Conversation, Message

    async with sf() as s, s.begin():
        c = Conversation(
            tenant_id=tenant_id,
            channel=channel,
            external_ref="ref",
            caller="+19055550101",
            controller=controller,
            health_context=health_context,
            band=band,
            started_at=started_at,
        )
        s.add(c)
        await s.flush()
        for role, text in turns:
            s.add(Message(conversation_id=c.id, role=role, text=text, created_at=started_at))
        return c.id


async def _item(sf, tenant_id="skincentrix", *, created_at=MIDDAY, health_context=False):
    from spatalk.models import Item

    async with sf() as s, s.begin():
        it = Item(
            tenant_id=tenant_id,
            type="callback",
            urgency="normal",
            preferred_window={},
            channel="voice",
            health_context=health_context,
            state="open",
            due_at=created_at,
            owner="owner@example.test",
            created_at=created_at,
        )
        s.add(it)
        await s.flush()
        return it.id


async def _rows(sf, model, order=None):
    from sqlalchemy import select

    async with sf() as s:
        stmt = select(model)
        if order is not None:
            stmt = stmt.order_by(order)
        return list((await s.scalars(stmt)).all())


# --- the lexicon scan -------------------------------------------------------------------


async def test_a_clinical_term_handled_as_band_1_is_flagged_and_a_band_3_one_is_not(
    sf, registry
):
    from spatalk.ops.nightly_audit import lexicon_scan

    missed = await _conversation(
        sf, band=1, turns=[("user", "I have a rash after my treatment"), ("assistant", "ok")]
    )
    await _conversation(
        sf, band=3, turns=[("user", "I have a rash after my treatment"), ("assistant", "ok")]
    )

    found = await lexicon_scan(_ctx(sf, registry, _clock()), DAY)

    assert found["count"] == 1
    assert found["conversations_with_clinical_terms_not_band3"] == [str(missed)]


async def test_the_scan_reads_the_tenants_own_clinical_additions(sf, registry):
    """`guard.yaml` adds "after my peel"; a tenant's lexicon is part of the scan."""
    from spatalk.ops.nightly_audit import lexicon_scan

    missed = await _conversation(sf, band=2, turns=[("user", "itchy after my peel yesterday")])

    found = await lexicon_scan(_ctx(sf, registry, _clock()), DAY)

    assert found["conversations_with_clinical_terms_not_band3"] == [str(missed)]


async def test_the_scan_covers_the_tenants_local_day_not_the_utc_one(sf, registry):
    from spatalk.ops.nightly_audit import lexicon_scan

    late = await _conversation(sf, started_at=LATE, band=1, turns=[("user", "my skin is burning")])
    await _conversation(sf, started_at=TOO_EARLY, band=1, turns=[("user", "my skin is burning")])

    found = await lexicon_scan(_ctx(sf, registry, _clock()), DAY)

    assert found["conversations_with_clinical_terms_not_band3"] == [str(late)]


async def test_a_transcript_without_a_clinical_term_is_not_flagged(sf, registry):
    from spatalk.ops.nightly_audit import lexicon_scan

    await _conversation(sf, band=1, turns=[("user", "how much is a facial?")])

    found = await lexicon_scan(_ctx(sf, registry, _clock()), DAY)

    assert found == {"conversations_with_clinical_terms_not_band3": [], "count": 0}


async def test_the_scan_is_scoped_to_one_tenant_when_asked(sf, registry):
    from spatalk.ops.nightly_audit import lexicon_scan

    await _second_tenant(registry)
    mine = await _conversation(sf, "skincentrix", band=1, turns=[("user", "a rash")])
    theirs = await _conversation(sf, "otherclinic", band=1, turns=[("user", "a rash")])
    ctx = _ctx(sf, registry, _clock())

    assert (await lexicon_scan(ctx, DAY, "skincentrix"))[
        "conversations_with_clinical_terms_not_band3"
    ] == [str(mine)]
    assert (await lexicon_scan(ctx, DAY, "otherclinic"))[
        "conversations_with_clinical_terms_not_band3"
    ] == [str(theirs)]
    assert (await lexicon_scan(ctx, DAY))["count"] == 2


# --- the band audit ---------------------------------------------------------------------


async def test_the_judge_reviews_every_transcript_and_disagreements_are_returned(sf, registry):
    from spatalk.ops.nightly_audit import band_audit

    handled = await _conversation(sf, band=1, turns=[("user", "what are your hours?")])
    missed = await _conversation(
        sf, started_at=LATE, band=1, turns=[("user", "my face is peeling badly since friday")]
    )
    judge = _judge(_verdict(1, "hours question"), _verdict(3, "a reaction needs a person"))

    result = await band_audit(_ctx(sf, registry, _clock()), DAY, judge)

    assert result["reviewed"] == 2
    assert result["disagreements"] == [
        {
            "conversation_id": str(missed),
            "actual_band": 1,
            "judged_band": 3,
            "reason": "a reaction needs a person",
        }
    ]
    assert str(handled) not in str(result["disagreements"])


async def test_the_judge_prompt_carries_the_transcript_and_the_three_band_definitions(
    sf, registry
):
    from spatalk.ops.nightly_audit import BAND_DEFINITIONS, band_audit

    await _conversation(
        sf,
        band=1,
        turns=[("user", "do you do microneedling?"), ("assistant", "we do, here is the link")],
    )
    judge = _judge(_verdict(1))

    await band_audit(_ctx(sf, registry, _clock()), DAY, judge)

    system, history = judge.calls[0]
    for band, definition in BAND_DEFINITIONS.items():
        assert definition in system, f"band {band}'s definition is not in the judge prompt"
    transcript = history[-1]["content"]
    assert "do you do microneedling?" in transcript
    assert "we do, here is the link" in transcript


async def test_a_conversation_a_human_took_over_is_not_judged(sf, registry):
    from spatalk.ops.nightly_audit import band_audit

    await _conversation(sf, band=1, controller="human", turns=[("user", "my face is burning")])
    judge = _judge(_verdict(3))

    result = await band_audit(_ctx(sf, registry, _clock()), DAY, judge)

    assert result["reviewed"] == 0
    assert result["disagreements"] == []
    assert judge.calls == []


async def test_a_conversation_with_no_transcript_is_not_sent_to_the_judge(sf, registry):
    from spatalk.ops.nightly_audit import band_audit

    await _conversation(sf, band=1, turns=[])
    judge = _judge(_verdict(3))

    result = await band_audit(_ctx(sf, registry, _clock()), DAY, judge)

    assert result["reviewed"] == 0
    assert judge.calls == []


async def test_an_unreadable_judge_answer_is_counted_as_an_error_not_a_disagreement(
    sf, registry
):
    from spatalk.ops.nightly_audit import band_audit

    await _conversation(sf, band=1, turns=[("user", "hello")])
    judge = _judge("I think this one is fine, honestly")

    result = await band_audit(_ctx(sf, registry, _clock()), DAY, judge)

    assert result["disagreements"] == []
    assert result["errors"] == 1


async def test_a_judge_answer_wrapped_in_a_code_fence_is_still_read(sf, registry):
    from spatalk.ops.nightly_audit import band_audit

    missed = await _conversation(sf, band=2, turns=[("user", "hello")])
    judge = _judge('```json\n{"band": 3, "reason": "complaint"}\n```')

    result = await band_audit(_ctx(sf, registry, _clock()), DAY, judge)

    assert result["errors"] == 0
    assert result["disagreements"][0]["conversation_id"] == str(missed)


# --- health context ---------------------------------------------------------------------


async def test_health_context_stats_count_the_days_conversations_and_items(sf, registry):
    from spatalk.ops.nightly_audit import health_context_stats

    await _conversation(sf, health_context=True, turns=[("user", "I am pregnant")])
    await _conversation(sf, health_context=False, turns=[("user", "what are your hours?")])
    await _conversation(sf, started_at=TOO_EARLY, health_context=True, turns=[("user", "x")])
    await _item(sf, health_context=True)
    await _item(sf, health_context=False)
    await _item(sf, created_at=TOO_EARLY, health_context=True)

    stats = await health_context_stats(_ctx(sf, registry, _clock()), DAY)

    assert stats == {"conversations": 2, "flagged": 1, "items_flagged": 1}


# --- the whole run ----------------------------------------------------------------------


async def test_a_blocking_finding_is_recorded_and_raises_an_alert(sf, registry):
    from spatalk.models import AlertLog
    from spatalk.ops.nightly_audit import run_nightly_audit

    missed = await _conversation(sf, band=1, turns=[("user", "my face is burning")])
    ctx = _ctx(sf, registry, _clock())

    report = await run_nightly_audit(ctx, DAY, _judge(_verdict(3, "a reaction")))

    tenant = next(t for t in report.tenants if t.tenant_id == "skincentrix")
    assert tenant.blocking == [
        {
            "conversation_id": str(missed),
            "actual_band": 1,
            "judged_band": 3,
            "reason": "a reaction",
        }
    ]
    alerts = await _rows(sf, AlertLog)
    assert len(alerts) == 1
    assert alerts[0].key == f"audit_blocking:skincentrix:{DAY.isoformat()}"
    assert "skincentrix" in alerts[0].subject


async def test_a_disagreement_that_is_not_an_under_escalation_does_not_alert(sf, registry):
    from spatalk.models import AlertLog
    from spatalk.ops.nightly_audit import run_nightly_audit

    await _conversation(sf, band=3, turns=[("user", "what are your hours?")])
    ctx = _ctx(sf, registry, _clock())

    report = await run_nightly_audit(ctx, DAY, _judge(_verdict(1, "just an hours question")))

    tenant = next(t for t in report.tenants if t.tenant_id == "skincentrix")
    assert tenant.bands["disagreements"]
    assert tenant.blocking == []
    assert await _rows(sf, AlertLog) == []


async def test_the_report_is_persisted_per_tenant_and_emailed_to_ops(sf, registry):
    from spatalk.models import AuditReport as AuditReportRow
    from spatalk.ops.nightly_audit import run_nightly_audit

    await _second_tenant(registry)
    await _conversation(sf, "skincentrix", band=1, turns=[("user", "my face is burning")])
    await _conversation(sf, "otherclinic", band=1, turns=[("user", "what are your hours?")])
    ctx = _ctx(sf, registry, _clock())

    # Tenants are audited in id order, so "otherclinic" takes the first verdict.
    await run_nightly_audit(ctx, DAY, _judge(_verdict(1, "fine"), _verdict(3, "a reaction")))

    rows = await _rows(sf, AuditReportRow, AuditReportRow.tenant_id)
    assert [r.tenant_id for r in rows] == ["otherclinic", "skincentrix"]
    assert all(r.day == DAY for r in rows)
    stored = {r.tenant_id: r.report for r in rows}
    assert stored["skincentrix"]["bands"]["reviewed"] == 1
    assert stored["skincentrix"]["blocking"][0]["judged_band"] == 3
    assert stored["otherclinic"]["blocking"] == []

    # Two emails: the blocking alert for skincentrix, and the night's report.
    reports = [e for e in ctx.delivery.emails if e[1].startswith("SpaTalk nightly audit")]
    assert len(reports) == 1
    to, subject, body = reports[0]
    assert to == OPS_EMAIL
    assert DAY.isoformat() in subject
    assert "skincentrix" in body and "otherclinic" in body
    assert "1 blocking" in subject and "blocking: 1" in body


async def test_a_day_with_no_conversations_produces_a_zero_report_and_no_alert(sf, registry):
    from spatalk.models import AlertLog, AuditReport as AuditReportRow
    from spatalk.ops.nightly_audit import run_nightly_audit

    ctx = _ctx(sf, registry, _clock())

    report = await run_nightly_audit(ctx, DAY, _judge())

    tenant = next(t for t in report.tenants if t.tenant_id == "skincentrix")
    assert tenant.lexicon == {"conversations_with_clinical_terms_not_band3": [], "count": 0}
    assert tenant.bands["reviewed"] == 0
    assert tenant.health_context == {"conversations": 0, "flagged": 0, "items_flagged": 0}
    assert tenant.blocking == []
    assert await _rows(sf, AlertLog) == []
    assert len(await _rows(sf, AuditReportRow)) == 1
    # The nightly proof of life still goes out: a silent job is indistinguishable from a
    # dead one otherwise.
    assert len(ctx.delivery.emails) == 1


async def test_a_second_run_for_the_same_day_replaces_the_row_and_does_not_alert_twice(
    sf, registry
):
    from spatalk.models import AlertLog
    from spatalk.models import AuditReport as AuditReportRow
    from spatalk.ops.nightly_audit import run_nightly_audit

    await _conversation(sf, band=1, turns=[("user", "my face is burning")])
    ctx = _ctx(sf, registry, _clock())

    await run_nightly_audit(ctx, DAY, _judge(_verdict(3, "a reaction")))
    await run_nightly_audit(ctx, DAY, _judge(_verdict(3, "a reaction")))

    rows = await _rows(sf, AuditReportRow)
    assert len(rows) == 1
    assert rows[0].report["bands"]["reviewed"] == 1
    # `alerts.notify` deduplicates on the key for six hours.
    assert len(await _rows(sf, AlertLog)) == 1


async def test_every_run_is_recorded_in_ops_runs(sf, registry):
    from spatalk.models import OpsRun
    from spatalk.ops.nightly_audit import RUN_KIND, run_nightly_audit

    ctx = _ctx(sf, registry, _clock())
    await run_nightly_audit(ctx, DAY, _judge())

    runs = await _rows(sf, OpsRun)
    assert len(runs) == 1
    assert runs[0].kind == RUN_KIND
    assert runs[0].ok is True
    assert runs[0].finished_at is not None
    assert runs[0].summary["day"] == DAY.isoformat()


async def test_a_failing_run_is_recorded_as_not_ok_and_raises(sf, registry):
    from spatalk.models import OpsRun
    from spatalk.ops.nightly_audit import run_nightly_audit

    async def boom(_tenant_id):
        raise RuntimeError("registry down")

    ctx = _ctx(sf, registry, _clock())
    ctx.registry.get = boom
    with pytest.raises(RuntimeError):
        await run_nightly_audit(ctx, DAY, _judge())

    runs = await _rows(sf, OpsRun)
    assert len(runs) == 1 and runs[0].ok is False
    assert "registry down" in runs[0].summary["error"]


# --- the judge client -------------------------------------------------------------------


async def test_the_judge_is_flash_with_thinking_enabled_and_is_none_without_a_key():
    from spatalk.ops.nightly_audit import JUDGE_THINKING_BUDGET, make_judge

    assert make_judge(_settings()) is None

    judge = make_judge(_settings(google_api_key="k"))
    assert judge is not None
    assert judge._model == "gemini-3.5-flash-lite"
    # Unlike the conversational client, which sets 0 for latency: a band judgement is an
    # offline call where reasoning time is free.
    assert JUDGE_THINKING_BUDGET == -1
    assert judge._thinking_budget == JUDGE_THINKING_BUDGET


async def test_the_judge_model_comes_from_settings():
    from spatalk.ops.nightly_audit import make_judge

    judge = make_judge(_settings(google_api_key="k", judge_model="gemini-2.5-flash-lite"))
    assert judge._model == "gemini-2.5-flash-lite"


# --- scheduling -------------------------------------------------------------------------


async def test_the_nightly_audit_is_queued_once_a_day_from_0400_utc(sf, registry):
    from spatalk.ledger.scheduler import ensure_nightly_audit_scheduled
    from spatalk.models import Job
    from spatalk.ops.nightly_audit import RUN_KIND

    clock = _clock(datetime(2026, 9, 2, 3, 59, tzinfo=timezone.utc))
    ctx = _ctx(sf, registry, clock)
    assert await ensure_nightly_audit_scheduled(ctx) is False

    clock.advance(minutes=1)
    assert await ensure_nightly_audit_scheduled(ctx) is True
    clock.advance(hours=6)
    assert await ensure_nightly_audit_scheduled(ctx) is False
    clock.advance(hours=20)
    assert await ensure_nightly_audit_scheduled(ctx) is True

    queued = [j for j in await _rows(sf, Job) if j.kind == RUN_KIND]
    assert len(queued) == 2


async def test_the_queued_job_audits_the_previous_day(sf, registry, monkeypatch):
    from spatalk import jobs
    from spatalk.ledger.scheduler import ensure_nightly_audit_scheduled
    from spatalk.models import AuditReport as AuditReportRow
    from spatalk.ops import nightly_audit

    await _conversation(sf, band=1, turns=[("user", "my face is burning")])
    ctx = _ctx(sf, registry, _clock())
    monkeypatch.setattr(nightly_audit, "make_judge", lambda _s: _judge(_verdict(3, "a reaction")))

    assert await ensure_nightly_audit_scheduled(ctx) is True
    assert await jobs.run_once(sf, ctx) == 1

    rows = await _rows(sf, AuditReportRow)
    assert [r.day for r in rows] == [DAY]
    assert rows[0].report["blocking"]


async def test_the_run_survives_a_missing_judge(sf, registry, monkeypatch):
    """No GOOGLE_API_KEY: the lexicon scan and the counts still run and still report."""
    from spatalk.models import AuditReport as AuditReportRow
    from spatalk.ops import nightly_audit

    await _conversation(sf, band=1, turns=[("user", "my face is burning")])
    ctx = _ctx(sf, registry, _clock())
    monkeypatch.setattr(nightly_audit, "make_judge", lambda _s: None)

    report = await nightly_audit.run_nightly_audit(ctx, DAY)

    tenant = next(t for t in report.tenants if t.tenant_id == "skincentrix")
    assert tenant.lexicon["count"] == 1
    assert tenant.bands == {"reviewed": 0, "disagreements": [], "errors": 0, "skipped": True}
    rows = await _rows(sf, AuditReportRow)
    assert rows[0].report["bands"]["skipped"] is True


# --- what the portal reads --------------------------------------------------------------


@pytest_asyncio.fixture
async def client(sf, registry):
    from spatalk.http.app import create_app

    ctx = _ctx(sf, registry, _clock())
    app = create_app(ctx, start_background=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": "owner@example.test"},
    ) as c:
        c.ctx = ctx
        yield c


async def test_the_portal_reads_the_latest_report_for_a_tenant(client, sf, registry):
    from spatalk.ops.nightly_audit import run_nightly_audit

    await _conversation(sf, band=1, turns=[("user", "my face is burning")])
    await run_nightly_audit(client.ctx, DAY, _judge(_verdict(3, "a reaction")))

    r = await client.get("/internal/tenants/skincentrix/audit/latest")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["day"] == DAY.isoformat()
    assert body["report"]["blocking"][0]["judged_band"] == 3
    assert body["created_at"] is not None


async def test_a_tenant_with_no_audit_yet_reads_an_empty_latest(client):
    r = await client.get("/internal/tenants/skincentrix/audit/latest")

    assert r.status_code == 200, r.text
    assert r.json() == {"day": None, "created_at": None, "report": None}


async def test_the_latest_audit_needs_the_internal_key(client):
    r = await client.get(
        "/internal/tenants/skincentrix/audit/latest", headers={"X-Internal-Key": "wrong"}
    )

    assert r.status_code == 401
