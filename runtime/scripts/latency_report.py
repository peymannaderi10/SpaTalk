#!/usr/bin/env python
"""Print the per-tenant turn and stage latency of the last N days (operations plan, E5).

    uv run python scripts/latency_report.py --days 7

Read-only: it reports what the calls recorded and never sends an alert. The nightly job
(`ops.latency_report`) is what alerts; this is the founder's way of looking at the week
before deciding whether a stage really needs swapping, and after a swap, whether it helped.

Every figure comes from `conversations.latency_ms` and `conversations.stage_ms`, which the
call itself wrote at the end of the call. A day with no calls prints no line.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spatalk.http.app import build_context  # noqa: E402
from spatalk.ops.latency import BUDGETS_MS, daily_latency, latency_table  # noqa: E402
from spatalk.settings import get_settings  # noqa: E402


async def collect(days: int, end: date) -> list[dict]:
    """Every tenant's row for each of the `days` local days ending on `end`, oldest first."""
    ctx = build_context(get_settings())
    rows: list[dict] = []
    for back in range(days - 1, -1, -1):
        rows += await daily_latency(ctx, end - timedelta(days=back))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7, help="how many days back to report")
    parser.add_argument(
        "--end",
        default="",
        help="last day to report, YYYY-MM-DD (default: yesterday, the last complete day)",
    )
    args = parser.parse_args(argv)
    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
    rows = asyncio.run(collect(max(1, args.days), end))
    if not rows:
        print(f"no calls with recorded latency in the {args.days} day(s) ending {end}")
        return 0
    print(latency_table(rows))
    print()
    print("budgets (ms): " + ", ".join(f"{k} {v}" for k, v in BUDGETS_MS.items()))
    breached = [r for r in rows if r["over_budget"]]
    for row in breached:
        print(f"over budget on {row['day']}: {row['tenant_id']} -> {', '.join(row['over_budget'])}")
    return 1 if breached else 0


if __name__ == "__main__":
    raise SystemExit(main())
