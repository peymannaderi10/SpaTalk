
async def test_breached_item_is_escalated_once_on_all_channels(sf, registry, fixed_clock, monkeypatch):
    monkeypatch.setenv("SKINCENTRIX_SLACK_WEBHOOK", "https://hooks.slack.com/services/T/B/x")
    from spatalk import jobs
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.ledger.scheduler import escalate_breached
    from spatalk.settings import Settings
    cfg = await registry.get("skincentrix")
    ledger = PgLedger(sf, fixed_clock)
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice", caller_phone="+19055550101")
    await ledger.create_item(ref, ItemDraft(type="callback", urgency="normal", contact=ContactInfo(name="Dana")))
    delivery = MemoryDelivery()
    ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=registry, ledger=ledger, delivery=delivery,
                          settings=Settings(_env_file=None, public_base_url="https://api.test", secret_key="s"))
    assert await escalate_breached(ctx) == 0
    fixed_clock.advance(days=2)
    assert await escalate_breached(ctx) == 1
    assert await escalate_breached(ctx) == 0
    await jobs.run_once(sf, ctx)
    assert len(delivery.slack) == 1 and len(delivery.emails) == 2      # destination email + owner email
    assert all("ESCALATED" in e[1] for e in delivery.emails)


async def test_digest_sent_once_per_local_day_after_digest_time(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.ledger.scheduler import send_digests
    from spatalk.settings import Settings
    delivery = MemoryDelivery()
    ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=registry, ledger=PgLedger(sf, fixed_clock),
                          delivery=delivery, settings=Settings(_env_file=None, public_base_url="https://api.test", secret_key="s"))
    # fixed_clock is 14:00 Toronto, digest_time 07:30, not yet sent today -> sends
    assert await send_digests(ctx) == 1
    assert await send_digests(ctx) == 0
    await jobs.run_once(sf, ctx)
    assert len(delivery.emails) == 1 and "digest" in delivery.emails[0][1]
