from __future__ import annotations

import asyncio
from datetime import time
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select

from spatalk import jobs
from spatalk.ledger.delivery import schedule_item_delivery
from spatalk.models import Tenant


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


async def run_scheduler_forever(ctx: jobs.JobContext, interval_seconds: float = 60.0) -> None:
    while True:
        try:
            await escalate_breached(ctx)
            await send_digests(ctx)
        except Exception as e:  # noqa: BLE001
            logger.exception("scheduler error: {}", e)
        await asyncio.sleep(interval_seconds)
