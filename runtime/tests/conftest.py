import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test"
)


@pytest.fixture
def fixed_clock():
    from spatalk.clock import FixedClock

    # Tuesday 2026-09-01 14:00 Toronto = 18:00 UTC
    return FixedClock(datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc))


@pytest_asyncio.fixture
async def engine():
    """Fresh schema per test: simple, loop-safe, and ids restart at 1 (tests rely on that)."""
    from spatalk.db import make_engine, Base
    import spatalk.models  # noqa: F401
    eng = make_engine(os.environ["TEST_DATABASE_URL"])
    async with eng.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS runtime"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sf(engine):
    from spatalk.db import make_session_factory
    return make_session_factory(engine)


@pytest_asyncio.fixture
async def registry(sf, fixed_clock):
    from pathlib import Path
    from spatalk.tenants.registry import TenantRegistry
    reg = TenantRegistry(sf, fixed_clock)
    await reg.import_bundle(Path(__file__).resolve().parents[1] / "tenants" / "skincentrix", created_by="test")
    await reg.add_number("+19055550100", "skincentrix", "voice")
    return reg
