"""Latency budgets per stage, the daily report and the SLO check (operations plan, E5).

The brief's S7 budget is 800 ms from the caller finishing a sentence to the assistant
starting one. That single number tells you a call was slow; it never tells you what to do
about it. Spec §10 weakness 3 is exactly that gap, and the answer here is three numbers
underneath the one: the STT's, the LLM's and the TTS's own time to first byte.

* :data:`BUDGETS_MS` is the split, and it adds up: 300 + 450 + 200 = 950 ms of vendor time
  against a 800 ms turn, because the stages overlap (the LLM starts on a partial transcript,
  the TTS on the first tokens). A stage over its own budget is actionable even when the turn
  as a whole squeaked in.
* :func:`daily_latency` reports each tenant's day: turns, p50, p95, the per-stage p95 and
  the stages over budget.
* :func:`check_slo` turns a breach into one alert per stage per tenant per day, and every
  alert names the swap that fixes it. There is a configured alternative for each of the
  three vendors, so no alert here ends in "investigate".

The per-call figures come from the call itself: `UsageObserver` files each TTFB reading
under its stage and `voice/pipeline._finalize` stores the call's own p95 in
`conversations.stage_ms`. Nothing recomputes them afterwards, which matters because the
retention job (Task E3) deletes the transcript long before the 400-day conversation stub.

The day's stage figure is therefore a p95 of per-call p95s — the tail of a tail. That is
the intended question: "was there a call where the model kept the caller waiting", not
"what did the average turn cost".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk import jobs
from spatalk.models import Conversation, OpsRun, Tenant
from spatalk.ops import alerts
from spatalk.ops.nightly_audit import day_window

# The job kind the scheduler queues, and the `ops_runs.kind` this job writes.
RUN_KIND = "ops.latency_report"

# The brief's S7 turn budget and the vendor split under it, in milliseconds.
BUDGETS_MS: dict[str, int] = {"stt": 300, "llm": 450, "tts": 200, "turn": 800}

# The three vendor stages, in the order the audio flows. `turn` is the whole of it.
STAGES: tuple[str, ...] = ("stt", "llm", "tts")

# One swap per stage, so an alert ends in a command rather than a shrug. Each is a change
# of environment variable and a restart; `docs/runbooks/model-swap.md` carries the drill.
SUGGESTED_FIX: dict[str, str] = {
    "stt": (
        "set STT_PROVIDER=deepgram_flux to move transcription to Deepgram Flux "
        "(spatalk/voice/pipeline.py, make_stt)"
    ),
    "llm": (
        "set LLM_MODEL=gemini-2.5-flash-lite, or the openai: alternative, and re-run the "
        "swap drill in docs/runbooks/model-swap.md"
    ),
    "tts": (
        "set TTS_PROVIDER=deepgram_aura2 to move speech synthesis to the other vendor "
        "(spatalk/voice/pipeline.py, make_tts)"
    ),
    "turn": (
        "no single vendor stage is over its own budget: read the stage figures in this "
        "alert, then the per-call stage_ms rows, before swapping anything"
    ),
}


# --- percentiles ------------------------------------------------------------------------


def percentile(values: list[int], q: float) -> int | None:
    """The nearest-rank percentile of `values`, or None when there is nothing to rank.

    Deliberately not interpolated: these are observed waits, and a reported figure that no
    call actually experienced is harder to argue with than one that did.
    """
    if not values:
        return None
    ordered = sorted(values)
    return int(ordered[min(len(ordered) - 1, int(len(ordered) * q))])


def p50(values: list[int]) -> int | None:
    return percentile(values, 0.5)


def p95(values: list[int]) -> int | None:
    return percentile(values, 0.95)


def session_stage_ms(session) -> dict[str, int]:
    """One call's per-stage p95, as `conversations.stage_ms` stores it.

    A stage that reported nothing is left out rather than written as zero: "the TTS never
    spoke" and "the TTS answered instantly" are different facts.
    """
    out: dict[str, int] = {}
    for stage in STAGES:
        value = p95(list(session.stage_ttfb_ms.get(stage) or []))
        if value is not None:
            out[stage] = value
    return out


def over_budget(turn_p95: int | None, stage_p95: dict[str, int | None]) -> list[str]:
    """Every budget the day missed, turn first then the stages in pipeline order."""
    breached: list[str] = []
    if turn_p95 is not None and turn_p95 > BUDGETS_MS["turn"]:
        breached.append("turn")
    for stage in STAGES:
        value = stage_p95.get(stage)
        if value is not None and value > BUDGETS_MS[stage]:
            breached.append(stage)
    return breached


# --- the daily report -------------------------------------------------------------------


async def _tenant_ids(ctx) -> list[str]:
    async with ctx.sf() as s:
        return list((await s.scalars(select(Tenant.id).order_by(Tenant.id))).all())


async def daily_latency(ctx, day: date) -> list[dict]:
    """One row per tenant that had a measured call that local day. Reads, never writes.

    A tenant with no calls produces no row: a p95 of nothing is not zero, and a zero would
    read as a perfect day on the dashboard the founder looks at.
    """
    rows: list[dict] = []
    for tenant_id in await _tenant_ids(ctx):
        cfg = await ctx.registry.get(tenant_id)
        start, end = day_window(cfg.timezone, day)
        async with ctx.sf() as s:
            calls = (
                await s.execute(
                    select(Conversation.latency_ms, Conversation.stage_ms).where(
                        Conversation.tenant_id == tenant_id,
                        Conversation.started_at >= start,
                        Conversation.started_at < end,
                    )
                )
            ).all()
        turns: list[int] = []
        per_stage: dict[str, list[int]] = {stage: [] for stage in STAGES}
        conversations = 0
        for latency_ms, stage_ms in calls:
            measured = [int(v) for v in (latency_ms or [])]
            if measured:
                conversations += 1
                turns += measured
            for stage in STAGES:
                value = (stage_ms or {}).get(stage)
                if value is not None:
                    per_stage[stage].append(int(value))
        if not turns and not any(per_stage.values()):
            continue
        stage_p95 = {stage: p95(per_stage[stage]) for stage in STAGES}
        rows.append(
            {
                "day": day.isoformat(),
                "tenant_id": tenant_id,
                "conversations": conversations,
                "turns": len(turns),
                "p50": p50(turns),
                "p95": p95(turns),
                "stage_p95": stage_p95,
                "over_budget": over_budget(p95(turns), stage_p95),
            }
        )
    return rows


# --- the SLO check ----------------------------------------------------------------------


@dataclass(frozen=True)
class Alert:
    """One breached budget: which tenant, which stage, by how much, and what to do."""

    tenant_id: str
    day: date
    stage: str
    p95_ms: int
    budget_ms: int
    subject: str
    body: str

    @property
    def key(self) -> str:
        """The identity of the incident, which is what the six-hour dedup is keyed on."""
        return f"slo:{self.stage}:{self.tenant_id}:{self.day.isoformat()}"


def _describe(row: dict) -> str:
    stages = ", ".join(
        f"{stage} p95 {row['stage_p95'][stage]} ms (budget {BUDGETS_MS[stage]} ms)"
        for stage in STAGES
        if row["stage_p95"].get(stage) is not None
    )
    return (
        f"{row['tenant_id']} on {row['day']}: {row['turns']} turn(s) over "
        f"{row['conversations']} call(s), p50 {row['p50']} ms, p95 {row['p95']} ms"
        + (f"\nstages: {stages}" if stages else "")
    )


def _alert(row: dict, day: date, stage: str) -> Alert:
    measured = row["p95"] if stage == "turn" else row["stage_p95"][stage]
    subject = (
        f"SpaTalk SLO: {row['tenant_id']} {stage} p95 {measured} ms over the "
        f"{BUDGETS_MS[stage]} ms budget on {row['day']}"
    )
    body = "\n".join([subject, "", _describe(row), "", f"Suggested fix: {SUGGESTED_FIX[stage]}"])
    return Alert(
        tenant_id=row["tenant_id"],
        day=day,
        stage=stage,
        p95_ms=int(measured),
        budget_ms=BUDGETS_MS[stage],
        subject=subject,
        body=body,
    )


async def slo_alerts(ctx, day: date) -> list[Alert]:
    """Every budget the day missed, as alerts. Reads, never writes, never sends."""
    return [
        _alert(row, day, stage)
        for row in await daily_latency(ctx, day)
        for stage in row["over_budget"]
    ]


async def check_slo(ctx, day: date) -> list[Alert]:
    """Raise every breach through `alerts.notify`. Returns the ones that actually went out.

    A breach that the six-hour dedup swallowed is not returned: the caller's question is
    "what did this run report", and re-reporting a breach already sent would make a quiet
    morning look like a new incident.
    """
    sent: list[Alert] = []
    for alert in await slo_alerts(ctx, day):
        if await alerts.notify(ctx, alert.key, alert.subject, alert.body):
            sent.append(alert)
    return sent


# --- the printed table ------------------------------------------------------------------

_COLUMNS = ("day", "tenant", "calls", "turns", "p50", "p95", "stt", "llm", "tts", "over budget")


def _cell(value) -> str:
    return "-" if value is None else str(value)


def latency_table(rows: list[dict]) -> str:
    """The report `scripts/latency_report.py` prints: one line per tenant per day."""
    table = [list(_COLUMNS)]
    for row in rows:
        table.append(
            [
                str(row["day"]),
                row["tenant_id"],
                _cell(row.get("conversations")),
                _cell(row["turns"]),
                _cell(row["p50"]),
                _cell(row["p95"]),
                *[_cell(row["stage_p95"].get(stage)) for stage in STAGES],
                ", ".join(row["over_budget"]) or "-",
            ]
        )
    widths = [max(len(r[i]) for r in table) for i in range(len(_COLUMNS))]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(table[0])).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for row in table[1:]:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


# --- the scheduled run ------------------------------------------------------------------


async def _start_run(sf: async_sessionmaker, now: datetime) -> int:
    async with sf() as s, s.begin():
        run = OpsRun(kind=RUN_KIND, started_at=now, ok=False, summary={})
        s.add(run)
        await s.flush()
        return run.id


async def _finish_run(
    sf: async_sessionmaker, run_id: int, now: datetime, *, ok: bool, summary: dict
) -> None:
    async with sf() as s, s.begin():
        await s.execute(
            update(OpsRun).where(OpsRun.id == run_id).values(finished_at=now, ok=ok, summary=summary)
        )


async def run_latency_report(ctx, day: date | None = None) -> dict:
    """Report one local day and alert on every breached budget.

    `day` defaults to yesterday, which is what the nightly job wants. The run row is written
    whether or not anything was found: a job that silently stopped running looks exactly
    like a fast day unless the row says otherwise (Global Constraints).
    """
    at = ctx.clock.now()
    day = day or (at.astimezone(timezone.utc).date() - timedelta(days=1))
    run_id = await _start_run(ctx.sf, at)
    try:
        rows = await daily_latency(ctx, day)
        raised = await check_slo(ctx, day)
    except Exception as e:
        await _finish_run(
            ctx.sf,
            run_id,
            ctx.clock.now(),
            ok=False,
            summary={"day": day.isoformat(), "error": f"{type(e).__name__}: {e}"[:500]},
        )
        raise
    report = {"day": day.isoformat(), "tenants": rows, "alerts": [a.key for a in raised]}
    await _finish_run(ctx.sf, run_id, ctx.clock.now(), ok=True, summary=report)
    logger.info(
        "latency report {}: {} tenant(s), {} slo alert(s)", day, len(rows), len(raised)
    )
    return report


@jobs.register_handler(RUN_KIND)
async def _latency_report_job(payload: dict, ctx: jobs.JobContext) -> None:
    day = payload.get("day")
    await run_latency_report(ctx, date.fromisoformat(day) if day else None)
