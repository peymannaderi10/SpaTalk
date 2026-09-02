"""Monthly cost reconciliation (operations plan, Task E9).

Spec §10 weakness 1 is that two of the rates the business case rests on are unverified.
The answer is not a better guess but a monthly comparison: what the metered usage says a
month should have cost, against what each provider actually billed. Drift is the finding.

Three things this suite pins hard:

* a provider with no invoice recorded reads "not entered", never zero. A zero would make an
  unentered invoice look like a free month, which is the one reading that hides a surprise.
* the per-tenant total carries the per-tenant fixed cost (the DID and toll-free rentals) as
  well as the metered usage, because the margin against the CA$999 price is only honest if
  it counts everything a tenant costs.
* the month is a UTC calendar month, the same window a provider bills on. A tenant-local
  month would sum two tenants over different windows and then compare the union to one
  invoice.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio

MONTH = "2026-08"
# Inside the month.
MID = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
# One second before it starts, and the first instant after it ends.
JUST_BEFORE = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
JUST_AFTER = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
# The first of the following month, when the report for MONTH is queued.
NOW = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)

OPS_EMAIL = "ops@example.test"


def _settings(**kw):
    from spatalk.settings import Settings

    return Settings(
        _env_file=None,
        public_base_url="https://api.test",
        secret_key="s",
        **{"ops_email": OPS_EMAIL, **kw},
    )


def _clock(at=NOW):
    from spatalk.clock import FixedClock

    return FixedClock(at)


def _ctx(sf, registry, clock, settings=None):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger

    return jobs.JobContext(
        sf=sf,
        clock=clock,
        registry=registry,
        ledger=PgLedger(sf, clock),
        delivery=MemoryDelivery(),
        settings=settings or _settings(),
    )


async def _rows(sf, model):
    from sqlalchemy import select

    async with sf() as s:
        return list((await s.scalars(select(model))).all())


async def _second_tenant(registry, tenant_id="otherclinic"):
    """A second tenant that differs from Skincentrix only in its identity."""
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


async def _usage(sf, tenant_id, channel, provider, unit, qty, at=MID):
    from spatalk.models import UsageEvent

    async with sf() as s, s.begin():
        s.add(
            UsageEvent(
                tenant_id=tenant_id,
                conversation_id=None,
                channel=channel,
                provider=provider,
                unit=unit,
                qty=qty,
                created_at=at,
            )
        )


@pytest_asyncio.fixture
async def two_tenants(sf, registry):
    await _second_tenant(registry)
    return registry


# --- the month window -------------------------------------------------------------------


def test_the_month_is_a_utc_calendar_month():
    from spatalk.ops.cost_report import month_window

    start, end = month_window("2026-08")
    assert start == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 1, tzinfo=timezone.utc)
    # December rolls the year, which an unguarded month + 1 does not.
    assert month_window("2026-12")[1] == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_a_malformed_month_is_refused():
    from spatalk.ops.cost_report import month_window

    for bad in ("2026-13", "2026", "august", "2026-8-1"):
        with pytest.raises(ValueError):
            month_window(bad)


def test_previous_month_is_what_the_first_of_the_month_reports_on():
    from spatalk.ops.cost_report import previous_month

    assert previous_month(NOW) == MONTH
    assert previous_month(datetime(2027, 1, 1, 5, 0, tzinfo=timezone.utc)) == "2026-12"


# --- totals, channels and the margin ----------------------------------------------------


async def test_totals_per_tenant_and_channel_carry_the_fixed_cost_and_the_margin(
    sf, two_tenants
):
    from spatalk.ops.cost_report import PRICE_CAD_PER_TENANT_MONTH, cost_report, per_tenant_fixed

    ctx = _ctx(sf, two_tenants, _clock())
    # Skincentrix: an hour of calls plus a hundred outbound texts.
    await _usage(sf, "skincentrix", "voice", "telnyx", "telephony_seconds", 3600)
    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 100)
    # The other clinic: texts only.
    await _usage(sf, "otherclinic", "sms", "telnyx", "sms_out", 40)

    report = await cost_report(ctx, MONTH)
    skin = report["per_tenant"]["skincentrix"]
    other = report["per_tenant"]["otherclinic"]

    assert set(skin) == {"voice", "sms", "fixed", "total"}
    assert skin["voice"] > 0 and skin["sms"] > 0
    assert skin["fixed"] == per_tenant_fixed()
    # Every channel plus the fixed cost is the tenant's month.
    assert skin["total"] == pytest.approx(
        skin["voice"] + skin["sms"] + skin["fixed"], abs=0.01
    )
    # A channel the tenant never used is absent, not a zero row.
    assert "voice" not in other
    assert other["sms"] < skin["sms"]

    price = PRICE_CAD_PER_TENANT_MONTH
    assert report["price_cad"] == price
    assert report["per_tenant_margin_pct"]["skincentrix"] == pytest.approx(
        (price - skin["total"]) / price * 100, abs=0.05
    )
    # The whole business case: a tenant costs a few dollars against a $999 price.
    assert report["per_tenant_margin_pct"]["skincentrix"] > 90


async def test_a_tenant_with_no_usage_still_appears_with_its_fixed_cost(sf, two_tenants):
    from spatalk.ops.cost_report import cost_report, per_tenant_fixed

    ctx = _ctx(sf, two_tenants, _clock())
    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 10)

    report = await cost_report(ctx, MONTH)
    # A quiet tenant is not an absent tenant: it still rents a number.
    assert report["per_tenant"]["otherclinic"] == {
        "fixed": per_tenant_fixed(),
        "total": per_tenant_fixed(),
    }


async def test_usage_outside_the_month_is_not_counted(sf, registry):
    from spatalk.ops.cost_report import cost_report, per_tenant_fixed

    ctx = _ctx(sf, registry, _clock())
    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 1000, at=JUST_BEFORE)
    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 1000, at=JUST_AFTER)

    report = await cost_report(ctx, MONTH)
    assert report["per_tenant"]["skincentrix"]["total"] == per_tenant_fixed()
    assert report["per_provider_estimate"] == {}


async def test_the_estimate_is_grouped_by_the_recorded_provider(sf, registry):
    from spatalk.ops.cost_report import cost_report

    ctx = _ctx(sf, registry, _clock())
    await _usage(sf, "skincentrix", "voice", "telnyx", "telephony_seconds", 3600)
    await _usage(sf, "skincentrix", "voice", "soniox", "stt_seconds", 3600)
    await _usage(sf, "skincentrix", "voice", "inworld", "tts_chars", 500_000)
    await _usage(sf, "skincentrix", "voice", "gemini-2.5-flash", "llm_output_tokens", 200_000)

    estimate = (await cost_report(ctx, MONTH))["per_provider_estimate"]
    assert set(estimate) == {"telnyx", "soniox", "inworld", "gemini-2.5-flash"}
    assert all(v > 0 for v in estimate.values())
    # 60 minutes of Soniox at 0.002 USD/min x 1.3896.
    assert estimate["soniox"] == pytest.approx(60 * 0.002 * 1.3896, abs=0.001)


async def test_a_unit_the_rates_table_does_not_price_costs_nothing(sf, registry):
    from spatalk.ops.cost_report import cost_report

    ctx = _ctx(sf, registry, _clock())
    # Chat and social message counts cost nothing beyond the LLM tokens they generate.
    await _usage(sf, "skincentrix", "chat", "internal", "chat_in", 500)

    report = await cost_report(ctx, MONTH)
    assert report["per_provider_estimate"]["internal"] == 0.0
    assert report["per_tenant"]["skincentrix"]["chat"] == 0.0


# --- invoices and drift -----------------------------------------------------------------


async def test_add_invoice_records_what_a_provider_billed(sf, registry):
    from spatalk.models import ProviderInvoice
    from spatalk.ops.cost_report import add_invoice, recorded_invoices

    ctx = _ctx(sf, registry, _clock())
    await add_invoice(ctx.sf, "telnyx", MONTH, 41.5, now=ctx.clock.now())

    rows = await _rows(sf, ProviderInvoice)
    assert len(rows) == 1
    assert (rows[0].provider, rows[0].month, float(rows[0].amount_cad)) == (
        "telnyx",
        MONTH,
        41.5,
    )
    assert await recorded_invoices(sf, MONTH) == {"telnyx": 41.5}


async def test_a_second_entry_for_the_same_provider_and_month_corrects_the_first(sf, registry):
    from spatalk.models import ProviderInvoice
    from spatalk.ops.cost_report import add_invoice, recorded_invoices

    ctx = _ctx(sf, registry, _clock())
    await add_invoice(ctx.sf, "telnyx", MONTH, 41.5, now=ctx.clock.now())
    await add_invoice(ctx.sf, "telnyx", MONTH, 44.0, now=ctx.clock.now())

    assert len(await _rows(sf, ProviderInvoice)) == 1
    assert await recorded_invoices(sf, MONTH) == {"telnyx": 44.0}


async def test_drift_is_the_invoice_against_the_estimate(sf, registry):
    from spatalk.ops.cost_report import add_invoice, cost_report

    ctx = _ctx(sf, registry, _clock())
    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 1000)
    estimate = (await cost_report(ctx, MONTH))["per_provider_estimate"]["telnyx"]

    # The provider billed a quarter more than the rates table predicted.
    await add_invoice(ctx.sf, "telnyx", MONTH, round(estimate * 1.25, 2), now=ctx.clock.now())
    report = await cost_report(ctx, MONTH)

    assert report["invoices"]["telnyx"] == pytest.approx(estimate * 1.25, abs=0.02)
    assert report["drift_pct"]["telnyx"] == pytest.approx(25.0, abs=0.5)


async def test_a_missing_invoice_reads_not_entered_rather_than_zero(sf, registry):
    from spatalk.ops.cost_report import cost_report, report_email

    ctx = _ctx(sf, registry, _clock())
    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 100)

    report = await cost_report(ctx, MONTH)
    # None, not 0.0: an unentered invoice must never read as a free month.
    assert report["invoices"]["telnyx"] is None
    assert report["drift_pct"]["telnyx"] is None

    _subject, body = report_email(report)
    assert "not entered" in body
    assert "telnyx" in body


async def test_an_invoice_from_a_provider_with_no_usage_still_shows(sf, registry):
    from spatalk.ops.cost_report import add_invoice, cost_report

    ctx = _ctx(sf, registry, _clock())
    await add_invoice(ctx.sf, "sentry", MONTH, 12.0, now=ctx.clock.now())

    report = await cost_report(ctx, MONTH)
    assert report["invoices"]["sentry"] == 12.0
    assert report["per_provider_estimate"]["sentry"] == 0.0
    # Nothing was estimated, so a percentage would be a division by zero, not a finding.
    assert report["drift_pct"]["sentry"] is None


async def test_an_invoice_for_another_month_is_not_read(sf, registry):
    from spatalk.ops.cost_report import add_invoice, cost_report

    ctx = _ctx(sf, registry, _clock())
    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 100)
    await add_invoice(ctx.sf, "telnyx", "2026-07", 999.0, now=ctx.clock.now())

    report = await cost_report(ctx, MONTH)
    assert report["invoices"]["telnyx"] is None


# --- the email --------------------------------------------------------------------------


async def test_the_email_names_the_top_drift_and_the_margin(sf, two_tenants):
    from spatalk.ops.cost_report import add_invoice, cost_report, report_email

    ctx = _ctx(sf, two_tenants, _clock())
    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 1000)
    await _usage(sf, "skincentrix", "voice", "soniox", "stt_seconds", 36000)
    telnyx = (await cost_report(ctx, MONTH))["per_provider_estimate"]["telnyx"]
    soniox = (await cost_report(ctx, MONTH))["per_provider_estimate"]["soniox"]
    await add_invoice(ctx.sf, "telnyx", MONTH, round(telnyx * 1.05, 2), now=ctx.clock.now())
    await add_invoice(ctx.sf, "soniox", MONTH, round(soniox * 2.0, 2), now=ctx.clock.now())

    report = await cost_report(ctx, MONTH)
    subject, body = report_email(report)

    assert MONTH in subject
    # The worst drift leads, so the finding is the first thing read.
    assert body.index("soniox") < body.index("telnyx")
    assert "skincentrix" in body and "otherclinic" in body
    assert "999" in body and "margin" in body.lower()


# --- the run ----------------------------------------------------------------------------


async def test_the_run_stores_ops_runs_and_emails_the_report(sf, registry):
    from spatalk.models import OpsRun
    from spatalk.ops.cost_report import RUN_KIND, run_cost_report

    ctx = _ctx(sf, registry, _clock())
    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 100)

    report = await run_cost_report(ctx, MONTH)
    assert report["month"] == MONTH

    runs = await _rows(sf, OpsRun)
    assert len(runs) == 1
    assert runs[0].kind == RUN_KIND
    assert runs[0].ok is True
    assert runs[0].finished_at is not None
    assert runs[0].summary["month"] == MONTH

    assert len(ctx.delivery.emails) == 1
    to, subject, _body = ctx.delivery.emails[0]
    assert to == OPS_EMAIL and MONTH in subject


async def test_a_run_without_an_ops_email_still_records_the_month(sf, registry):
    from spatalk.models import OpsRun
    from spatalk.ops.cost_report import run_cost_report

    ctx = _ctx(sf, registry, _clock(), settings=_settings(ops_email=""))
    await run_cost_report(ctx, MONTH)

    assert ctx.delivery.emails == []
    runs = await _rows(sf, OpsRun)
    assert len(runs) == 1 and runs[0].ok is True


async def test_a_failing_run_is_recorded_as_not_ok_and_raises(sf, registry):
    from spatalk.models import OpsRun
    from spatalk.ops.cost_report import run_cost_report

    ctx = _ctx(sf, registry, _clock())

    async def boom(*_a, **_k):
        raise RuntimeError("database down")

    ctx.delivery.send_email = boom
    with pytest.raises(RuntimeError):
        await run_cost_report(ctx, MONTH)

    runs = await _rows(sf, OpsRun)
    assert len(runs) == 1 and runs[0].ok is False
    assert "database down" in runs[0].summary["error"]


# --- scheduling -------------------------------------------------------------------------


async def test_the_cost_report_is_queued_once_on_the_first_of_the_month(sf, registry):
    from spatalk.ledger.scheduler import ensure_monthly_cost_report_scheduled
    from spatalk.models import Job
    from spatalk.ops.cost_report import RUN_KIND

    clock = _clock(datetime(2026, 9, 1, 4, 59, tzinfo=timezone.utc))
    ctx = _ctx(sf, registry, clock)
    assert await ensure_monthly_cost_report_scheduled(ctx) is False

    clock.advance(minutes=1)
    assert await ensure_monthly_cost_report_scheduled(ctx) is True
    # Same day, and every day of the month after it: already done.
    clock.advance(hours=6)
    assert await ensure_monthly_cost_report_scheduled(ctx) is False
    clock.advance(days=10)
    assert await ensure_monthly_cost_report_scheduled(ctx) is False
    # The first of October.
    clock.advance(days=20)
    assert await ensure_monthly_cost_report_scheduled(ctx) is True

    queued = [j for j in await _rows(sf, Job) if j.kind == RUN_KIND]
    assert len(queued) == 2
    assert queued[0].payload["month"] == MONTH


async def test_the_queued_job_reports_the_previous_month(sf, registry):
    from spatalk import jobs
    from spatalk.ledger.scheduler import ensure_monthly_cost_report_scheduled
    from spatalk.models import OpsRun

    await _usage(sf, "skincentrix", "sms", "telnyx", "sms_out", 5)
    ctx = _ctx(sf, registry, _clock())

    assert await ensure_monthly_cost_report_scheduled(ctx) is True
    assert await jobs.run_once(sf, ctx) == 1

    runs = await _rows(sf, OpsRun)
    assert [r.summary["month"] for r in runs] == [MONTH]


# --- the operator commands --------------------------------------------------------------


def test_cli_invoices_add_records_the_amount(monkeypatch):
    from typer.testing import CliRunner

    from spatalk import cli
    from spatalk.ops import cost_report as module

    recorded: list[tuple] = []

    async def _add(sf, provider, month, amount_cad, now=None):
        recorded.append((provider, month, amount_cad))

    class _Ctx:
        sf = None
        clock = _clock()

    monkeypatch.setattr(cli, "_ctx", lambda: _Ctx())
    monkeypatch.setattr(module, "add_invoice", _add)

    result = CliRunner().invoke(cli.app, ["invoices", "add", "telnyx", MONTH, "41.50"])
    assert result.exit_code == 0, result.output
    assert recorded == [("telnyx", MONTH, 41.5)]
    assert "telnyx" in result.output and MONTH in result.output


def test_cli_cost_report_prints_the_drift_and_the_missing_invoice(monkeypatch):
    from typer.testing import CliRunner

    from spatalk import cli
    from spatalk.ops import cost_report as module

    canned = {
        "month": MONTH,
        "price_cad": 999.0,
        "per_tenant": {"skincentrix": {"sms": 1.5, "fixed": 4.5, "total": 6.0}},
        "per_tenant_margin_pct": {"skincentrix": 99.4},
        "per_provider_estimate": {"telnyx": 1.5, "soniox": 2.0},
        "invoices": {"telnyx": 1.8, "soniox": None},
        "drift_pct": {"telnyx": 20.0, "soniox": None},
    }

    async def _report(ctx, month, **kw):
        assert month == MONTH
        return canned

    class _Ctx:
        sf = None
        clock = _clock()

    monkeypatch.setattr(cli, "_ctx", lambda: _Ctx())
    monkeypatch.setattr(module, "cost_report", _report)

    result = CliRunner().invoke(cli.app, ["cost", "report", MONTH])
    assert result.exit_code == 0, result.output
    assert "telnyx" in result.output and "20.0" in result.output
    assert "not entered" in result.output
    assert "skincentrix" in result.output and "99.4" in result.output
