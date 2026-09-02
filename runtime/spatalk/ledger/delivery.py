from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib
import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk import jobs
from spatalk.brain.hours import humanize_due
from spatalk.ledger.links import sign_action
from spatalk.models import Item
from spatalk.tenants.schema import TenantConfig

TYPE_LABELS = {
    "callback": "Callback requested",
    "new_booking": "Wants to book",
    "question": "Question for the team",
    "training_enquiry": "Training course enquiry",
    "reschedule": "Reschedule request",
    "cancel": "Cancellation request",
    "send_link": "Send booking link",
    "escalation_human_request": "Asked for a person",
    "escalation_clinical": "CLINICAL question",
    "escalation_complaint": "COMPLAINT",
    "escalation_payment": "Payment question",
    "escalation_legal": "Legal question",
    "escalation_unsure": "Assistant was unsure",
}


@dataclass(frozen=True)
class ActionLinks:
    ack_url: str
    resolve_url: str
    transcript_url: str


def build_links(settings, item: Item) -> ActionLinks:
    base = settings.public_base_url.rstrip("/")
    ack = sign_action(settings.secret_key, item.id, "ack", item.tenant_id)
    res = sign_action(settings.secret_key, item.id, "resolve", item.tenant_id)
    tr = sign_action(settings.secret_key, item.id, "transcript", item.tenant_id)
    return ActionLinks(f"{base}/a/{ack}", f"{base}/a/{res}", f"{base}/a/{tr}")


def _summary(item: Item, cfg: TenantConfig, now: datetime) -> list[str]:
    known = cfg.service(item.service_id) if item.service_id else None
    service = known.name if known else None
    window = item.preferred_window or {}
    when = ", ".join(
        x
        for x in (
            window.get("date") if window.get("date") not in (None, "any") else None,
            window.get("part_of_day") if window.get("part_of_day") not in (None, "any") else None,
        )
        if x
    )
    lines = [
        f"{TYPE_LABELS.get(item.type, item.type)} via {item.channel}",
        f"Who: {item.contact_name or 'name not given'} "
        f"{item.contact_phone or ''} {item.contact_email or ''}".strip(),
    ]
    if service:
        lines.append(f"Service: {service}")
    if when:
        lines.append(f"Preferred: {when}")
    lines.append(f"Due: {humanize_due(item.due_at, now, cfg.timezone, item.urgency == 'urgent')}")
    if getattr(item, "health_context", False):
        lines.append(
            "Caller mentioned a health condition or medication: "
            "read the transcript before calling back"
        )
    return lines


def build_slack_blocks(
    item: Item, cfg: TenantConfig, links: ActionLinks, now: datetime | None = None
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    head = ("\U0001f534 URGENT: " if item.urgency == "urgent" else "") + TYPE_LABELS.get(
        item.type, item.type
    )
    body = "\n".join(_summary(item, cfg, now)[1:])
    return [
        {"type": "header", "text": {"type": "plain_text", "text": f"#{item.id} {head}"[:150]}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": body + f"\n<{links.transcript_url}|Open transcript>",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "ack",
                    "value": str(item.id),
                    "text": {"type": "plain_text", "text": "Acknowledge"},
                },
                {
                    "type": "button",
                    "action_id": "resolve",
                    "value": str(item.id),
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Resolve"},
                },
            ],
        },
    ]


def build_email(
    item: Item, cfg: TenantConfig, links: ActionLinks, now: datetime | None = None
) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    lines = _summary(item, cfg, now)
    prefix = "URGENT: " if item.urgency == "urgent" else ""
    subject = f"{prefix}{cfg.name} front desk #{item.id}: {TYPE_LABELS.get(item.type, item.type)}"
    body = (
        "\n".join(lines)
        + f"\n\nAcknowledge: {links.ack_url}\nResolve: {links.resolve_url}"
        + f"\nTranscript: {links.transcript_url}\n"
    )
    return subject, body


class DeliveryPort(Protocol):
    async def send_slack(self, webhook_url: str, blocks: list[dict], text: str) -> None: ...

    async def send_email(self, to: str, subject: str, body: str) -> None: ...


class HttpSlackEmailDelivery:
    def __init__(self, settings, http: httpx.AsyncClient | None = None):
        self._settings, self._http = settings, http or httpx.AsyncClient(timeout=10)

    async def send_slack(self, webhook_url: str, blocks: list[dict], text: str) -> None:
        r = await self._http.post(webhook_url, json={"text": text, "blocks": blocks})
        r.raise_for_status()

    async def send_email(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self._settings.mail_from, to, subject
        msg.set_content(body)
        await aiosmtplib.send(
            msg,
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            username=self._settings.smtp_user or None,
            password=self._settings.smtp_pass or None,
            start_tls=self._settings.smtp_port == 587,
        )


class MemoryDelivery:
    def __init__(self):
        self.slack: list[tuple[str, list[dict], str]] = []
        self.emails: list[tuple[str, str, str]] = []

    async def send_slack(self, webhook_url, blocks, text):
        self.slack.append((webhook_url, blocks, text))

    async def send_email(self, to, subject, body):
        self.emails.append((to, subject, body))


async def schedule_item_delivery(
    sf: async_sessionmaker, item: Item, cfg: TenantConfig, escalation: bool = False
) -> None:
    urgent = item.urgency == "urgent" or escalation
    for dest in cfg.delivery.destinations:
        if dest.urgent_only and not urgent:
            continue
        if dest.kind == "slack":
            await jobs.enqueue(
                sf,
                "deliver.slack",
                {
                    "item_id": item.id,
                    "tenant_id": cfg.id,
                    "env": dest.webhook_env,
                    "escalation": escalation,
                },
            )
        elif dest.kind == "email":
            await jobs.enqueue(
                sf,
                "deliver.email",
                {
                    "item_id": item.id,
                    "tenant_id": cfg.id,
                    "to": dest.address,
                    "escalation": escalation,
                },
            )
    if escalation:
        await jobs.enqueue(
            sf,
            "deliver.email",
            {
                "item_id": item.id,
                "tenant_id": cfg.id,
                "to": cfg.escalation.owner_email,
                "escalation": True,
            },
        )


@jobs.register_handler("deliver.slack")
async def _deliver_slack(payload: dict, ctx: jobs.JobContext) -> None:
    item = await ctx.ledger.get(payload["item_id"])
    cfg = await ctx.registry.get(payload["tenant_id"])
    url = os.environ.get(payload["env"], "")
    if not url:
        logger.warning("slack webhook env {} not set; skipping", payload["env"])
        return
    links = build_links(ctx.settings, item)
    blocks = build_slack_blocks(item, cfg, links, ctx.clock.now())
    prefix = "ESCALATED, past due: " if payload.get("escalation") else ""
    await ctx.delivery.send_slack(
        url, blocks, f"{prefix}#{item.id} {TYPE_LABELS.get(item.type, item.type)}"
    )


@jobs.register_handler("deliver.email")
async def _deliver_email(payload: dict, ctx: jobs.JobContext) -> None:
    item = await ctx.ledger.get(payload["item_id"])
    cfg = await ctx.registry.get(payload["tenant_id"])
    subject, body = build_email(item, cfg, build_links(ctx.settings, item), ctx.clock.now())
    if payload.get("escalation"):
        subject = "ESCALATED, past due: " + subject
    await ctx.delivery.send_email(payload["to"], subject, body)


@jobs.register_handler("digest.email")
async def _digest_email(payload: dict, ctx: jobs.JobContext) -> None:
    cfg = await ctx.registry.get(payload["tenant_id"])
    items = await ctx.ledger.list_open(cfg.id)
    now = ctx.clock.now()
    lines = [f"{cfg.name}: {len(items)} open front-desk item(s)\n"]
    for it in items:
        links = build_links(ctx.settings, it)
        lines.append(
            f"#{it.id} " + " | ".join(_summary(it, cfg, now)) + f"\n  resolve: {links.resolve_url}"
        )
    for dest in cfg.delivery.destinations:
        if dest.kind == "email":
            await ctx.delivery.send_email(
                dest.address, f"{cfg.name} front desk: morning digest", "\n".join(lines)
            )
