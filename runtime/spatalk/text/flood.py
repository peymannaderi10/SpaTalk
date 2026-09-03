"""SMS flood guard (plan F, Task F1): bound what one number, or one tenant's day, can cost.

Every inbound text costs the carrier fee whether or not we answer; that part is the
carrier's to stop. What this module bounds is everything after it: the model call and the
outbound reply. A number that texts past its burst or daily limit is muted for a while, a
tenant whose assistant has replied past its daily ceiling is paused until the local day
rolls, and a person can block a number outright. Nothing is dropped silently: the route
still stores every suppressed text on the sender's conversation, so the portal shows what
the number sent. Only the reply and the model call are withheld.

Counts come from the `messages` and `conversations` rows that already exist (the text
service stamps them with the application clock), so there are no counters to keep in sync.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk.models import AlertLog, Conversation, Message, SmsBlock
from spatalk.tenants.schema import TenantConfig
from spatalk.text.staff import staff_numbers

Verdict = Literal["ok", "blocked", "muted", "capped"]

FLOOD_ALERT_KEY = "sms.flood:{tenant}:{phone}"
CAP_ALERT_KEY = "sms.daily_cap:{tenant}:{day}"
PAUSED_NOTICE_KEY = "sms.paused_notice:{tenant}:{phone}:{day}"
PAUSED_NOTICE_HOURS = 24


def local_day_start(cfg: TenantConfig, now: datetime) -> datetime:
    """Midnight of the tenant's current local day, as an aware datetime."""
    local = now.astimezone(ZoneInfo(cfg.timezone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def local_day(cfg: TenantConfig, now: datetime) -> str:
    return now.astimezone(ZoneInfo(cfg.timezone)).date().isoformat()


async def _count_messages(
    sf: async_sessionmaker, tenant_id: str, role: str, since: datetime, caller: str | None
) -> int:
    stmt = (
        select(func.count(Message.id))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel == "sms",
            Message.role == role,
            Message.created_at >= since,
        )
    )
    if caller is not None:
        stmt = stmt.where(Conversation.caller == caller)
    async with sf() as s:
        return int(await s.scalar(stmt) or 0)


async def replies_today(ctx, cfg: TenantConfig, now: datetime) -> int:
    """Assistant replies this tenant has sent by SMS since its local midnight."""
    return await _count_messages(ctx.sf, cfg.id, "assistant", local_day_start(cfg, now), None)


async def mute(
    ctx, cfg: TenantConfig, phone: str, until: datetime, reason: str, created_by: str
) -> None:
    """Mute `phone` until `until`. A permanent block is never shortened by a mute."""
    async with ctx.sf() as s, s.begin():
        await s.execute(
            insert(SmsBlock)
            .values(
                tenant_id=cfg.id, phone=phone, until=until, reason=reason, created_by=created_by
            )
            .on_conflict_do_update(
                index_elements=[SmsBlock.tenant_id, SmsBlock.phone],
                set_={"until": until, "reason": reason, "created_by": created_by},
                where=SmsBlock.until.isnot(None),
            )
        )


async def block(ctx, cfg: TenantConfig, phone: str, created_by: str) -> None:
    """Block `phone` for this tenant permanently (a person's decision, or the CLI)."""
    async with ctx.sf() as s, s.begin():
        await s.execute(
            insert(SmsBlock)
            .values(
                tenant_id=cfg.id, phone=phone, until=None, reason="manual", created_by=created_by
            )
            .on_conflict_do_update(
                index_elements=[SmsBlock.tenant_id, SmsBlock.phone],
                set_={"until": None, "reason": "manual", "created_by": created_by},
            )
        )


async def unblock(ctx, tenant_id: str, phone: str) -> bool:
    """Remove a block or a mute. True when a row was removed."""
    async with ctx.sf() as s, s.begin():
        result = await s.execute(
            delete(SmsBlock).where(SmsBlock.tenant_id == tenant_id, SmsBlock.phone == phone)
        )
        return bool(result.rowcount)


async def list_blocks(ctx, tenant_id: str) -> list[SmsBlock]:
    async with ctx.sf() as s:
        rows = await s.scalars(
            select(SmsBlock).where(SmsBlock.tenant_id == tenant_id).order_by(SmsBlock.created_at)
        )
        return list(rows.all())


async def paused_notice_once(ctx, cfg: TenantConfig, phone: str, now: datetime) -> bool:
    """True the first time today this sender is told the assistant is paused.

    Recorded in `alert_log` under a per-sender, per-day key, without email or ops SMS: it
    is a bookkeeping row, not an incident. The second text of the day gets nothing.
    """
    key = PAUSED_NOTICE_KEY.format(tenant=cfg.id, phone=phone, day=local_day(cfg, now))
    since = now - timedelta(hours=PAUSED_NOTICE_HOURS)
    async with ctx.sf() as s, s.begin():
        seen = await s.scalar(
            select(func.count(AlertLog.id)).where(AlertLog.key == key, AlertLog.sent_at >= since)
        )
        if seen:
            return False
        s.add(AlertLog(key=key, subject=f"paused notice sent to {phone}", sent_at=now))
    return True


async def inbound_verdict(ctx, cfg: TenantConfig, sender: str, now: datetime) -> Verdict:
    """Decide whether this inbound text may cost a model call and a reply.

    Order: a permanent block, a live mute, an expired mute (forgotten), the sender's burst
    and daily counts (a breach mutes and alerts), then the tenant's daily reply ceiling.
    Staff numbers are always `ok`.
    """
    from spatalk.ops.alerts import notify

    if sender in staff_numbers(cfg):
        return "ok"

    async with ctx.sf() as s:
        row = await s.get(SmsBlock, {"tenant_id": cfg.id, "phone": sender})
    if row is not None:
        if row.until is None:
            return "blocked"
        if row.until > now:
            return "muted"
        await unblock(ctx, cfg.id, sender)

    g = cfg.sms_guard
    burst = await _count_messages(
        ctx.sf, cfg.id, "user", now - timedelta(minutes=g.burst_window_minutes), sender
    )
    today = await _count_messages(ctx.sf, cfg.id, "user", local_day_start(cfg, now), sender)
    if burst >= g.burst_limit or today >= g.daily_limit:
        until = now + timedelta(hours=g.mute_hours)
        await mute(ctx, cfg, sender, until, "flood", "system:flood")
        n = max(burst, today) + 1
        window = (
            f"{g.burst_window_minutes} minutes" if burst >= g.burst_limit else "one day"
        )
        subject = f"{cfg.name}: {sender} muted for {g.mute_hours}h after {n} texts in {window}"
        body = (
            f"{subject}.\n\nIts texts are still stored on the conversation and nothing is "
            "answered until the mute ends. Block the number permanently from the portal or "
            f"with `spatalk sms block {cfg.id} {sender}` if it is not a customer."
        )
        logger.warning("sms flood: {}", subject)
        await notify(ctx, FLOOD_ALERT_KEY.format(tenant=cfg.id, phone=sender), subject, body)
        return "muted"

    if await replies_today(ctx, cfg, now) >= g.tenant_daily_replies:
        day = local_day(cfg, now)
        subject = (
            f"{cfg.name}: assistant paused on SMS, {g.tenant_daily_replies} replies today ({day})"
        )
        body = (
            f"{subject}.\n\nNew texts are stored and each sender is told once that the "
            "assistant is paused; nothing is generated until the local day rolls over. Raise "
            "`sms_guard.tenant_daily_replies` in the tenant settings if this volume is real."
        )
        logger.warning("sms flood: {}", subject)
        await notify(ctx, CAP_ALERT_KEY.format(tenant=cfg.id, day=day), subject, body)
        return "capped"
    return "ok"
