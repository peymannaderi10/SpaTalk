"""The portal's only way into the runtime: `/internal/*` (portal plan, Task C3).

Two planes, zero shared tables (CLAUDE.md non-negotiable 7). The portal owns the `public`
schema and never opens a connection to `runtime`; everything it shows about tenants,
conversations, items and usage arrives through this router, authenticated with a shared
key and carrying the acting user's email in `X-Actor` so the runtime can write the audit
row itself. The committed OpenAPI snapshot at `docs/contracts/runtime-internal.openapi.json`
is generated from these routes and is what the portal's typed client is built from, so a
change here is a contract change and must be regenerated deliberately.

Dates in query strings are plain `YYYY-MM-DD` days in the *tenant's* timezone, never UTC
days: a clinic's Monday is what its owner is looking at (CLAUDE.md non-negotiable 8).
"""

from __future__ import annotations

import hmac
import json
import math
import uuid as uuidlib
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk.models import (
    AuditLog,
    AuditReport,
    Conversation,
    Item,
    Job,
    Message,
    SmsBlock,
    Tenant,
    TenantConfigVersion,
    TenantNumber,
    UsageEvent,
)
from spatalk.ledger.summary import preferred_text, summarize_item
from spatalk.rates import estimate_cad, load_rates
from spatalk.tenants.bundle import config_from_texts
from spatalk.tenants.schema import TenantConfig
from spatalk.tenants.starter import TenantBasics, render_starter
from spatalk.text import flood
from spatalk.text.staff import staff_numbers

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 400

ActorHeader = Annotated[str | None, Header(alias="X-Actor")]

internal_key_scheme = APIKeyHeader(
    name="X-Internal-Key",
    auto_error=False,
    description="Shared key from INTERNAL_API_KEY; compared in constant time.",
)


async def require_internal_key(
    request: Request, presented: Annotated[str | None, Depends(internal_key_scheme)]
) -> None:
    """Fails closed: with no key configured, nobody gets in."""
    expected = getattr(request.app.state.ctx.settings, "internal_api_key", "")
    if not expected or not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid internal key")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_key)],
)


# --- response models ------------------------------------------------------------------


class NumberOut(BaseModel):
    number: str
    kind: str


class TenantSummary(BaseModel):
    id: str
    name: str
    version: int
    numbers: list[NumberOut]
    sms_from_number: str | None
    integration_tier: str


class TenantCreated(BaseModel):
    id: str
    version: int


class VersionOut(BaseModel):
    version: int


class ConfigOut(BaseModel):
    version: int
    config: dict[str, Any]


class ConfigVersionOut(BaseModel):
    version: int
    created_by: str
    created_at: datetime


class ConfigIn(BaseModel):
    config: dict[str, Any]
    created_by: str = "portal"


class RollbackIn(BaseModel):
    version: int
    created_by: str = "portal"


class ActorIn(BaseModel):
    actor: str


class AuditIn(BaseModel):
    actor: str
    action: str
    record_type: str
    record_id: str


class UsageTotals(BaseModel):
    calls: int
    call_minutes: float
    sms_in: int
    sms_out: int
    chats: int
    ig_messages: int
    llm_input_tokens: int
    llm_cached_tokens: int
    llm_output_tokens: int
    tts_chars: int
    est_cost_cad: float


class UsageDay(UsageTotals):
    date: date


class UsageOut(BaseModel):
    days: list[UsageDay]
    totals: UsageTotals


class ConversationRow(BaseModel):
    id: uuidlib.UUID
    channel: str
    started_at: datetime
    ended_at: datetime | None
    duration_s: int | None
    band: int | None
    health_context: bool
    controller: str
    item_count: int
    caller_masked: str | None


class ConversationPage(BaseModel):
    items: list[ConversationRow]
    total: int


class ConversationFull(ConversationRow):
    tenant_id: str
    caller: str | None
    external_ref: str | None
    # --- call notes (call-notes plan, Task N1) ---
    # The notes drafted from this conversation's transcript, under the tenant's own label in
    # the portal. Null until the drafting job has run, and null again for good when
    # retention takes the transcript. The list view stays without them on purpose: a page of
    # conversations is a list of rows, and the notes are read on the page that shows the
    # transcript beside them.
    notes: str | None
    notes_at: datetime | None


# The name the call-notes plan gives the conversation output model. The model itself has
# been `ConversationFull` since the portal plan, and renaming it would rename a schema the
# portal's generated client already imports.
ConversationOut = ConversationFull


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role: str
    text: str
    created_at: datetime


class ItemOut(BaseModel):
    """Every column of `runtime.items`. There is no free-text column and never will be."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: str
    conversation_id: uuidlib.UUID | None
    type: str
    urgency: str
    service_id: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    preferred_window: dict[str, Any]
    channel: str
    health_context: bool
    # --- lead context (plan L, Task L1) ---
    returning_client: bool | None
    practitioner: str | None
    concern: str | None
    state: str
    due_at: datetime
    owner: str
    escalated_at: datetime | None
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None
    resolved_by: str | None
    created_at: datetime
    # Derived in the runtime so the portal, the owner's SMS and the email say one thing.
    summary: str
    service_name: str | None
    preferred_text: str
    # --- call notes (call-notes plan, Task N1) ---
    # Read from the item's *conversation*, never stored here: `items` has no free-text
    # column and never will (CLAUDE.md non-negotiable 2). It travels with the item so the
    # request card needs one call rather than a second fetch per row.
    notes: str | None


# The four fields above that are composed or joined rather than read from a column.
DERIVED_ITEM_FIELDS = ("summary", "service_name", "preferred_text", "notes")


def item_out(item: Item, cfg: TenantConfig, notes: str | None = None) -> ItemOut:
    """One item as the portal sees it: its columns plus the derived, deterministic wording."""
    known = cfg.service(item.service_id) if item.service_id else None
    return ItemOut(
        **{
            name: getattr(item, name)
            for name in ItemOut.model_fields
            if name not in DERIVED_ITEM_FIELDS
        },
        summary=summarize_item(item, cfg),
        service_name=known.name if known else None,
        preferred_text=preferred_text(item.preferred_window),
        notes=notes,
    )


async def notes_by_conversation(sf: async_sessionmaker, items: list[Item]) -> dict:
    """The drafted notes for a page of items, in one query keyed by conversation id."""
    ids = {i.conversation_id for i in items if i.conversation_id is not None}
    if not ids:
        return {}
    async with sf() as s:
        rows = (
            await s.execute(
                select(Conversation.id, Conversation.notes).where(
                    Conversation.id.in_(ids), Conversation.notes.is_not(None)
                )
            )
        ).all()
    return dict(rows)


class ConversationDetail(BaseModel):
    conversation: ConversationFull
    messages: list[MessageOut]
    items: list[ItemOut]


class LatencyDay(BaseModel):
    date: date
    turns: int
    p50_ms: int
    p95_ms: int


class TenantHealth(BaseModel):
    open_items: int
    overdue_items: int
    last_call_at: datetime | None
    last_sms_at: datetime | None
    config_version: int | None
    # SMS flood guard (plan F, F2): numbers currently muted, numbers blocked for good, and
    # assistant replies sent today in the tenant's local day.
    sms_muted_numbers: int = 0
    sms_blocked_numbers: int = 0
    sms_replies_today: int = 0


class RuntimeHealth(BaseModel):
    ok: bool
    queued_jobs: int
    oldest_queued_age_s: float | None
    dead_jobs: int


# --- helpers --------------------------------------------------------------------------


def _ctx(request: Request):
    return request.app.state.ctx


def mask_caller(caller: str | None) -> str | None:
    """List views show the last four digits only; the detail view shows the number."""
    if not caller:
        return None
    digits = [c for c in caller if c.isdigit()]
    return "***" + "".join(digits[-4:]) if digits else "***"


def portal_actor(x_actor: str | None, fallback: str | None = None) -> str:
    """`portal:<email>` as the data model spells it, or plain `portal` if unnamed."""
    who = (x_actor or fallback or "").strip()
    return f"portal:{who}" if who else "portal"


async def write_audit(sf: async_sessionmaker, actor: str, action: str, rtype: str, rid: str):
    async with sf() as s, s.begin():
        s.add(AuditLog(actor=actor, action=action, record_type=rtype, record_id=rid))


async def config_versions(sf: async_sessionmaker) -> dict[str, int]:
    """The current config version of every tenant, for `/healthz`."""
    async with sf() as s:
        rows = (
            await s.execute(
                select(TenantConfigVersion.tenant_id, func.max(TenantConfigVersion.version))
                .group_by(TenantConfigVersion.tenant_id)
                .order_by(TenantConfigVersion.tenant_id)
            )
        ).all()
    return {tenant_id: version for tenant_id, version in rows}


async def _tenant_config(ctx, tenant_id: str) -> TenantConfig:
    try:
        return await ctx.registry.get(tenant_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown tenant {tenant_id}")


def _validation_error(loc: list[str], message: str) -> HTTPException:
    return HTTPException(
        status_code=422, detail=[{"loc": loc, "msg": message, "type": "value_error"}]
    )


def _validate_config(raw: dict[str, Any]) -> TenantConfig:
    try:
        return TenantConfig.model_validate(raw)
    except ValidationError as e:
        detail = [
            {"loc": ["config", *(str(part) for part in err["loc"])], "msg": err["msg"],
             "type": err["type"]}
            for err in json.loads(e.json())
        ]
        raise HTTPException(status_code=422, detail=detail)


def _day_range(
    tz_name: str, from_: date | None, to: date | None, now: datetime, span: int
) -> tuple[date, date, datetime, datetime]:
    """Local first and last day, and the half-open UTC window that holds them."""
    zone = ZoneInfo(tz_name)
    today = now.astimezone(zone).date()
    last = to or today
    first = from_ or (last - timedelta(days=span - 1))
    if first > last:
        raise _validation_error(["query", "from"], "from is after to")
    if (last - first).days + 1 > MAX_RANGE_DAYS:
        raise _validation_error(["query", "from"], f"range longer than {MAX_RANGE_DAYS} days")
    start = datetime.combine(first, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=zone).astimezone(
        timezone.utc
    )
    return first, last, start, end


def _percentile(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return int(ordered[rank - 1])


def _local_day(tz_name: str, column):
    return cast(func.timezone(tz_name, column), Date)


# --- tenants and configuration --------------------------------------------------------


@router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(request: Request):
    ctx = _ctx(request)
    async with ctx.sf() as s:
        tenants = (await s.scalars(select(Tenant).order_by(Tenant.id))).all()
        versions = dict(
            (
                await s.execute(
                    select(TenantConfigVersion.tenant_id, func.max(TenantConfigVersion.version))
                    .group_by(TenantConfigVersion.tenant_id)
                )
            ).all()
        )
        numbers: dict[str, list[NumberOut]] = defaultdict(list)
        for row in (await s.scalars(select(TenantNumber).order_by(TenantNumber.number))).all():
            numbers[row.tenant_id].append(NumberOut(number=row.number, kind=row.kind))
    out = []
    for t in tenants:
        cfg = await _tenant_config(ctx, t.id)
        out.append(
            TenantSummary(
                id=t.id,
                name=t.name,
                version=versions.get(t.id, 0),
                numbers=numbers.get(t.id, []),
                sms_from_number=cfg.sms_from_number,
                integration_tier=cfg.integration_tier,
            )
        )
    return out


async def _save_config(ctx, cfg: TenantConfig, created_by: str, actor: str, action: str) -> int:
    version = await ctx.registry.import_config(cfg, created_by)
    # The write happened in this process, so this process's cache can go now; other
    # processes wait out the registry TTL (flows.md 7.3).
    ctx.registry.invalidate(cfg.id)
    await write_audit(ctx.sf, actor, action, "tenant", cfg.id)
    return version


@router.post("/tenants", response_model=TenantCreated)
async def create_tenant(request: Request, body: ConfigIn, x_actor: ActorHeader = None):
    ctx = _ctx(request)
    cfg = _validate_config(body.config)
    version = await _save_config(
        ctx, cfg, body.created_by, portal_actor(x_actor, body.created_by), "config_save"
    )
    return TenantCreated(id=cfg.id, version=version)


@router.post("/tenants/from-bundle", response_model=TenantCreated)
async def create_tenant_from_bundle(
    request: Request,
    tenant: Annotated[UploadFile, File(description="tenant.yaml")],
    services: Annotated[UploadFile, File(description="services.yaml")],
    knowledge: Annotated[UploadFile, File(description="knowledge.md")],
    scripts: Annotated[UploadFile, File(description="scripts.yaml")],
    guard: Annotated[UploadFile, File(description="guard.yaml")],
    created_by: Annotated[str, Form()] = "portal",
    x_actor: ActorHeader = None,
):
    """The five-file YAML bundle, uploaded instead of read from disk.

    The onboarding wizard (Task C5) posts the files the founder was given; they go through
    exactly the rules `spatalk tenant import` uses, so a bundle that imports from the CLI
    imports from the portal and the other way round.
    """
    ctx = _ctx(request)
    uploads = {
        "tenant.yaml": tenant,
        "services.yaml": services,
        "knowledge.md": knowledge,
        "scripts.yaml": scripts,
        "guard.yaml": guard,
    }
    texts: dict[str, str] = {}
    for name, upload in uploads.items():
        try:
            texts[name] = (await upload.read()).decode("utf-8")
        except UnicodeDecodeError:
            raise _validation_error(["body", name], "file is not UTF-8 text")
    try:
        cfg = config_from_texts(texts, source="upload")
    except ValueError as e:
        raise _validation_error(["body", "bundle"], str(e))
    version = await _save_config(
        ctx, cfg, created_by, portal_actor(x_actor, created_by), "config_save"
    )
    return TenantCreated(id=cfg.id, version=version)


class TenantBasicsIn(TenantBasics):
    created_by: str = "portal"


@router.post("/tenants/from-basics", response_model=TenantCreated)
async def create_tenant_from_basics(
    request: Request, body: TenantBasicsIn, x_actor: ActorHeader = None
):
    """A tenant from the basics alone: the starter bundle rendered around them.

    The wizard's "start from the basics" path (onboarding roadmap, section 4). The five
    texts go through `config_from_texts` like an upload would, so the tenant is judged by
    the same rules. Unlike `from-bundle`, which deliberately versions an existing tenant,
    this refuses one that already exists: a form must never overwrite a configured clinic.
    """
    ctx = _ctx(request)
    try:
        await ctx.registry.get(body.id)
    except KeyError:
        pass
    else:
        raise HTTPException(
            status_code=409,
            detail=f"tenant {body.id} already exists; edit it on its Settings page instead",
        )
    try:
        cfg = config_from_texts(render_starter(body), source="starter")
    except ValueError as e:
        raise _validation_error(["body", "basics"], str(e))
    version = await _save_config(
        ctx, cfg, body.created_by, portal_actor(x_actor, body.created_by), "config_save"
    )
    return TenantCreated(id=cfg.id, version=version)


@router.get("/tenants/{tenant_id}/config", response_model=ConfigOut)
async def get_config(request: Request, tenant_id: str):
    ctx = _ctx(request)
    async with ctx.sf() as s:
        row = await s.scalar(
            select(TenantConfigVersion)
            .where(TenantConfigVersion.tenant_id == tenant_id)
            .order_by(TenantConfigVersion.version.desc())
            .limit(1)
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown tenant {tenant_id}")
    return ConfigOut(version=row.version, config=row.config)


@router.put("/tenants/{tenant_id}/config", response_model=VersionOut)
async def put_config(
    request: Request, tenant_id: str, body: ConfigIn, x_actor: ActorHeader = None
):
    ctx = _ctx(request)
    cfg = _validate_config(body.config)
    if cfg.id != tenant_id:
        raise _validation_error(["config", "id"], f"config is for {cfg.id}, not {tenant_id}")
    version = await _save_config(
        ctx, cfg, body.created_by, portal_actor(x_actor, body.created_by), "config_save"
    )
    return VersionOut(version=version)


@router.get("/tenants/{tenant_id}/config/versions", response_model=list[ConfigVersionOut])
async def list_config_versions(request: Request, tenant_id: str):
    ctx = _ctx(request)
    async with ctx.sf() as s:
        rows = (
            await s.scalars(
                select(TenantConfigVersion)
                .where(TenantConfigVersion.tenant_id == tenant_id)
                .order_by(TenantConfigVersion.version.desc())
            )
        ).all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"unknown tenant {tenant_id}")
    return [
        ConfigVersionOut(version=r.version, created_by=r.created_by, created_at=r.created_at)
        for r in rows
    ]


@router.post("/tenants/{tenant_id}/config/rollback", response_model=VersionOut)
async def rollback_config(
    request: Request, tenant_id: str, body: RollbackIn, x_actor: ActorHeader = None
):
    """A rollback is a new version equal to the old one. Nothing is ever deleted."""
    ctx = _ctx(request)
    async with ctx.sf() as s:
        row = await s.scalar(
            select(TenantConfigVersion).where(
                TenantConfigVersion.tenant_id == tenant_id,
                TenantConfigVersion.version == body.version,
            )
        )
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"{tenant_id} has no version {body.version}"
        )
    cfg = _validate_config(row.config)
    version = await _save_config(
        ctx, cfg, body.created_by, portal_actor(x_actor, body.created_by), "config_rollback"
    )
    return VersionOut(version=version)


@router.get("/schema/tenant-config", response_model=dict[str, Any])
async def tenant_config_schema():
    """The pydantic models are the single source of truth; the portal's forms are built
    from this schema, so a field added anywhere else is a defect."""
    return TenantConfig.model_json_schema()


# --- usage, conversations, items ------------------------------------------------------


@router.get("/tenants/{tenant_id}/usage", response_model=UsageOut)
async def tenant_usage(
    request: Request,
    tenant_id: str,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
):
    ctx = _ctx(request)
    cfg = await _tenant_config(ctx, tenant_id)
    first, last, start, end = _day_range(
        cfg.timezone, from_, to, ctx.clock.now(), DEFAULT_RANGE_DAYS
    )
    unit_day = _local_day(cfg.timezone, UsageEvent.created_at)
    conv_day = _local_day(cfg.timezone, Conversation.started_at)
    async with ctx.sf() as s:
        unit_rows = (
            await s.execute(
                select(unit_day, UsageEvent.unit, func.sum(UsageEvent.qty))
                .where(
                    UsageEvent.tenant_id == tenant_id,
                    UsageEvent.created_at >= start,
                    UsageEvent.created_at < end,
                )
                .group_by(unit_day, UsageEvent.unit)
            )
        ).all()
        conv_rows = (
            await s.execute(
                select(conv_day, Conversation.channel, func.count())
                .where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.started_at >= start,
                    Conversation.started_at < end,
                )
                .group_by(conv_day, Conversation.channel)
            )
        ).all()
    units: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for day, unit, qty in unit_rows:
        units[day][unit] += float(qty)
    counts: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for day, channel, count in conv_rows:
        counts[day][channel] += int(count)

    def row(u: dict[str, float], c: dict[str, int]) -> dict[str, Any]:
        return {
            "calls": c.get("voice", 0),
            "call_minutes": round(u.get("telephony_seconds", 0.0) / 60, 2),
            "sms_in": int(u.get("sms_in", 0)),
            "sms_out": int(u.get("sms_out", 0)),
            "chats": c.get("chat", 0),
            "ig_messages": int(u.get("ig_in", 0) + u.get("ig_out", 0)),
            "llm_input_tokens": int(u.get("llm_input_tokens", 0)),
            "llm_cached_tokens": int(u.get("llm_cached_tokens", 0)),
            "llm_output_tokens": int(u.get("llm_output_tokens", 0)),
            "tts_chars": int(u.get("tts_chars", 0)),
            "est_cost_cad": estimate_cad(u),
        }

    days: list[UsageDay] = []
    totals_units: dict[str, float] = defaultdict(float)
    totals_counts: dict[str, int] = defaultdict(int)
    cursor = first
    while cursor <= last:
        u, c = units.get(cursor, {}), counts.get(cursor, {})
        for unit, qty in u.items():
            totals_units[unit] += qty
        for channel, count in c.items():
            totals_counts[channel] += count
        days.append(UsageDay(date=cursor, **row(u, c)))
        cursor += timedelta(days=1)
    return UsageOut(days=days, totals=UsageTotals(**row(totals_units, totals_counts)))


@router.get("/tenants/{tenant_id}/conversations", response_model=ConversationPage)
async def tenant_conversations(
    request: Request,
    tenant_id: str,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    channel: Annotated[str | None, Query()] = None,
    band: Annotated[int | None, Query(ge=1, le=3)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
):
    ctx = _ctx(request)
    cfg = await _tenant_config(ctx, tenant_id)
    where = [Conversation.tenant_id == tenant_id]
    if from_ or to:
        _, _, start, end = _day_range(
            cfg.timezone, from_, to, ctx.clock.now(), DEFAULT_RANGE_DAYS
        )
        where += [Conversation.started_at >= start, Conversation.started_at < end]
    if channel:
        where.append(Conversation.channel == channel)
    if band is not None:
        where.append(Conversation.band == band)
    item_count = (
        select(func.count(Item.id))
        .where(Item.conversation_id == Conversation.id)
        .correlate(Conversation)
        .scalar_subquery()
    )
    async with ctx.sf() as s:
        total = await s.scalar(select(func.count()).select_from(Conversation).where(*where))
        rows = (
            await s.execute(
                select(Conversation, item_count)
                .where(*where)
                .order_by(Conversation.started_at.desc(), Conversation.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    return ConversationPage(
        items=[_conversation_row(c, n) for c, n in rows], total=int(total or 0)
    )


def _duration_s(c: Conversation) -> int | None:
    if c.ended_at is None:
        return None
    return int((c.ended_at - c.started_at).total_seconds())


def _conversation_row(c: Conversation, item_count: int) -> ConversationRow:
    return ConversationRow(
        id=c.id,
        channel=c.channel,
        started_at=c.started_at,
        ended_at=c.ended_at,
        duration_s=_duration_s(c),
        band=c.band,
        health_context=c.health_context,
        controller=c.controller,
        item_count=int(item_count),
        caller_masked=mask_caller(c.caller),
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def read_conversation(
    request: Request, conversation_id: uuidlib.UUID, x_actor: ActorHeader = None
):
    """Reading a transcript is an audited act, whoever the reader is."""
    ctx = _ctx(request)
    async with ctx.sf() as s:
        conv = await s.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="unknown conversation")
        messages = (
            await s.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id)
            )
        ).all()
        items = (
            await s.scalars(
                select(Item).where(Item.conversation_id == conversation_id).order_by(Item.id)
            )
        ).all()
    await write_audit(
        ctx.sf,
        portal_actor(x_actor),
        "read_transcript",
        "conversation",
        str(conversation_id),
    )
    cfg = await _tenant_config(ctx, conv.tenant_id)
    row = _conversation_row(conv, len(items))
    return ConversationDetail(
        conversation=ConversationFull(
            **row.model_dump(),
            tenant_id=conv.tenant_id,
            caller=conv.caller,
            external_ref=conv.external_ref,
            notes=conv.notes,
            notes_at=conv.notes_at,
        ),
        messages=[MessageOut.model_validate(m) for m in messages],
        items=[item_out(i, cfg, conv.notes) for i in items],
    )


@router.get("/tenants/{tenant_id}/items", response_model=list[ItemOut])
async def tenant_items(
    request: Request,
    tenant_id: str,
    state: Annotated[
        Literal["open", "acknowledged", "resolved", "expired", "all"], Query()
    ] = "open",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
):
    ctx = _ctx(request)
    where = [Item.tenant_id == tenant_id]
    if state != "all":
        where.append(Item.state == state)
    async with ctx.sf() as s:
        rows = (
            await s.scalars(
                select(Item)
                .where(*where)
                .order_by(Item.due_at, Item.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    cfg = await _tenant_config(ctx, tenant_id)
    notes = await notes_by_conversation(ctx.sf, list(rows))
    return [item_out(i, cfg, notes.get(i.conversation_id)) for i in rows]


async def _transition(request: Request, item_id: int, body: ActorIn, x_actor: str | None, verb):
    ctx = _ctx(request)
    item = await (ctx.ledger.acknowledge if verb == "ack" else ctx.ledger.resolve)(
        item_id, body.actor
    )
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown item {item_id}")
    await write_audit(ctx.sf, portal_actor(x_actor, body.actor), verb, "item", str(item_id))
    notes = await notes_by_conversation(ctx.sf, [item])
    return item_out(
        item, await _tenant_config(ctx, item.tenant_id), notes.get(item.conversation_id)
    )


@router.post("/items/{item_id}/acknowledge", response_model=ItemOut)
async def acknowledge_item(
    request: Request, item_id: int, body: ActorIn, x_actor: ActorHeader = None
):
    return await _transition(request, item_id, body, x_actor, "ack")


@router.post("/items/{item_id}/resolve", response_model=ItemOut)
async def resolve_item(
    request: Request, item_id: int, body: ActorIn, x_actor: ActorHeader = None
):
    return await _transition(request, item_id, body, x_actor, "resolve")


@router.get("/tenants/{tenant_id}/latency", response_model=list[LatencyDay])
async def tenant_latency(
    request: Request,
    tenant_id: str,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
):
    ctx = _ctx(request)
    cfg = await _tenant_config(ctx, tenant_id)
    first, last, start, end = _day_range(
        cfg.timezone, from_, to, ctx.clock.now(), DEFAULT_RANGE_DAYS
    )
    day = _local_day(cfg.timezone, Conversation.started_at)
    async with ctx.sf() as s:
        rows = (
            await s.execute(
                select(day, Conversation.latency_ms).where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.started_at >= start,
                    Conversation.started_at < end,
                    Conversation.latency_ms.isnot(None),
                )
            )
        ).all()
    by_day: dict[date, list[int]] = defaultdict(list)
    for local_day, turns in rows:
        by_day[local_day].extend(int(t) for t in (turns or []))
    return [
        LatencyDay(
            date=d,
            turns=len(values),
            p50_ms=_percentile(values, 50),
            p95_ms=_percentile(values, 95),
        )
        for d, values in sorted(by_day.items())
        if values and first <= d <= last
    ]


@router.get("/tenants/{tenant_id}/health", response_model=TenantHealth)
async def tenant_health(request: Request, tenant_id: str):
    ctx = _ctx(request)
    cfg = await _tenant_config(ctx, tenant_id)
    now = ctx.clock.now()
    unresolved = Item.state.in_(("open", "acknowledged"))
    async with ctx.sf() as s:
        open_items = await s.scalar(
            select(func.count()).select_from(Item).where(Item.tenant_id == tenant_id, unresolved)
        )
        overdue = await s.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.tenant_id == tenant_id, unresolved, Item.due_at < now)
        )
        last_call = await s.scalar(
            select(func.max(Conversation.started_at)).where(
                Conversation.tenant_id == tenant_id, Conversation.channel == "voice"
            )
        )
        last_sms = await s.scalar(
            select(
                func.max(func.coalesce(Conversation.last_message_at, Conversation.started_at))
            ).where(Conversation.tenant_id == tenant_id, Conversation.channel == "sms")
        )
        version = await s.scalar(
            select(func.max(TenantConfigVersion.version)).where(
                TenantConfigVersion.tenant_id == tenant_id
            )
        )
        muted = await s.scalar(
            select(func.count())
            .select_from(SmsBlock)
            .where(SmsBlock.tenant_id == tenant_id, SmsBlock.until.isnot(None), SmsBlock.until > now)
        )
        blocked = await s.scalar(
            select(func.count())
            .select_from(SmsBlock)
            .where(SmsBlock.tenant_id == tenant_id, SmsBlock.until.is_(None))
        )
    return TenantHealth(
        open_items=int(open_items or 0),
        overdue_items=int(overdue or 0),
        last_call_at=last_call,
        last_sms_at=last_sms,
        config_version=version,
        sms_muted_numbers=int(muted or 0),
        sms_blocked_numbers=int(blocked or 0),
        sms_replies_today=await flood.replies_today(ctx, cfg, now),
    )


# --- sms blocks (plan F, F2) ---------------------------------------------------------------
# A person's decision about a number, from the portal: block it for good, or lift a block or
# a flood mute. Staff numbers cannot be blocked. Every change is an audit row.

E164 = r"^\+[1-9][0-9]{7,14}$"


class SmsBlockIn(BaseModel):
    phone: str = Field(pattern=E164)
    actor: str


class SmsBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    phone: str
    until: datetime | None
    reason: str
    created_by: str
    created_at: datetime


class SmsBlockRemoved(BaseModel):
    removed: bool


@router.get("/tenants/{tenant_id}/sms-blocks", response_model=list[SmsBlockOut])
async def sms_blocks(request: Request, tenant_id: str):
    ctx = _ctx(request)
    await _tenant_config(ctx, tenant_id)
    return [SmsBlockOut.model_validate(b) for b in await flood.list_blocks(ctx, tenant_id)]


@router.post("/tenants/{tenant_id}/sms-blocks", response_model=SmsBlockOut)
async def add_sms_block(
    request: Request, tenant_id: str, body: SmsBlockIn, x_actor: ActorHeader = None
):
    ctx = _ctx(request)
    cfg = await _tenant_config(ctx, tenant_id)
    if body.phone in staff_numbers(cfg):
        raise HTTPException(
            status_code=409, detail=f"{body.phone} is a staff number for {tenant_id}"
        )
    actor = portal_actor(x_actor, body.actor)
    await flood.block(ctx, cfg, body.phone, created_by=actor)
    await write_audit(ctx.sf, actor, "sms.block", "sms_block", body.phone)
    rows = {b.phone: b for b in await flood.list_blocks(ctx, tenant_id)}
    return SmsBlockOut.model_validate(rows[body.phone])


@router.delete("/tenants/{tenant_id}/sms-blocks/{phone}", response_model=SmsBlockRemoved)
async def remove_sms_block(
    request: Request,
    tenant_id: str,
    phone: str,
    actor: Annotated[str, Query()],
    x_actor: ActorHeader = None,
):
    ctx = _ctx(request)
    await _tenant_config(ctx, tenant_id)
    if not await flood.unblock(ctx, tenant_id, phone):
        raise HTTPException(status_code=404, detail=f"no block or mute for {phone}")
    await write_audit(ctx.sf, portal_actor(x_actor, actor), "sms.unblock", "sms_block", phone)
    return SmsBlockRemoved(removed=True)


# --- operations (operations plan, Task E4) --------------------------------------------


class AuditLatest(BaseModel):
    """The most recent nightly escalation audit for one tenant.

    All three fields are null until the first night has run, so the admin health page can
    render "no audit yet" without treating an empty history as an error.
    """

    day: date | None
    created_at: datetime | None
    report: dict[str, Any] | None


@router.get("/tenants/{tenant_id}/audit/latest", response_model=AuditLatest)
async def tenant_latest_audit(request: Request, tenant_id: str):
    """What the admin health page reads (portal plan C5): last night's audit for a tenant."""
    ctx = _ctx(request)
    await _tenant_config(ctx, tenant_id)
    async with ctx.sf() as s:
        row = (
            await s.scalars(
                select(AuditReport)
                .where(AuditReport.tenant_id == tenant_id)
                .order_by(AuditReport.day.desc(), AuditReport.id.desc())
                .limit(1)
            )
        ).first()
    if row is None:
        return AuditLatest(day=None, created_at=None, report=None)
    return AuditLatest(day=row.day, created_at=row.created_at, report=row.report)


# --- platform ------------------------------------------------------------------------


@router.get("/health", response_model=RuntimeHealth)
async def runtime_health(request: Request):
    """Queue depth for the agency's health page (Task C5), not a liveness probe."""
    ctx = _ctx(request)
    now = ctx.clock.now()
    async with ctx.sf() as s:
        queued = await s.scalar(
            select(func.count()).select_from(Job).where(Job.state == "queued")
        )
        oldest = await s.scalar(select(func.min(Job.run_at)).where(Job.state == "queued"))
        dead = await s.scalar(select(func.count()).select_from(Job).where(Job.state == "dead"))
    age = max(0.0, (now - oldest).total_seconds()) if oldest is not None else None
    return RuntimeHealth(
        ok=True,
        queued_jobs=int(queued or 0),
        oldest_queued_age_s=age,
        dead_jobs=int(dead or 0),
    )


@router.get("/rates", response_model=dict[str, Any])
async def rates():
    """The prices behind every `est_cost_cad`, so the portal can show its working."""
    return load_rates()


@router.post("/audit", status_code=204, response_class=Response)
async def post_audit(request: Request, body: AuditIn):
    """The portal records an act of its own (an export, a settings view it performed)."""
    await write_audit(_ctx(request).sf, body.actor, body.action, body.record_type, body.record_id)
    return Response(status_code=204)


# --- social integrations (instagram plan, Task D3) ------------------------------------


class MessengerPageSelectIn(BaseModel):
    """Which Facebook Page the owner picked, and the handle the callback handed them."""

    pending: str
    page_id: str


class MessengerPageSelected(BaseModel):
    """The connected Page. No token, encrypted or otherwise, ever crosses this boundary."""

    tenant_id: str
    provider: str
    external_id: str
    display_name: str


@router.post(
    "/tenants/{tenant_id}/integrations/messenger/select",
    response_model=MessengerPageSelected,
)
async def select_messenger_page(request: Request, tenant_id: str, body: MessengerPageSelectIn):
    """Finish a Page connection when the person administers more than one Page.

    `GET /messenger/callback` cannot choose for them and cannot repeat the exchange (the
    OAuth code is single use), so it parks the Pages behind an opaque handle and sends the
    browser back to the portal with their names. This is where the choice lands.
    """
    from spatalk.social.messenger import select_page

    result = await select_page(_ctx(request), tenant_id, body.pending, body.page_id)
    return MessengerPageSelected(
        tenant_id=result.tenant_id,
        provider=result.provider,
        external_id=result.external_id,
        display_name=result.display_name,
    )


# --- social integrations, portal side (instagram plan, Task D4) ------------------------

# The providers the runtime has adapters for, in the order the portal draws its cards: the
# two Meta surfaces and, since one-click connect (onboarding roadmap, section 3), Slack.
INTEGRATION_PROVIDERS = ("instagram", "messenger", "slack")
# The name the instagram plan gave the tuple, kept for anything that still imports it.
SOCIAL_PROVIDERS = INTEGRATION_PROVIDERS


class IntegrationOut(BaseModel):
    """What the portal may know about a connected Meta account or Slack workspace.

    Never the token: not the plaintext, not the ciphertext, not its length. The portal has
    no use for it and no way to keep it as safely as the runtime does. For Slack the same
    goes for the incoming-webhook URL and the channel id; `display_name` already names the
    channel in words.
    """

    provider: str
    connected: bool
    # This runtime has an app id and secret for the provider; without them Connect is a
    # button that could only fail, so the portal shows why instead.
    configured: bool
    external_id: str | None = None
    display_name: str | None = None
    token_expires_at: datetime | None = None
    scopes: list[str] = []
    needs_reconnect: bool = False
    connected_by: str | None = None
    connected_at: datetime | None = None


class ConnectUrlOut(BaseModel):
    """Where to send the browser to connect, and how long that link is good for."""

    url: str
    expires_in: int


class IntegrationRemoved(BaseModel):
    """`disconnected` is the row; `unsubscribed` is whether the provider agreed to stop.

    For a Meta account that is the webhook unsubscribe; for a Slack workspace it is Slack
    confirming the bot token was revoked (`auth.revoke`). Both are best effort, and the row
    goes either way, so the portal can say which of the two happened.
    """

    provider: str
    disconnected: bool
    unsubscribed: bool


def _provider(provider: str) -> str:
    if provider not in INTEGRATION_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider {provider}")
    return provider


def _provider_configured(settings, provider: str) -> bool:
    if provider == "instagram":
        return bool(settings.instagram_app_id and settings.instagram_app_secret)
    if provider == "slack":
        return bool(settings.slack_client_id and settings.slack_client_secret)
    return bool(settings.facebook_app_id and settings.facebook_app_secret)


@router.get("/tenants/{tenant_id}/integrations", response_model=list[IntegrationOut])
async def tenant_integrations(request: Request, tenant_id: str):
    """One row per provider, connected or not, so the page can draw every card."""
    from spatalk.social.meta_oauth import integration_for

    ctx = _ctx(request)
    await _tenant_config(ctx, tenant_id)
    out: list[IntegrationOut] = []
    for provider in INTEGRATION_PROVIDERS:
        row = await integration_for(ctx.sf, tenant_id, provider)
        configured = _provider_configured(ctx.settings, provider)
        if row is None:
            out.append(IntegrationOut(provider=provider, connected=False, configured=configured))
            continue
        out.append(
            IntegrationOut(
                provider=provider,
                connected=True,
                configured=configured,
                external_id=row.external_id,
                display_name=row.display_name,
                token_expires_at=row.token_expires_at,
                scopes=list(row.scopes or []),
                needs_reconnect=bool(row.needs_reconnect),
                connected_by=row.connected_by,
                connected_at=row.created_at,
            )
        )
    return out


@router.get(
    "/tenants/{tenant_id}/integrations/{provider}/connect-url", response_model=ConnectUrlOut
)
async def integration_connect_url(
    request: Request,
    tenant_id: str,
    provider: str,
    return_to: str | None = None,
    x_actor: ActorHeader = None,
):
    """The provider's authorisation URL, with a signed state carrying the tenant and `return_to`.

    The state is what makes this safe to hand out: `/instagram/callback` (or `/messenger/`,
    `/slack/`) will only store an account against the tenant this key-holder named, and will
    only bounce the browser back to the address signed here. It is minted per click, because
    it is good for fifteen minutes and a settings page can sit open for longer than that.
    """
    from spatalk.social.meta_oauth import (
        STATE_MAX_AGE,
        build_instagram_start_url,
        build_page_start_url,
        sign_state,
    )
    from spatalk.social.slack_oauth import build_slack_start_url

    ctx = _ctx(request)
    await _tenant_config(ctx, tenant_id)
    provider = _provider(provider)
    if return_to and not return_to.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="return_to must be an http or https url")
    if not _provider_configured(ctx.settings, provider):
        raise HTTPException(
            status_code=409, detail=f"{provider} is not configured on this service"
        )
    state = sign_state(ctx.settings.secret_key, tenant_id, return_to)
    if provider == "instagram":
        url = build_instagram_start_url(ctx.settings, state)
    elif provider == "slack":
        url = build_slack_start_url(ctx.settings, state)
    else:
        url = build_page_start_url(ctx.settings, state)
    await write_audit(
        ctx.sf, portal_actor(x_actor), "integration_connect_started", "tenant", tenant_id
    )
    return ConnectUrlOut(url=url, expires_in=STATE_MAX_AGE)


@router.delete("/tenants/{tenant_id}/integrations/{provider}", response_model=IntegrationRemoved)
async def disconnect_integration(
    request: Request, tenant_id: str, provider: str, x_actor: ActorHeader = None
):
    """Disconnect: the provider is told to stop, then the row and its token go.

    The order matters. Meta's unsubscribe and Slack's `auth.revoke` both need the token, so
    they happen first; each is best effort, and a provider that refuses does not trap a
    tenant in a connection they have asked to end. The answer says which of the two happened.
    """
    from spatalk.social.meta_oauth import (
        delete_integration,
        integration_for,
        unsubscribe_integration,
    )
    from spatalk.social.slack_oauth import revoke_integration

    ctx = _ctx(request)
    await _tenant_config(ctx, tenant_id)
    provider = _provider(provider)
    row = await integration_for(ctx.sf, tenant_id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{tenant_id} has no {provider} connection")
    graph = getattr(ctx, "graph", None)
    if provider == "slack":
        unsubscribed = await revoke_integration(ctx.settings, row, graph)
    else:
        unsubscribed = await unsubscribe_integration(ctx.settings, row, graph)
    disconnected = await delete_integration(ctx.sf, tenant_id, provider)
    await write_audit(ctx.sf, portal_actor(x_actor), "integration_disconnect", "tenant", tenant_id)
    return IntegrationRemoved(
        provider=provider, disconnected=disconnected, unsubscribed=unsubscribed
    )


# --- the contract ---------------------------------------------------------------------


def _referenced_schemas(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            out.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _referenced_schemas(value, out)
    elif isinstance(node, list):
        for value in node:
            _referenced_schemas(value, out)


def openapi_document(internal_only: bool = True) -> dict:
    """The app's OpenAPI document, optionally narrowed to the portal's contract.

    Generated from a context-free app: this describes routes, never data, so it needs no
    database and no configuration.
    """
    from spatalk.http.app import create_app

    doc = json.loads(json.dumps(create_app(None, start_background=False).openapi()))
    if not internal_only:
        return doc
    doc["paths"] = {p: v for p, v in doc["paths"].items() if p.startswith("/internal")}
    kept: set[str] = set()
    _referenced_schemas(doc["paths"], kept)
    schemas = doc.get("components", {}).get("schemas", {})
    while True:
        grown: set[str] = set()
        for name in kept:
            _referenced_schemas(schemas.get(name, {}), grown)
        if grown <= kept:
            break
        kept |= grown
    if schemas:
        doc["components"]["schemas"] = {k: v for k, v in schemas.items() if k in kept}
    return doc
