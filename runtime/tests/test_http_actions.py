import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    settings = Settings(public_base_url="https://api.test", secret_key="s3cret", slack_signing_secret="slacksecret")
    ledger = PgLedger(sf, fixed_clock)
    ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=registry, ledger=ledger, delivery=MemoryDelivery(), settings=settings)
    app = create_app(ctx, start_background=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        yield c, ledger, settings


async def _item(sf, registry, ledger):
    from spatalk.brain.ports import ItemDraft
    from spatalk.brain.requests import ContactInfo, ConversationRef
    from spatalk.conversations import start_conversation
    cfg = await registry.get("skincentrix")
    cid = await start_conversation(sf, "skincentrix", "voice", "c1", "+19055550101")
    ref = ConversationRef(conversation_id=cid, tenant=cfg, channel="voice", caller_phone="+19055550101")
    return await ledger.create_item(ref, ItemDraft(type="callback", urgency="normal", contact=ContactInfo(name="Dana")))


async def test_get_shows_confirm_page_and_post_acknowledges(client, sf, registry):
    c, ledger, settings = client
    from spatalk.ledger.links import sign_action
    rec = await _item(sf, registry, ledger)
    tok = sign_action(settings.secret_key, rec.id, "ack", "skincentrix")
    r = await c.get(f"/a/{tok}")
    assert r.status_code == 200 and "<form" in r.text and (await ledger.get(rec.id)).state == "open"
    r = await c.post(f"/a/{tok}", data={"actor": "dana@clinic"})
    assert r.status_code == 200 and (await ledger.get(rec.id)).state == "acknowledged"


async def test_bad_token_is_404(client):
    c, _, _ = client
    assert (await c.get("/a/not-a-token")).status_code == 404


async def test_slack_interaction_requires_valid_signature_and_resolves(client, sf, registry):
    import hashlib
    import hmac
    import json
    import time
    from urllib.parse import urlencode
    c, ledger, settings = client
    rec = await _item(sf, registry, ledger)
    payload = json.dumps({"type": "block_actions", "user": {"username": "dana"},
                          "actions": [{"action_id": "resolve", "value": str(rec.id)}]})
    body = urlencode({"payload": payload})
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(b"slacksecret", f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    r = await c.post("/slack/interactions", content=body, headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig})
    assert r.status_code == 200 and (await ledger.get(rec.id)).state == "resolved"
    r = await c.post("/slack/interactions", content=body, headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=bad"})
    assert r.status_code == 401
