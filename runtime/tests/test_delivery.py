async def test_item_delivery_enqueues_per_destination_and_sends(sf, registry, fixed_clock, monkeypatch):
    monkeypatch.setenv("SKINCENTRIX_SLACK_WEBHOOK", "https://hooks.slack.com/services/T/B/x")
    # The bundle carries four destinations: email, Slack, the dormant WhatsApp number (W1)
    # and, since the sms staff delivery plan (S1), the owner mobile as ordinary SMS.
    monkeypatch.setenv("SKINCENTRIX_WHATSAPP_STAFF", "+15195550123")
    monkeypatch.setenv("SKINCENTRIX_STAFF_SMS", "+15195550124")
    from spatalk import jobs
    from spatalk.brain.ports import ItemDraft, MemorySms
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.delivery import MemoryDelivery, schedule_item_delivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    delivery, sms = MemoryDelivery(), MemorySms()
    settings = Settings(_env_file=None, public_base_url="https://api.test", secret_key="s")

    async def on_created(item, cfg_):
        await schedule_item_delivery(sf, item, cfg_)
    ledger = PgLedger(sf, fixed_clock, on_created=on_created)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice", caller_phone="+19055550101")
    rec = await ledger.create_item(ref, ItemDraft(type="callback", urgency="normal",
                                                  contact=ContactInfo(name="Dana", phone="+19055550101")))
    ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=registry, ledger=ledger, delivery=delivery, settings=settings, sms=sms)
    assert await jobs.run_once(sf, ctx) == 4
    # The staff SMS: from the tenant number in the bundle, to the number the env names (S1).
    assert len(sms.sent) == 1 and sms.sent[0][0] == cfg.sms_from_number
    assert sms.sent[0][1] == "+15195550124"
    assert f"#{rec.id}" in sms.sent[0][2] and "Reply ACK" in sms.sent[0][2]
    # No window row for this number, so WhatsApp uses the approved template (W1).
    assert len(delivery.whatsapp_templates) == 1
    assert delivery.whatsapp_templates[0]["to"] == "+15195550123"
    assert delivery.whatsapp_templates[0]["template"] == "front_desk_item"
    assert len(delivery.emails) == 1 and delivery.emails[0][0] == "info@skincentrix.com"
    assert "Dana" in delivery.emails[0][2] and "https://api.test/a/" in delivery.emails[0][2]
    assert len(delivery.slack) == 1 and delivery.slack[0][0].startswith("https://hooks.slack.com")
    blocks = delivery.slack[0][1]
    action_ids = [e["action_id"] for b in blocks if b["type"] == "actions" for e in b["elements"]]
    assert action_ids == ["ack", "resolve"]
    from spatalk.ledger.links import verify_action
    values = [e["value"] for b in blocks if b["type"] == "actions" for e in b["elements"]]
    assert all(not v.isdigit() for v in values)
    claims = [verify_action(settings.secret_key, v) for v in values]
    assert [cl.action for cl in claims] == ["ack", "resolve"]
    assert {cl.tenant_id for cl in claims} == {"skincentrix"}
    assert {cl.item_id for cl in claims} == {rec.id}


def test_email_and_blocks_contain_no_free_text_from_caller(fixed_clock):
    from types import SimpleNamespace
    from pathlib import Path
    from spatalk.ledger.delivery import ActionLinks, build_email, build_slack_blocks
    from spatalk.tenants.bundle import load_bundle
    cfg = load_bundle(Path(__file__).resolve().parents[1] / "tenants" / "skincentrix")
    item = SimpleNamespace(id=5, type="reschedule", urgency="normal", service_id="facial", contact_name="Dana",
                           contact_phone="+19055550101", contact_email=None, preferred_window={"date": "any", "part_of_day": "morning"},
                           channel="voice", due_at=fixed_clock.now(), state="open", conversation_id=None)
    from spatalk.ledger.links import sign_action
    ack_token = sign_action("s", 5, "ack", cfg.id)
    resolve_token = sign_action("s", 5, "resolve", cfg.id)
    links = ActionLinks("https://a/ack", "https://a/res", "https://a/t", ack_token, resolve_token)
    subject, body = build_email(item, cfg, links)
    assert "reschedule" in subject.lower() and "Dana" in body and "morning" in body
    blocks = build_slack_blocks(item, cfg, links)
    assert any("Dana" in str(b) for b in blocks)
    values = [e["value"] for b in blocks if b["type"] == "actions" for e in b["elements"]]
    assert values == [ack_token, resolve_token]


# --- slack one-click connect (onboarding roadmap, section 3) -------------------------------
# A workspace a clinic connected from the portal replaces the bundle's `slack` destination:
# its webhook and bot token come from the encrypted row, never from `.env`, and a tenant
# whose bundle still names an environment variable gets one post, not two.

SLACK_TEAM = "T0123ABC"
SLACK_CHANNEL_ID = "C0FRONTDESK"
SLACK_BOT_TOKEN = "xoxb-slack-bot-token-for-skincentrix"
SLACK_WEBHOOK = "https://hooks.slack.com/services/T0123ABC/B0WEBHOOK/s3cretpart"
ENV_WEBHOOK = "https://hooks.slack.com/services/T/B/from-the-env"


def _slack_settings(**overrides):
    from cryptography.fernet import Fernet
    from spatalk.settings import Settings
    values = dict(
        public_base_url="https://api.test",
        secret_key="s",
        slack_client_id="SLACK_CLIENT_ID",
        slack_client_secret="slack-client-secret",
        meta_token_encryption_key=Fernet.generate_key().decode(),
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


async def _connect_slack(sf, settings, fixed_clock, channel_id=SLACK_CHANNEL_ID):
    from spatalk.social.meta_oauth import store_integration
    return await store_integration(
        sf, settings, fixed_clock,
        tenant_id="skincentrix", provider="slack", external_id=SLACK_TEAM,
        display_name="Skincentrix · #front-desk", access_token=SLACK_BOT_TOKEN,
        scopes=["incoming-webhook", "chat:write"], connected_by="slack connect link",
        channel_id=channel_id, webhook_url=SLACK_WEBHOOK,
    )


async def _deliver_one_item(sf, registry, fixed_clock, settings, delivery):
    """A callback item for one SMS conversation, every delivery job run. Returns the job count."""
    from spatalk import jobs
    from spatalk.brain.ports import ItemDraft, MemorySms
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.delivery import schedule_item_delivery
    from spatalk.ledger.items import PgLedger
    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "sms", "c2", "+19055550101")

    async def on_created(item, cfg_):
        await schedule_item_delivery(sf, item, cfg_)
    ledger = PgLedger(sf, fixed_clock, on_created=on_created)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="sms", caller_phone="+19055550101")
    await ledger.create_item(ref, ItemDraft(type="callback", urgency="normal",
                                            contact=ContactInfo(name="Dana", phone="+19055550101")))
    ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=registry, ledger=ledger,
                          delivery=delivery, settings=settings, sms=MemorySms())
    return await jobs.run_once(sf, ctx), cid


async def test_a_connected_workspace_replaces_the_env_slack_destination(sf, registry, fixed_clock, monkeypatch):
    """One post, to the row's webhook: the bundle's `SKINCENTRIX_SLACK_WEBHOOK` is never read."""
    monkeypatch.setenv("SKINCENTRIX_SLACK_WEBHOOK", ENV_WEBHOOK)
    from spatalk.ledger.delivery import MemoryDelivery
    settings = _slack_settings()
    await _connect_slack(sf, settings, fixed_clock)
    delivery = MemoryDelivery()

    ran, _ = await _deliver_one_item(sf, registry, fixed_clock, settings, delivery)

    assert ran == 4  # email, the workspace, whatsapp, sms: the env destination is not a fifth
    assert [url for url, _, _ in delivery.slack] == [SLACK_WEBHOOK]
    assert delivery.slack_tokens == [None]  # a webhook needs no token
    action_ids = [e["action_id"] for b in delivery.slack[0][1] if b["type"] == "actions" for e in b["elements"]]
    assert action_ids == ["ack", "resolve"]


async def test_a_connected_workspace_with_a_channel_opens_a_thread_with_its_own_token(sf, registry, fixed_clock, monkeypatch):
    monkeypatch.setenv("SKINCENTRIX_SLACK_WEBHOOK", ENV_WEBHOOK)
    from spatalk.ledger.delivery import MemoryBotDelivery
    from spatalk.models import Conversation
    settings = _slack_settings(slack_bot_token="")
    await _connect_slack(sf, settings, fixed_clock)
    delivery = MemoryBotDelivery()

    _, cid = await _deliver_one_item(sf, registry, fixed_clock, settings, delivery)

    assert delivery.slack == []
    assert [channel for channel, _, _ in delivery.roots] == [SLACK_CHANNEL_ID]
    assert delivery.root_tokens == [SLACK_BOT_TOKEN]
    async with sf() as s:
        conv = await s.get(Conversation, cid)
    assert (conv.slack_channel, conv.slack_ts) == (SLACK_CHANNEL_ID, delivery.posted_ts[0])


async def test_a_bot_not_invited_to_the_channel_falls_back_to_the_webhook_with_a_warning(sf, registry, fixed_clock):
    """Slack answers not_in_channel until someone invites the bot; the item still lands."""
    from loguru import logger
    from slack_sdk.errors import SlackApiError
    from spatalk.ledger.delivery import MemoryBotDelivery

    class Uninvited(MemoryBotDelivery):
        async def post_thread_root(self, channel_id, blocks, text, token=None):
            raise SlackApiError("not_in_channel", {"ok": False, "error": "not_in_channel"})
    settings = _slack_settings()
    await _connect_slack(sf, settings, fixed_clock)
    delivery = Uninvited()
    warnings: list[str] = []
    handle = logger.add(lambda message: warnings.append(message.record["message"]), level="WARNING")
    try:
        await _deliver_one_item(sf, registry, fixed_clock, settings, delivery)
    finally:
        logger.remove(handle)

    assert delivery.roots == []
    assert [url for url, _, _ in delivery.slack] == [SLACK_WEBHOOK]
    assert any("Invite the bot to the channel" in w for w in warnings)


async def test_a_connected_workspace_without_a_channel_uses_its_webhook(sf, registry, fixed_clock):
    from spatalk.ledger.delivery import MemoryBotDelivery
    settings = _slack_settings()
    await _connect_slack(sf, settings, fixed_clock, channel_id=None)
    delivery = MemoryBotDelivery()

    await _deliver_one_item(sf, registry, fixed_clock, settings, delivery)

    assert delivery.roots == []
    assert [url for url, _, _ in delivery.slack] == [SLACK_WEBHOOK]


async def test_without_a_connected_workspace_the_env_destination_is_used_exactly_as_before(sf, registry, fixed_clock, monkeypatch):
    monkeypatch.setenv("SKINCENTRIX_SLACK_WEBHOOK", ENV_WEBHOOK)
    from spatalk.ledger.delivery import MemoryDelivery
    delivery = MemoryDelivery()

    ran, _ = await _deliver_one_item(sf, registry, fixed_clock, _slack_settings(), delivery)

    assert ran == 4
    assert [url for url, _, _ in delivery.slack] == [ENV_WEBHOOK]


async def test_without_a_connected_workspace_a_missing_env_still_skips_with_the_warning(sf, registry, fixed_clock, monkeypatch):
    from loguru import logger
    from spatalk.ledger.delivery import MemoryDelivery
    monkeypatch.delenv("SKINCENTRIX_SLACK_WEBHOOK", raising=False)
    warnings: list[str] = []
    handle = logger.add(lambda message: warnings.append(message.record["message"]), level="WARNING")
    try:
        delivery = MemoryDelivery()
        await _deliver_one_item(sf, registry, fixed_clock, _slack_settings(), delivery)
    finally:
        logger.remove(handle)

    assert delivery.slack == []
    assert "slack webhook env SKINCENTRIX_SLACK_WEBHOOK not set; skipping" in warnings


async def test_a_workspace_disconnected_between_enqueue_and_send_is_skipped_with_a_warning(sf, registry, fixed_clock):
    from loguru import logger
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.social.meta_oauth import delete_integration
    settings = _slack_settings()
    await _connect_slack(sf, settings, fixed_clock)
    delivery = MemoryDelivery()
    cfg = await registry.get("skincentrix")
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.delivery import schedule_item_delivery
    cid = await start_conversation(sf, "skincentrix", "sms", "c3", "+19055550101")
    ledger = PgLedger(sf, fixed_clock)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="sms", caller_phone="+19055550101")
    item = await ledger.create_item(ref, ItemDraft(type="callback", urgency="normal",
                                                   contact=ContactInfo(name="Dana", phone="+19055550101")))
    await schedule_item_delivery(sf, item, cfg)
    await delete_integration(sf, "skincentrix", "slack")
    warnings: list[str] = []
    handle = logger.add(lambda message: warnings.append(message.record["message"]), level="WARNING")
    try:
        ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=registry, ledger=ledger,
                              delivery=delivery, settings=settings)
        await jobs.run_once(sf, ctx)
    finally:
        logger.remove(handle)

    assert delivery.slack == []
    assert any("slack workspace for skincentrix is no longer connected" in w for w in warnings)


def test_make_delivery_returns_the_bot_delivery_when_the_slack_app_is_configured():
    from spatalk.ledger.delivery import HttpSlackEmailDelivery, SlackBotDelivery, make_delivery
    from spatalk.settings import Settings
    assert isinstance(make_delivery(_slack_settings(slack_bot_token="")), SlackBotDelivery)
    assert isinstance(make_delivery(Settings(_env_file=None, slack_bot_token="xoxb-global")), SlackBotDelivery)
    plain = make_delivery(Settings(_env_file=None, slack_bot_token="", slack_client_id="", slack_client_secret=""))
    assert type(plain) is HttpSlackEmailDelivery


def test_the_bot_delivery_keeps_one_client_per_token_and_the_global_one_for_none():
    from spatalk.ledger.delivery import SlackBotDelivery
    from spatalk.settings import Settings
    delivery = SlackBotDelivery(Settings(_env_file=None, slack_bot_token="xoxb-global"))
    per_tenant = delivery.client_for("xoxb-tenant-a")
    assert per_tenant is delivery.client_for("xoxb-tenant-a")
    assert per_tenant is not delivery.client_for("xoxb-tenant-b")
    assert per_tenant.token == "xoxb-tenant-a"
    assert delivery.client_for(None) is delivery.client
    assert delivery.client.token == "xoxb-global"
