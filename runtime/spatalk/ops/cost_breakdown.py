"""What one call costs, per call and per component (cost gap C1).

`cost_report` answers the month's question — metered cost against the provider invoices, per
tenant, against the price. It cannot answer the question the pricing calculator asks, which
is *why* a minute costs what it costs: it sums the tenant's month into one number per
provider, and the levers (how many turns, how much of the input was cached, how many
characters were spoken) live inside a single call.

So this reads the ledger per conversation and prints the same call the founder just made:
minutes, turns, input tokens cached and uncached, output tokens, spoken characters, and the
cost split by component and per minute on `live_stack`.

Three decisions, each with an obvious wrong alternative:

* **The turn count is the call's own latency readings.** One reading is written per turn by
  `TurnLatencyObserver` (caller stopped speaking -> assistant started), so `len(latency_ms)`
  is the number of model turns that reached the caller. Counting transcript messages instead
  would count the fixed scripts, which cost no tokens, and miss a turn the caller barged in on.
* **Usage with no conversation still reaches the total.** A staff text is recorded against
  the tenant and no call; leaving it out of the total would make the month look cheaper than
  the invoice.
* **A call with no minutes reports no cost per minute**, rather than dividing by zero or
  quietly reporting the cost as if it were a minute's worth.
"""

from __future__ import annotations

import uuid as uuidlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from spatalk import rates
from spatalk.models import Conversation, UsageEvent


@dataclass(frozen=True)
class CallCost:
    """One call's metered usage and what it cost.

    The same shape carries the window's total, with `conversation_id` and `started_at` unset,
    so the report prints one renderer over both.
    """

    conversation_id: uuidlib.UUID | None
    started_at: datetime | None
    minutes: float
    turns: int
    units: dict[str, float]
    components: dict[str, float]

    @property
    def total_cad(self) -> float:
        return round(sum(self.components.values()), 6)

    @property
    def cad_per_minute(self) -> float | None:
        """None, not zero and not a division by zero, when nothing was spent on the clock."""
        if not self.minutes:
            return None
        return self.total_cad / self.minutes

    @property
    def cached_fraction(self) -> float | None:
        """How much of the input the provider read from its cache, or None with no input."""
        total = self.units.get("llm_input_tokens", 0.0)
        if not total:
            return None
        return self.units.get("llm_cached_tokens", 0.0) / total


def _window(tz: str, since: date, until: date | None, now: datetime) -> tuple[datetime, datetime]:
    """Tenant-local days, half open, in UTC (CLAUDE.md non-negotiable 8).

    "Today" is the tenant's today, taken from the injected clock and not from the machine
    the report runs on: a founder in Toronto reading a clinic in Vancouver would otherwise
    lose the evening, and a test on a fixed clock would follow the wall.
    """
    zone = ZoneInfo(tz)
    start = datetime.combine(since, time.min, tzinfo=zone)
    last = until or now.astimezone(zone).date()
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _cost(
    conversation_id: uuidlib.UUID | None,
    started_at: datetime | None,
    turns: int,
    units: dict[str, float],
) -> CallCost:
    minutes = units.get("telephony_seconds", 0.0) / 60
    return CallCost(
        conversation_id=conversation_id,
        started_at=started_at,
        minutes=round(minutes, 4),
        turns=turns,
        units=units,
        components=rates.components_cad(units),
    )


async def call_costs(
    ctx, tenant_id: str, since: date, until: date | None = None
) -> tuple[list[CallCost], CallCost]:
    """Every voice call in the window with its own cost, and the window's total.

    The total is not the sum of the calls: it also carries the usage recorded against the
    tenant with no conversation (staff texts, outbound messages), which is money the month
    was billed for.
    """
    cfg = await ctx.registry.get(tenant_id)
    start, end = _window(cfg.timezone, since, until, ctx.clock.now())
    async with ctx.sf() as s:
        convs = (
            await s.execute(
                select(Conversation.id, Conversation.started_at, Conversation.latency_ms)
                .where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.channel == "voice",
                    Conversation.started_at >= start,
                    Conversation.started_at < end,
                )
                .order_by(Conversation.started_at)
            )
        ).all()
        rows = (
            await s.execute(
                select(UsageEvent.conversation_id, UsageEvent.unit, func.sum(UsageEvent.qty))
                .where(
                    UsageEvent.tenant_id == tenant_id,
                    UsageEvent.created_at >= start,
                    UsageEvent.created_at < end,
                )
                .group_by(UsageEvent.conversation_id, UsageEvent.unit)
            )
        ).all()

    per_conv: dict[uuidlib.UUID | None, dict[str, float]] = {}
    totals: dict[str, float] = {}
    for conversation_id, unit, qty in rows:
        per_conv.setdefault(conversation_id, {})[unit] = float(qty or 0)
        totals[unit] = totals.get(unit, 0.0) + float(qty or 0)

    calls = [
        _cost(cid, started_at, len(latency or []), per_conv.get(cid, {}))
        for cid, started_at, latency in convs
    ]
    total = _cost(None, None, sum(c.turns for c in calls), totals)
    return calls, total


# --- printing ---------------------------------------------------------------------------


def _n(value: float) -> str:
    return f"{value:,.0f}"


def lines(calls: list[CallCost], total: CallCost, tenant_id: str) -> list[str]:
    """The breakdown as printed lines: one block per call, then the window's total."""
    live = rates.live_stack(rates.load_rates())
    out = [
        f"{tenant_id}: {len(calls)} calls, {total.minutes:,.2f} minutes, "
        f"{total.turns} model turns",
        f"priced on {live['label']}",
        "",
        f"{'call':>10} {'start':<17} {'mins':>6} {'turns':>6} {'in':>9} {'cached':>9} "
        f"{'cache%':>7} {'out':>7} {'chars':>7} {'CA$':>9} {'CA$/min':>8}",
    ]
    for c in calls + [total]:
        ref = str(c.conversation_id)[:8] if c.conversation_id else "TOTAL"
        when = c.started_at.strftime("%Y-%m-%d %H:%M") if c.started_at else ""
        cached = c.cached_fraction
        per_min = c.cad_per_minute
        out.append(
            f"{ref:>10} {when:<17} {c.minutes:6.2f} {c.turns:6d} "
            f"{_n(c.units.get('llm_input_tokens', 0)):>9} "
            f"{_n(c.units.get('llm_cached_tokens', 0)):>9} "
            f"{(f'{cached * 100:.0f}%' if cached is not None else '-'):>7} "
            f"{_n(c.units.get('llm_output_tokens', 0)):>7} "
            f"{_n(c.units.get('tts_chars', 0)):>7} "
            f"{c.total_cad:9.4f} "
            f"{(f'{per_min:8.4f}' if per_min is not None else '       -')}"
        )
    out += ["", "components, CA$ and CA$ per minute:"]
    for name in rates.COMPONENTS:
        cad = total.components[name]
        per_min = cad / total.minutes if total.minutes else None
        out.append(
            f"  {name:<12} {cad:9.4f}"
            + (f"  {per_min:.4f} per minute" if per_min is not None else "")
        )
    out.append(
        f"  {'TOTAL':<12} {total.total_cad:9.4f}"
        + (
            f"  {total.cad_per_minute:.4f} per minute"
            if total.cad_per_minute is not None
            else ""
        )
    )
    if total.turns and total.minutes:
        out += [
            "",
            f"per model turn: {total.units.get('llm_input_tokens', 0) / total.turns:,.0f} input "
            f"tokens ({total.units.get('llm_cached_tokens', 0) / total.turns:,.0f} cached), "
            f"{total.units.get('llm_output_tokens', 0) / total.turns:,.0f} output",
            f"per call minute: {total.turns / total.minutes:.2f} turns, "
            f"{total.units.get('tts_chars', 0) / total.minutes:,.0f} characters sent to be spoken",
        ]
        spoken = total.units.get("tts_seconds", 0.0)
        if spoken:
            out.append(
                f"the assistant spoke for {spoken / 60:,.2f} minutes, "
                f"{spoken / 60 / total.minutes * 100:.0f}% of the clock, at "
                f"{total.units.get('tts_chars', 0) / (spoken / 60):,.0f} characters a spoken minute"
            )
    return out
