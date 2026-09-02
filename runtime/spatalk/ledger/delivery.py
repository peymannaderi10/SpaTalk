from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib
import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker

from spatalk import jobs
from spatalk.brain.hours import humanize_due
from spatalk.conversations import record_usage
from spatalk.ledger.links import sign_action
from spatalk.models import Item, WhatsAppWindow
from spatalk.tenants.schema import Destination, TenantConfig
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


# --- whatsapp (plan W) ---------------------------------------------------------------------
# Meta's own limits, asserted rather than hoped for: an interactive message body is at most
# 1,024 characters, a reply button carries at most three buttons, each title at most 20
# characters and each id at most 256. A template parameter may not contain a newline, a tab
# or a run of more than four spaces.
WHATSAPP_BODY_LIMIT = 1024
WHATSAPP_TEXT_LIMIT = 4096
WHATSAPP_MAX_BUTTONS = 3
WHATSAPP_TITLE_LIMIT = 20
WHATSAPP_BUTTON_ID_LIMIT = 256
ESCALATED_PREFIX = "ESCALATED, past due: "
_WHITESPACE = re.compile(r"\s+")


def whatsapp_param(value: str) -> str:
    """One template parameter: a single line, no tabs, no long space runs, under the cap."""
    return _WHITESPACE.sub(" ", str(value)).strip()[:WHATSAPP_BODY_LIMIT]


def build_whatsapp_text(
    item: Item,
    cfg: TenantConfig,
    links: ActionLinks,
    now: datetime | None = None,
    escalation: bool = False,
) -> str:
    """The staff message: the item's own fields, the fixed labels, and the transcript link.

    Every line comes from :func:`_summary`, which reads structured columns only. No model
    output reaches a staff phone (CLAUDE.md non-negotiable 1).
    """
    now = now or datetime.now(timezone.utc)
    lines = _summary(item, cfg, now)
    head = (ESCALATED_PREFIX if escalation else "") + (
        "URGENT: " if item.urgency == "urgent" else ""
    )
    body = "\n".join([f"{head}#{item.id} {lines[0]}", *lines[1:]])
    return f"{body}\nTranscript: {links.transcript_url}"[:WHATSAPP_BODY_LIMIT]


def build_whatsapp_buttons(item: Item, links: ActionLinks) -> list[tuple[str, str]]:
    """The two reply buttons, each carrying the signed token the webhook verifies (W2)."""
    return [
        (f"ack:{links.ack_token}", "Acknowledge"),
        (f"resolve:{links.resolve_token}", "Resolve"),
    ]


def build_whatsapp_template_params(
    item: Item,
    cfg: TenantConfig,
    links: ActionLinks,
    now: datetime | None = None,
    escalation: bool = False,
) -> list[str]:
    """The five body parameters of the approved ``front_desk_item`` template.

    "{{1}} via {{2}}. Who: {{3}}. Due {{4}}. Transcript: {{5}}" — see
    docs/runbooks/whatsapp-setup.md. Order is the template's; wording is Meta-approved and
    lives there, not here.
    """
    now = now or datetime.now(timezone.utc)
    label = (ESCALATED_PREFIX if escalation else "") + (
        "URGENT: " if item.urgency == "urgent" else ""
    ) + TYPE_LABELS.get(item.type, item.type)
    who = (
        f"{item.contact_name or 'name not given'} "
        f"{item.contact_phone or ''} {item.contact_email or ''}"
    )
    due = humanize_due(item.due_at, now, cfg.timezone, item.urgency == "urgent")
    return [whatsapp_param(x) for x in (label, item.channel, who, due, links.transcript_url)]


class WhatsAppPort(Protocol):
    """What the WhatsApp Cloud API is used for, and nothing more."""

    async def send_text(self, to: str, body: str) -> str: ...

    async def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> str: ...

    async def send_template(
        self,
        to: str,
        template: str,
        lang: str,
        body_params: list[str],
        button_params: list[str],
    ) -> str: ...


class WhatsAppDelivery:
    """The Cloud API sender: one POST to ``/{phone_number_id}/messages`` per message.

    Every call goes through the :class:`~spatalk.social.graph.GraphClient` seam, so tests
    assert the payload against :class:`FakeGraphClient` and never reach Meta.
    """

    def __init__(self, settings, graph=None):
        self._settings = settings
        self._graph = graph

    @property
    def graph(self):
        if self._graph is None:
            from spatalk.social.graph import HttpGraphClient

            self._graph = HttpGraphClient(
                f"https://graph.facebook.com/{self._settings.meta_graph_version}",
                lambda: self._settings.whatsapp_access_token,
            )
        return self._graph

    async def _send(self, payload: dict) -> str:
        path = f"/{self._settings.whatsapp_phone_number_id}/messages"
        answer = await self.graph.post(path, json={"messaging_product": "whatsapp", **payload})
        messages = answer.get("messages") or [{}]
        return str(messages[0].get("id", ""))

    async def send_text(self, to: str, body: str) -> str:
        return await self._send(
            {
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": body[:WHATSAPP_TEXT_LIMIT]},
            }
        )

    async def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> str:
        if not 1 <= len(buttons) <= WHATSAPP_MAX_BUTTONS:
            raise ValueError(f"whatsapp allows 1 to {WHATSAPP_MAX_BUTTONS} reply buttons")
        for button_id, title in buttons:
            if len(title) > WHATSAPP_TITLE_LIMIT:
                raise ValueError(f"whatsapp button title over {WHATSAPP_TITLE_LIMIT} chars")
            if len(button_id) > WHATSAPP_BUTTON_ID_LIMIT:
                raise ValueError(f"whatsapp button id over {WHATSAPP_BUTTON_ID_LIMIT} chars")
        return await self._send(
            {
                "recipient_type": "individual",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body[:WHATSAPP_BODY_LIMIT]},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": bid, "title": title}}
                            for bid, title in buttons
                        ]
                    },
                },
            }
        )

    async def send_template(
        self,
        to: str,
        template: str,
        lang: str,
        body_params: list[str],
        button_params: list[str],
    ) -> str:
        components: list[dict] = [
            {
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in body_params],
            }
        ]
        for index, payload in enumerate(button_params):
            components.append(
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(index),
                    "parameters": [{"type": "payload", "payload": payload}],
                }
            )
        return await self._send(
            {
                "recipient_type": "individual",
                "to": to,
                "type": "template",
                "template": {
                    "name": template,
                    "language": {"code": lang},
                    "components": components,
                },
            }
        )


async def whatsapp_window_open(
    sf: async_sessionmaker, tenant_id: str, phone: str, now: datetime
) -> bool:
    """True when this number wrote to us inside the last 24 hours.

    Read by delivery and written by the webhook (W2), so the two agree on one rule.
    """
    async with sf() as s:
        row = await s.get(WhatsAppWindow, {"tenant_id": tenant_id, "phone": phone})
        if row is None:
            return False
        return row.last_inbound_at > now - timedelta(hours=24)


def destination_address(dest: Destination) -> str:
    """The address a destination resolves to now: a literal, or the environment it names."""
    if dest.address:
        return dest.address
    if dest.address_env:
        return os.environ.get(dest.address_env, "")
    return ""


def whatsapp_port(ctx: jobs.JobContext) -> WhatsAppPort:
    """The context's delivery object when it speaks WhatsApp, a real sender otherwise.

    Tests inject :class:`MemoryDelivery`, which does; production injects the Slack/email
    delivery, which does not, and gets a :class:`WhatsAppDelivery` built from settings.
    """
    if getattr(ctx.delivery, "send_buttons", None) is not None:
        return ctx.delivery
    return WhatsAppDelivery(ctx.settings, getattr(ctx, "graph", None))


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
        # --- whatsapp (plan W) ---
        # Every WhatsApp message in order: (to, body or template name, buttons or params).
        # `whatsapp_templates` keeps the full template record, which a tuple cannot hold.
        self.whatsapp: list[tuple[str, str, list]] = []
        self.whatsapp_templates: list[dict] = []

    async def send_slack(self, webhook_url, blocks, text):
        self.slack.append((webhook_url, blocks, text))

    async def send_email(self, to, subject, body):
        self.emails.append((to, subject, body))

    # --- whatsapp (plan W) ---
    async def send_text(self, to: str, body: str) -> str:
        self.whatsapp.append((to, body, []))
        return f"wamid.mem{len(self.whatsapp)}"

    async def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> str:
        self.whatsapp.append((to, body, list(buttons)))
        return f"wamid.mem{len(self.whatsapp)}"

    async def send_template(
        self,
        to: str,
        template: str,
        lang: str,
        body_params: list[str],
        button_params: list[str],
    ) -> str:
        self.whatsapp.append((to, template, list(body_params)))
        self.whatsapp_templates.append(
            {
                "to": to,
                "template": template,
                "lang": lang,
                "body_params": list(body_params),
                "button_params": list(button_params),
            }
        )
        return f"wamid.mem{len(self.whatsapp)}"


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
                    # A mailbox a tenant would rather not commit is named, not written (W1).
                    "to_env": dest.address_env,
                    "escalation": escalation,
                },
            )
        # --- whatsapp (plan W) ---
        elif dest.kind == "whatsapp":
            await jobs.enqueue(
                sf,
                "deliver.whatsapp",
                {
                    "item_id": item.id,
                    "tenant_id": cfg.id,
                    "to_env": dest.address_env,
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
    to = payload.get("to") or os.environ.get(payload.get("to_env") or "", "")
    if not to:
        logger.warning("email destination env {} not set; skipping", payload.get("to_env"))
        return
    item = await ctx.ledger.get(payload["item_id"])
    cfg = await ctx.registry.get(payload["tenant_id"])
    subject, body = build_email(item, cfg, build_links(ctx.settings, item), ctx.clock.now())
    if payload.get("escalation"):
        subject = ESCALATED_PREFIX + subject
    await ctx.delivery.send_email(to, subject, body)


# --- whatsapp (plan W) ---------------------------------------------------------------------


@jobs.register_handler("deliver.whatsapp")
async def _deliver_whatsapp(payload: dict, ctx: jobs.JobContext) -> None:
    """One tracked item to one staff number, with Acknowledge and Resolve as reply buttons.

    Inside Meta's 24-hour customer-service window the message is free-form text plus the two
    interactive buttons; outside it, the approved template carries the same fields and the
    same two quick replies. There is no third path: a send never silently disappears.
    """
    to_env = payload.get("to_env") or ""
    to = os.environ.get(to_env, "")
    if not to:
        logger.warning("whatsapp number env {} not set; skipping", to_env)
        return
    item = await ctx.ledger.get(payload["item_id"])
    cfg = await ctx.registry.get(payload["tenant_id"])
    links = build_links(ctx.settings, item)
    now = ctx.clock.now()
    escalation = bool(payload.get("escalation"))
    port = whatsapp_port(ctx)

    if await whatsapp_window_open(ctx.sf, cfg.id, to, now):
        await port.send_buttons(
            to,
            build_whatsapp_text(item, cfg, links, now, escalation),
            build_whatsapp_buttons(item, links),
        )
    else:
        await port.send_template(
            to,
            ctx.settings.whatsapp_template_item,
            ctx.settings.whatsapp_template_lang,
            build_whatsapp_template_params(item, cfg, links, now, escalation),
            [button_id for button_id, _ in build_whatsapp_buttons(item, links)],
        )
    await record_usage(ctx.sf, cfg.id, item.conversation_id, "whatsapp", "meta", "wa_out", 1)


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
    body = "\n".join(lines)
    for dest in cfg.delivery.destinations:
        if dest.kind == "email":
            address = destination_address(dest)
            if not address:
                logger.warning("email destination env {} not set; skipping", dest.address_env)
                continue
            await ctx.delivery.send_email(
                address, f"{cfg.name} front desk: morning digest", body
            )
        # --- whatsapp (plan W) ---
        elif dest.kind == "whatsapp":
            await _digest_whatsapp(ctx, cfg, dest, body, now)


async def _digest_whatsapp(
    ctx: jobs.JobContext, cfg: TenantConfig, dest: Destination, body: str, now: datetime
) -> None:
    """The same digest, to a staff WhatsApp number: text inside the window, template outside."""
    to = destination_address(dest)
    if not to:
        logger.warning("whatsapp number env {} not set; skipping", dest.address_env)
        return
    port = whatsapp_port(ctx)
    if await whatsapp_window_open(ctx.sf, cfg.id, to, now):
        await port.send_text(to, body[:WHATSAPP_TEXT_LIMIT])
    else:
        await port.send_template(
            to,
            ctx.settings.whatsapp_template_digest,
            ctx.settings.whatsapp_template_lang,
            [whatsapp_param(body)],
            [],
        )
    await record_usage(ctx.sf, cfg.id, None, "whatsapp", "meta", "wa_out", 1)
