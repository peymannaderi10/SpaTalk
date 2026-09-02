from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from spatalk.db import Base


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    last_digest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantConfigVersion(Base):
    __tablename__ = "tenant_config_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("runtime.tenants.id"))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantNumber(Base):
    __tablename__ = "tenant_numbers"
    number: Mapped[str] = mapped_column(String(20), primary_key=True)  # E.164
    tenant_id: Mapped[str] = mapped_column(ForeignKey("runtime.tenants.id"))
    kind: Mapped[str] = mapped_column(String(10))  # voice | sms


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conv_tenant_started", "tenant_id", "started_at"),
        Index("ix_conv_lookup", "tenant_id", "channel", "external_ref", "last_message_at"),
        # Human takeover (Task B5): a staff reply arrives naming only its Slack thread.
        Index("ix_conv_slack_ts", "slack_ts"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("runtime.tenants.id"))
    channel: Mapped[str] = mapped_column(String(16))
    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    caller: Mapped[str | None] = mapped_column(String(200), nullable=True)
    controller: Mapped[str] = mapped_column(String(10), default="ai")
    health_context: Mapped[bool] = mapped_column(Boolean, default=False)
    band: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # --- text channels (text-channels plan, Task B2) ---
    # Last inbound or outbound message: the 24-hour window that decides find-or-create.
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A text conversation the assistant ended; a new message starts a new conversation.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The single follow-up, ever. A column, not a scheduler's memory.
    followup_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Link to a related conversation (SMS text-back -> the voice conversation it followed).
    external_session: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # --- human takeover (text-channels plan, Task B5) ---
    # The Slack thread staff read and reply in: the channel and the root message's ts.
    slack_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slack_ts: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # --- operations (operations plan, Task E5; created here by E3) ---
    # Per-stage p95 for the call, {stt, llm, tts}. E5 fills it from the pipeline observer;
    # E3 needs the column now because retention nulls it alongside latency_ms when the
    # transcript goes (docs/reference/data-model.md, conversations.stage_ms).
    stage_ms: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_msg_conv", "conversation_id", "id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.conversations.id"))
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        Index("ix_items_tenant_state_due", "tenant_id", "state", "due_at"),
        Index(
            "ix_items_breach",
            "due_at",
            postgresql_where=text("state = 'open' AND escalated_at IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("runtime.tenants.id"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runtime.conversations.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(40))
    urgency: Mapped[str] = mapped_column(String(10))
    service_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    preferred_window: Mapped[dict] = mapped_column(JSONB, default=dict)
    channel: Mapped[str] = mapped_column(String(16))
    health_context: Mapped[bool] = mapped_column(Boolean, default=False)
    # open | acknowledged | resolved | expired
    state: Mapped[str] = mapped_column(String(16), default="open")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    owner: Mapped[str] = mapped_column(String(200))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_tenant_created", "tenant_id", "created_at"),
        Index("ix_usage_conv", "conversation_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("runtime.tenants.id"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runtime.conversations.id"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(40))
    # telephony_seconds, stt_seconds, tts_chars, llm_*_tokens, sms_in, sms_out, chat_in, chat_out
    unit: Mapped[str] = mapped_column(String(40))
    qty: Mapped[float] = mapped_column(Numeric(14, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_state_run", "state", "run_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    state: Mapped[str] = mapped_column(String(16), default="queued")  # queued | done | dead
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_record", "record_type", "record_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(64))
    record_type: Mapped[str] = mapped_column(String(32))
    record_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- text channels (text-channels plan, Task B2) ---------------------------------------


class InboundMessage(Base):
    """Dedup key for every inbound provider event. The primary key is the dedup."""

    __tablename__ = "inbound_messages"
    provider_message_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(16))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SmsOptout(Base):
    """A number that must never receive a send from this tenant again, until START."""

    __tablename__ = "sms_optouts"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Textback(Base):
    """One missed-call text-back per caller per day (text-channels plan, Task B3)."""

    __tablename__ = "textbacks"
    __table_args__ = (Index("ix_textback_lookup", "tenant_id", "phone", "sent_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(32))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- operations (operations plan, Task E1) ---------------------------------------------


class AlertLog(Base):
    """Every operational alert the runtime raised, and when.

    Task E1 writes one row per blocked self-call so the founder can see a bad forwarding
    chain the morning after. Task E7's `alerts.notify` reads the same table to deduplicate
    an alert per `key` for six hours, which is why the key is the caller-supplied identity
    of the incident rather than a message.
    """

    __tablename__ = "alert_log"
    __table_args__ = (Index("ix_alert_key_sent", "key", "sent_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(400))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- operations (operations plan, Task E3) ---------------------------------------------


class OpsRun(Base):
    """One row per scheduled operations run, written whether or not the run succeeded.

    The operations plan's global constraint is that every scheduled job is idempotent and
    records a row when it runs. `ok` is what makes the record worth keeping: a nightly job
    that silently stopped running looks exactly like one that ran and found nothing to do,
    unless the run itself is the artefact.
    """

    __tablename__ = "ops_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)


class DeletionReceipt(Base):
    """Proof that a retention delete happened: what, how much, and up to when.

    Retention deletes are hard deletes, so nothing is left to inspect afterwards. The
    receipt is the only evidence the founder can show that a transcript is gone, which is
    why a row is written per (tenant, kind) only when the count is non-zero: a receipt for
    nothing would dilute the ones that mean something.
    """

    __tablename__ = "deletion_receipts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Not a foreign key: a receipt has to outlive the tenant whose data it accounts for.
    tenant_id: Mapped[str] = mapped_column(String(64))
    # messages | conversations | items | usage_events
    kind: Mapped[str] = mapped_column(String(20))
    count: Mapped[int] = mapped_column(Integer)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- operations (operations plan, Task E4) ---------------------------------------------


class AuditReport(Base):
    """One night's escalation audit for one tenant, kept so the finding outlives the email.

    The nightly audit is the only check that can catch a band-3 intent the deterministic
    gate missed, and its value is entirely in being comparable night to night: the report is
    a row, not a message in an inbox. Unique on `(day, tenant_id)` because a re-run of the
    same night replaces its verdict rather than accumulating a second opinion.
    """

    __tablename__ = "audit_reports"
    __table_args__ = (UniqueConstraint("day", "tenant_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The tenant's own local day, not a UTC one: a clinic's Monday is what its owner reads.
    day: Mapped[date] = mapped_column(Date)
    tenant_id: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- whatsapp (plan W) -----------------------------------------------------------------


class WhatsAppWindow(Base):
    """When a staff number last wrote to the platform number: the 24-hour window anchor.

    Meta lets a business send free-form text and interactive buttons only inside 24 hours of
    the person's own last inbound message; outside it, only an approved template goes
    through. Delivery reads this row to choose between the two, so the rule is enforced in
    code rather than assumed (whatsapp plan, Global Constraints).

    Separate from ``meta_windows`` because that table is keyed by an Instagram or Page-scoped
    sender id, and this one by an E.164 phone number that belongs to no Meta account.
    """

    __tablename__ = "whatsapp_windows"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- operations (operations plan, Task E9) ---------------------------------------------


class ProviderInvoice(Base):
    """What a provider actually billed for one month, in Canadian dollars.

    The metered estimate in `spatalk.rates` is a model built on published prices, two of
    which the research could not verify (spec §10 weakness 1). The only thing that settles
    it is the invoice, so the founder types each one in and the monthly reconciliation
    compares the two. Unique on `(provider, month)` because a corrected invoice replaces the
    figure rather than adding a second one; nothing here is a running total.
    """

    __tablename__ = "provider_invoices"
    __table_args__ = (UniqueConstraint("provider", "month"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The name as `usage_events.provider` spells it, so the two sides join by eye.
    provider: Mapped[str] = mapped_column(String(40))
    # `YYYY-MM`, a UTC calendar month: the window providers bill on.
    month: Mapped[str] = mapped_column(String(7))
    amount_cad: Mapped[float] = mapped_column(Numeric(12, 2))
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
