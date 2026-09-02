"""The portal's only way in: `/internal/*` (portal plan, Task C3).

Every test here is named after a behaviour in the task's Interfaces and Behaviour lists.
The seeded fixture is one tenant with two conversations, two items and a day of usage, so
day grouping, tenant-time boundaries and cost estimation can all be asserted on real rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

INTERNAL_KEY = "test-internal-key"
ACTOR = "owner@example.com"

# The clock every test runs on: 2026-09-01 18:00 UTC = 14:00 America/Toronto.
TODAY_LOCAL = "2026-09-01"
YESTERDAY_LOCAL = "2026-08-31"


def _dt(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def ctx(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings

    return jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=Settings(
            _env_file=None,
            secret_key="s", internal_api_key=INTERNAL_KEY, git_commit="deadbeefcafe"
        ),
    )


@pytest_asyncio.fixture
async def app(ctx):
    from spatalk.http.app import create_app

    return create_app(ctx, start_background=False)


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": INTERNAL_KEY, "X-Actor": ACTOR},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def seeded(sf):
    """Two conversations, three items, one day of voice usage and one day of SMS usage."""
    from spatalk.models import Conversation, Item, Message, UsageEvent

    voice_id = uuid.uuid4()
    sms_id = uuid.uuid4()
    async with sf() as s, s.begin():
        s.add(
            Conversation(
                id=voice_id,
                tenant_id="skincentrix",
                channel="voice",
                external_ref="v3:abc",
                caller="+19055550101",
                band=1,
                health_context=True,
                latency_ms=[400, 800, 1200],
                started_at=_dt(2026, 9, 1, 17, 0),
                ended_at=_dt(2026, 9, 1, 17, 5),
            )
        )
        s.add(
            Conversation(
                id=sms_id,
                tenant_id="skincentrix",
                channel="sms",
                external_ref="+19055550102",
                caller="+19055550102",
                band=2,
                started_at=_dt(2026, 8, 31, 16, 0),
                last_message_at=_dt(2026, 8, 31, 16, 5),
            )
        )
        s.add_all(
            [
                Message(
                    conversation_id=voice_id,
                    role="user",
                    text="How much is a facial?",
                    created_at=_dt(2026, 9, 1, 17, 1),
                ),
                Message(
                    conversation_id=voice_id,
                    role="assistant",
                    text="Facials start at $99.",
                    created_at=_dt(2026, 9, 1, 17, 2),
                ),
            ]
        )
        s.add_all(
            [
                Item(
                    tenant_id="skincentrix",
                    conversation_id=voice_id,
                    type="callback",
                    urgency="urgent",
                    channel="voice",
                    contact_name="Dana",
                    contact_phone="+19055550101",
                    preferred_window={},
                    state="open",
                    due_at=_dt(2026, 9, 1, 17, 30),  # already overdue at 18:00
                    owner="info@skincentrix.com",
                    created_at=_dt(2026, 9, 1, 17, 3),
                ),
                Item(
                    tenant_id="skincentrix",
                    conversation_id=sms_id,
                    type="new_booking",
                    urgency="normal",
                    channel="sms",
                    preferred_window={},
                    state="open",
                    due_at=_dt(2026, 9, 2, 20, 0),  # not yet due
                    owner="info@skincentrix.com",
                    created_at=_dt(2026, 8, 31, 16, 5),
                ),
                Item(
                    tenant_id="skincentrix",
                    conversation_id=None,
                    type="question",
                    urgency="normal",
                    channel="chat",
                    preferred_window={},
                    state="resolved",
                    due_at=_dt(2026, 8, 31, 20, 0),
                    owner="info@skincentrix.com",
                    resolved_at=_dt(2026, 8, 31, 21, 0),
                    resolved_by="dana@skincentrix.com",
                    created_at=_dt(2026, 8, 31, 16, 6),
                ),
            ]
        )
        usage = [
            ("voice", "telnyx", "telephony_seconds", 300),
            ("voice", "soniox", "stt_seconds", 150),
            ("voice", "inworld", "tts_chars", 1200),
            ("voice", "gemini-2.5-flash", "llm_input_tokens", 5000),
            ("voice", "gemini-2.5-flash", "llm_cached_tokens", 20000),
            ("voice", "gemini-2.5-flash", "llm_output_tokens", 300),
        ]
        for channel, provider, unit, qty in usage:
            s.add(
                UsageEvent(
                    tenant_id="skincentrix",
                    conversation_id=voice_id,
                    channel=channel,
                    provider=provider,
                    unit=unit,
                    qty=qty,
                    created_at=_dt(2026, 9, 1, 17, 5),
                )
            )
        for unit, qty in (("sms_in", 1), ("sms_out", 2)):
            s.add(
                UsageEvent(
                    tenant_id="skincentrix",
                    conversation_id=sms_id,
                    channel="sms",
                    provider="telnyx",
                    unit=unit,
                    qty=qty,
                    created_at=_dt(2026, 8, 31, 16, 5),
                )
            )
    yield {"voice": voice_id, "sms": sms_id}


async def _audit_rows(sf):
    from spatalk.models import AuditLog

    async with sf() as s:
        return list((await s.scalars(select(AuditLog).order_by(AuditLog.id))).all())


# --- authentication -------------------------------------------------------------------


async def test_a_request_without_the_internal_key_is_401(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://runtime") as c:
        r = await c.get("/internal/tenants")
    assert r.status_code == 401


async def test_a_request_with_the_wrong_internal_key_is_401(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://runtime",
        headers={"X-Internal-Key": "not-the-key"},
    ) as c:
        r = await c.get("/internal/tenants")
    assert r.status_code == 401


async def test_every_internal_route_requires_the_key(app):
    internal = [r for r in app.routes if getattr(r, "path", "").startswith("/internal")]
    assert internal, "no /internal routes are attached"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://runtime") as c:
        for route in internal:
            path = route.path.replace("{tenant_id}", "skincentrix").replace("{item_id}", "1")
            path = path.replace("{conversation_id}", str(uuid.uuid4()))
            method = sorted(set(route.methods) - {"HEAD", "OPTIONS"})[0]
            r = await c.request(method, path)
            assert r.status_code == 401, f"{method} {path} answered {r.status_code}"


# --- tenants and configuration --------------------------------------------------------


async def test_tenants_lists_id_name_version_numbers_and_tier(client):
    r = await client.get("/internal/tenants")
    assert r.status_code == 200
    assert r.json() == [
        {
            "id": "skincentrix",
            "name": "Skincentrix",
            "version": 1,
            "numbers": [
                {"number": "+12899170079", "kind": "sms"},
                {"number": "+19055550100", "kind": "voice"},
            ],
            "sms_from_number": "+12899170079",
            "integration_tier": "C",
        }
    ]


async def test_get_config_returns_the_current_version_and_the_config(client):
    r = await client.get("/internal/tenants/skincentrix/config")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert body["config"]["id"] == "skincentrix"
    assert body["config"]["scripts"]["goodbye"].startswith("Thanks for calling")


async def test_get_config_for_an_unknown_tenant_is_404(client):
    assert (await client.get("/internal/tenants/nobody/config")).status_code == 404


async def test_post_tenants_creates_a_tenant_at_version_one(client):
    cfg = (await client.get("/internal/tenants/skincentrix/config")).json()["config"]
    # A second tenant cannot claim skincentrix's messaging number, so it starts without one.
    cfg = {
        **cfg,
        "id": "otherclinic",
        "name": "Other Clinic",
        "voice_numbers": ["+15145550111"],
        "sms_from_number": None,
    }
    r = await client.post(
        "/internal/tenants", json={"config": cfg, "created_by": "admin@agency.test"}
    )
    assert r.status_code == 200
    assert r.json() == {"id": "otherclinic", "version": 1}
    listed = {t["id"]: t for t in (await client.get("/internal/tenants")).json()}
    assert listed["otherclinic"]["numbers"] == [{"number": "+15145550111", "kind": "voice"}]


async def test_put_config_writes_the_next_version_and_audits_config_save(client, ctx):
    cfg = (await client.get("/internal/tenants/skincentrix/config")).json()["config"]
    cfg["hours"]["mon"] = [["09:00", "17:00"]]
    r = await client.put(
        "/internal/tenants/skincentrix/config",
        json={"config": cfg, "created_by": ACTOR},
    )
    assert r.status_code == 200 and r.json() == {"version": 2}
    fresh = (await client.get("/internal/tenants/skincentrix/config")).json()
    assert fresh["version"] == 2
    assert fresh["config"]["hours"]["mon"] == [["09:00", "17:00"]]
    rows = await _audit_rows(ctx.sf)
    assert [(a.actor, a.action, a.record_type, a.record_id) for a in rows] == [
        (f"portal:{ACTOR}", "config_save", "tenant", "skincentrix")
    ]


async def test_put_an_invalid_config_returns_422_with_the_field_path(client):
    cfg = (await client.get("/internal/tenants/skincentrix/config")).json()["config"]
    cfg["hours"]["mon"] = [["25:00", "17:00"]]
    r = await client.put(
        "/internal/tenants/skincentrix/config", json={"config": cfg, "created_by": ACTOR}
    )
    assert r.status_code == 422
    locs = [tuple(e["loc"]) for e in r.json()["detail"]]
    assert ("config", "hours") in locs
    # nothing was written
    assert (await client.get("/internal/tenants/skincentrix/config")).json()["version"] == 1


async def test_put_a_config_whose_id_differs_from_the_path_is_422(client):
    cfg = (await client.get("/internal/tenants/skincentrix/config")).json()["config"]
    cfg["id"] = "somewhere-else"
    r = await client.put(
        "/internal/tenants/skincentrix/config", json={"config": cfg, "created_by": ACTOR}
    )
    assert r.status_code == 422
    assert ("config", "id") in [tuple(e["loc"]) for e in r.json()["detail"]]


async def test_config_versions_lists_every_version_with_its_author(client):
    cfg = (await client.get("/internal/tenants/skincentrix/config")).json()["config"]
    await client.put(
        "/internal/tenants/skincentrix/config", json={"config": cfg, "created_by": ACTOR}
    )
    r = await client.get("/internal/tenants/skincentrix/config/versions")
    assert r.status_code == 200
    rows = r.json()
    assert [row["version"] for row in rows] == [2, 1]
    assert rows[0]["created_by"] == ACTOR and rows[1]["created_by"] == "test"
    assert rows[0]["created_at"]


async def test_rollback_creates_a_new_version_equal_to_the_chosen_one(client, ctx):
    original = (await client.get("/internal/tenants/skincentrix/config")).json()["config"]
    changed = {**original, "hours": {**original["hours"], "mon": [["09:00", "17:00"]]}}
    await client.put(
        "/internal/tenants/skincentrix/config", json={"config": changed, "created_by": ACTOR}
    )
    r = await client.post(
        "/internal/tenants/skincentrix/config/rollback",
        json={"version": 1, "created_by": ACTOR},
    )
    assert r.status_code == 200 and r.json() == {"version": 3}
    now = (await client.get("/internal/tenants/skincentrix/config")).json()
    assert now["version"] == 3 and now["config"] == original
    actions = [a.action for a in await _audit_rows(ctx.sf)]
    assert actions == ["config_save", "config_rollback"]


async def test_rollback_to_an_unknown_version_is_404(client):
    r = await client.post(
        "/internal/tenants/skincentrix/config/rollback", json={"version": 9, "created_by": ACTOR}
    )
    assert r.status_code == 404


async def test_the_tenant_config_json_schema_is_served(client):
    r = await client.get("/internal/schema/tenant-config")
    assert r.status_code == 200
    schema = r.json()
    assert schema["title"] == "TenantConfig"
    assert {"id", "name", "hours", "scripts", "services"} <= set(schema["properties"])
    assert "Scripts" in schema["$defs"]


async def test_a_bundle_posted_as_multipart_creates_a_tenant_version(client):
    from pathlib import Path

    bundle = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
    files = {
        "tenant": ("tenant.yaml", (bundle / "tenant.yaml").read_bytes(), "application/x-yaml"),
        "services": (
            "services.yaml",
            (bundle / "services.yaml").read_bytes(),
            "application/x-yaml",
        ),
        "knowledge": ("knowledge.md", (bundle / "knowledge.md").read_bytes(), "text/markdown"),
        "scripts": ("scripts.yaml", (bundle / "scripts.yaml").read_bytes(), "application/x-yaml"),
        "guard": ("guard.yaml", (bundle / "guard.yaml").read_bytes(), "application/x-yaml"),
    }
    r = await client.post(
        "/internal/tenants/from-bundle", files=files, data={"created_by": ACTOR}
    )
    assert r.status_code == 200
    assert r.json() == {"id": "skincentrix", "version": 2}


async def test_an_invalid_bundle_posted_as_multipart_is_422(client):
    from pathlib import Path

    bundle = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
    files = {
        "tenant": ("tenant.yaml", b"id: broken\n", "application/x-yaml"),
        "services": (
            "services.yaml",
            (bundle / "services.yaml").read_bytes(),
            "application/x-yaml",
        ),
        "knowledge": ("knowledge.md", b"nothing", "text/markdown"),
        "scripts": ("scripts.yaml", (bundle / "scripts.yaml").read_bytes(), "application/x-yaml"),
        "guard": ("guard.yaml", (bundle / "guard.yaml").read_bytes(), "application/x-yaml"),
    }
    r = await client.post(
        "/internal/tenants/from-bundle", files=files, data={"created_by": ACTOR}
    )
    assert r.status_code == 422


# --- usage, conversations, items ------------------------------------------------------


async def test_usage_groups_days_in_tenant_time_and_estimates_cost(client, seeded):
    from spatalk.rates import estimate_cad

    r = await client.get(
        f"/internal/tenants/skincentrix/usage?from={YESTERDAY_LOCAL}&to={TODAY_LOCAL}"
    )
    assert r.status_code == 200
    body = r.json()
    days = {d["date"]: d for d in body["days"]}
    assert list(days) == [YESTERDAY_LOCAL, TODAY_LOCAL]
    today = days[TODAY_LOCAL]
    assert today["calls"] == 1
    assert today["call_minutes"] == 5.0
    assert today["llm_cached_tokens"] == 20000
    assert today["tts_chars"] == 1200
    assert today["est_cost_cad"] == estimate_cad(
        {
            "telephony_seconds": 300,
            "stt_seconds": 150,
            "tts_chars": 1200,
            "llm_input_tokens": 5000,
            "llm_cached_tokens": 20000,
            "llm_output_tokens": 300,
        }
    )
    yesterday = days[YESTERDAY_LOCAL]
    assert (yesterday["sms_in"], yesterday["sms_out"], yesterday["calls"]) == (1, 2, 0)
    assert body["totals"]["calls"] == 1
    assert body["totals"]["sms_out"] == 2
    assert body["totals"]["est_cost_cad"] == estimate_cad(
        {
            "telephony_seconds": 300,
            "stt_seconds": 150,
            "tts_chars": 1200,
            "llm_input_tokens": 5000,
            "llm_cached_tokens": 20000,
            "llm_output_tokens": 300,
            "sms_in": 1,
            "sms_out": 2,
        }
    )


async def test_usage_defaults_to_the_last_thirty_tenant_days(client, seeded):
    body = (await client.get("/internal/tenants/skincentrix/usage")).json()
    assert len(body["days"]) == 30
    assert body["days"][-1]["date"] == TODAY_LOCAL
    assert body["days"][0]["date"] == "2026-08-03"


async def test_conversations_are_listed_newest_first_with_the_caller_masked(client, seeded):
    r = await client.get("/internal/tenants/skincentrix/conversations")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    first = body["items"][0]
    assert first["channel"] == "voice"
    assert first["caller_masked"] == "***0101"
    assert "+19055550101" not in r.text
    assert first["duration_s"] == 300
    assert first["band"] == 1 and first["health_context"] is True
    assert first["item_count"] == 1
    assert first["controller"] == "ai"


async def test_conversations_filter_by_channel_band_and_date(client, seeded):
    only_sms = (
        await client.get("/internal/tenants/skincentrix/conversations?channel=sms")
    ).json()
    assert only_sms["total"] == 1 and only_sms["items"][0]["channel"] == "sms"
    band_one = (await client.get("/internal/tenants/skincentrix/conversations?band=1")).json()
    assert band_one["total"] == 1 and band_one["items"][0]["band"] == 1
    today = (
        await client.get(
            f"/internal/tenants/skincentrix/conversations?from={TODAY_LOCAL}&to={TODAY_LOCAL}"
        )
    ).json()
    assert today["total"] == 1 and today["items"][0]["channel"] == "voice"


async def test_conversations_paginate_with_a_default_of_fifty_and_a_maximum_of_two_hundred(
    client, seeded
):
    page = (
        await client.get("/internal/tenants/skincentrix/conversations?page=2&page_size=1")
    ).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert page["items"][0]["channel"] == "sms"
    too_big = await client.get("/internal/tenants/skincentrix/conversations?page_size=500")
    assert too_big.status_code == 422


async def test_a_transcript_read_returns_messages_and_items_and_audits_the_actor(
    client, seeded, ctx
):
    r = await client.get(f"/internal/conversations/{seeded['voice']}")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation"]["caller"] == "+19055550101"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["text"] == "How much is a facial?"
    assert [i["type"] for i in body["items"]] == ["callback"]
    rows = await _audit_rows(ctx.sf)
    assert [(a.actor, a.action, a.record_type, a.record_id) for a in rows] == [
        (f"portal:{ACTOR}", "read_transcript", "conversation", str(seeded["voice"]))
    ]


async def test_reading_an_unknown_conversation_is_404(client, seeded):
    assert (await client.get(f"/internal/conversations/{uuid.uuid4()}")).status_code == 404


async def test_items_are_listed_by_state(client, seeded):
    open_items = (await client.get("/internal/tenants/skincentrix/items")).json()
    assert [i["type"] for i in open_items] == ["callback", "new_booking"]
    assert open_items[0]["contact_phone"] == "+19055550101"
    resolved = (
        await client.get("/internal/tenants/skincentrix/items?state=resolved")
    ).json()
    assert [i["type"] for i in resolved] == ["question"]
    every = (await client.get("/internal/tenants/skincentrix/items?state=all")).json()
    assert len(every) == 3


async def test_acknowledge_and_resolve_record_the_actor_and_audit_the_action(
    client, seeded, ctx
):
    ack = await client.post("/internal/items/1/acknowledge", json={"actor": ACTOR})
    assert ack.status_code == 200
    assert ack.json()["state"] == "acknowledged"
    assert ack.json()["acknowledged_by"] == ACTOR
    res = await client.post("/internal/items/1/resolve", json={"actor": ACTOR})
    assert res.json()["state"] == "resolved" and res.json()["resolved_by"] == ACTOR
    rows = await _audit_rows(ctx.sf)
    assert [(a.actor, a.action, a.record_type, a.record_id) for a in rows] == [
        (f"portal:{ACTOR}", "ack", "item", "1"),
        (f"portal:{ACTOR}", "resolve", "item", "1"),
    ]


async def test_acting_on_an_unknown_item_is_404(client, seeded):
    assert (
        await client.post("/internal/items/999/resolve", json={"actor": ACTOR})
    ).status_code == 404


async def test_latency_reports_turns_p50_and_p95_per_day(client, seeded):
    r = await client.get("/internal/tenants/skincentrix/latency")
    assert r.status_code == 200
    assert r.json() == [{"date": TODAY_LOCAL, "turns": 3, "p50_ms": 800, "p95_ms": 1200}]


async def test_tenant_health_counts_open_and_overdue_items_and_last_activity(client, seeded):
    r = await client.get("/internal/tenants/skincentrix/health")
    assert r.status_code == 200
    body = r.json()
    assert body["open_items"] == 2
    assert body["overdue_items"] == 1
    assert body["config_version"] == 1
    assert body["last_call_at"].startswith("2026-09-01T17:00")
    # the last message on the text conversation, not when it opened
    assert body["last_sms_at"].startswith("2026-08-31T16:05")


async def test_runtime_health_reports_the_queue_depth_and_dead_jobs(client, ctx):
    from spatalk import jobs
    from spatalk.models import Job

    await jobs.enqueue(ctx.sf, "deliver.slack", {"item_id": 1})
    async with ctx.sf() as s, s.begin():
        s.add(Job(kind="deliver.email", payload={}, state="dead", run_at=_dt(2026, 9, 1, 12, 0)))
    r = await client.get("/internal/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["queued_jobs"] == 1
    assert body["dead_jobs"] == 1
    assert body["oldest_queued_age_s"] >= 0


async def test_the_rates_table_is_served(client):
    from spatalk.rates import load_rates

    r = await client.get("/internal/rates")
    assert r.status_code == 200
    assert r.json() == load_rates()


async def test_the_audit_endpoint_writes_a_row(client, ctx):
    r = await client.post(
        "/internal/audit",
        json={
            "actor": "portal:owner@example.com",
            "action": "export",
            "record_type": "tenant",
            "record_id": "skincentrix",
        },
    )
    assert r.status_code == 204
    rows = await _audit_rows(ctx.sf)
    assert [(a.actor, a.action, a.record_type, a.record_id) for a in rows] == [
        ("portal:owner@example.com", "export", "tenant", "skincentrix")
    ]


async def test_usage_for_an_unknown_tenant_is_404(client):
    assert (await client.get("/internal/tenants/nobody/usage")).status_code == 404


# --- /healthz -------------------------------------------------------------------------


async def test_healthz_reports_config_versions_and_the_deployed_commit(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["tenants"] == ["skincentrix"]
    assert body["config_versions"] == {"skincentrix": 1}
    assert body["commit"] == "deadbeefcafe"


# --- the rates table itself -----------------------------------------------------------


def test_the_packaged_rates_match_the_researched_table():
    import json
    from pathlib import Path

    from spatalk.rates import RATES_PATH

    root = Path(__file__).resolve().parents[2]
    researched = json.loads((root / "docs" / "research" / "rates.json").read_text("utf-8"))
    assert json.loads(RATES_PATH.read_text("utf-8")) == researched


def test_estimate_cad_prices_the_recommended_stack():
    from spatalk.rates import estimate_cad

    assert estimate_cad({}) == 0.0
    # 5 minutes of telephony at 0.0095 + 0.0035, 2.5 minutes of Soniox, 1200 Inworld chars,
    # and one Gemini 2.5 Flash turn, converted at the recorded USD->CAD rate.
    assert estimate_cad(
        {
            "telephony_seconds": 300,
            "stt_seconds": 150,
            "tts_chars": 1200,
            "llm_input_tokens": 5000,
            "llm_cached_tokens": 20000,
            "llm_output_tokens": 300,
        }
    ) == pytest.approx(0.1262, abs=5e-4)
    # one inbound and two outbound toll-free messages, carrier fees included
    assert estimate_cad({"sms_in": 1, "sms_out": 2}) == pytest.approx(0.0521, abs=5e-4)


def test_estimate_cad_accepts_call_minutes_instead_of_seconds():
    from spatalk.rates import estimate_cad

    assert estimate_cad({"call_minutes": 5}) == estimate_cad({"telephony_seconds": 300})
