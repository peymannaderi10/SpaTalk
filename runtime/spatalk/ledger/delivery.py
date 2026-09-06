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
import unicodedata

from spatalk.conversations import get_notes, record_usage
from spatalk.ledger.links import sign_action
from spatalk.ledger.summary import TYPE_LABELS, preferred_text, summarize_item
from spatalk.models import Item, WhatsAppWindow
from spatalk.tenants.schema import Destination, TenantConfig
from spatalk.text import takeover


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
    """The staff lines for one item: the type line, the summary sentence, then the facts.

    Line 0 names the type and the channel and is what a header repeats; line 1 is the one
    sentence every channel shows (lead context plan, Task L1), composed by
    :func:`spatalk.ledger.summary.summarize_item` from closed columns and fixed labels.
    """
    known = cfg.service(item.service_id) if item.service_id else None
    service = known.name if known else None
    window = item.preferred_window or {}
    lines = [
        f"{TYPE_LABELS.get(item.type, item.type)} via {item.channel}",
        summarize_item(item, cfg),
        f"Who: {item.contact_name or 'name not given'} "
        f"{item.contact_phone or ''} {item.contact_email or ''}".strip(),
    ]
    if service:
        lines.append(f"Service: {service}")
    if window.get("date") not in (None, "any") or window.get("part_of_day") not in (None, "any"):
        lines.append(f"Preferred: {preferred_text(window)}")
    lines.append(f"Due: {humanize_due(item.due_at, now, cfg.timezone, item.urgency == 'urgent')}")
    if getattr(item, "health_context", False):
        lines.append(
            "Caller mentioned a health condition or medication: "
            "read the transcript before calling back"
        )
    return lines


def _body_lines(item: Item, cfg: TenantConfig, now: datetime) -> list[str]:
    """The same lines for a body with no header of its own: the summary sentence first."""
    head, summary, *rest = _summary(item, cfg, now)
    return [summary, head, *rest]


def notes_block(notes: str | None, cfg: TenantConfig) -> str:
    """The drafted notes under the tenant's label, or "" when there are none (plan N, N1).

    Never a heading with nothing under it: staff reading a labelled empty block would take
    the silence for a finding. The label is the tenant's wording, so the portal card, the
    email and the Slack post all name the notes the same way.
    """
    body = (notes or "").strip()
    return f"\n\n{cfg.scripts.notes_label}\n{body}" if body else ""


def build_slack_blocks(
    item: Item,
    cfg: TenantConfig,
    links: ActionLinks,
    now: datetime | None = None,
    handback: bool = False,
    notes: str | None = None,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    head = ("\U0001f534 URGENT: " if item.urgency == "urgent" else "") + TYPE_LABELS.get(
        item.type, item.type
    )
    body = "\n".join(_summary(item, cfg, now)[1:]) + notes_block(notes, cfg)
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
    item: Item,
    cfg: TenantConfig,
    links: ActionLinks,
    now: datetime | None = None,
    notes: str | None = None,
) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    lines = _body_lines(item, cfg, now)
    prefix = "URGENT: " if item.urgency == "urgent" else ""
    subject = f"{prefix}{cfg.name} front desk #{item.id}: {TYPE_LABELS.get(item.type, item.type)}"
    body = (
        "\n".join(lines)
        + notes_block(notes, cfg)
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
    # `token` is a connected workspace's own bot token (slack one-click connect); None is
    # the global token, and a webhook URL needs none at all.
    async def send_slack(
        self, webhook_url: str, blocks: list[dict], text: str, token: str | None = None
    ) -> None: ...

    async def send_email(self, to: str, subject: str, body: str) -> None: ...


class HttpSlackEmailDelivery:
    def __init__(self, settings, http: httpx.AsyncClient | None = None):
        self._settings, self._http = settings, http or httpx.AsyncClient(timeout=10)

    async def send_slack(
        self, webhook_url: str, blocks: list[dict], text: str, token: str | None = None
    ) -> None:
        # A webhook carries its own authority; the token exists so every delivery object
        # speaks the same signature.
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
        # One Web API client per bot token: the global one above, and one per workspace a
        # clinic connected from the portal (slack one-click connect). Built on first use.
        self._clients: dict[str, object] = {}

    @property
    def client(self):
        if self._client is None:
            from slack_sdk.web.async_client import AsyncWebClient

            self._client = AsyncWebClient(token=self._settings.slack_bot_token)
        return self._client

    def client_for(self, token: str | None):
        """The client speaking with a workspace's own token; the global client for None."""
        if not token:
            return self.client
        client = self._clients.get(token)
        if client is None:
            from slack_sdk.web.async_client import AsyncWebClient

            client = self._clients[token] = AsyncWebClient(token=token)
        return client

    async def send_slack(
        self, webhook_url: str, blocks: list[dict], text: str, token: str | None = None
    ) -> None:
        if webhook_url.startswith("http"):
            await super().send_slack(webhook_url, blocks, text)
            return
        await self.client_for(token).chat_postMessage(
            channel=webhook_url, blocks=blocks, text=text
        )

    async def post_thread_root(
        self, channel_id: str, blocks: list[dict], text: str, token: str | None = None
    ) -> str:
        response = await self.client_for(token).chat_postMessage(
            channel=channel_id, blocks=blocks, text=text
        )
        return str(response["ts"])

    async def post_in_thread(
        self,
        channel_id: str,
        thread_ts: str,
        text: str,
        blocks: list[dict] | None = None,
        token: str | None = None,
    ) -> None:
        await self.client_for(token).chat_postMessage(
            channel=channel_id, thread_ts=thread_ts, text=text, blocks=blocks
        )


def make_delivery(settings, http: httpx.AsyncClient | None = None) -> DeliveryPort:
    """The bot when a token or the Slack app is configured, the incoming webhook otherwise.

    The app's client id and secret mean a clinic may connect its own workspace, and a
    connected workspace posts as the bot with its own token (slack one-click connect), so
    the bot delivery is needed even with no global token.
    """
    app_configured = bool(
        getattr(settings, "slack_client_id", "") and getattr(settings, "slack_client_secret", "")
    )
    if getattr(settings, "slack_bot_token", "") or app_configured:
        return SlackBotDelivery(settings, http)
    return HttpSlackEmailDelivery(settings, http)


class MemoryDelivery:
    def __init__(self):
        self.slack: list[tuple[str, list[dict], str]] = []
        # The token each Slack post went out with, in step with `slack` (None: a webhook, or
        # the global token). Kept beside the tuples so older tests keep their shape.
        self.slack_tokens: list[str | None] = []
        self.emails: list[tuple[str, str, str]] = []
        # --- whatsapp (plan W) ---
        # Every WhatsApp message in order: (to, body or template name, buttons or params).
        # `whatsapp_templates` keeps the full template record, which a tuple cannot hold.
        self.whatsapp: list[tuple[str, str, list]] = []
        self.whatsapp_templates: list[dict] = []

    async def send_slack(self, webhook_url, blocks, text, token=None):
        self.slack.append((webhook_url, blocks, text))
        self.slack_tokens.append(token)

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
        # The token each root and each thread post went out with, in step with the lists
        # above (None: the global token).
        self.root_tokens: list[str | None] = []
        self.thread_tokens: list[str | None] = []

    async def post_thread_root(self, channel_id, blocks, text, token=None) -> str:
        ts = f"1712.{len(self.roots) + 1:06d}"
        self.roots.append((channel_id, blocks, text))
        self.posted_ts.append(ts)
        self.root_tokens.append(token)
        return ts

    async def post_in_thread(self, channel_id, thread_ts, text, blocks=None, token=None) -> None:
        self.thread.append((channel_id, thread_ts, text, blocks))
        self.thread_tokens.append(token)


async def connected_slack_workspace(sf: async_sessionmaker, tenant_id: str):
    """The workspace this tenant connected from the portal, or None (slack one-click connect)."""
    # Imported here, not at module level: `social` imports `text`, which sits beside this
    # module, and the two must not need each other at import time.
    from spatalk.social.meta_oauth import integration_for

    return await integration_for(sf, tenant_id, "slack")


async def schedule_item_delivery(
    sf: async_sessionmaker, item: Item, cfg: TenantConfig, escalation: bool = False
) -> None:
    urgent = item.urgency == "urgent" or escalation
    # A workspace the clinic connected from the portal (slack one-click connect) replaces the
    # bundle's `slack` destinations: one post to the row's channel or webhook, and no read of
    # `.env`. With no row, the loop below is exactly what it was.
    workspace = await connected_slack_workspace(sf, cfg.id)
    if workspace is not None:
        await jobs.enqueue(
            sf,
            "deliver.slack",
            {
                "item_id": item.id,
                "tenant_id": cfg.id,
                "integration": True,
                "channel_id": workspace.channel_id,
                "escalation": escalation,
            },
        )
    for dest in cfg.delivery.destinations:
        if dest.urgent_only and not urgent:
            continue
        if dest.kind == "slack":
            if workspace is not None:
                continue
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
        # --- sms staff delivery (plan S) ---
        elif dest.kind == "sms":
            await jobs.enqueue(
                sf,
                "deliver.sms",
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

    # The notes are usually still being drafted when the immediate alert goes out; the
    # block appears when they exist and is absent when they do not (call-notes plan, N1).
    notes = await get_notes(ctx.sf, item.conversation_id)

    # A workspace the clinic connected from the portal: its own token and webhook come from
    # the encrypted row, never from `.env` (slack one-click connect).
    if payload.get("integration"):
        await _deliver_slack_to_workspace(ctx, payload, item, cfg, links, now, text, notes)
        return

    # With a bot token and a channel id, the conversation gets one thread: the first item is
    # its root, everything after it is a reply (Task B5). Without them, nothing changes.
    channel_id = payload.get("channel_id")
    if channel_id and _threads(ctx) and getattr(ctx.settings, "slack_bot_token", ""):
        await _deliver_slack_in_thread(ctx, item, cfg, links, now, channel_id, text, notes)
        return

    url = os.environ.get(payload["env"], "")
    if not url:
        logger.warning("slack webhook env {} not set; skipping", payload["env"])
        return
    await ctx.delivery.send_slack(
        url, build_slack_blocks(item, cfg, links, now, notes=notes), text
    )


def _threads(ctx: jobs.JobContext) -> bool:
    """Whether the delivery object can post as the bot (a thread needs the Web API)."""
    return getattr(ctx.delivery, "post_thread_root", None) is not None


def _not_in_channel(error: Exception) -> bool:
    """Slack's answer when the bot was never invited to the channel the install chose."""
    response = getattr(error, "response", None)
    if response is None:
        return False
    try:
        return response.get("error") == "not_in_channel"
    except Exception:
        return False


async def _deliver_slack_to_workspace(
    ctx: jobs.JobContext,
    payload: dict,
    item: Item,
    cfg: TenantConfig,
    links: ActionLinks,
    now: datetime,
    text: str,
    notes: str | None,
) -> None:
    """The clinic's connected workspace: a thread with its own token, else its webhook.

    The row is read when the job runs, not when it was queued, so a workspace disconnected
    in between is a skip with a warning, never a post with a revoked token. A bot that was
    not invited to the channel cannot open a thread; the item then goes through the
    webhook, which the install authorised for that channel, so it still lands.
    """
    from spatalk.social.slack_oauth import slack_bot_token, slack_webhook_url

    row = await connected_slack_workspace(ctx.sf, cfg.id)
    if row is None:
        logger.warning("slack workspace for {} is no longer connected; skipping", cfg.id)
        return
    token = slack_bot_token(row, ctx.settings)
    webhook = slack_webhook_url(row, ctx.settings)
    channel_id = payload.get("channel_id") or row.channel_id
    if channel_id and _threads(ctx):
        try:
            await _deliver_slack_in_thread(
                ctx, item, cfg, links, now, channel_id, text, notes, token=token
            )
            return
        except Exception as e:
            if not (_not_in_channel(e) and webhook):
                raise
            logger.warning(
                "the bot is not in {}'s slack channel {}; item #{} posted through the webhook "
                "instead. Invite the bot to the channel for threads.",
                cfg.id,
                channel_id,
                item.id,
            )
    if not webhook:
        logger.warning(
            "slack workspace for {} has no channel the bot can post in and no webhook; skipping",
            cfg.id,
        )
        return
    await ctx.delivery.send_slack(
        webhook, build_slack_blocks(item, cfg, links, now, notes=notes), text
    )


async def _deliver_slack_in_thread(
    ctx: jobs.JobContext,
    item: Item,
    cfg: TenantConfig,
    links: ActionLinks,
    now: datetime,
    channel_id: str,
    text: str,
    notes: str | None = None,
    token: str | None = None,
) -> None:
    thread = await takeover.thread_for(ctx.sf, item.conversation_id)
    if thread is None:
        rooted = item.conversation_id is not None
        blocks = build_slack_blocks(item, cfg, links, now, handback=rooted, notes=notes)
        ts = await ctx.delivery.post_thread_root(channel_id, blocks, text, token=token)
        if item.conversation_id is not None:
            await takeover.store_thread(ctx.sf, item.conversation_id, channel_id, ts)
        return
    await ctx.delivery.post_in_thread(
        thread[0],
        thread[1],
        text,
        build_slack_blocks(item, cfg, links, now, notes=notes),
        token=token,
    )


@jobs.register_handler("deliver.email")
async def _deliver_email(payload: dict, ctx: jobs.JobContext) -> None:
    to = payload.get("to") or os.environ.get(payload.get("to_env") or "", "")
    if not to:
        logger.warning("email destination env {} not set; skipping", payload.get("to_env"))
        return
    item = await ctx.ledger.get(payload["item_id"])
    cfg = await ctx.registry.get(payload["tenant_id"])
    subject, body = build_email(
        item,
        cfg,
        build_links(ctx.settings, item),
        ctx.clock.now(),
        notes=await get_notes(ctx.sf, item.conversation_id),
    )
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
        # --- sms staff delivery (plan S) ---
        elif dest.kind == "sms":
            await _digest_sms(ctx, cfg, dest, len(items))


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


# --- sms staff delivery (plan S) ------------------------------------------------------------
# Founder decision 2026-09-02: a tracked item lands on the owner's own mobile as an ordinary
# SMS from the tenant's Telnyx number, and the owner acknowledges or resolves by replying.
# Everything below is built from the item's structured columns and fixed wording; no model
# output ever reaches a staff phone (CLAUDE.md non-negotiable 1).

# Three GSM-7 segments. A concatenated segment carries 153 septets, not 160: the six-byte
# UDH that lets the handset reassemble the parts eats the difference.
SMS_SINGLE_GSM7 = 160
SMS_MULTI_GSM7 = 153
SMS_SINGLE_UCS2 = 70
SMS_MULTI_UCS2 = 67
SMS_STAFF_LIMIT = 3 * SMS_MULTI_GSM7          # 459
SMS_STAFF_SEGMENTS = 3

SMS_HEALTH_LINE = "Caller mentioned a health condition; read the transcript first."
SMS_DIGEST_TEXT = "{name} front desk: {n} open item(s). Reply LIST for details."
SMS_LIST_HEADER = "{name} front desk: {n} open item(s)."
SMS_LIST_MAX_ITEMS = 5

# GSM 03.38: the default alphabet, and the extension table whose characters cost two septets.
GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_"
    "ΦΓΛΩΠΨΣΘΞÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXTENDED = set("^{}\\[~]|€")


def sms_segments(text: str) -> int:
    """How many SMS segments this body costs, which is what the carrier bills for."""
    if not text:
        return 1
    if all(c in GSM7_BASIC or c in GSM7_EXTENDED for c in text):
        length = sum(2 if c in GSM7_EXTENDED else 1 for c in text)
        single, multi = SMS_SINGLE_GSM7, SMS_MULTI_GSM7
    else:
        # UCS-2: a segment is counted in 16-bit code units, so an emoji costs two.
        length = len(text.encode("utf-16-le")) // 2
        single, multi = SMS_SINGLE_UCS2, SMS_MULTI_UCS2
    return 1 if length <= single else -(-length // multi)


# Characters a phone keyboard or a CRM export produces that GSM 03.38 lacks, with the nearest
# character it has. One character outside the alphabet turns the whole body into UCS-2, where
# three segments hold 201 characters instead of 459.
_GSM7_FOLD = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " ", "\u2026": "...",
}


def gsm7_fold(text: str) -> str:
    """The same text in the GSM-7 alphabet wherever a lossless swap exists.

    Curly quotes, dashes and non-breaking spaces become their plain forms; accented letters
    the alphabet lacks lose their accent; anything else (a name in another script) is kept
    as it is, and the segment rule then decides what gives way.
    """
    out = []
    for c in text:
        if c in GSM7_BASIC or c in GSM7_EXTENDED:
            out.append(c)
            continue
        if c in _GSM7_FOLD:
            out.append(_GSM7_FOLD[c])
            continue
        base = "".join(
            ch for ch in unicodedata.normalize("NFKD", c) if not unicodedata.combining(ch)
        )
        out.append(base if base and all(ch in GSM7_BASIC for ch in base) else c)
    return "".join(out)


def _fits_staff_sms(text: str) -> bool:
    """The rule is three segments as the carrier counts them, not a character total."""
    return sms_segments(text) <= SMS_STAFF_SEGMENTS


def _sms_who(item: Item) -> str:
    who = (
        f"{item.contact_name or 'name not given'} "
        f"{item.contact_phone or ''} {item.contact_email or ''}"
    )
    return " ".join(who.split())


def build_sms_text(
    item: Item,
    cfg: TenantConfig,
    links: ActionLinks,
    now: datetime | None = None,
    escalation: bool = False,
) -> str:
    """One tracked item as at most three SMS segments, ending in the transcript link.

    The second line is the summary sentence (lead context plan, Task L1), so the owner can
    act on the lead without opening anything. Lines are dropped, never truncated, and in a
    fixed order: the summary first, then the health line, then the who line. The summary is
    the longest line and the most recoverable — every word of it is on the portal card and
    in the transcript — while the health line tells the owner how to read the call before
    they make it and the who line is the number they call. The link survives every cut,
    because a staff member who cannot open the transcript cannot act on the item.
    """
    now = now or datetime.now(timezone.utc)
    prefix = (ESCALATED_PREFIX if escalation else "") + (
        "URGENT: " if item.urgency == "urgent" else ""
    )
    head = (
        f"{prefix}{cfg.name} front desk #{item.id}: "
        f"{TYPE_LABELS.get(item.type, item.type)} via {item.channel}."
    )
    summary = summarize_item(item, cfg)
    who = f"Who: {_sms_who(item)}."
    urgent = item.urgency == "urgent"
    due = f"Due {humanize_due(item.due_at, now, cfg.timezone, urgent)}."
    reply = f"Reply ACK {item.id} or DONE {item.id}."
    tail = f"Transcript: {links.transcript_url}"
    flagged = bool(getattr(item, "health_context", False))

    def assemble(with_health: bool, with_who: bool, with_summary: bool) -> str:
        parts = [head]
        if with_summary:
            parts.append(summary)
        if with_who:
            parts.append(who)
        parts.append(due)
        if with_health:
            parts.append(SMS_HEALTH_LINE)
        parts += [reply, tail]
        return " ".join(parts)

    text = ""
    for with_health, with_who, with_summary in (
        (flagged, True, True),
        (flagged, True, False),
        (False, True, False),
        (False, False, False),
    ):
        text = gsm7_fold(assemble(with_health, with_who, with_summary))
        if _fits_staff_sms(text):
            return text
    # Nothing left to drop: cut the front, keep the link whole. Measured in segments, so a
    # name in another script costs the front of the message, never the link.
    body = text[: len(text) - len(tail)].rstrip()
    while body and not _fits_staff_sms(f"{body} {tail}"):
        body = body[:-1].rstrip()
    return f"{body} {tail}" if body else tail


def build_list_sms(items: list[Item], cfg: TenantConfig, now: datetime | None = None) -> str:
    """The open items as one short text: a count, then up to five lines with their ids."""
    now = now or datetime.now(timezone.utc)
    lines = [SMS_LIST_HEADER.format(name=cfg.name, n=len(items))]
    for item in items[:SMS_LIST_MAX_ITEMS]:
        due = humanize_due(item.due_at, now, cfg.timezone, item.urgency == "urgent")
        # A caller dictated the name; collapsing its whitespace keeps one item to one line.
        name = " ".join((item.contact_name or "name not given").split())
        lines.append(f"#{item.id} {TYPE_LABELS.get(item.type, item.type)}, {name}, due {due}")
    lines = [gsm7_fold(line) for line in lines]
    while len(lines) > 1 and not _fits_staff_sms("\n".join(lines)):
        lines.pop()
    return "\n".join(lines)


def sms_destination_numbers(cfg: TenantConfig) -> set[str]:
    """Every staff number an ``sms`` destination names, resolved now. Missing env is ignored.

    Delivery and the inbound webhook must agree on who counts as staff, so both read this.
    Task S2 folds it into ``spatalk.text.staff.staff_numbers`` together with
    ``delivery.staff_phone_numbers``.
    """
    numbers = set()
    for dest in cfg.delivery.destinations:
        if dest.kind == "sms":
            number = destination_address(dest)
            if number:
                numbers.add(number)
    return numbers


async def _staff_number_opted_out(ctx: jobs.JobContext, tenant_id: str, number: str) -> bool:
    """An opt-out binds even for the owner: the carrier rule has no staff exemption."""
    from spatalk.text.service import is_opted_out

    return await is_opted_out(ctx.sf, tenant_id, number)


@jobs.register_handler("deliver.sms")
async def _deliver_sms(payload: dict, ctx: jobs.JobContext) -> None:
    """One tracked item to one staff mobile, with the two reply keywords in the body.

    A missing environment variable is a configuration gap and is logged, not retried. A
    missing ``sms_from_number`` is different: the tenant cannot text at all, and a silent
    skip would leave the team believing an item had been delivered, so it raises and the
    job dead-letters where the job-health alert will find it.
    """
    to_env = payload.get("to_env") or ""
    to = os.environ.get(to_env, "")
    if not to:
        logger.warning("staff sms number env {} not set; skipping", to_env)
        return
    item = await ctx.ledger.get(payload["item_id"])
    cfg = await ctx.registry.get(payload["tenant_id"])
    if await _staff_number_opted_out(ctx, cfg.id, to):
        logger.warning(
            "staff number for {} is opted out of texts; item #{} not sent by sms", cfg.id, item.id
        )
        return
    if not cfg.sms_from_number:
        raise RuntimeError(
            f"tenant {cfg.id} has no sms_from_number; item #{item.id} cannot be texted to staff"
        )
    text = build_sms_text(
        item,
        cfg,
        build_links(ctx.settings, item),
        ctx.clock.now(),
        bool(payload.get("escalation")),
    )
    await ctx.sms.send(cfg.sms_from_number, to, text)
    await record_usage(
        ctx.sf, cfg.id, item.conversation_id, "sms", "telnyx", "sms_out", sms_segments(text)
    )


async def _digest_sms(
    ctx: jobs.JobContext, cfg: TenantConfig, dest: Destination, open_items: int
) -> None:
    """The morning digest as one text: how many are open, and how to see them.

    The detail stays behind ``LIST`` rather than arriving unbidden as six segments.
    """
    to = destination_address(dest)
    if not to:
        logger.warning("staff sms number env {} not set; skipping", dest.address_env)
        return
    if not cfg.sms_from_number:
        logger.warning("tenant {} has no sms_from_number; digest not texted", cfg.id)
        return
    if await _staff_number_opted_out(ctx, cfg.id, to):
        logger.warning("staff number for {} is opted out of texts; digest not sent", cfg.id)
        return
    text = SMS_DIGEST_TEXT.format(name=cfg.name, n=open_items)
    await ctx.sms.send(cfg.sms_from_number, to, text)
    await record_usage(ctx.sf, cfg.id, None, "sms", "telnyx", "sms_out", sms_segments(text))
