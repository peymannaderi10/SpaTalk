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
