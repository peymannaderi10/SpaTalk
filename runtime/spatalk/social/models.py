"""The three tables the social channels own (data-model.md: instagram plan).

They sit in the same ``runtime`` schema and on the same declarative ``Base`` as everything
else, so one migration chain and one ``Base.metadata.create_all`` cover them. They are here
rather than in :mod:`spatalk.models` because the instagram plan's file structure puts them
here; anything importing them must import this module for the mappers to register.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from spatalk.db import Base


class TenantIntegration(Base):
    """One connected account per tenant per provider, with its token encrypted.

    A Meta row is an Instagram account or a Facebook Page: ``external_id`` is what a webhook
    ``entry.id`` carries, so it is how an inbound event finds its tenant. A Slack row
    (onboarding roadmap, section 3) is a workspace the clinic installed the app in:
    ``external_id`` is the team id, the token is the bot token, and the two nullable columns
    at the end are the channel the install chose and its incoming webhook.
    """

    __tablename__ = "tenant_integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_integration_tenant_provider"),
        Index("ix_integration_external", "provider", "external_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("runtime.tenants.id"))
    provider: Mapped[str] = mapped_column(String(16))  # instagram | messenger | slack
    external_id: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(200))
    # Fernet ciphertext. The token itself never lands in a column, a log line or an email.
    access_token_enc: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # The refresh job could not renew this token: the tenant must reconnect in the portal.
    needs_reconnect: Mapped[bool] = mapped_column(Boolean, default=False)
    connected_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # --- slack one-click connect (onboarding roadmap, section 3; migration 0014) ---
    # The channel the workspace chose at install, and that channel's incoming-webhook URL.
    # Whoever holds the URL can post to the channel, so it is Fernet ciphertext exactly like
    # the token. Both null on a Meta row.
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    webhook_url_enc: Mapped[str | None] = mapped_column(Text, nullable=True)


class MetaEvent(Base):
    """Dedup key for every Meta webhook event. The primary key is the dedup."""

    __tablename__ = "meta_events"
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))  # comment | message | postback | read | echo
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MetaWindow(Base):
    """The 24-hour messaging window anchor: when this sender last wrote to us."""

    __tablename__ = "meta_windows"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    sender_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
