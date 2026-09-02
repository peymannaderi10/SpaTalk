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
from spatalk.text import takeover

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
    ack_token: str
    resolve_token: str
    # Signed like the other two; only a Slack thread root carries the button (Task B5).
    handback_token: str = ""


def build_links(settings, item: Item) -> ActionLinks:
    base = settings.public_base_url.rstrip("/")
    ack = sign_action(settings.secret_key, item.id, "ack", item.tenant_id)
    res = sign_action(settings.secret_key, item.id, "resolve", item.tenant_id)
    tr = sign_action(settings.secret_key, item.id, "transcript", item.tenant_id)
    back = sign_action(settings.secret_key, item.id, "handback", item.tenant_id)
    return ActionLinks(f"{base}/a/{ack}", f"{base}/a/{res}", f"{base}/a/{tr}", ack, res, back)


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
    item: Item,
    cfg: TenantConfig,
    links: ActionLinks,
    now: datetime | None = None,
    handback: bool = False,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    head = ("\U0001f534 URGENT: " if item.urgency == "urgent" else "") + TYPE_LABELS.get(
        item.type, item.type
    )
    body = "\n".join(_summary(item, cfg, now)[1:])
    buttons: list[dict] = []
    if handback and links.handback_token:
        # Only on a thread root: the thread is where a person takes the conversation over,
        # so it is the only place the way back belongs (Task B5).
        buttons.append(
            {
                "type": "button",
                "action_id": "handback",
                "value": links.handback_token,
                "text": {"type": "plain_text", "text": "Hand back to assistant"},
            }
        )
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
                    "value": links.ack_token,
                    "text": {"type": "plain_text", "text": "Acknowledge"},
                },
                {
                    "type": "button",
                    "action_id": "resolve",
                    "value": links.resolve_token,
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Resolve"},
                },
                *buttons,
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


class SlackBotDelivery(HttpSlackEmailDelivery):
    """Slack through the bot API, so every conversation gets a thread staff can reply in.

    ``send_slack`` still satisfies :class:`DeliveryPort`: given a webhook URL it posts to the
    webhook exactly as before, given a channel id it posts as the bot. Email is unchanged.
    """

    def __init__(self, settings, http: httpx.AsyncClient | None = None, client=None):
        super().__init__(settings, http)
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from slack_sdk.web.async_client import AsyncWebClient

            self._client = AsyncWebClient(token=self._settings.slack_bot_token)
        return self._client

    async def send_slack(self, webhook_url: str, blocks: list[dict], text: str) -> None:
        if webhook_url.startswith("http"):
            await super().send_slack(webhook_url, blocks, text)
            return
        await self.client.chat_postMessage(channel=webhook_url, blocks=blocks, text=text)

    async def post_thread_root(self, channel_id: str, blocks: list[dict], text: str) -> str:
        response = await self.client.chat_postMessage(
            channel=channel_id, blocks=blocks, text=text
        )
        return str(response["ts"])

    async def post_in_thread(
        self, channel_id: str, thread_ts: str, text: str, blocks: list[dict] | None = None
    ) -> None:
        await self.client.chat_postMessage(
            channel=channel_id, thread_ts=thread_ts, text=text, blocks=blocks
        )


def make_delivery(settings, http: httpx.AsyncClient | None = None) -> DeliveryPort:
    """The bot when a token is configured, the incoming webhook otherwise."""
    if getattr(settings, "slack_bot_token", ""):
        return SlackBotDelivery(settings, http)
    return HttpSlackEmailDelivery(settings, http)


class MemoryDelivery:
    def __init__(self):
        self.slack: list[tuple[str, list[dict], str]] = []
        self.emails: list[tuple[str, str, str]] = []

    async def send_slack(self, webhook_url, blocks, text):
        self.slack.append((webhook_url, blocks, text))

    async def send_email(self, to, subject, body):
        self.emails.append((to, subject, body))


class MemoryBotDelivery(MemoryDelivery):
    """In-memory stand-in for :class:`SlackBotDelivery`, threads included."""

    def __init__(self):
        super().__init__()
        self.roots: list[tuple[str, list[dict], str]] = []
        self.thread: list[tuple[str, str, str, list[dict] | None]] = []
        self.posted_ts: list[str] = []

    async def post_thread_root(self, channel_id, blocks, text) -> str:
        ts = f"1712.{len(self.roots) + 1:06d}"
        self.roots.append((channel_id, blocks, text))
        self.posted_ts.append(ts)
        return ts

    async def post_in_thread(self, channel_id, thread_ts, text, blocks=None) -> None:
        self.thread.append((channel_id, thread_ts, text, blocks))


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
                    # Slack channel id, used with a bot token to open a thread (Task B5).
                    "channel_id": dest.channel_id,
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
    links = build_links(ctx.settings, item)
    now = ctx.clock.now()
    prefix = "ESCALATED, past due: " if payload.get("escalation") else ""
    text = f"{prefix}#{item.id} {TYPE_LABELS.get(item.type, item.type)}"

    # With a bot token and a channel id, the conversation gets one thread: the first item is
    # its root, everything after it is a reply (Task B5). Without them, nothing changes.
    channel_id = payload.get("channel_id")
    if channel_id and getattr(ctx.delivery, "post_thread_root", None) is not None:
        await _deliver_slack_in_thread(ctx, item, cfg, links, now, channel_id, text)
        return

    url = os.environ.get(payload["env"], "")
    if not url:
        logger.warning("slack webhook env {} not set; skipping", payload["env"])
        return
    await ctx.delivery.send_slack(url, build_slack_blocks(item, cfg, links, now), text)


async def _deliver_slack_in_thread(
    ctx: jobs.JobContext,
    item: Item,
    cfg: TenantConfig,
    links: ActionLinks,
    now: datetime,
    channel_id: str,
    text: str,
) -> None:
    thread = await takeover.thread_for(ctx.sf, item.conversation_id)
    if thread is None:
        rooted = item.conversation_id is not None
        blocks = build_slack_blocks(item, cfg, links, now, handback=rooted)
        ts = await ctx.delivery.post_thread_root(channel_id, blocks, text)
        if item.conversation_id is not None:
            await takeover.store_thread(ctx.sf, item.conversation_id, channel_id, ts)
        return
    await ctx.delivery.post_in_thread(
        thread[0], thread[1], text, build_slack_blocks(item, cfg, links, now)
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
