from datetime import timedelta


def _ref(cfg, cid):
    from spatalk.brain.requests import ConversationRef
    return ConversationRef(conversation_id=cid, tenant=cfg, channel="voice", caller_phone="+19055550101")


async def test_create_ack_resolve_and_breach(sf, registry, fixed_clock):
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo
    from spatalk.conversations import start_conversation
    from spatalk.ledger.items import PgLedger
    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    created = []
    async def on_created(item, cfg_):
        created.append(item.id)
    ledger = PgLedger(sf, fixed_clock, on_created=on_created)
    rec = await ledger.create_item(_ref(cfg, cid), ItemDraft(type="callback", urgency="normal",
                                                             contact=ContactInfo(name="Dana", phone="+19055550101")))
    assert rec.id == 1 and created == [1]
    assert (await ledger.get(1)).owner == "info@skincentrix.com"
    assert [i.id for i in await ledger.list_open("skincentrix")] == [1]
    assert await ledger.breached(fixed_clock.now()) == []
    late = fixed_clock.now() + timedelta(days=2)
    assert [i.id for i in await ledger.breached(late)] == [1]
    await ledger.mark_escalated(1, late)
    assert await ledger.breached(late) == []
    acked = await ledger.acknowledge(1, "dana@clinic")
    assert acked.state == "acknowledged" and acked.acknowledged_by == "dana@clinic"
    resolved = await ledger.resolve(1, "dana@clinic")
    assert resolved.state == "resolved"
    assert await ledger.list_open("skincentrix") == []
    assert await ledger.acknowledge(999, "x") is None
