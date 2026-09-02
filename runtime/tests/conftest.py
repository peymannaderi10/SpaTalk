import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://spatalk:spatalk@localhost:5432/spatalk_test"
)


@pytest.fixture
def fixed_clock():
    from spatalk.clock import FixedClock

    # Tuesday 2026-09-01 14:00 Toronto = 18:00 UTC
    return FixedClock(datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc))
