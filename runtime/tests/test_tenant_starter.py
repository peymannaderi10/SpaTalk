"""A tenant from a few basics (onboarding roadmap, section 4, row 1).

The five-file bundle stays the only thing the runtime judges: `render_starter` turns the
basics into the five texts and `config_from_texts` reads them back, so a tenant born from
a form or from `spatalk tenant new` obeys exactly the rules `spatalk tenant import`
enforces. The starter's `scripts.yaml` and `guard.yaml` ship as package data and reach the
new tenant byte for byte, placeholders and all.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

INTERNAL_KEY = "test-internal-key"
ACTOR = "owner@example.com"

STARTER = resources.files("spatalk.tenants") / "starter"

HOURS = {
    "mon": [],
    "tue": [("10:00", "18:00")],
    "wed": [("10:00", "20:00")],
    "thu": [("12:00", "20:00")],
    "fri": [("10:00", "19:00")],
    "sat": [("10:00", "18:00")],
    "sun": [],
}


def _basics(**overrides):
    from spatalk.tenants.starter import TenantBasics

    data = {
        "id": "north-clinic",
        "name": "North Clinic",
        "timezone": "America/Toronto",
        "hours": HOURS,
        "booking_url": "https://north.janeapp.com/",
        "public_phone": "+19055550123",
        "owner_name": "Dana Front Desk",
        "owner_email": "owner@north.test",
    }
    data.update(overrides)
    return TenantBasics(**data)


def _body(**overrides) -> dict:
    body = {
        "id": "north-clinic",
        "name": "North Clinic",
        "timezone": "America/Toronto",
        "hours": {day: [list(span) for span in spans] for day, spans in HOURS.items()},
        "booking_url": "https://north.janeapp.com/",
        "public_phone": "+19055550123",
        "owner_name": "Dana Front Desk",
        "owner_email": "owner@north.test",
        "created_by": ACTOR,
    }
    body.update(overrides)
    return body


# --- rendering ------------------------------------------------------------------------


def test_the_starter_ships_the_four_fixed_files_as_package_data():
    for name in ("scripts.yaml", "guard.yaml", "knowledge.md", "services.yaml"):
        assert (STARTER / name).is_file(), f"starter is missing {name}"


def test_render_starter_yields_a_valid_config_from_the_basics():
    from spatalk.tenants.bundle import FILES, config_from_texts
    from spatalk.tenants.starter import render_starter

    texts = render_starter(_basics())
    assert set(texts) == set(FILES)

    cfg = config_from_texts(texts, source="starter")
    assert cfg.id == "north-clinic"
    assert cfg.name == "North Clinic"
    assert cfg.timezone == "America/Toronto"
    assert cfg.hours["tue"] == [("10:00", "18:00")]
    assert cfg.hours["mon"] == [] and cfg.hours["sun"] == []
    assert cfg.booking_url_default == "https://north.janeapp.com/"
    assert cfg.public_phone == "+19055550123"
    assert cfg.persona.assistant_name == "Ava"
    assert cfg.escalation.owner_name == "Dana Front Desk"
    assert cfg.escalation.owner_email == "owner@north.test"
    assert cfg.escalation.urgent_minutes == 15
    assert cfg.escalation.standard_business_hours == 3
    assert cfg.services == []
    assert cfg.delivery.digest_time_local == "07:30"
    # The same guard and social defaults Skincentrix carries.
    assert cfg.sms_guard.burst_limit == 12 and cfg.sms_guard.tenant_daily_replies == 400
    assert cfg.social.comment_mode == "keyword"
    assert "price" in cfg.social.comment_keywords
    assert cfg.social.public_reply_enabled is False


def test_the_staff_destinations_are_the_owner_email_and_an_environment_variable_name():
    from spatalk.tenants.bundle import config_from_texts
    from spatalk.tenants.starter import render_starter

    texts = render_starter(_basics())
    cfg = config_from_texts(texts, source="starter")
    kinds = [(d.kind, d.address, d.address_env) for d in cfg.delivery.destinations]
    assert kinds == [
        ("email", "owner@north.test", None),
        ("sms", None, "NORTH_CLINIC_STAFF_SMS"),
    ]
    # CLAUDE.md non-negotiable 5: the bundle names the variable, never the number.
    assert not any(ch.isdigit() for ch in "NORTH_CLINIC_STAFF_SMS")
    assert "+1" not in texts["tenant.yaml"].replace("+19055550123", "")


def test_the_rendered_scripts_and_guard_are_the_starter_files_byte_for_byte():
    from spatalk.tenants.starter import render_starter

    texts = render_starter(_basics(name="Clinic {with} braces"))
    assert texts["scripts.yaml"].encode("utf-8") == (STARTER / "scripts.yaml").read_bytes()
    assert texts["guard.yaml"].encode("utf-8") == (STARTER / "guard.yaml").read_bytes()


def test_the_starter_scripts_keep_the_runtime_placeholders_and_name_no_clinic():
    scripts = (STARTER / "scripts.yaml").read_text(encoding="utf-8")
    for placeholder in ("{name}", "{service}", "{phone}", "{booking_url}", "{assistant_name}"):
        assert placeholder in scripts, f"starter scripts lost {placeholder}"
    assert "skincentrix" not in scripts.lower()
    assert "skinc" not in (STARTER / "guard.yaml").read_text(encoding="utf-8").lower()


def test_the_placeholders_render_for_the_new_tenant(fixed_clock):
    from spatalk.brain.renderer import render_script
    from spatalk.tenants.bundle import config_from_texts
    from spatalk.tenants.starter import render_starter

    cfg = config_from_texts(render_starter(_basics(assistant_name="Mia")), source="starter")
    now = fixed_clock.now()
    disclosure = render_script("disclosure", cfg, now, urgent=False)
    assert "North Clinic" in disclosure and "Mia" in disclosure
    assert "{" not in disclosure
    greeting = render_script("chat_greeting", cfg, now, urgent=False)
    assert "Mia" in greeting and "North Clinic" in greeting
    assert "North Clinic" in render_script("missed_call_text", cfg, now, urgent=False)
    assert "+19055550123" in render_script("help_text", cfg, now, urgent=False)


def test_the_knowledge_skeleton_states_the_facts_it_was_given():
    from spatalk.tenants.starter import render_starter

    knowledge = render_starter(_basics())["knowledge.md"]
    assert knowledge.startswith("# North Clinic\n")
    assert "Tuesday 10:00 to 18:00" in knowledge
    assert "Monday closed" in knowledge
    assert "https://north.janeapp.com/" in knowledge
    assert "+19055550123" in knowledge


# --- validation -----------------------------------------------------------------------


def test_hours_need_known_days_and_at_least_one_open_day():
    with pytest.raises(ValidationError, match="unknown weekday"):
        _basics(hours={**HOURS, "monday": []})
    with pytest.raises(ValidationError, match="at least one"):
        _basics(hours={day: [] for day in HOURS})
    with pytest.raises(ValidationError, match="bad hours"):
        _basics(hours={"mon": [("18:00", "10:00")]})
    with pytest.raises(ValidationError, match="bad hours"):
        _basics(hours={"mon": [("9am", "5pm")]})
    # Days left out are closed, not missing: the config always carries all seven.
    partial = _basics(hours={"mon": [("09:00", "17:00")]})
    assert set(partial.hours) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    assert partial.hours["sat"] == []


def test_the_slug_timezone_phone_and_email_are_checked():
    for bad_id in ("A", "North Clinic", "north_clinic", "x" * 41):
        with pytest.raises(ValidationError):
            _basics(id=bad_id)
    with pytest.raises(ValidationError, match="timezone"):
        _basics(timezone="Toronto/Eastern")
    with pytest.raises(ValidationError, match="E.164"):
        _basics(public_phone="905-555-0123")
    assert _basics(public_phone="").public_phone == ""
    assert _basics(public_phone=" +19055550123 ").public_phone == "+19055550123"
    with pytest.raises(ValidationError, match="email"):
        _basics(owner_email="not-an-address")
    assert _basics(owner_email=" Owner@North.test ").owner_email == "owner@north.test"
    with pytest.raises(ValidationError):
        _basics(booking_url="north.janeapp.com")
    with pytest.raises(ValidationError):
        _basics(name="N")


def test_a_missing_owner_name_becomes_the_clinic_front_desk():
    from spatalk.tenants.bundle import config_from_texts
    from spatalk.tenants.starter import render_starter

    cfg = config_from_texts(render_starter(_basics(owner_name="")), source="starter")
    assert cfg.escalation.owner_name == "North Clinic front desk"


# --- POST /internal/tenants/from-basics -----------------------------------------------


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


async def test_from_basics_creates_the_tenant_and_a_second_post_is_409(client, sf):
    from spatalk.models import AuditLog

    r = await client.post("/internal/tenants/from-basics", json=_body())
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "north-clinic", "version": 1}

    cfg = (await client.get("/internal/tenants/north-clinic/config")).json()
    assert cfg["version"] == 1
    assert cfg["config"]["name"] == "North Clinic"
    assert cfg["config"]["services"] == []
    assert cfg["config"]["delivery"]["destinations"][1]["address_env"] == "NORTH_CLINIC_STAFF_SMS"

    # A form must never overwrite a configured clinic: no second version, a 409 instead.
    again = await client.post("/internal/tenants/from-basics", json=_body(name="Renamed"))
    assert again.status_code == 409
    assert "north-clinic" in again.json()["detail"]
    assert (await client.get("/internal/tenants/north-clinic/config")).json()["version"] == 1

    async with sf() as s:
        rows = (
            await s.execute(
                select(AuditLog.actor, AuditLog.action, AuditLog.record_type, AuditLog.record_id)
            )
        ).all()
    assert (f"portal:{ACTOR}", "config_save", "tenant", "north-clinic") in rows


async def test_from_basics_refuses_a_tenant_that_already_exists(client):
    before = (await client.get("/internal/tenants/skincentrix/config")).json()["version"]
    r = await client.post(
        "/internal/tenants/from-basics", json=_body(id="skincentrix", name="Skincentrix")
    )
    assert r.status_code == 409
    after = (await client.get("/internal/tenants/skincentrix/config")).json()["version"]
    assert after == before


async def test_from_basics_refuses_bad_basics_with_422(client):
    r = await client.post("/internal/tenants/from-basics", json=_body(timezone="Mars/Olympus"))
    assert r.status_code == 422
    r = await client.post(
        "/internal/tenants/from-basics", json=_body(hours={day: [] for day in HOURS})
    )
    assert r.status_code == 422
    r = await client.post("/internal/tenants/from-basics", json=_body(id="North Clinic"))
    assert r.status_code == 422


def test_the_contract_carries_from_basics():
    from spatalk.http.internal import openapi_document

    doc = openapi_document(internal_only=True)
    post = doc["paths"]["/internal/tenants/from-basics"]["post"]
    body = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = doc["components"]["schemas"][body.rsplit("/", 1)[-1]]
    assert {"id", "name", "timezone", "hours", "booking_url", "owner_email"} <= set(
        schema["required"]
    )
    assert "created_by" in schema["properties"]


# --- spatalk tenant new ---------------------------------------------------------------


def _new(args: list[str]):
    from typer.testing import CliRunner

    from spatalk.cli import app

    return CliRunner().invoke(app, ["tenant", "new", *args])


def test_the_cli_writes_the_five_files_and_refuses_to_overwrite(tmp_path: Path):
    from spatalk.tenants.bundle import FILES, load_bundle

    out = tmp_path / "north-clinic"
    result = _new(
        [
            "north-clinic",
            "--name",
            "North Clinic",
            "--timezone",
            "America/Toronto",
            "--owner-email",
            "owner@north.test",
            "--booking-url",
            "https://north.janeapp.com/",
            "--public-phone",
            "+19055550123",
            "--out",
            str(out),
        ]
    )
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in out.iterdir()) == sorted(FILES)
    cfg = load_bundle(out)
    assert cfg.id == "north-clinic" and cfg.name == "North Clinic"
    # No --hours-json: weekdays nine to five, so the calendar has something to work with.
    assert cfg.hours["mon"] == [("09:00", "17:00")] and cfg.hours["sat"] == []
    assert (out / "scripts.yaml").read_bytes() == (STARTER / "scripts.yaml").read_bytes()
    assert str(out) in result.output

    again = _new(
        [
            "north-clinic",
            "--name",
            "Other",
            "--owner-email",
            "x@y.test",
            "--booking-url",
            "https://x.test/",
            "--out",
            str(out),
        ]
    )
    assert again.exit_code == 1
    assert "already exists" in again.output
    assert load_bundle(out).name == "North Clinic"


def test_the_cli_takes_hours_as_json_and_refuses_bad_basics(tmp_path: Path):
    from spatalk.tenants.bundle import load_bundle

    out = tmp_path / "hours-clinic"
    result = _new(
        [
            "hours-clinic",
            "--name",
            "Hours Clinic",
            "--owner-email",
            "owner@hours.test",
            "--booking-url",
            "https://hours.test/",
            "--hours-json",
            '{"sat": [["10:00", "14:00"]]}',
            "--out",
            str(out),
        ]
    )
    assert result.exit_code == 0, result.output
    cfg = load_bundle(out)
    assert cfg.hours["sat"] == [("10:00", "14:00")] and cfg.hours["mon"] == []

    bad = _new(
        [
            "bad-clinic",
            "--name",
            "Bad Clinic",
            "--owner-email",
            "nope",
            "--booking-url",
            "https://bad.test/",
            "--out",
            str(tmp_path / "bad-clinic"),
        ]
    )
    assert bad.exit_code == 1
    assert "email" in bad.output
    assert not (tmp_path / "bad-clinic").exists()
