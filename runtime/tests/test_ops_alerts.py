"""Monitoring, error reporting and alerts (operations plan, Task E7).

The runtime is one container on one VPS with no operator watching it. Everything here
exists so that a failure the founder cannot see becomes a message the founder does see,
exactly once per incident per six hours:

* `/healthz` says what the queue is doing, so an external uptime monitor can decide the
  process is alive *and* working (`"ok":true` and `"dead_jobs":0` as keyword checks);
* the scheduler re-derives the same conditions every five minutes and raises them by email
  and, when a number is configured, by one SMS;
* nothing that leaves the building carries a caller's phone number or email into a
  third-party error tracker: `scrub_pii` runs on every Sentry event and breadcrumb.

Every test drives fakes. No test reaches SMTP, Telnyx or Sentry.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

# Tuesday 2026-09-01 14:00 in Toronto.
NOW = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
OPS_EMAIL = "ops@example.test"
OPS_SMS = "+15145550199"
SMS_FROM = "+18005550111"


def _settings(**kw):
    from spatalk.settings import Settings

    kw.setdefault("ops_email", OPS_EMAIL)
    return Settings(_env_file=None, public_base_url="https://api.test", secret_key="s", **kw)


def _clock(at=NOW):
    from spatalk.clock import FixedClock

    return FixedClock(at)


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


async def _texting_tenant(registry):
    """Skincentrix with an SMS number: the ops SMS has to be sent *from* something."""
    cfg = await registry.get("skincentrix")
    await registry.import_config(
        cfg.model_copy(update={"sms_from_number": SMS_FROM}), created_by="test"
    )
    # `get` above cached the old config, and an import never clears another reader's cache.
    registry.invalidate("skincentrix")


async def _silent_tenant(registry):
    """Skincentrix without a messaging number: the bundle carries one since S1."""
    cfg = await registry.get("skincentrix")
    await registry.import_config(
        cfg.model_copy(update={"sms_from_number": None}), created_by="test"
    )
    registry.invalidate("skincentrix")


async def _job(sf, kind="deliver.email", *, state="queued", run_at=NOW, payload=None, error=None):
    from spatalk.models import Job

    async with sf() as s, s.begin():
        j = Job(
            kind=kind,
            payload=payload or {},
            state=state,
            run_at=run_at,
            created_at=run_at,
            last_error=error,
        )
        s.add(j)
        await s.flush()
        return j.id


async def _alerts(sf):
    from spatalk.models import AlertLog

    async with sf() as s:
        return list((await s.scalars(select(AlertLog).order_by(AlertLog.id))).all())


@pytest_asyncio.fixture(autouse=True)
async def _clean_monitoring_state():
    """The scheduler tick and the five-minute throttle are process state; reset both."""
    from spatalk.ledger.scheduler import reset_alert_check_state

    reset_alert_check_state()
    yield
    reset_alert_check_state()


@pytest.fixture
def restore_logging():
    """`configure_logging` replaces loguru's sinks; put the default back afterwards."""
    import sys

    from loguru import logger

    yield
    logger.remove()
    logger.add(sys.stderr)


# --- the dedup rule ---------------------------------------------------------------------


async def test_the_first_alert_for_a_key_is_recorded_and_emailed(sf, registry):
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    assert await alerts.notify(ctx, "jobs_dead", "2 jobs dead", "body") is True

    rows = await _alerts(sf)
    assert [(r.key, r.subject) for r in rows] == [("jobs_dead", "2 jobs dead")]
    assert rows[0].sent_at == NOW
    assert ctx.delivery.emails == [(OPS_EMAIL, "2 jobs dead", "body")]


async def test_a_second_alert_for_the_same_key_inside_six_hours_is_swallowed(sf, registry):
    from spatalk.ops import alerts

    clock = _clock()
    ctx = _ctx(sf, registry, clock)
    await alerts.notify(ctx, "jobs_dead", "first", "body")
    clock.advance(hours=5, minutes=59)

    assert await alerts.notify(ctx, "jobs_dead", "second", "body") is False
    assert len(await _alerts(sf)) == 1
    assert len(ctx.delivery.emails) == 1


async def test_the_same_key_alerts_again_once_the_six_hour_window_has_passed(sf, registry):
    from spatalk.ops import alerts

    clock = _clock()
    ctx = _ctx(sf, registry, clock)
    await alerts.notify(ctx, "jobs_dead", "first", "body")
    clock.advance(hours=6, minutes=1)

    assert await alerts.notify(ctx, "jobs_dead", "second", "body") is True
    assert [r.subject for r in await _alerts(sf)] == ["first", "second"]
    assert len(ctx.delivery.emails) == 2


async def test_one_key_never_deduplicates_another(sf, registry):
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    assert await alerts.notify(ctx, "jobs_dead", "a", "body") is True
    assert await alerts.notify(ctx, "queue_stale", "b", "body") is True
    assert len(await _alerts(sf)) == 2


# --- the SMS leg ------------------------------------------------------------------------


async def test_an_ops_sms_number_gets_exactly_one_sms_per_alert(sf, registry):
    from spatalk.ops import alerts

    await _texting_tenant(registry)
    ctx = _ctx(sf, registry, _clock(), _settings(ops_sms_number=OPS_SMS))
    await alerts.notify(ctx, "jobs_dead", "2 jobs dead", "the long body")

    assert len(ctx.sms.sent) == 1
    from_number, to, text = ctx.sms.sent[0]
    assert (from_number, to) == (SMS_FROM, OPS_SMS)
    assert "2 jobs dead" in text


async def test_a_deduplicated_alert_sends_no_sms(sf, registry):
    from spatalk.ops import alerts

    await _texting_tenant(registry)
    ctx = _ctx(sf, registry, _clock(), _settings(ops_sms_number=OPS_SMS))
    await alerts.notify(ctx, "jobs_dead", "first", "body")
    await alerts.notify(ctx, "jobs_dead", "second", "body")

    assert len(ctx.sms.sent) == 1


async def test_without_an_ops_sms_number_nothing_is_texted(sf, registry):
    from spatalk.ops import alerts

    await _texting_tenant(registry)
    ctx = _ctx(sf, registry, _clock())
    await alerts.notify(ctx, "jobs_dead", "first", "body")

    assert ctx.sms.sent == []
    assert len(ctx.delivery.emails) == 1


async def test_with_no_tenant_number_to_send_from_the_alert_is_still_recorded(sf, registry):
    """A tenant that cannot text still gets its incident on the record, by email."""
    from spatalk.ops import alerts

    await _silent_tenant(registry)
    ctx = _ctx(sf, registry, _clock(), _settings(ops_sms_number=OPS_SMS))
    assert await alerts.notify(ctx, "jobs_dead", "first", "body") is True

    assert ctx.sms.sent == []
    assert len(await _alerts(sf)) == 1
    assert len(ctx.delivery.emails) == 1


async def test_a_delivery_failure_never_erases_the_incident(sf, registry):
    """The row is the record that it happened; a dead mail server must not remove it."""
    from spatalk.ops import alerts

    await _texting_tenant(registry)
    ctx = _ctx(sf, registry, _clock(), _settings(ops_sms_number=OPS_SMS))

    async def boom(*a, **k):
        raise RuntimeError("smtp is down")

    ctx.delivery.send_email = boom
    ctx.sms.send = boom

    assert await alerts.notify(ctx, "jobs_dead", "first", "body") is True
    assert len(await _alerts(sf)) == 1


# --- the conditions ---------------------------------------------------------------------


async def test_a_healthy_runtime_raises_nothing(sf, registry):
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    alerts.record_scheduler_tick(NOW)
    await _job(sf, state="done", run_at=NOW - timedelta(hours=2))
    await _job(sf, state="queued", run_at=NOW - timedelta(seconds=30))

    assert await alerts.check_alert_conditions(ctx) == []
    assert await _alerts(sf) == []


async def test_a_dead_job_raises_an_alert_naming_it(sf, registry):
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    alerts.record_scheduler_tick(NOW)
    await _job(sf, "text.followup", state="dead", error="RuntimeError: nope")

    assert "jobs_dead" in await alerts.check_alert_conditions(ctx)
    subject, body = ctx.delivery.emails[0][1], ctx.delivery.emails[0][2]
    assert "1" in subject
    assert "text.followup" in body and "RuntimeError: nope" in body


async def test_a_dead_escalation_delivery_job_raises_its_own_alert(sf, registry):
    """The worst failure the queue can have: an item breached and nobody was told."""
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    alerts.record_scheduler_tick(NOW)
    await _job(
        sf,
        "deliver.slack",
        state="dead",
        payload={"item_id": 7, "tenant_id": "skincentrix", "escalation": True},
        error="HTTPError: 500",
    )

    keys = await alerts.check_alert_conditions(ctx)
    assert "escalation_delivery_dead" in keys
    subjects = [e[1] for e in ctx.delivery.emails]
    assert any("escalation" in s.lower() for s in subjects)


async def test_a_dead_ordinary_delivery_job_is_not_an_escalation_alert(sf, registry):
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    alerts.record_scheduler_tick(NOW)
    await _job(
        sf,
        "deliver.slack",
        state="dead",
        payload={"item_id": 7, "tenant_id": "skincentrix", "escalation": False},
    )

    assert await alerts.check_alert_conditions(ctx) == ["jobs_dead"]


async def test_a_queued_job_older_than_five_minutes_raises_an_alert(sf, registry):
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    alerts.record_scheduler_tick(NOW)
    await _job(sf, "deliver.email", state="queued", run_at=NOW - timedelta(minutes=6))

    assert "queue_stale" in await alerts.check_alert_conditions(ctx)
    assert "360" in ctx.delivery.emails[0][2] or "6" in ctx.delivery.emails[0][1]


async def test_a_queued_job_inside_the_five_minutes_raises_nothing(sf, registry):
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    alerts.record_scheduler_tick(NOW)
    await _job(sf, "deliver.email", state="queued", run_at=NOW - timedelta(minutes=4))

    assert await alerts.check_alert_conditions(ctx) == []


async def test_a_job_scheduled_for_later_is_not_a_backlog(sf, registry):
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    alerts.record_scheduler_tick(NOW)
    await _job(sf, "ops.retention", state="queued", run_at=NOW + timedelta(hours=9))

    assert await alerts.check_alert_conditions(ctx) == []


async def test_a_scheduler_tick_older_than_three_minutes_raises_an_alert(sf, registry):
    from spatalk.ops import alerts

    clock = _clock()
    ctx = _ctx(sf, registry, clock)
    alerts.record_scheduler_tick(NOW)
    clock.advance(minutes=4)

    assert "scheduler_tick_stale" in await alerts.check_alert_conditions(ctx)


async def test_a_fresh_scheduler_tick_raises_nothing(sf, registry):
    from spatalk.ops import alerts

    clock = _clock()
    ctx = _ctx(sf, registry, clock)
    alerts.record_scheduler_tick(NOW)
    clock.advance(minutes=2)

    assert await alerts.check_alert_conditions(ctx) == []


async def test_a_runtime_that_has_never_ticked_is_not_reported_as_stale(sf, registry):
    """Nothing has run yet is not the same fact as the scheduler stopped running."""
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    assert alerts.last_scheduler_tick() is None
    assert await alerts.check_alert_conditions(ctx) == []


async def test_a_condition_that_persists_alerts_once_per_six_hours(sf, registry):
    from spatalk.ops import alerts

    clock = _clock()
    ctx = _ctx(sf, registry, clock)
    alerts.record_scheduler_tick(clock.now())
    await _job(sf, "text.followup", state="dead")

    assert await alerts.check_alert_conditions(ctx) == ["jobs_dead"]
    clock.advance(minutes=5)
    alerts.record_scheduler_tick(clock.now())
    assert await alerts.check_alert_conditions(ctx) == []
    assert len(await _alerts(sf)) == 1


# --- the scheduler hook -----------------------------------------------------------------


async def test_the_scheduler_checks_the_conditions_at_most_every_five_minutes(sf, registry):
    from spatalk.ops import alerts
    from spatalk.ledger.scheduler import ensure_alert_conditions_checked

    clock = _clock()
    ctx = _ctx(sf, registry, clock)
    alerts.record_scheduler_tick(clock.now())
    await _job(sf, "text.followup", state="dead")

    assert await ensure_alert_conditions_checked(ctx) == ["jobs_dead"]
    clock.advance(minutes=4)
    alerts.record_scheduler_tick(clock.now())
    # Inside the window the conditions are not even evaluated.
    assert await ensure_alert_conditions_checked(ctx) is None
    clock.advance(minutes=2)
    alerts.record_scheduler_tick(clock.now())
    # Evaluated again, but the six-hour dedup is what keeps the mailbox quiet.
    assert await ensure_alert_conditions_checked(ctx) == []


async def test_one_pass_of_the_scheduler_loop_records_a_tick(sf, registry):
    import asyncio

    from spatalk.ledger.scheduler import run_scheduler_forever
    from spatalk.ops import alerts

    ctx = _ctx(sf, registry, _clock())
    assert alerts.last_scheduler_tick() is None
    task = asyncio.create_task(run_scheduler_forever(ctx, interval_seconds=3600))
    try:
        for _ in range(300):
            if alerts.last_scheduler_tick() is not None:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
    assert alerts.last_scheduler_tick() == NOW


# --- /healthz ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def health_client(sf, registry):
    from spatalk.http.app import create_app

    ctx = _ctx(sf, registry, _clock(), _settings(git_commit="cafef00d"))
    app = create_app(ctx, start_background=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_healthz_carries_the_queue_and_scheduler_fields(sf, health_client):
    from spatalk.ops import alerts

    alerts.record_scheduler_tick(NOW)
    await _job(sf, "deliver.email", state="queued", run_at=NOW - timedelta(minutes=2))
    await _job(sf, "text.followup", state="dead")

    body = (await health_client.get("/healthz")).json()
    assert body["ok"] is True
    assert body["commit"] == "cafef00d"
    assert body["queued_jobs"] == 1
    assert body["oldest_queued_age_s"] == 120
    assert body["dead_jobs"] == 1
    assert body["last_scheduler_tick"] == NOW.isoformat()


async def test_healthz_on_an_idle_runtime_reports_zeroes_and_no_tick(health_client):
    body = (await health_client.get("/healthz")).json()
    assert body["queued_jobs"] == 0
    assert body["oldest_queued_age_s"] == 0
    assert body["dead_jobs"] == 0
    assert body["last_scheduler_tick"] is None


async def test_healthz_answers_the_two_keyword_checks_the_monitor_uses(health_client):
    """UptimeRobot matches raw text, so the exact bytes matter, not the parsed shape."""
    raw = (await health_client.get("/healthz")).text
    assert '"ok":true' in raw
    assert '"dead_jobs":0' in raw


# --- PII scrubbing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "number",
    ["+19055550100", "905-703-7546", "(905) 703-7546", "905.703.7546", "+1 905 555 0100"],
)
def test_the_scrubber_masks_a_phone_number_in_every_shape_a_caller_gives_it(number):
    from spatalk.ops.alerts import scrub_pii

    out = scrub_pii(f"call from {number} failed")
    assert number not in out
    assert "5550100" not in out and "7037546" not in out
    assert "[phone]" in out


def test_the_scrubber_masks_an_email_address():
    from spatalk.ops.alerts import scrub_pii

    out = scrub_pii("could not reach sarah.lee+book@gmail.com about it")
    assert "sarah.lee+book@gmail.com" not in out
    assert "[email]" in out


def test_the_scrubber_leaves_operational_numbers_alone():
    """A timestamp, an item id and a job id are what the alert is *for*."""
    from spatalk.ops.alerts import scrub_pii

    text = "job 41 for item 7 failed at 2026-09-01T18:00:00+00:00 after 3 attempts"
    assert scrub_pii(text) == text


def test_a_sentry_breadcrumb_is_scrubbed_before_it_leaves_the_process():
    from spatalk.ops.alerts import scrub_breadcrumb

    crumb = scrub_breadcrumb(
        {
            "message": "sms to +19055550100 failed",
            "data": {"to": "sarah@example.com", "attempt": 2},
        },
        None,
    )
    assert "+19055550100" not in crumb["message"] and "[phone]" in crumb["message"]
    assert crumb["data"]["to"] == "[email]"
    assert crumb["data"]["attempt"] == 2


def test_a_sentry_event_is_scrubbed_message_exception_and_breadcrumbs():
    from spatalk.ops.alerts import scrub_event

    event = scrub_event(
        {
            "message": "failed for 905-703-7546",
            "logentry": {"message": "failed for 905-703-7546"},
            "exception": {"values": [{"type": "ValueError", "value": "bad to=+19055550100"}]},
            "breadcrumbs": {"values": [{"message": "from sarah@example.com"}]},
        },
        None,
    )
    assert "703-7546" not in json.dumps(event)
    assert "sarah@example.com" not in json.dumps(event)
    assert event["exception"]["values"][0]["type"] == "ValueError"


# --- Sentry and log format --------------------------------------------------------------


def test_sentry_is_not_initialised_without_a_dsn(monkeypatch):
    from spatalk.ops import alerts

    calls = []
    monkeypatch.setattr(alerts, "_sentry_init", lambda **kw: calls.append(kw))
    assert alerts.init_sentry(_settings()) is False
    assert calls == []


def test_sentry_is_initialised_with_scrubbers_when_a_dsn_is_set(monkeypatch):
    from spatalk.ops import alerts

    calls = []
    monkeypatch.setattr(alerts, "_sentry_init", lambda **kw: calls.append(kw))
    assert alerts.init_sentry(_settings(sentry_dsn="https://k@sentry.test/1", git_commit="c0")) is True

    (kw,) = calls
    assert kw["dsn"] == "https://k@sentry.test/1"
    assert kw["send_default_pii"] is False
    assert kw["before_send"] is alerts.scrub_event
    assert kw["before_breadcrumb"] is alerts.scrub_breadcrumb
    assert kw["release"] == "c0"


def test_a_missing_sentry_package_is_a_warning_not_a_crash(monkeypatch):
    from spatalk.ops import alerts

    def missing(**kw):
        raise ImportError("no sentry_sdk")

    monkeypatch.setattr(alerts, "_sentry_init", missing)
    assert alerts.init_sentry(_settings(sentry_dsn="https://k@sentry.test/1")) is False


def test_the_default_log_format_leaves_loguru_alone(restore_logging):
    from spatalk.ops.alerts import configure_logging

    assert configure_logging(_settings()) is False


def test_log_format_json_emits_one_json_object_per_line(capsys, restore_logging):
    from loguru import logger

    from spatalk.ops.alerts import configure_logging

    assert configure_logging(_settings(log_format="json")) is True
    logger.info("hello {}", "ops")
    line = capsys.readouterr().err.strip().splitlines()[-1]
    assert json.loads(line)["record"]["message"] == "hello ops"


# --- configuration and the runbook ------------------------------------------------------


def test_the_operations_settings_read_their_documented_environment_variables(monkeypatch):
    from spatalk.settings import Settings

    monkeypatch.setenv("OPS_SMS_NUMBER", OPS_SMS)
    monkeypatch.setenv("SENTRY_DSN", "https://k@sentry.test/1")
    monkeypatch.setenv("LOG_FORMAT", "json")
    s = Settings(_env_file=None)
    assert (s.ops_sms_number, s.sentry_dsn, s.log_format) == (
        OPS_SMS,
        "https://k@sentry.test/1",
        "json",
    )


def test_the_env_example_names_every_operations_variable():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for var in ("OPS_EMAIL", "OPS_SMS_NUMBER", "SENTRY_DSN", "LOG_FORMAT", "GIT_COMMIT"):
        assert f"\n{var}=" in text, f".env.example does not name {var}"


def test_no_env_example_value_is_actually_an_inline_comment():
    """QA gate B: python-dotenv only strips an inline comment when the value is non-empty,
    so `GIT_COMMIT=   # set by the build` made /healthz report the comment as the commit."""
    from dotenv import dotenv_values

    poisoned = {
        k: v
        for k, v in dotenv_values(ROOT / ".env.example").items()
        if v and v.lstrip().startswith("#")
    }
    assert poisoned == {}


def test_the_monitoring_runbook_carries_the_checks_the_founder_must_create():
    text = (REPO / "docs" / "runbooks" / "monitoring.md").read_text(encoding="utf-8")
    for needed in ('"ok":true', '"dead_jobs":0', "/healthz", "UptimeRobot", "MEDIA_HOST"):
        assert needed in text, f"monitoring runbook is missing {needed!r}"
    assert "OPS_EMAIL" in text and "OPS_SMS_NUMBER" in text
    assert "SENTRY_DSN" in text and "LOG_FORMAT" in text
