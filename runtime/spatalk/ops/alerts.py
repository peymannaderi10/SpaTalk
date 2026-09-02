"""Operational alerts with a six-hour dedup (operations plan, Task E7).

Nobody watches this runtime. It is one container on one VPS, and the only way a failure
becomes visible is if the process says so: an email to `OPS_EMAIL`, one SMS to
`OPS_SMS_NUMBER` when a number is configured, and the queue counters on `/healthz` that an
external uptime monitor reads. Everything in here exists to make a failure loud exactly
once, not repeatedly: one alert per incident per six hours.

`notify` was written for E4 (a band-3 intent handled as band 1 or 2 has to wake somebody
up rather than sit in a table); E7 kept its signature and added the SMS leg, the conditions
the scheduler re-derives every five minutes, the `/healthz` snapshot, the JSON log format
and the Sentry wiring. Sentry never receives a caller: `scrub_pii` masks phone numbers and
email addresses out of every event and breadcrumb before it leaves the process.

The dedup key is the identity of the incident, never a message: E1 set the convention with
`loop_guard:<tenant_id>:<E.164>`, so the same number stuck in a forwarding loop dedups to
one alert rather than one per ring.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import func, select

from spatalk.models import AlertLog, Job

# One alert per key per six hours (operations plan, Global Constraints).
DEDUP_HOURS = 6

# A job that has been due this long and is still queued means the worker is not draining.
STALE_QUEUE_SECONDS = 300
# The scheduler loops once a minute; three missed loops is a stopped scheduler. This is the
# same threshold the uptime monitor applies to `last_scheduler_tick` on `/healthz`.
STALE_TICK_SECONDS = 180
# How many dead jobs an alert body names before it stops listing them.
DEAD_JOBS_IN_BODY = 10


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
    if to:
        try:
            await ctx.delivery.send_email(to, subject, body)
        except Exception as e:  # noqa: BLE001  the incident is recorded; say so and move on
            logger.exception("alert {} could not be emailed to {}: {}", key, to, e)
    else:
        logger.warning("alert {} recorded but OPS_EMAIL is not set: {}", key, subject)
    await _send_ops_sms(ctx, key, subject)
    return True


# --- the SMS leg (operations plan, Task E7) ---------------------------------------------


async def ops_sms_from(ctx) -> str | None:
    """The number an ops SMS is sent from: the first tenant SMS number the registry knows.

    There is one Telnyx account and the runtime owns no operations number of its own, so an
    alert goes out from a number the account actually holds or the carrier refuses it. Until
    a tenant has a verified `sms_from_number` there is nothing to send from, and the alert
    stays email-only rather than pretending to have texted.
    """
    registry = getattr(ctx, "registry", None)
    if registry is None:
        return None
    for tenant_id in sorted(await registry.list_tenants()):
        cfg = await registry.get(tenant_id)
        if cfg.sms_from_number:
            return cfg.sms_from_number
    return None


async def _send_ops_sms(ctx, key: str, subject: str) -> bool:
    """One SMS per incident per six hours, carrying the subject and nothing else."""
    to = getattr(ctx.settings, "ops_sms_number", "")
    if not to or ctx.sms is None:
        return False
    from_number = await ops_sms_from(ctx)
    if not from_number:
        logger.warning("alert {} not texted: no tenant has an sms_from_number", key)
        return False
    try:
        await ctx.sms.send(from_number, to, f"spatalk: {subject}"[:300])
    except Exception as e:  # noqa: BLE001  the incident is recorded; a failed SMS is not one
        logger.exception("alert {} could not be texted to {}: {}", key, to, e)
        return False
    return True


# --- what the runtime knows about itself (operations plan, Task E7) ---------------------

# The last completed pass of the scheduler loop, in this process. It is deliberately not a
# database row: the fact being reported is "this process is still looping", and a row would
# be written a thousand times a day to say so. `/healthz` publishes it and the uptime
# monitor decides; the scheduler also checks it so a loop that stalls mid-pass is caught.
_LAST_TICK: datetime | None = None


def record_scheduler_tick(now: datetime) -> None:
    """Called by the scheduler at the end of every completed pass."""
    global _LAST_TICK
    _LAST_TICK = now


def last_scheduler_tick() -> datetime | None:
    return _LAST_TICK


def reset_monitoring_state() -> None:
    """Forget the recorded tick. For tests, and for a process that restarts its scheduler."""
    global _LAST_TICK
    _LAST_TICK = None


async def health_snapshot(ctx) -> dict:
    """The queue and scheduler fields `/healthz` publishes.

    `queued_jobs` counts everything still queued, including work deliberately scheduled for
    later; `oldest_queued_age_s` counts only how long the oldest *due* job has been waiting,
    which is the number that says the worker has stopped draining.
    """
    now = ctx.clock.now()
    async with ctx.sf() as s:
        queued = await s.scalar(select(func.count(Job.id)).where(Job.state == "queued"))
        dead = await s.scalar(select(func.count(Job.id)).where(Job.state == "dead"))
        oldest = await s.scalar(
            select(func.min(Job.run_at)).where(Job.state == "queued", Job.run_at <= now)
        )
    tick = last_scheduler_tick()
    return {
        "queued_jobs": int(queued or 0),
        "oldest_queued_age_s": max(0, int((now - oldest).total_seconds())) if oldest else 0,
        "dead_jobs": int(dead or 0),
        "last_scheduler_tick": tick.isoformat() if tick else None,
    }


# --- the conditions (operations plan, Task E7) ------------------------------------------


@dataclass(frozen=True)
class AlertCondition:
    """One thing that is wrong, named by the key it deduplicates on."""

    key: str
    subject: str
    body: str


def _is_escalation_delivery(job: Job) -> bool:
    payload = job.payload or {}
    return job.kind.startswith("deliver.") and bool(payload.get("escalation"))


def _describe(job: Job) -> str:
    return f"#{job.id} {job.kind}: {job.last_error or 'no error recorded'}"


async def alert_conditions(ctx) -> list[AlertCondition]:
    """Everything currently wrong, most consequential first. Reads, never writes."""
    now = ctx.clock.now()
    snapshot = await health_snapshot(ctx)
    found: list[AlertCondition] = []

    if snapshot["dead_jobs"]:
        async with ctx.sf() as s:
            dead = list(
                (
                    await s.scalars(
                        select(Job)
                        .where(Job.state == "dead")
                        .order_by(Job.id.desc())
                        .limit(DEAD_JOBS_IN_BODY)
                    )
                ).all()
            )
        escalations = [j for j in dead if _is_escalation_delivery(j)]
        if escalations:
            # An item passed its due time, the runtime tried to tell somebody, and the
            # attempt died. Nobody at the clinic knows the customer is waiting.
            found.append(
                AlertCondition(
                    "escalation_delivery_dead",
                    f"spatalk: {len(escalations)} escalation delivery job(s) dead",
                    "An escalated item was never delivered:\n"
                    + "\n".join(_describe(j) for j in escalations),
                )
            )
        found.append(
            AlertCondition(
                "jobs_dead",
                f"spatalk: {snapshot['dead_jobs']} job(s) dead",
                "Jobs that exhausted their attempts:\n"
                + "\n".join(_describe(j) for j in dead),
            )
        )

    waited = snapshot["oldest_queued_age_s"]
    if waited > STALE_QUEUE_SECONDS:
        found.append(
            AlertCondition(
                "queue_stale",
                f"spatalk: job queue is {waited // 60} minute(s) behind",
                f"The oldest due job has waited {waited} s, over the "
                f"{STALE_QUEUE_SECONDS} s budget, with {snapshot['queued_jobs']} job(s) "
                "queued. The worker is not draining.",
            )
        )

    tick = last_scheduler_tick()
    # No tick at all means this process has not finished a pass yet, which is a start-up
    # state, not an incident. Only a tick that has gone stale is one.
    if tick is not None:
        age = int((now - tick).total_seconds())
        if age > STALE_TICK_SECONDS:
            found.append(
                AlertCondition(
                    "scheduler_tick_stale",
                    f"spatalk: scheduler last completed a pass {age} s ago",
                    f"The scheduler loop runs every 60 s; the last completed pass was at "
                    f"{tick.isoformat()}, {age} s ago. Escalations and digests are not "
                    "being queued.",
                )
            )
    return found


async def check_alert_conditions(ctx) -> list[str]:
    """Raise every current condition, subject to the six-hour dedup. Returns the keys sent."""
    sent: list[str] = []
    for condition in await alert_conditions(ctx):
        if await notify(ctx, condition.key, condition.subject, condition.body):
            sent.append(condition.key)
    return sent


# --- PII scrubbing (operations plan, Task E7) -------------------------------------------

# A caller's number in every shape a transcript, a webhook payload or an exception writes
# it: +19055550100, 905-703-7546, (905) 703-7546, 905.703.7546, +1 905 555 0100. The
# lookaround is what keeps an id, a timestamp and a byte count out of the match.
PHONE_RE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[ .\-]?)?(?:\(\d{3}\)|\d{3})[ .\-]?\d{3}[ .\-]?\d{4}(?![\w])"
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_MASK = "[phone]"
EMAIL_MASK = "[email]"


def scrub_pii(value: str) -> str:
    """Mask phone numbers and email addresses. Everything operational survives untouched.

    Emails go first: an address can contain a ten-digit local part, and masking it as a
    phone number would leave the domain behind.
    """
    return PHONE_RE.sub(PHONE_MASK, EMAIL_RE.sub(EMAIL_MASK, value))


def _scrub_any(value):
    if isinstance(value, str):
        return scrub_pii(value)
    if isinstance(value, dict):
        return {k: _scrub_any(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_any(v) for v in value]
    return value


def scrub_breadcrumb(crumb: dict, hint=None) -> dict:
    """Sentry `before_breadcrumb`: nothing with a caller in it leaves the process."""
    return _scrub_any(crumb)


def scrub_event(event: dict, hint=None) -> dict:
    """Sentry `before_send`: the message, the exception values and the breadcrumbs."""
    for field in ("message", "logentry", "exception", "breadcrumbs", "extra", "request"):
        if field in event:
            event[field] = _scrub_any(event[field])
    return event


# --- error reporting and log format (operations plan, Task E7) --------------------------


def _sentry_init(**kwargs) -> None:
    """Isolated so a test can replace it and no test ever initialises a real client."""
    import sentry_sdk

    sentry_sdk.init(**kwargs)


def init_sentry(settings) -> bool:
    """Initialise Sentry only when a DSN is configured, and never with PII.

    `send_default_pii=False` stops the SDK attaching headers, cookies and client IPs; the
    two scrubbers cover what our own code puts in a message. Returns False when there is no
    DSN or the SDK is not installed — error reporting is optional, and its absence must not
    stop the service booting.
    """
    dsn = getattr(settings, "sentry_dsn", "")
    if not dsn:
        return False
    try:
        _sentry_init(
            dsn=dsn,
            send_default_pii=False,
            before_send=scrub_event,
            before_breadcrumb=scrub_breadcrumb,
            release=getattr(settings, "git_commit", "") or None,
            traces_sample_rate=0.0,
        )
    except Exception as e:  # noqa: BLE001  no error tracker is better than no service
        logger.warning("sentry not initialised: {}", e)
        return False
    logger.info("sentry initialised")
    return True


def configure_logging(settings) -> bool:
    """With `LOG_FORMAT=json`, emit one JSON object per line instead of the console format.

    `diagnose=False` is not a preference: loguru's diagnostic tracebacks print the value of
    every local variable, which on this service means a caller's number in the log of the
    exception that mentioned it.
    """
    if (getattr(settings, "log_format", "") or "").strip().lower() != "json":
        return False
    logger.remove()
    logger.add(sys.stderr, serialize=True, backtrace=False, diagnose=False)
    return True
