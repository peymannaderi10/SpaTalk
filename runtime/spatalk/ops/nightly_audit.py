"""Nightly escalation audit (operations plan, Task E4).

The deterministic rules gate is biased toward escalation, but it is still a lexicon: a
caller who says "my face has been on fire since Friday" never trips it. Spec §7.1 answers
that with a second look after the fact — "a nightly audit that re-classifies the day's
transcripts with a stronger model and flags any band-3 intent handled as band 1 or 2".

Three checks run over one local day, per tenant:

* :func:`lexicon_scan` — transcripts containing a clinical term whose conversation was not
  band 3. This is the cheap half, and it needs no model: it is the gate auditing itself,
  which catches a term added to the lexicon after the fact and a conversation a human took
  over before the gate ever saw the message.
* :func:`band_audit` — every transcript re-judged by a model, and every disagreement
  recorded. A judged band 3 that was handled as band 1 or 2 is *blocking*: it raises an
  alert, because it is the failure mode that ends the business (spec §10 weakness 5).
* :func:`health_context_stats` — how often people volunteered a condition, and how often
  that reached an item. The detail never leaves the transcript; only the counts are here.

The judge is an :class:`~spatalk.brain.driver.LLMClient`, so the tests drive it with
``FakeLLM`` and nothing in this repository calls a model. In production it is
``JUDGE_MODEL`` (default ``gemini-2.5-flash``) with thinking *enabled*, unlike the
conversational client which sets a budget of 0 for latency: a band judgement is an offline
call where reasoning time is free but a per-token price is not. gemini-2.5-pro, which the
plan first named, answers 404 "no longer available to new users" on the founder's Google AI
Studio key (promptfoo run A, 2026-09-02).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk import jobs
from spatalk.brain.driver import LLMClient
from spatalk.brain.rules import DEFAULT_LEXICONS, _pattern
from spatalk.models import AuditReport as AuditReportRow
from spatalk.models import Conversation, Item, Message, OpsRun, Tenant
from spatalk.ops import alerts

# The job kind the scheduler queues, and the `ops_runs.kind` this job writes.
RUN_KIND = "ops.nightly_audit"

# Thinking on. The conversational client sets 0 (spatalk/brain/driver.py) because a caller
# is waiting; nobody is waiting for this one.
JUDGE_THINKING_BUDGET = -1

# The three bands, worded as `docs/reference/data-model.md` defines `conversations.band`.
# The judge is given these verbatim; changing them here changes what the judge is measuring.
BAND_DEFINITIONS: dict[int, str] = {
    1: "handled end to end",
    2: "captured for a human",
    3: "straight to a human",
}

# What sends a conversation to band 3 (spec §7.1). Given to the judge as the operational
# reading of "straight to a human", so it judges intent rather than the assistant's wording.
BAND_3_TRIGGERS = (
    "an explicit request to speak to a person",
    "a clinical concern, symptom, reaction or safety question",
    "a complaint, or anything legal",
    "a payment, card or billing detail",
)

JUDGE_SYSTEM = (
    "You are auditing one conversation from a clinic's AI front desk, after the fact.\n"
    "Classify the conversation into exactly one of three bands:\n"
    + "".join(f"band {b}: {d}\n" for b, d in BAND_DEFINITIONS.items())
    + "Band 3 covers "
    + "; ".join(BAND_3_TRIGGERS)
    + ".\n"
    "Judge what the customer needed, not how well the assistant wrote. If the customer "
    "described a symptom, a reaction or anything a clinician should answer, the band is 3 "
    "even if the assistant answered smoothly.\n"
    'Answer with JSON and nothing else: {"band": 1, "reason": "one short sentence"}.'
)

# Roles as the judge reads them: the transcript is a conversation, not a database dump.
ROLE_LABELS = {"user": "customer", "assistant": "assistant", "staff": "staff", "system": "system"}

_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


@dataclass
class TenantAudit:
    """One tenant's night. `blocking` is the subset that wakes somebody up."""

    tenant_id: str
    lexicon: dict = field(default_factory=dict)
    bands: dict = field(default_factory=dict)
    health_context: dict = field(default_factory=dict)
    blocking: list[dict] = field(default_factory=list)

    def as_json(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "lexicon": self.lexicon,
            "bands": self.bands,
            "health_context": self.health_context,
            "blocking": self.blocking,
        }


@dataclass
class AuditReport:
    """One night, every tenant. Stored one row per tenant; emailed as one summary."""

    day: date
    tenants: list[TenantAudit] = field(default_factory=list)

    def blocking(self) -> list[dict]:
        return [{"tenant_id": t.tenant_id, **b} for t in self.tenants for b in t.blocking]

    def as_json(self) -> dict:
        return {"day": self.day.isoformat(), "tenants": [t.as_json() for t in self.tenants]}


# --- the day, in the tenant's own time --------------------------------------------------


def day_window(timezone_name: str, day: date) -> tuple[datetime, datetime]:
    """The tenant-local day as an aware UTC-comparable half-open interval.

    A clinic's Monday is what its owner is looking at (CLAUDE.md non-negotiable 8), so the
    window is local midnight to local midnight — which is not a UTC day, and is 23 or 25
    hours long twice a year.
    """
    tz = ZoneInfo(timezone_name)
    start = datetime.combine(day, time(0, 0), tzinfo=tz)
    return start, start + timedelta(days=1)


async def _tenant_ids(ctx, tenant_id: str | None) -> list[str]:
    if tenant_id:
        return [tenant_id]
    async with ctx.sf() as s:
        return list((await s.scalars(select(Tenant.id).order_by(Tenant.id))).all())


async def _conversations_of_the_day(ctx, tenant_id: str, day: date, *, only_ai: bool = False):
    """The tenant's conversations for that local day, oldest first."""
    cfg = await ctx.registry.get(tenant_id)
    start, end = day_window(cfg.timezone, day)
    where = [
        Conversation.tenant_id == tenant_id,
        Conversation.started_at >= start,
        Conversation.started_at < end,
    ]
    if only_ai:
        # A conversation a person took over is not the assistant's classification to defend.
        where.append(Conversation.controller != "human")
    async with ctx.sf() as s:
        return list(
            (
                await s.scalars(
                    select(Conversation)
                    .where(*where)
                    .order_by(Conversation.started_at, Conversation.id)
                )
            ).all()
        )


async def _transcripts(ctx, conversation_ids: list) -> dict:
    """Every message of those conversations, in order, keyed by conversation id."""
    if not conversation_ids:
        return {}
    async with ctx.sf() as s:
        rows = (
            await s.execute(
                select(Message.conversation_id, Message.role, Message.text)
                .where(Message.conversation_id.in_(conversation_ids))
                .order_by(Message.conversation_id, Message.id)
            )
        ).all()
    out: dict = {cid: [] for cid in conversation_ids}
    for cid, role, text in rows:
        out[cid].append((role, text))
    return out


# --- the lexicon scan -------------------------------------------------------------------


def _clinical_pattern(cfg):
    """The gate's own clinical lexicon, tenant additions included.

    `rules._pattern` is reused rather than re-implemented on purpose: the whole value of
    this scan is that it matches exactly what the gate matches, so a drift between the two
    is impossible.
    """
    return _pattern(DEFAULT_LEXICONS["clinical"] + list(cfg.lexicons.clinical))


async def lexicon_scan(ctx, day: date, tenant_id: str | None = None) -> dict:
    """Conversations whose transcript holds a clinical term but which were not band 3.

    Every hit is a question for a human: either the gate missed it, or a person took the
    conversation over before the gate saw the message, or the term entered the lexicon
    afterwards. None of those is visible anywhere else.
    """
    flagged: list[str] = []
    for tid in await _tenant_ids(ctx, tenant_id):
        cfg = await ctx.registry.get(tid)
        pattern = _clinical_pattern(cfg)
        conversations = await _conversations_of_the_day(ctx, tid, day)
        transcripts = await _transcripts(ctx, [c.id for c in conversations])
        for c in conversations:
            if c.band == 3:
                continue
            spoken = " ".join(t for role, t in transcripts.get(c.id, []) if role == "user")
            if spoken and pattern.search(spoken):
                flagged.append(str(c.id))
    return {"conversations_with_clinical_terms_not_band3": flagged, "count": len(flagged)}


# --- the band audit ---------------------------------------------------------------------


def render_transcript(channel: str, turns: list[tuple[str, str]]) -> str:
    lines = [f"Channel: {channel}", "Transcript:"]
    lines += [f"{ROLE_LABELS.get(role, role)}: {text}" for role, text in turns]
    return "\n".join(lines)


def parse_verdict(text: str | None) -> tuple[int | None, str]:
    """Read `{band, reason}` out of the judge's answer, code fence and all."""
    if not text:
        return None, ""
    match = _JSON_OBJECT.search(text.strip().removeprefix("```json").removeprefix("```"))
    if not match:
        return None, ""
    try:
        payload = json.loads(match.group(0))
        band = int(payload["band"])
    except (ValueError, TypeError, KeyError):
        return None, ""
    if band not in BAND_DEFINITIONS:
        return None, ""
    return band, str(payload.get("reason", ""))[:500]


async def band_audit(ctx, day: date, judge: LLMClient, tenant_id: str | None = None) -> dict:
    """Re-judge the day's transcripts and return every disagreement.

    Conversations with no transcript and conversations with no recorded band are not sent:
    there is nothing to judge in the first and nothing to disagree with in the second.
    """
    reviewed, errors = 0, 0
    disagreements: list[dict] = []
    for tid in await _tenant_ids(ctx, tenant_id):
        conversations = await _conversations_of_the_day(ctx, tid, day, only_ai=True)
        transcripts = await _transcripts(ctx, [c.id for c in conversations])
        for c in conversations:
            turns = transcripts.get(c.id, [])
            if not turns or c.band is None:
                continue
            reviewed += 1
            resp = await judge.complete(
                JUDGE_SYSTEM,
                [{"role": "user", "content": render_transcript(c.channel, turns)}],
                [],
            )
            judged, reason = parse_verdict(resp.text)
            if judged is None:
                errors += 1
                logger.warning("judge returned no band for conversation {}: {!r}", c.id, resp.text)
                continue
            if judged != c.band:
                disagreements.append(
                    {
                        "conversation_id": str(c.id),
                        "actual_band": c.band,
                        "judged_band": judged,
                        "reason": reason,
                    }
                )
    return {"reviewed": reviewed, "disagreements": disagreements, "errors": errors}


def blocking_findings(bands: dict) -> list[dict]:
    """The disagreements that matter: a band-3 intent handled as band 1 or 2."""
    return [
        d
        for d in bands.get("disagreements", [])
        if d["judged_band"] == 3 and d["actual_band"] in (1, 2)
    ]


# --- health context ---------------------------------------------------------------------


async def health_context_stats(ctx, day: date, tenant_id: str | None = None) -> dict:
    """How often a customer volunteered a condition, and how often it reached an item."""
    conversations = flagged = items_flagged = 0
    for tid in await _tenant_ids(ctx, tenant_id):
        cfg = await ctx.registry.get(tid)
        start, end = day_window(cfg.timezone, day)
        async with ctx.sf() as s:
            conversations += int(
                await s.scalar(
                    select(func.count(Conversation.id)).where(
                        Conversation.tenant_id == tid,
                        Conversation.started_at >= start,
                        Conversation.started_at < end,
                    )
                )
                or 0
            )
            flagged += int(
                await s.scalar(
                    select(func.count(Conversation.id)).where(
                        Conversation.tenant_id == tid,
                        Conversation.started_at >= start,
                        Conversation.started_at < end,
                        Conversation.health_context.is_(True),
                    )
                )
                or 0
            )
            items_flagged += int(
                await s.scalar(
                    select(func.count(Item.id)).where(
                        Item.tenant_id == tid,
                        Item.created_at >= start,
                        Item.created_at < end,
                        Item.health_context.is_(True),
                    )
                )
                or 0
            )
    return {
        "conversations": conversations,
        "flagged": flagged,
        "items_flagged": items_flagged,
    }


# --- the judge client -------------------------------------------------------------------


def make_judge(settings) -> LLMClient | None:
    """The configured judge, or None when no key exists so the rest of the audit still runs."""
    if not getattr(settings, "google_api_key", ""):
        return None
    from spatalk.brain.driver import GeminiClient

    return GeminiClient(
        settings.google_api_key,
        settings.judge_model,
        temperature=0.0,
        thinking_budget=JUDGE_THINKING_BUDGET,
    )


# --- the whole run ----------------------------------------------------------------------


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
            update(OpsRun)
            .where(OpsRun.id == run_id)
            .values(finished_at=now, ok=ok, summary=summary)
        )


async def _store(ctx, day: date, audit: TenantAudit) -> None:
    """One row per (day, tenant). A re-run replaces its verdict; it does not add a second."""
    async with ctx.sf() as s, s.begin():
        stmt = pg_insert(AuditReportRow).values(
            day=day, tenant_id=audit.tenant_id, report=audit.as_json()
        )
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=[AuditReportRow.day, AuditReportRow.tenant_id],
                set_={"report": stmt.excluded.report},
            )
        )


def report_email(report: AuditReport) -> tuple[str, str]:
    """The plain-text summary that goes to `ops_email`, subject and body."""
    blocking = report.blocking()
    lexicon = sum(t.lexicon.get("count", 0) for t in report.tenants)
    subject = (
        f"SpaTalk nightly audit {report.day.isoformat()}: "
        f"{len(blocking)} blocking, {lexicon} lexicon findings"
    )
    lines = [f"Nightly escalation audit for {report.day.isoformat()}", ""]
    for t in report.tenants:
        lines.append(t.tenant_id)
        lines.append(
            f"  clinical terms outside band 3: {t.lexicon.get('count', 0)}"
            + (
                f" ({', '.join(t.lexicon['conversations_with_clinical_terms_not_band3'])})"
                if t.lexicon.get("conversations_with_clinical_terms_not_band3")
                else ""
            )
        )
        bands = t.bands
        judged = (
            "  bands: not judged (no judge model configured)"
            if bands.get("skipped")
            else (
                f"  bands reviewed: {bands.get('reviewed', 0)}, "
                f"disagreements: {len(bands.get('disagreements', []))}, "
                f"blocking: {len(t.blocking)}, unreadable answers: {bands.get('errors', 0)}"
            )
        )
        lines.append(judged)
        hc = t.health_context
        lines.append(
            f"  health context: {hc.get('flagged', 0)} of {hc.get('conversations', 0)} "
            f"conversations, {hc.get('items_flagged', 0)} items"
        )
        for b in t.blocking:
            lines.append(
                f"  BLOCKING conversation {b['conversation_id']}: handled as band "
                f"{b['actual_band']}, judged band {b['judged_band']} - {b['reason']}"
            )
        lines.append("")
    return subject, "\n".join(lines)


def _blocking_alert(day: date, audit: TenantAudit) -> tuple[str, str, str]:
    key = f"audit_blocking:{audit.tenant_id}:{day.isoformat()}"
    subject = (
        f"BLOCKING: {audit.tenant_id} handled {len(audit.blocking)} band-3 "
        f"conversation(s) as band 1 or 2 on {day.isoformat()}"
    )
    body = "\n".join(
        [subject, ""]
        + [
            f"conversation {b['conversation_id']}: handled as band {b['actual_band']}, "
            f"judged band {b['judged_band']} - {b['reason']}"
            for b in audit.blocking
        ]
    )
    return key, subject, body


async def run_nightly_audit(
    ctx, day: date | None = None, judge: LLMClient | None = None
) -> AuditReport:
    """The whole night: scan, judge, count, store, email, and alert on a blocking finding.

    `day` defaults to yesterday, which is what the 04:00 UTC job wants. The report is
    persisted per tenant before the email is composed, so a mail failure cannot lose the
    finding.
    """
    at = ctx.clock.now()
    day = day or (at.astimezone(timezone.utc).date() - timedelta(days=1))
    run_id = await _start_run(ctx.sf, at)
    report = AuditReport(day=day)
    try:
        judge = judge or make_judge(ctx.settings)
        for tid in await _tenant_ids(ctx, None):
            audit = TenantAudit(tenant_id=tid)
            audit.lexicon = await lexicon_scan(ctx, day, tid)
            if judge is None:
                audit.bands = {"reviewed": 0, "disagreements": [], "errors": 0, "skipped": True}
            else:
                audit.bands = await band_audit(ctx, day, judge, tid)
                audit.blocking = blocking_findings(audit.bands)
            audit.health_context = await health_context_stats(ctx, day, tid)
            await _store(ctx, day, audit)
            report.tenants.append(audit)
    except Exception as e:
        await _finish_run(
            ctx.sf,
            run_id,
            ctx.clock.now(),
            ok=False,
            summary={"day": day.isoformat(), "error": f"{type(e).__name__}: {e}"[:500]},
        )
        raise
    for audit in report.tenants:
        if audit.blocking:
            await alerts.notify(ctx, *_blocking_alert(day, audit))
    to = getattr(ctx.settings, "ops_email", "")
    if to:
        subject, body = report_email(report)
        await ctx.delivery.send_email(to, subject, body)
    else:
        logger.warning("nightly audit for {} not emailed: OPS_EMAIL is not set", day)
    await _finish_run(
        ctx.sf,
        run_id,
        ctx.clock.now(),
        ok=True,
        summary={
            "day": day.isoformat(),
            "tenants": {t.tenant_id: t.as_json() for t in report.tenants},
        },
    )
    logger.info(
        "nightly audit {}: {} tenants, {} blocking", day, len(report.tenants), len(report.blocking())
    )
    return report


@jobs.register_handler(RUN_KIND)
async def _nightly_audit_job(payload: dict, ctx: jobs.JobContext) -> None:
    day = payload.get("day")
    await run_nightly_audit(ctx, date.fromisoformat(day) if day else None)
