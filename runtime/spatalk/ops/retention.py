"""Retention with receipts (operations plan, Task E3).

Spec §10 weakness 5 is that transcripts hold health statements. The answer is not a promise
in a privacy policy but a nightly job that hard-deletes them on the tenant's own clock and
leaves a countable artefact behind, so "it was deleted" is a row somebody can read rather
than an assurance.

The four thresholds, from `docs/reference/data-model.md`:

* transcripts (`messages`) — the tenant's own `retention_days`, default 30, measured from
  the end of the conversation, and with them the model-drafted `conversations.notes`, which
  are a view of the transcript and cannot outlive it (call-notes plan, Task N1);
* conversations — kept 400 days as a stub with no caller and no latency, then deleted;
* items and usage events — 400 days;
* audit log — two years, and tenant-independent because the table carries no tenant.

Everything is a hard delete. Nothing here soft-deletes, and nothing here writes a receipt
for a count of zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk import jobs
from spatalk.models import (
    AuditLog,
    Conversation,
    DeletionReceipt,
    Item,
    Message,
    OpsRun,
    Tenant,
    UsageEvent,
)

# The job kind the scheduler queues; also the `ops_runs.kind` this job writes.
RUN_KIND = "ops.retention"

# Fixed, not per tenant: the stub's life, and the audit log's.
STUB_DAYS = 400
AUDIT_LOG_DAYS = 730

# `notes` counts conversations whose model-drafted notes were cleared, not rows deleted:
# the notes are three columns on a conversation that is kept as a stub, so the sweep nulls
# them where it deletes the transcript they were drafted from (call-notes plan, Task N1).
KINDS: tuple[str, ...] = ("messages", "conversations", "items", "usage_events", "notes")


@dataclass
class RetentionSummary:
    """What one run deleted. `per_tenant` carries every tenant, including the quiet ones."""

    per_tenant: dict[str, dict[str, int]] = field(default_factory=dict)
    # The audit log has no tenant column, so its count sits outside `per_tenant`.
    audit_log: int = 0

    def total(self) -> int:
        return sum(sum(c.values()) for c in self.per_tenant.values()) + self.audit_log

    def as_json(self) -> dict:
        return {"per_tenant": self.per_tenant, "audit_log": self.audit_log}


def _finished(cutoff_column=Conversation.ended_at):
    """When a conversation stopped, for retention purposes.

    `docs/reference/data-model.md` measures transcript retention from `ended_at`. A text
    conversation the customer simply abandoned never gets one — `text/service.py` sets
    `ended_at` only when the assistant ends the turn — so falling back through `closed_at`,
    the last message and finally the start makes the rule total. Every conversation that
    does have an `ended_at` is treated exactly as the reference says.
    """
    return func.coalesce(
        cutoff_column,
        Conversation.closed_at,
        Conversation.last_message_at,
        Conversation.started_at,
    )


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


async def _sweep_tenant(sf: async_sessionmaker, tenant_id: str, now: datetime, days: int) -> dict:
    """One tenant's deletes, in one transaction, with its receipts."""
    transcript_cutoff = now - timedelta(days=days)
    long_cutoff = now - timedelta(days=STUB_DAYS)
    counts = dict.fromkeys(KINDS, 0)

    async with sf() as s, s.begin():
        expired = select(Conversation.id).where(
            Conversation.tenant_id == tenant_id, _finished() < transcript_cutoff
        )
        counts["messages"] += (
            await s.execute(delete(Message).where(Message.conversation_id.in_(expired)))
        ).rowcount
        # What is left is analytics: channel, band, timestamps. No caller, no latency.
        await s.execute(
            update(Conversation)
            .where(Conversation.id.in_(expired))
            .values(caller=None, latency_ms=None, stage_ms=None)
        )
        # The drafted notes are a view of the transcript, so they go with it. Counted
        # separately, and only where there was something to clear, so a second sweep the
        # same night accounts for nothing (call-notes plan, Task N1).
        counts["notes"] += (
            await s.execute(
                update(Conversation)
                .where(Conversation.id.in_(expired), Conversation.notes_at.is_not(None))
                .values(notes=None, notes_model=None, notes_at=None)
            )
        ).rowcount

        counts["items"] += (
            await s.execute(
                delete(Item).where(Item.tenant_id == tenant_id, Item.created_at < long_cutoff)
            )
        ).rowcount
        counts["usage_events"] += (
            await s.execute(
                delete(UsageEvent).where(
                    UsageEvent.tenant_id == tenant_id, UsageEvent.created_at < long_cutoff
                )
            )
        ).rowcount

        # The stub's own life is up. Anything still pointing at it goes with it, whatever
        # its own age, or the foreign keys would refuse the delete.
        old = select(Conversation.id).where(
            Conversation.tenant_id == tenant_id, Conversation.started_at < long_cutoff
        )
        counts["messages"] += (
            await s.execute(delete(Message).where(Message.conversation_id.in_(old)))
        ).rowcount
        counts["items"] += (
            await s.execute(delete(Item).where(Item.conversation_id.in_(old)))
        ).rowcount
        counts["usage_events"] += (
            await s.execute(delete(UsageEvent).where(UsageEvent.conversation_id.in_(old)))
        ).rowcount
        counts["conversations"] += (
            await s.execute(
                delete(Conversation).where(
                    Conversation.tenant_id == tenant_id, Conversation.started_at < long_cutoff
                )
            )
        ).rowcount

        for kind in KINDS:
            if not counts[kind]:
                continue
            s.add(
                DeletionReceipt(
                    tenant_id=tenant_id,
                    kind=kind,
                    count=counts[kind],
                    cutoff=(
                        transcript_cutoff if kind in ("messages", "notes") else long_cutoff
                    ),
                    run_at=now,
                )
            )
    return counts


async def _sweep_audit_log(sf: async_sessionmaker, now: datetime) -> int:
    """Two years, tenant-independent: `audit_log` carries no tenant column."""
    async with sf() as s, s.begin():
        return (
            await s.execute(
                delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=AUDIT_LOG_DAYS))
            )
        ).rowcount


async def run_retention(ctx: jobs.JobContext, now: datetime | None = None) -> RetentionSummary:
    """Delete everything past its threshold, once, and account for it.

    Idempotent: a second run the same night finds nothing past a cutoff, so it deletes
    nothing and writes no receipts. It still records an `ops_runs` row, because a run that
    found nothing to do is a fact worth keeping.
    """
    at = now or ctx.clock.now()
    run_id = await _start_run(ctx.sf, at)
    summary = RetentionSummary()
    try:
        async with ctx.sf() as s:
            tenant_ids = list((await s.scalars(select(Tenant.id).order_by(Tenant.id))).all())
        for tenant_id in tenant_ids:
            cfg = await ctx.registry.get(tenant_id)
            summary.per_tenant[tenant_id] = await _sweep_tenant(
                ctx.sf, tenant_id, at, cfg.retention_days
            )
        summary.audit_log = await _sweep_audit_log(ctx.sf, at)
    except Exception as e:
        await _finish_run(
            ctx.sf,
            run_id,
            ctx.clock.now(),
            ok=False,
            summary={"error": f"{type(e).__name__}: {e}"[:500], **summary.as_json()},
        )
        raise
    await _finish_run(ctx.sf, run_id, ctx.clock.now(), ok=True, summary=summary.as_json())
    logger.info(
        "retention: {} rows deleted across {} tenants", summary.total(), len(summary.per_tenant)
    )
    return summary


@jobs.register_handler(RUN_KIND)
async def _retention_job(payload: dict, ctx: jobs.JobContext) -> None:
    await run_retention(ctx, ctx.clock.now())
