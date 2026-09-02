from __future__ import annotations

import asyncio
from datetime import time, timezone
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import func, select

from spatalk import jobs
from spatalk.ledger.delivery import schedule_item_delivery
from spatalk.models import Job, Tenant
# Operations plan, Task E3: importing this also registers the ops.retention handler.
from spatalk.ops import retention
# Operations plan, Task E4: importing this also registers the ops.nightly_audit handler.
from spatalk.ops import nightly_audit
# Instagram plan, Task D1: importing this also registers the social.refresh_tokens handler.
from spatalk.social.meta_oauth import ensure_daily_refresh_scheduled
from spatalk.text.takeover import hand_back_stale


async def escalate_breached(ctx: jobs.JobContext) -> int:
    """Deliver every open item past its due time to all channels, once."""
    now = ctx.clock.now()
    count = 0
    for item in await ctx.ledger.breached(now):
        cfg = await ctx.registry.get(item.tenant_id)
        await schedule_item_delivery(ctx.sf, item, cfg, escalation=True)
        await ctx.ledger.mark_escalated(item.id, now)
        count += 1
        logger.warning("escalated item {} for {} (due {})", item.id, item.tenant_id, item.due_at)
    return count


async def send_digests(ctx: jobs.JobContext) -> int:
    """Queue one digest per tenant per local day, once its local digest time has passed."""
    now = ctx.clock.now()
    sent = 0
    async with ctx.sf() as s, s.begin():
        for tenant in (await s.scalars(select(Tenant))).all():
            cfg = await ctx.registry.get(tenant.id)
            local = now.astimezone(ZoneInfo(cfg.timezone))
            h, m = cfg.delivery.digest_time_local.split(":")
            if local.timetz().replace(tzinfo=None) < time(int(h), int(m)):
                continue
            if tenant.last_digest_date == local.date():
                continue
            await jobs.enqueue(ctx.sf, "digest.email", {"tenant_id": tenant.id})
            tenant.last_digest_date = local.date()
            sent += 1
    return sent


# --- operations (operations plan, Task E3) ---------------------------------------------

# Retention runs on UTC, not on a tenant's clock: it is one sweep over every tenant, and a
# tenant-local 03:00 would mean as many nightly runs as there are timezones.
NIGHTLY_RETENTION_UTC_HOUR = 3


async def ensure_nightly_retention_scheduled(ctx: jobs.JobContext) -> bool:
    """Queue the retention job at most once per UTC day, from 03:00 UTC.

    The marker is the queued job's own `run_at`, set from the application clock, so the
    "already done today" test survives a scheduler that restarts and cannot be fooled by
    the database's wall clock drifting from the runtime's.
    """
    now = ctx.clock.now().astimezone(timezone.utc)
    boundary = now.replace(hour=NIGHTLY_RETENTION_UTC_HOUR, minute=0, second=0, microsecond=0)
    if now < boundary:
        return False
    async with ctx.sf() as s:
        already = await s.scalar(
            select(func.count(Job.id)).where(
                Job.kind == retention.RUN_KIND, Job.run_at >= boundary
            )
        )
    if already:
        return False
    await jobs.enqueue(ctx.sf, retention.RUN_KIND, {}, run_at=now)
    logger.info("queued {} for {}", retention.RUN_KIND, now.isoformat())
    return True


# --- operations (operations plan, Task E4) ---------------------------------------------

# An hour after retention, and for the same reason it is not tenant-local: one sweep over
# every tenant. 03:00 deletes the transcripts, 04:00 audits what is left, which is why a
# tenant on a `retention_days` of 1 would audit a day whose transcripts have just gone.
NIGHTLY_AUDIT_UTC_HOUR = 4


async def ensure_nightly_audit_scheduled(ctx: jobs.JobContext) -> bool:
    """Queue the nightly audit at most once per UTC day, from 04:00 UTC.

    Same marker as retention: the queued job's own `run_at`, set from the application clock,
    so a restarted scheduler cannot be fooled by the database's wall clock drifting.
    """
    now = ctx.clock.now().astimezone(timezone.utc)
    boundary = now.replace(hour=NIGHTLY_AUDIT_UTC_HOUR, minute=0, second=0, microsecond=0)
    if now < boundary:
        return False
    async with ctx.sf() as s:
        already = await s.scalar(
            select(func.count(Job.id)).where(
                Job.kind == nightly_audit.RUN_KIND, Job.run_at >= boundary
            )
        )
    if already:
        return False
    await jobs.enqueue(ctx.sf, nightly_audit.RUN_KIND, {}, run_at=now)
    logger.info("queued {} for {}", nightly_audit.RUN_KIND, now.isoformat())
    return True


async def run_scheduler_forever(ctx: jobs.JobContext, interval_seconds: float = 60.0) -> None:
    while True:
        try:
            await escalate_breached(ctx)
            await send_digests(ctx)
            # A conversation a person took over and then left silent (Task B5).
            await hand_back_stale(ctx)
            # Meta tokens expire; this queues the daily refresh job once a day (Task D1).
            await ensure_daily_refresh_scheduled(ctx.sf, ctx.clock)
            # Hard-delete everything past its retention threshold, nightly (Task E3).
            await ensure_nightly_retention_scheduled(ctx)
            # Re-judge yesterday's bands and scan its transcripts, nightly (Task E4).
            await ensure_nightly_audit_scheduled(ctx)
        except Exception as e:  # noqa: BLE001
            logger.exception("scheduler error: {}", e)
        await asyncio.sleep(interval_seconds)
