"""Task E1: the loop guard on inbound calls, and the carrier failover bin.

Spec §10 weakness 7: the clinic's back-line may not exist, and the forwarding chain is
configured by hand at TELUS. If our own number is ever forwarded back to us, or a member of
staff calls the assistant from the clinic's own line, the assistant must not answer it: the
call would be the assistant talking to the assistant, billed both ways, with a conversation
row that means nothing. It says the fixed `loop_guard` script, hangs up, records an alert
for the founder, and starts no conversation.

The failover bin is the other half: wording the carrier speaks when our server cannot be
reached at all, printed by `spatalk texml failover-bin <tenant>` for the founder to paste
into Telnyx (no server is involved when it plays, which is the point).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "tenants" / "skincentrix"

OWN_VOICE = "+19055550100"          # the number tests/conftest.py maps to skincentrix
PUBLIC_PHONE_E164 = "+19057037546"  # tenant.yaml carries it as "905-703-7546"
CALLER = "+19055550101"
SMS_FROM = "+18885550100"
BOOKING_URL = "https://skincentrix.janeapp.com/"
NOW = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


def _bundle_config(**overrides):
    from spatalk.tenants.bundle import load_bundle

    cfg = load_bundle(BUNDLE)
    return cfg.model_copy(update=overrides) if overrides else cfg


@pytest.fixture
async def ctx(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.settings import Settings

    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=None,
        delivery=None,
        settings=Settings(_env_file=None, secret_key="s", media_ws_host="media.test"),
    )


@pytest.fixture
async def client(ctx):
    from spatalk.http.app import attach_router
    from spatalk.voice.texml import router

    app = FastAPI()
    attach_router(app, router)
    app.state.ctx = ctx
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        yield c


async def _counts(sf):
    from spatalk.models import AlertLog, Conversation

    async with sf() as s:
        conversations = await s.scalar(select(func.count()).select_from(Conversation))
        alerts = list((await s.scalars(select(AlertLog))).all())
    return conversations, alerts


# --- is_own_number ----------------------------------------------------------------------


async def test_is_own_number_true_for_a_number_the_registry_maps_to_this_tenant(registry):
    from spatalk.ops.loop_guard import is_own_number

    cfg = await registry.get("skincentrix")
    assert await is_own_number(cfg, registry, OWN_VOICE) is True


async def test_is_own_number_true_for_the_public_phone_in_local_format(registry):
    from spatalk.ops.loop_guard import is_own_number

    cfg = await registry.get("skincentrix")
    assert cfg.public_phone == "905-703-7546"
    # The carrier presents E.164; the bundle carries the clinic's own number as typed.
    assert await is_own_number(cfg, registry, PUBLIC_PHONE_E164) is True
    assert await is_own_number(cfg, registry, "905-703-7546") is True
    assert await is_own_number(cfg, registry, "(905) 703-7546") is True


async def test_is_own_number_false_for_an_ordinary_caller(registry):
    from spatalk.ops.loop_guard import is_own_number

    cfg = await registry.get("skincentrix")
    assert await is_own_number(cfg, registry, CALLER) is False
    assert await is_own_number(cfg, registry, "") is False
    assert await is_own_number(cfg, registry, "anonymous") is False


async def test_is_own_number_false_for_another_tenants_number(sf, registry):
    """A number in the registry that belongs to somebody else is not a loop."""
    from spatalk.models import Tenant
    from spatalk.ops.loop_guard import is_own_number

    async with sf() as s, s.begin():
        s.add(Tenant(id="other-clinic", name="Other Clinic"))
    await registry.add_number("+14165550199", "other-clinic", "voice")
    cfg = await registry.get("skincentrix")
    assert await is_own_number(cfg, registry, "+14165550199") is False


# --- POST /telnyx/texml -----------------------------------------------------------------


async def test_texml_hangs_up_on_a_call_from_our_own_number(client, sf):
    r = await client.post(
        "/telnyx/texml", data={"From": OWN_VOICE, "To": OWN_VOICE, "CallSid": "loop-1"}
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert "<Hangup" in r.text and "<Stream" not in r.text
    assert "cannot transfer to itself" in r.text
    conversations, alerts = await _counts(sf)
    assert conversations == 0
    assert len(alerts) == 1
    assert alerts[0].key == f"loop_guard:skincentrix:{OWN_VOICE}"
    assert OWN_VOICE in alerts[0].subject


async def test_a_second_loop_call_inside_the_window_raises_no_second_alert(client, sf):
    """The alert goes through notify: one row with a sent_at, deduplicated per number."""
    for sid in ("loop-3", "loop-4"):
        await client.post(
            "/telnyx/texml", data={"From": OWN_VOICE, "To": OWN_VOICE, "CallSid": sid}
        )
    conversations, alerts = await _counts(sf)
    assert conversations == 0
    assert len(alerts) == 1 and alerts[0].sent_at is not None


async def test_texml_hangs_up_on_a_call_from_the_clinics_public_phone(client, sf):
    r = await client.post(
        "/telnyx/texml",
        data={"From": PUBLIC_PHONE_E164, "To": OWN_VOICE, "CallSid": "loop-2"},
    )
    assert "<Hangup" in r.text and "<Stream" not in r.text
    assert "cannot transfer to itself" in r.text
    conversations, alerts = await _counts(sf)
    assert conversations == 0
    assert len(alerts) == 1
    assert alerts[0].key == f"loop_guard:skincentrix:{PUBLIC_PHONE_E164}"


async def test_texml_still_streams_for_an_ordinary_caller(client, sf):
    r = await client.post(
        "/telnyx/texml", data={"From": CALLER, "To": OWN_VOICE, "CallSid": "abc"}
    )
    assert '<Stream url="wss://media.test/ws/' in r.text and 'bidirectionalMode="rtp"' in r.text
    conversations, alerts = await _counts(sf)
    assert conversations == 1 and alerts == []


# --- the carrier failover bin -----------------------------------------------------------


def test_failover_bin_is_the_tenants_wording_with_no_server_in_the_loop():
    from spatalk.voice.texml import failover_bin

    body = failover_bin(_bundle_config(sms_from_number=SMS_FROM), NOW)
    assert body.startswith("<Response>") and body.endswith("</Response>")
    assert '<Say voice="female" language="en-CA">' in body and "<Hangup/>" in body
    assert "We can't take your call right now." in body
    assert SMS_FROM in body and BOOKING_URL in body
    # A bin is static: it can hold no placeholder and must promise nothing.
    assert "{" not in body and "}" not in body
    for banned in ("booked", "confirmed", "scheduled"):
        assert banned not in body.lower()


def test_cli_prints_the_failover_bin(monkeypatch):
    from typer.testing import CliRunner

    from spatalk import cli
    from spatalk.clock import FixedClock

    cfg = _bundle_config(sms_from_number=SMS_FROM)

    class _Registry:
        async def get(self, tenant_id: str):
            assert tenant_id == "skincentrix"
            return cfg

    class _Ctx:
        registry = _Registry()
        clock = FixedClock(NOW)

    monkeypatch.setattr(cli, "_ctx", lambda: _Ctx())
    result = CliRunner().invoke(cli.app, ["texml", "failover-bin", "skincentrix"])
    assert result.exit_code == 0, result.output
    assert '<Say voice="female" language="en-CA">' in result.output
    assert "<Hangup/></Response>" in result.output
    assert SMS_FROM in result.output and BOOKING_URL in result.output


def test_failover_runbook_records_the_verification():
    runbook = ROOT.parent / "docs" / "runbooks" / "failover.md"
    assert runbook.exists()
    body = runbook.read_text(encoding="utf-8")
    assert "spatalk texml failover-bin" in body
    assert "Failover URL" in body
    assert "<Record>" in body  # the voicemail variant and why it is opt-in
