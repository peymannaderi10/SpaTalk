async def test_item_delivery_enqueues_per_destination_and_sends(sf, registry, fixed_clock, monkeypatch):
    monkeypatch.setenv("SKINCENTRIX_SLACK_WEBHOOK", "https://hooks.slack.com/services/T/B/x")
    from spatalk import jobs
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    from spatalk.ledger.delivery import MemoryDelivery, schedule_item_delivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    delivery = MemoryDelivery()
    settings = Settings(public_base_url="https://api.test", secret_key="s")

    async def on_created(item, cfg_):
        await schedule_item_delivery(sf, item, cfg_)
    ledger = PgLedger(sf, fixed_clock, on_created=on_created)
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice", caller_phone="+19055550101")
    rec = await ledger.create_item(ref, ItemDraft(type="callback", urgency="normal",
                                                  contact=ContactInfo(name="Dana", phone="+19055550101")))
    ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=registry, ledger=ledger, delivery=delivery, settings=settings)
    assert await jobs.run_once(sf, ctx) == 2
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
