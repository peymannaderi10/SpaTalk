"""Operational alerts with a six-hour dedup (operations plan, Task E7).

E7 owns this module; E4 needs `notify` before E7 lands, because the nightly audit's whole
point is that a band-3 intent handled as band 1 or 2 wakes somebody up rather than sitting
in a table. What is here is the part E4 uses and nothing more: the dedup rule, the
`alert_log` row and the email. E7 adds the SMS leg (`ops_sms_number`), the scheduler's
conditions (dead jobs, a stale queue, a stale tick) and the Sentry wiring, in this file,
without changing this signature.

The dedup key is the identity of the incident, never a message: E1 set the convention with
`loop_guard:<tenant_id>:<E.164>`, so the same number stuck in a forwarding loop dedups to
one alert rather than one per ring.
"""

from __future__ import annotations

from datetime import timedelta

from loguru import logger
from sqlalchemy import func, select

from spatalk.models import AlertLog

# One alert per key per six hours (operations plan, Global Constraints).
DEDUP_HOURS = 6


async def already_alerted(ctx, key: str) -> bool:
    """True when this key was alerted inside the dedup window."""
    since = ctx.clock.now() - timedelta(hours=DEDUP_HOURS)
    async with ctx.sf() as s:
        recent = await s.scalar(
            select(func.count(AlertLog.id)).where(AlertLog.key == key, AlertLog.sent_at >= since)
        )
    return bool(recent)


async def notify(ctx, key: str, subject: str, body: str) -> bool:
    """Raise one alert for `key`. Returns False when the dedup window swallowed it.

    The `alert_log` row is written whether or not the email leaves the building: the row is
    the record that the incident happened, and a mail server that is down must not erase it.
    A delivery failure is logged, not raised, so an alert about a failure cannot itself
    become the failure that stops the job that raised it.
    """
    if await already_alerted(ctx, key):
        logger.info("alert {} deduplicated inside {}h", key, DEDUP_HOURS)
        return False
    async with ctx.sf() as s, s.begin():
        s.add(AlertLog(key=key, subject=subject[:400], sent_at=ctx.clock.now()))
    to = getattr(ctx.settings, "ops_email", "")
    if not to:
        logger.warning("alert {} recorded but OPS_EMAIL is not set: {}", key, subject)
        return True
    try:
        await ctx.delivery.send_email(to, subject, body)
    except Exception as e:  # noqa: BLE001  the incident is already recorded; say so and move on
        logger.exception("alert {} could not be emailed to {}: {}", key, to, e)
    return True
