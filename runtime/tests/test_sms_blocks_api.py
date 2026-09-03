"""Block list management (plan F, Task F2): internal API, health counts, CLI.

A person blocks or unblocks a number from the portal (through `/internal`) or from the
command line; both refuse a staff number, both write an audit row, and the health endpoint
tells the portal how many numbers are muted or blocked and how many replies went out today.
"""

from __future__ import annotations

from datetime import timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

INTERNAL_KEY = "test-internal-key"
ACTOR = "owner@skincentrix.test"
STAFF = "+15195550123"
CALLER = "+19055550101"
OTHER = "+19055550102"
THIRD = "+19055550103"


@pytest_asyncio.fixture
async def ctx(sf, registry, fixed_clock, monkeypatch):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings

    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", STAFF)
    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=Settings(_env_file=None, secret_key="s", internal_api_key=INTERNAL_KEY),
    )


@pytest_asyncio.fixture
async def client(ctx):
    from spatalk.http.app import create_app

    app = create_app(ctx, start_background=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as c:
        yield c


async def _audit(sf):
    from spatalk.models import AuditLog

    async with sf() as s:
        rows = (await s.scalars(select(AuditLog).order_by(AuditLog.id))).all()
    return [(r.actor, r.action, r.record_type, r.record_id) for r in rows]


async def _sms_reply(sf, fixed_clock, tenant_id, caller, at):
    from spatalk.conversations import append_message, start_conversation

    cid = await start_conversation(sf, tenant_id, "sms", f"c-{caller}", caller)
    await append_message(sf, cid, "user", "hi", at=at)
    await append_message(sf, cid, "assistant", "We open at ten.", at=at)


# ----- internal API ----------------------------------------------------------------------


async def test_a_block_is_listed_audited_and_refused_for_a_staff_number(client, sf):
    r = await client.get("/internal/tenants/skincentrix/sms-blocks")
    assert r.status_code == 200 and r.json() == []

    r = await client.post(
        "/internal/tenants/skincentrix/sms-blocks", json={"phone": CALLER, "actor": ACTOR}
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["phone"], body["until"], body["reason"]) == (CALLER, None, "manual")
    assert ACTOR in body["created_by"]

    r = await client.get("/internal/tenants/skincentrix/sms-blocks")
    assert [b["phone"] for b in r.json()] == [CALLER]

    r = await client.post(
        "/internal/tenants/skincentrix/sms-blocks", json={"phone": STAFF, "actor": ACTOR}
    )
    assert r.status_code == 409 and "staff" in r.json()["detail"]

    r = await client.post(
        "/internal/tenants/skincentrix/sms-blocks", json={"phone": "hello", "actor": ACTOR}
    )
    assert r.status_code == 422

    rows = await _audit(sf)
    assert [(a, t, i) for _, a, t, i in rows] == [("sms.block", "sms_block", CALLER)]
    assert all(ACTOR in actor for actor, *_ in rows)


async def test_removing_a_block_or_a_mute_is_audited_and_absent_is_404(client, ctx, sf, registry):
    from spatalk.text.flood import mute

    cfg = await registry.get("skincentrix")
    await mute(ctx, cfg, OTHER, ctx.clock.now() + timedelta(hours=2), "flood", "system:flood")
    r = await client.get("/internal/tenants/skincentrix/sms-blocks")
    assert [(b["phone"], b["reason"]) for b in r.json()] == [(OTHER, "flood")]
    assert r.json()[0]["until"] is not None

    r = await client.delete(
        f"/internal/tenants/skincentrix/sms-blocks/{OTHER}", params={"actor": ACTOR}
    )
    assert r.status_code == 200 and r.json() == {"removed": True}
    r = await client.delete(
        f"/internal/tenants/skincentrix/sms-blocks/{OTHER}", params={"actor": ACTOR}
    )
    assert r.status_code == 404
    assert [(a, t, i) for _, a, t, i in await _audit(sf)] == [("sms.unblock", "sms_block", OTHER)]


async def test_health_counts_muted_blocked_and_todays_replies(client, ctx, sf, registry, fixed_clock):
    from spatalk.text.flood import block, mute

    cfg = await registry.get("skincentrix")
    now = fixed_clock.now()
    await mute(ctx, cfg, CALLER, now + timedelta(hours=1), "flood", "system:flood")
    await mute(ctx, cfg, OTHER, now - timedelta(hours=1), "flood", "system:flood")   # expired
    await block(ctx, cfg, THIRD, "cli:test")
    await _sms_reply(sf, fixed_clock, "skincentrix", "+19055550110", now - timedelta(hours=2))
    await _sms_reply(sf, fixed_clock, "skincentrix", "+19055550111", now - timedelta(minutes=5))
    await _sms_reply(sf, fixed_clock, "skincentrix", "+19055550112", now - timedelta(days=1))

    r = await client.get("/internal/tenants/skincentrix/health")
    assert r.status_code == 200
    h = r.json()
    assert (h["sms_muted_numbers"], h["sms_blocked_numbers"], h["sms_replies_today"]) == (1, 1, 2)


async def test_the_block_routes_require_the_internal_key(ctx):
    from spatalk.http.app import create_app

    app = create_app(ctx, start_background=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://runtime") as c:
        r = await c.get("/internal/tenants/skincentrix/sms-blocks")
        assert r.status_code == 401
        r = await c.post(
            "/internal/tenants/skincentrix/sms-blocks", json={"phone": CALLER, "actor": ACTOR}
        )
        assert r.status_code == 401


# ----- CLI -------------------------------------------------------------------------------


async def test_cli_work_blocks_lists_unblocks_and_refuses_staff(ctx):
    from spatalk import cli

    code, text = await cli.sms_block_work(ctx, "skincentrix", CALLER, "cli:test")
    assert (code, text) == (0, f"{CALLER} blocked for skincentrix")

    code, text = await cli.sms_blocks_work(ctx, "skincentrix")
    assert code == 0 and CALLER in text and "permanent" in text and "cli:test" in text

    code, text = await cli.sms_block_work(ctx, "skincentrix", STAFF, "cli:test")
    assert code == 1 and "staff" in text

    code, text = await cli.sms_unblock_work(ctx, "skincentrix", CALLER)
    assert (code, text) == (0, f"{CALLER} removed from skincentrix's block list")
    code, text = await cli.sms_unblock_work(ctx, "skincentrix", CALLER)
    assert code == 1 and "no block" in text
    code, text = await cli.sms_blocks_work(ctx, "skincentrix")
    assert code == 0 and "no blocked" in text


def test_the_cli_exposes_the_sms_commands_and_checks_the_number_format():
    from typer.testing import CliRunner

    from spatalk.cli import app

    runner = CliRunner()
    r = runner.invoke(app, ["sms", "--help"])
    assert r.exit_code == 0
    for word in ("block", "unblock", "blocks"):
        assert word in r.output
    r = runner.invoke(app, ["sms", "block", "skincentrix", "905-555-0101"])
    assert r.exit_code == 1 and "E.164" in r.output
