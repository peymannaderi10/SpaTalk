"""Monthly cost reconciliation (operations plan, Task E9).

Spec §10 weakness 1 is that the business case rests on published prices, two of which the
research could not verify: a Canadian SMS carrier pass-through and a Canadian DID inbound
rate. A cost model that is never checked against an invoice is a spreadsheet, not a fact.

So once a month this job puts the two side by side. `spatalk.rates.estimate_cad` prices the
month's metered usage per unit; `provider_invoices` holds what each provider actually
billed; drift is the difference as a percentage, and it is the finding. The per-tenant half
of the same report is the other question the brief asks: what does one clinic cost against
the CA$999 price, and is the gross margin still where §6 said it was.

Three decisions worth stating, because each one has an obvious wrong alternative:

* **The month is a UTC calendar month.** Everything else in this runtime uses tenant time
  (CLAUDE.md non-negotiable 8), and that is right for anything a customer or a clinic
  experiences. An invoice is neither: it is cut on the provider's calendar, and a
  tenant-local month would sum two tenants over two different windows and then compare the
  union against one invoice.
* **A provider with no invoice recorded is `None`, never `0.0`.** Zero would read as a free
  month, which is the single reading that hides a surprise. The email says "not entered".
* **The per-tenant total includes the per-tenant fixed cost** (the DID and toll-free
  rentals, `per_tenant_fixed_cad` in the rates table). A margin that counts only metered
  usage flatters itself.

The estimate prices every unit with the *recommended* stack in the rates table, which is
what `estimate_cad` does and what the portal already shows. Provider attribution comes from
the usage row itself, so a runtime configured onto a non-recommended provider produces an
estimate priced at the recommended provider's rate — and the drift against that provider's
invoice is exactly how that shows up. That is the check working, not a bug in it.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk import jobs, rates
from spatalk.models import OpsRun, ProviderInvoice, Tenant, UsageEvent

# The job kind the scheduler queues, and the `ops_runs.kind` this job writes.
RUN_KIND = "ops.cost_report"

# The list price one tenant pays per month, in Canadian dollars (spec §6: "gross margin at
# $999 is 92 percent at tenant one"). It lives here rather than in the tenant config because
# it is the number the business case was written against; a tenant on a different contract
# is a portal concern, and the reconciliation would then read its price from the portal.
PRICE_CAD_PER_TENANT_MONTH = 999.0

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


# --- the window -------------------------------------------------------------------------


def month_window(month: str) -> tuple[datetime, datetime]:
    """`YYYY-MM` as a half-open UTC interval. Raises ValueError on anything else."""
    m = _MONTH.match(month or "")
    if not m:
        raise ValueError(f"month must be YYYY-MM, got {month!r}")
    year, mon = int(m.group(1)), int(m.group(2))
    start = datetime(year, mon, 1, tzinfo=timezone.utc)
    end = (
        datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        if mon == 12
        else datetime(year, mon + 1, 1, tzinfo=timezone.utc)
    )
    return start, end


def previous_month(at: datetime) -> str:
    """The month that has just ended, which is the one the first of the month reports on."""
    first = at.astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return (first - timedelta(days=1)).strftime("%Y-%m")


def per_tenant_fixed() -> float:
    """The per-tenant fixed monthly cost from the rates table: DID, toll-free, SMS add-on."""
    return float(rates.load_rates().get("per_tenant_fixed_cad", 0.0))


# --- invoices ---------------------------------------------------------------------------


async def add_invoice(
    sf: async_sessionmaker,
    provider: str,
    month: str,
    amount_cad: float,
    now: datetime | None = None,
) -> None:
    """Record what one provider billed for one month. A second entry corrects the first."""
    month_window(month)  # refuse a malformed month before it reaches the table
    values = {"provider": provider, "month": month, "amount_cad": round(float(amount_cad), 2)}
    if now is not None:
        values["entered_at"] = now
    async with sf() as s, s.begin():
        stmt = pg_insert(ProviderInvoice).values(**values)
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=[ProviderInvoice.provider, ProviderInvoice.month],
                set_={
                    "amount_cad": stmt.excluded.amount_cad,
                    "entered_at": stmt.excluded.entered_at,
                },
            )
        )


async def recorded_invoices(sf: async_sessionmaker, month: str) -> dict[str, float]:
    """`{provider: cad}` for that month, only for the providers actually entered."""
    async with sf() as s:
        rows = (
            await s.execute(
                select(ProviderInvoice.provider, ProviderInvoice.amount_cad).where(
                    ProviderInvoice.month == month
                )
            )
        ).all()
    return {provider: float(amount) for provider, amount in rows}


# --- the estimate -----------------------------------------------------------------------


async def _metered(ctx, month: str) -> list[tuple[str, str, str, str, float]]:
    """`(tenant_id, channel, provider, unit, qty)` summed over the month."""
    start, end = month_window(month)
    async with ctx.sf() as s:
        rows = (
            await s.execute(
                select(
                    UsageEvent.tenant_id,
                    UsageEvent.channel,
                    UsageEvent.provider,
                    UsageEvent.unit,
                    func.sum(UsageEvent.qty),
                )
                .where(UsageEvent.created_at >= start, UsageEvent.created_at < end)
                .group_by(
                    UsageEvent.tenant_id,
                    UsageEvent.channel,
                    UsageEvent.provider,
                    UsageEvent.unit,
                )
            )
        ).all()
    return [(t, c, p, u, float(q or 0)) for t, c, p, u, q in rows]


async def _tenant_ids(ctx) -> list[str]:
    async with ctx.sf() as s:
        return list((await s.scalars(select(Tenant.id).order_by(Tenant.id))).all())


def drift_pct(estimate: float, invoice: float | None) -> float | None:
    """How far the invoice ran from the estimate, in percent.

    `None` when there is nothing to compare: no invoice entered, or an invoice against an
    estimate of zero, where a percentage would be a division by zero rather than a finding.
    """
    if invoice is None or not estimate:
        return None
    return round((invoice - estimate) / estimate * 100, 1)


async def cost_report(ctx, month: str, price_cad: float = PRICE_CAD_PER_TENANT_MONTH) -> dict:
    """One month's metered cost, per tenant and per provider, against the recorded invoices.

    Every tenant appears, including one with no usage at all: it still rents a number, and a
    tenant missing from the report would read as a tenant that costs nothing.
    """
    fixed = per_tenant_fixed()
    per_tenant: dict[str, dict[str, float]] = {
        tid: {"fixed": fixed, "total": fixed} for tid in await _tenant_ids(ctx)
    }
    per_provider: dict[str, float] = {}

    for tenant_id, channel, provider, unit, qty in await _metered(ctx, month):
        cad = rates.estimate_cad({unit: qty})
        tenant = per_tenant.setdefault(tenant_id, {"fixed": fixed, "total": fixed})
        tenant[channel] = round(tenant.get(channel, 0.0) + cad, 4)
        tenant["total"] = round(tenant["total"] + cad, 4)
        per_provider[provider] = round(per_provider.get(provider, 0.0) + cad, 4)

    invoiced = await recorded_invoices(ctx.sf, month)
    # Every provider on either side: one that billed without metered usage is as much a
    # finding as one whose usage was never invoiced.
    providers = sorted(set(per_provider) | set(invoiced))
    estimate = {p: per_provider.get(p, 0.0) for p in providers}
    invoices: dict[str, float | None] = {p: invoiced.get(p) for p in providers}

    return {
        "month": month,
        "price_cad": price_cad,
        "per_tenant": per_tenant,
        "per_tenant_margin_pct": {
            tid: round((price_cad - t["total"]) / price_cad * 100, 2)
            for tid, t in per_tenant.items()
        },
        "per_provider_estimate": estimate,
        "invoices": invoices,
        "drift_pct": {p: drift_pct(estimate[p], invoices[p]) for p in providers},
    }


# --- the email --------------------------------------------------------------------------


def providers_by_drift(report: dict) -> list[str]:
    """Providers worst drift first; the ones with no invoice last, in name order."""
    drift = report["drift_pct"]
    return sorted(
        report["per_provider_estimate"],
        key=lambda p: (drift[p] is None, -abs(drift[p] or 0.0), p),
    )


def format_cad(value: float | None) -> str:
    return "not entered" if value is None else f"CA${value:,.2f}"


def report_email(report: dict) -> tuple[str, str]:
    """The plain-text monthly summary for `ops_email`: subject and body."""
    month = report["month"]
    estimated = sum(report["per_provider_estimate"].values())
    invoiced = sum(v for v in report["invoices"].values() if v is not None)
    order = providers_by_drift(report)
    worst = next((p for p in order if report["drift_pct"][p] is not None), None)
    headline = (
        f"top drift {worst} {report['drift_pct'][worst]:+.1f}%"
        if worst
        else "no invoices entered"
    )
    subject = (
        f"SpaTalk cost report {month}: CA${estimated:,.2f} estimated, "
        f"CA${invoiced:,.2f} invoiced, {headline}"
    )

    lines = [f"Cost reconciliation for {month} (UTC calendar month)", "", "Providers"]
    for provider in order:
        d = report["drift_pct"][provider]
        lines.append(
            f"  {provider}: estimated {format_cad(report['per_provider_estimate'][provider])}, "
            f"invoiced {format_cad(report['invoices'][provider])}"
            + (f", drift {d:+.1f}%" if d is not None else "")
        )
    price = report["price_cad"]
    lines += ["", f"Tenants (price CA${price:,.2f} per month)"]
    for tenant_id, costs in sorted(report["per_tenant"].items()):
        channels = ", ".join(
            f"{name} {format_cad(cad)}"
            for name, cad in sorted(costs.items())
            if name not in ("total", "fixed")
        )
        lines.append(
            f"  {tenant_id}: total {format_cad(costs['total'])} "
            f"(fixed {format_cad(costs['fixed'])}{', ' + channels if channels else ''}), "
            f"gross margin {report['per_tenant_margin_pct'][tenant_id]:.2f}%"
        )
    lines.append("")
    return subject, "\n".join(lines)


# --- the run ----------------------------------------------------------------------------


async def _start_run(sf: async_sessionmaker, now: datetime) -> int:
    async with sf() as s, s.begin():
        run = OpsRun(kind=RUN_KIND, started_at=now, ok=False, summary={})
        s.add(run)
        await s.flush()
        return run.id


async def _finish_run(
    sf: async_sessionmaker, run_id: int, now: datetime, *, ok: bool, summary: dict
) -> None:
    async with sf() as s, s.begin():
        await s.execute(
            update(OpsRun)
            .where(OpsRun.id == run_id)
            .values(finished_at=now, ok=ok, summary=summary)
        )


async def run_cost_report(ctx, month: str | None = None) -> dict:
    """Reconcile one month, email the summary, and record the run.

    `month` defaults to the month that has just ended, which is what the first-of-the-month
    job wants. The `ops_runs` row is written whether or not the mail leaves the building, so
    a month nobody reconciled is visible as a missing row rather than as silence.
    """
    at = ctx.clock.now()
    month = month or previous_month(at)
    run_id = await _start_run(ctx.sf, at)
    try:
        report = await cost_report(ctx, month)
        to = getattr(ctx.settings, "ops_email", "")
        if to:
            subject, body = report_email(report)
            await ctx.delivery.send_email(to, subject, body)
        else:
            logger.warning("cost report for {} not emailed: OPS_EMAIL is not set", month)
    except Exception as e:
        await _finish_run(
            ctx.sf,
            run_id,
            ctx.clock.now(),
            ok=False,
            summary={"month": month, "error": f"{type(e).__name__}: {e}"[:500]},
        )
        raise
    await _finish_run(ctx.sf, run_id, ctx.clock.now(), ok=True, summary=report)
    logger.info(
        "cost report {}: {} tenants, {} providers",
        month,
        len(report["per_tenant"]),
        len(report["per_provider_estimate"]),
    )
    return report


@jobs.register_handler(RUN_KIND)
async def _cost_report_job(payload: dict, ctx: jobs.JobContext) -> None:
    await run_cost_report(ctx, payload.get("month"))
