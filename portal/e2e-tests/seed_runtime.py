"""Seed the runtime with one tenant and fixtures for the portal's client-page suite.

The portal owns no tenant, conversation, item or usage data (CLAUDE.md non-negotiable 7),
so the end-to-end tests for its client pages need a *runtime* with something in it. This
script puts exactly that there, in the runtime's own schema through the runtime's own
models, and it is the only thing in the portal that touches those tables.

It is idempotent and destructive for one tenant: everything belonging to `skincentrix` is
removed and rebuilt, so the config version is 1 on every run and the counts the overview
page shows are the counts asserted in `tests/client.spec.ts`.

Run it from `runtime/` with the runtime's environment:

    uv run python ../portal/e2e-tests/seed_runtime.py

`playwright.config.ts` runs it in `globalSetup` before the suite starts.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select

from spatalk.clock import SystemClock
from spatalk.db import make_engine, make_session_factory
from spatalk.models import (
    AuditLog,
    Conversation,
    Item,
    Message,
    TenantConfigVersion,
    TenantNumber,
    UsageEvent,
)
from spatalk.settings import get_settings
from spatalk.tenants.registry import TenantRegistry

TENANT = "skincentrix"
BUNDLE = Path(__file__).resolve().parents[2] / "runtime" / "tenants" / TENANT

VOICE_NUMBER = "+19055550100"
SMS_NUMBER = "+18885550100"

# Every conversation is seeded within the last half hour so that "this month" holds all of
# them whatever day the suite runs on, and so the 30-day chart always has one live day.
CALLER_ONE = "+19055550101"
CALLER_TWO = "+19055550102"
CALLER_SMS = "+19055550103"


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)
    clock = SystemClock()
    registry = TenantRegistry(sf, clock)
    now = clock.now()

    async with sf() as s, s.begin():
        conversations = select(Conversation.id).where(Conversation.tenant_id == TENANT)
        await s.execute(delete(Message).where(Message.conversation_id.in_(conversations)))
        await s.execute(delete(UsageEvent).where(UsageEvent.tenant_id == TENANT))
        await s.execute(delete(Item).where(Item.tenant_id == TENANT))
        await s.execute(delete(Conversation).where(Conversation.tenant_id == TENANT))
        await s.execute(
            delete(TenantConfigVersion).where(TenantConfigVersion.tenant_id == TENANT)
        )
        await s.execute(delete(TenantNumber).where(TenantNumber.tenant_id == TENANT))

    tenant_id, version = await registry.import_bundle(BUNDLE, created_by="e2e-seed")
    await registry.add_number(VOICE_NUMBER, TENANT, "voice")
    await registry.add_number(SMS_NUMBER, TENANT, "sms")

    handled = uuid.uuid4()      # band 1: the assistant answered and nothing was needed
    to_a_person = uuid.uuid4()  # band 3: clinical, straight to a human, health context
    texted = uuid.uuid4()       # sms
    chatted = uuid.uuid4()      # web chat

    async with sf() as s, s.begin():
        s.add_all(
            [
                Conversation(
                    id=handled,
                    tenant_id=TENANT,
                    channel="voice",
                    external_ref="v3:seed-handled",
                    caller=CALLER_ONE,
                    controller="ai",
                    health_context=False,
                    band=1,
                    latency_ms=[820, 1180, 2400],
                    started_at=now - timedelta(minutes=30),
                    ended_at=now - timedelta(minutes=26),
                ),
                Conversation(
                    id=to_a_person,
                    tenant_id=TENANT,
                    channel="voice",
                    external_ref="v3:seed-clinical",
                    caller=CALLER_TWO,
                    controller="ai",
                    health_context=True,
                    band=3,
                    latency_ms=[1500, 3000],
                    started_at=now - timedelta(minutes=25),
                    ended_at=now - timedelta(minutes=23),
                ),
                Conversation(
                    id=texted,
                    tenant_id=TENANT,
                    channel="sms",
                    external_ref=CALLER_SMS,
                    caller=CALLER_SMS,
                    controller="ai",
                    band=2,
                    started_at=now - timedelta(minutes=20),
                    last_message_at=now - timedelta(minutes=18),
                ),
                Conversation(
                    id=chatted,
                    tenant_id=TENANT,
                    channel="chat",
                    external_ref="chat-seed-session",
                    controller="ai",
                    band=2,
                    started_at=now - timedelta(minutes=15),
                    last_message_at=now - timedelta(minutes=14),
                ),
            ]
        )

    async with sf() as s, s.begin():
        s.add_all(
            [
                Message(
                    conversation_id=handled,
                    role="assistant",
                    text="Hi, thanks for calling Skincentrix. I'm Skincentrix's AI assistant.",
                    created_at=now - timedelta(minutes=30),
                ),
                Message(
                    conversation_id=handled,
                    role="user",
                    text="How much is a hydrafacial?",
                    created_at=now - timedelta(minutes=29),
                ),
                Message(
                    conversation_id=handled,
                    role="assistant",
                    text="A hydrafacial is from $180. Would you like the booking link?",
                    created_at=now - timedelta(minutes=28),
                ),
                Message(
                    conversation_id=to_a_person,
                    role="user",
                    text="My skin is burning after the peel yesterday.",
                    created_at=now - timedelta(minutes=25),
                ),
                Message(
                    conversation_id=to_a_person,
                    role="assistant",
                    text=(
                        "That's a question for our clinical team, and I don't want to guess. "
                        "I'm sending them an urgent request right now."
                    ),
                    created_at=now - timedelta(minutes=24),
                ),
                Message(
                    conversation_id=texted,
                    role="user",
                    text="Are you open Sunday?",
                    created_at=now - timedelta(minutes=20),
                ),
                Message(
                    conversation_id=texted,
                    role="assistant",
                    text="We're open Sunday from 1pm to 6pm.",
                    created_at=now - timedelta(minutes=18),
                ),
            ]
        )

        s.add_all(
            [
                # Voice call: four minutes of telephony, the speech and model units with it.
                UsageEvent(
                    tenant_id=TENANT,
                    conversation_id=handled,
                    channel="voice",
                    provider="telnyx",
                    unit="telephony_seconds",
                    qty=240,
                    created_at=now - timedelta(minutes=26),
                ),
                UsageEvent(
                    tenant_id=TENANT,
                    conversation_id=handled,
                    channel="voice",
                    provider="soniox",
                    unit="stt_seconds",
                    qty=240,
                    created_at=now - timedelta(minutes=26),
                ),
                UsageEvent(
                    tenant_id=TENANT,
                    conversation_id=handled,
                    channel="voice",
                    provider="inworld",
                    unit="tts_chars",
                    qty=620,
                    created_at=now - timedelta(minutes=26),
                ),
                UsageEvent(
                    tenant_id=TENANT,
                    conversation_id=handled,
                    channel="voice",
                    provider="gemini-2.5-flash",
                    unit="llm_input_tokens",
                    qty=4200,
                    created_at=now - timedelta(minutes=26),
                ),
                UsageEvent(
                    tenant_id=TENANT,
                    conversation_id=handled,
                    channel="voice",
                    provider="gemini-2.5-flash",
                    unit="llm_cached_tokens",
                    qty=3800,
                    created_at=now - timedelta(minutes=26),
                ),
                UsageEvent(
                    tenant_id=TENANT,
                    conversation_id=handled,
                    channel="voice",
                    provider="gemini-2.5-flash",
                    unit="llm_output_tokens",
                    qty=180,
                    created_at=now - timedelta(minutes=26),
                ),
                UsageEvent(
                    tenant_id=TENANT,
                    conversation_id=to_a_person,
                    channel="voice",
                    provider="telnyx",
                    unit="telephony_seconds",
                    qty=120,
                    created_at=now - timedelta(minutes=23),
                ),
                # Two texts in, two out.
                UsageEvent(
                    tenant_id=TENANT,
                    conversation_id=texted,
                    channel="sms",
                    provider="telnyx",
                    unit="sms_in",
                    qty=2,
                    created_at=now - timedelta(minutes=20),
                ),
                UsageEvent(
                    tenant_id=TENANT,
                    conversation_id=texted,
                    channel="sms",
                    provider="telnyx",
                    unit="sms_out",
                    qty=2,
                    created_at=now - timedelta(minutes=18),
                ),
            ]
        )

        s.add_all(
            [
                # Overdue and urgent: this is what the overview's "needs attention" list is for.
                Item(
                    tenant_id=TENANT,
                    conversation_id=to_a_person,
                    type="escalation_clinical",
                    urgency="urgent",
                    contact_name="Dana W",
                    contact_phone=CALLER_TWO,
                    preferred_window={},
                    channel="voice",
                    health_context=True,
                    state="open",
                    due_at=now - timedelta(hours=1),
                    owner="info@skincentrix.com",
                    created_at=now - timedelta(minutes=25),
                ),
                Item(
                    tenant_id=TENANT,
                    conversation_id=texted,
                    type="new_booking",
                    urgency="normal",
                    service_id="hydrafacial",
                    contact_name="Priya S",
                    contact_phone=CALLER_SMS,
                    preferred_window={"date": "2026-09-10", "part_of_day": "afternoon"},
                    channel="sms",
                    state="open",
                    due_at=now + timedelta(hours=3),
                    owner="info@skincentrix.com",
                    created_at=now - timedelta(minutes=19),
                ),
                Item(
                    tenant_id=TENANT,
                    conversation_id=handled,
                    type="question",
                    urgency="normal",
                    preferred_window={},
                    channel="voice",
                    state="acknowledged",
                    due_at=now + timedelta(hours=2),
                    owner="info@skincentrix.com",
                    acknowledged_at=now - timedelta(minutes=10),
                    acknowledged_by="owner@skincentrix.test",
                    created_at=now - timedelta(minutes=28),
                ),
                Item(
                    tenant_id=TENANT,
                    conversation_id=chatted,
                    type="send_link",
                    urgency="normal",
                    service_id="botox",
                    preferred_window={},
                    channel="chat",
                    state="resolved",
                    due_at=now + timedelta(hours=1),
                    owner="info@skincentrix.com",
                    resolved_at=now - timedelta(minutes=5),
                    resolved_by="owner@skincentrix.test",
                    created_at=now - timedelta(minutes=14),
                ),
            ]
        )

    async with sf() as s:
        item_ids = list(
            (
                await s.scalars(
                    select(Item.id).where(Item.tenant_id == TENANT).order_by(Item.id)
                )
            ).all()
        )
        audits = await s.scalar(
            select(AuditLog.id).where(AuditLog.record_id == str(handled)).limit(1)
        )

    await engine.dispose()

    print(
        json.dumps(
            {
                "tenant": tenant_id,
                "config_version": version,
                "conversations": {
                    "handled": str(handled),
                    "to_a_person": str(to_a_person),
                    "texted": str(texted),
                    "chatted": str(chatted),
                },
                "item_ids": item_ids,
                "pre_existing_audit_for_handled": audits,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
