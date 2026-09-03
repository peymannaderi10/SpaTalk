"""QA gate C: the checks the whole-system gate makes that nothing else proved.

Gate A proved the runtime against the brief, gate B the channels and the portal. Gate C
asks a different question: does the thing that gets *deployed* behave like the thing the
suite tests? Three answers were missing a test.

1. The suite builds its schema from `Base.metadata`; production builds it from
   `alembic upgrade head`. Nothing compared the two, so a model column added without a
   migration would pass every test in the suite and fail on the VPS. This module runs both
   against throwaway databases and diffs `information_schema`.
2. The nightly and monthly jobs register their handlers by module import. The server
   process only has the handlers whose modules `spatalk.http.app` reaches; a job whose
   handler is not imported is enqueued for ever and never runs. This pins the set.
3. `python docs/research/costmodel.py docs/research/rates.json` is one of the four commands
   `CLAUDE.md` names and no test ran it, so a rates file that no longer parses would be
   discovered by a founder, not by CI.

Nothing here calls a provider, and every database this module makes it also drops.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

RUNTIME = Path(__file__).resolve().parents[1]
ROOT = RUNTIME.parent


# ---------------------------------------------------------------------------
# 1. The migrated schema is the schema the models describe
# ---------------------------------------------------------------------------

# Every column, with the parts of its type that a migration can get wrong. `is_nullable`
# and the lengths are in here on purpose: `String(64)` against `String(200)` is exactly the
# kind of drift that only shows up as a truncated phone number in production.
COLUMNS_SQL = """
select table_name, column_name, data_type, is_nullable,
       coalesce(character_maximum_length, -1),
       coalesce(numeric_precision, -1),
       coalesce(numeric_scale, -1)
from information_schema.columns
where table_schema = 'runtime'
"""

# Compared by definition, not by name: Alembic's autogenerate and SQLAlchemy's create_all
# name indexes the same way today, but the definition is what the query planner sees.
INDEXES_SQL = "select tablename, indexdef from pg_indexes where schemaname = 'runtime'"


async def _snapshot(url: str) -> tuple[set, set]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            columns = {tuple(r) for r in (await conn.execute(text(COLUMNS_SQL))).all()}
            indexes = {
                (table, definition.split(" ON ", 1)[1])
                for table, definition in (await conn.execute(text(INDEXES_SQL))).all()
            }
    finally:
        await engine.dispose()
    return columns, indexes


async def test_alembic_head_and_the_orm_metadata_describe_the_same_schema():
    """`alembic upgrade head` must produce exactly what `Base.metadata` describes.

    The suite never runs a migration — `conftest.engine` calls `create_all` — so without
    this the only thing standing between a forgotten `alembic revision` and a broken deploy
    is that somebody remembered.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    base_url = os.environ["TEST_DATABASE_URL"].rsplit("/", 1)[0]
    migrated, declared = "spatalk_qa_gate_c_alembic", "spatalk_qa_gate_c_models"

    admin = create_async_engine(f"{base_url}/spatalk", isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            for name in (migrated, declared):
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
                await conn.execute(text(f'CREATE DATABASE "{name}" OWNER spatalk'))

        run = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=RUNTIME,
            env={**os.environ, "DATABASE_URL": f"{base_url}/{migrated}"},
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, f"alembic upgrade head failed:\n{run.stdout}\n{run.stderr}"

        from spatalk.db import Base, make_engine
        import spatalk.models  # noqa: F401
        import spatalk.social.models  # noqa: F401

        engine = make_engine(f"{base_url}/{declared}")
        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS runtime"))
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

        migrated_columns, migrated_indexes = await _snapshot(f"{base_url}/{migrated}")
        declared_columns, declared_indexes = await _snapshot(f"{base_url}/{declared}")

        # Alembic's own bookkeeping table has no model and is not drift.
        migrated_columns = {c for c in migrated_columns if c[0] != "alembic_version"}
        migrated_indexes = {i for i in migrated_indexes if i[0] != "alembic_version"}

        assert migrated_columns - declared_columns == set(), (
            "columns the migrations create that no model declares: "
            f"{sorted(migrated_columns - declared_columns)}"
        )
        assert declared_columns - migrated_columns == set(), (
            "columns the models declare that no migration creates (missing revision?): "
            f"{sorted(declared_columns - migrated_columns)}"
        )
        assert migrated_indexes ^ declared_indexes == set(), (
            f"index drift: only migrated={sorted(migrated_indexes - declared_indexes)} "
            f"only declared={sorted(declared_indexes - migrated_indexes)}"
        )
    finally:
        async with admin.connect() as conn:
            for name in (migrated, declared):
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


# ---------------------------------------------------------------------------
# 2. Every job kind the server enqueues has a handler in the server process
# ---------------------------------------------------------------------------

# Handlers register as a side effect of importing the module they live in, so a job kind
# whose module the app never imports is queued nightly and never runs — no error, no
# alert, just a growing `jobs` table. This is the list as it stands; a kind that leaves it
# has to leave `spatalk` too.
EXPECTED_JOB_KINDS = {
    "deliver.slack",
    "deliver.email",
    "deliver.sms",
    "deliver.whatsapp",
    "digest.email",
    "text.followup",
    "sms.textback",
    "social.ig_event",
    "social.fb_event",
    "social.refresh_tokens",
    "ops.retention",
    "ops.nightly_audit",
    "ops.latency_report",
    "ops.cost_report",
}


def test_every_job_kind_has_a_handler_in_the_server_process():
    """Import what the server imports, and nothing else, then read the registry it filled.

    In a subprocess, because the registry is process-global: a test module that registers a
    handler of its own (`test.fail` in `tests/test_jobs.py`) would otherwise be counted as
    part of the server's wiring, and the question here is what `spatalk serve` has.
    """
    probe = (
        "import json, spatalk.http.app; from spatalk import jobs; "
        "print(json.dumps(sorted(jobs._HANDLERS)))"
    )
    run = subprocess.run(
        [sys.executable, "-c", probe], cwd=RUNTIME, capture_output=True, text=True,
        env={**os.environ, "SPATALK_NO_ENV_FILE": "1"},
    )
    assert run.returncode == 0, f"importing the app failed:\n{run.stdout}\n{run.stderr}"
    registered = set(json.loads(run.stdout.strip().splitlines()[-1]))

    assert EXPECTED_JOB_KINDS - registered == set(), (
        "queued nightly, never run: "
        f"{sorted(EXPECTED_JOB_KINDS - registered)} have no handler in the server process"
    )
    assert registered - EXPECTED_JOB_KINDS == set(), (
        f"new job kinds not in the gate C list: {sorted(registered - EXPECTED_JOB_KINDS)}"
    )


def test_the_scheduled_ops_jobs_are_enqueued_under_the_kinds_their_handlers_registered():
    """The scheduler and the handler must agree on the string, or the job never runs."""
    from spatalk import jobs
    from spatalk.ops import cost_report, latency, nightly_audit, retention

    for module in (retention, nightly_audit, latency, cost_report):
        assert module.RUN_KIND in jobs._HANDLERS, f"{module.__name__}.RUN_KIND has no handler"

    scheduler_source = (RUNTIME / "spatalk" / "ledger" / "scheduler.py").read_text("utf-8")
    for module, symbol in (
        (retention, "retention.RUN_KIND"),
        (nightly_audit, "nightly_audit.RUN_KIND"),
        (latency, "latency.RUN_KIND"),
        (cost_report, "cost_report.RUN_KIND"),
    ):
        assert symbol in scheduler_source, f"the scheduler no longer enqueues {module.__name__}"


# ---------------------------------------------------------------------------
# 3. The cost model runs
# ---------------------------------------------------------------------------


def test_the_cost_model_runs_and_exits_zero_on_the_researched_rates():
    """`python docs/research/costmodel.py docs/research/rates.json` — a CLAUDE.md command."""
    script = ROOT / "docs" / "research" / "costmodel.py"
    rates = ROOT / "docs" / "research" / "rates.json"
    if not script.exists() or not rates.exists():  # pragma: no cover - a source checkout has both
        pytest.skip("the research directory is not part of this checkout")

    run = subprocess.run(
        [sys.executable, str(script), str(rates)], capture_output=True, text=True, cwd=ROOT
    )
    assert run.returncode == 0, f"costmodel exited {run.returncode}:\n{run.stdout}\n{run.stderr}"
    # The three sections the founder reads; a model that stops printing one of them has
    # silently stopped answering the question it exists for.
    for heading in ("=== VOICE, per call-minute", "=== FIXED platform cost", "=== MARGIN at"):
        assert heading in run.stdout, f"the cost model printed no {heading!r} section"


# ===========================================================================
# QA gate C re-run (2026-09-03). Two more checks the gate makes by hand every
# time and nothing proved. Appended as their own block; nothing above changed.
# ===========================================================================


# ---------------------------------------------------------------------------
# 4. The founder's environment reference is complete for the runtime
# ---------------------------------------------------------------------------

# The founder fills the VPS from `docs/reference/api-surface.md` and copies
# `runtime/.env.example`. A setting that exists in `Settings` but in neither document is a
# variable nobody knows to set: the service starts on the default and behaves differently
# in production from every test. `tests/test_ops_alerts.py` pins the six operations
# variables; nothing pinned the other forty-two, and nothing at all compared `Settings`
# against the reference the founder actually reads.
#
# Scope note: this asserts the *runtime* half only. The portal's variables live in
# `portal/.env.server.example` and are the portal suite's to guard; the gate C report
# records the two that the reference is missing (`PORTAL_EMAIL_PROVIDER`, `MAIL_FROM_NAME`)
# as a finding rather than failing the runtime suite for a portal document.


def _declared_in(text: str) -> set[str]:
    """Every `NAME=` assignment in a dotenv-shaped file, commented-out lines included."""
    import re

    return set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", text, re.M))


def test_every_runtime_setting_is_named_in_the_env_example_and_the_api_surface():
    from spatalk.settings import Settings

    example = (RUNTIME / ".env.example").read_text(encoding="utf-8")
    surface = (ROOT / "docs" / "reference" / "api-surface.md").read_text(encoding="utf-8")
    declared = _declared_in(example)

    names = sorted(field.upper() for field in Settings.model_fields)
    assert len(names) > 40, "Settings shrank unexpectedly; this guard is comparing nothing"

    missing_from_example = [n for n in names if n not in declared]
    assert not missing_from_example, (
        "runtime/.env.example does not name these settings, so nobody knows to set them: "
        f"{missing_from_example}"
    )
    missing_from_surface = [n for n in names if n not in surface]
    assert not missing_from_surface, (
        "docs/reference/api-surface.md does not name these settings: " f"{missing_from_surface}"
    )


def test_the_env_example_promises_no_variable_nothing_reads():
    """The other direction: a name in the example that nothing reads is a lie.

    The founder pastes the example into the VPS's `.env`; a variable no code and no bundle
    reads looks configured and does nothing. Three sources are legitimate readers, and only
    three: `Settings`; the tenant bundles, which carry destination *names* and never the
    address itself (CLAUDE.md non-negotiable 5, e.g. `webhook_env: SKINCENTRIX_SLACK_WEBHOOK`);
    and Caddy, which reads the four host variables out of the same file
    (`tests/test_deploy_assets.py::test_caddyfile_proxies_both_hosts_to_the_app_container`).
    """
    import re

    from spatalk.settings import Settings

    caddy_only = {"API_HOST", "MEDIA_HOST", "APP_HOST", "APP_API_HOST"}
    read_by_settings = {field.upper() for field in Settings.model_fields}
    bundles = " ".join(
        path.read_text(encoding="utf-8") for path in (RUNTIME / "tenants").rglob("*.yaml")
    )
    named_by_a_bundle = set(re.findall(r"\b([A-Z][A-Z0-9_]{3,})\b", bundles))

    example = (RUNTIME / ".env.example").read_text(encoding="utf-8")
    stray = sorted(
        n
        for n in _declared_in(example)
        if n not in read_by_settings and n not in caddy_only and n not in named_by_a_bundle
    )
    assert not stray, f"runtime/.env.example names variables nothing reads: {stray}"


# ---------------------------------------------------------------------------
# 5. The loop guard covers every number the tenant owns, not only the voice ones
# ---------------------------------------------------------------------------

# `spatalk.ops.loop_guard.own_numbers` claims `public_phone`, `sms_from_number` and every
# entry of `voice_numbers`. `tests/test_ops_loop_guard.py` drives a TeXML POST from the
# registry-mapped voice number and from the public phone; the messaging number — the one
# the clinic's own staff are most likely to dial back from, and the one a carrier
# forwarding rule is most likely to point at the wrong line — had no end-to-end case. The
# gate runs this by hand against a live `spatalk serve` every time; this is that check,
# committed.


async def test_the_loop_guard_refuses_a_call_from_the_tenants_own_sms_number(sf, registry, fixed_clock):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import func, select

    from spatalk import jobs
    from spatalk.http.app import attach_router
    from spatalk.models import AlertLog, Conversation
    from spatalk.settings import Settings
    from spatalk.voice.texml import router

    cfg = await registry.get("skincentrix")
    assert cfg.sms_from_number, "the Skincentrix bundle no longer carries a messaging number"

    app = FastAPI()
    attach_router(app, router)
    app.state.ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=None,
        delivery=None,
        settings=Settings(_env_file=None, secret_key="s", media_ws_host="media.test"),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.test") as client:
        r = await client.post(
            "/telnyx/texml",
            data={"From": cfg.sms_from_number, "To": "+19055550100", "CallSid": "c-sms-loop"},
        )

    assert r.status_code == 200
    # The tenant's fixed wording, and nothing that suggests a call is being connected.
    assert cfg.scripts.loop_guard in r.text
    assert "<Hangup/>" in r.text
    assert "<Stream" not in r.text
    async with sf() as s:
        assert await s.scalar(select(func.count()).select_from(Conversation)) == 0
        keys = list((await s.scalars(select(AlertLog.key))).all())
    assert keys == [f"loop_guard:skincentrix:{cfg.sms_from_number}"]
