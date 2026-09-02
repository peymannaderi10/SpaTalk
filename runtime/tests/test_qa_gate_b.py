"""QA gate B: the text channels and the Meta adapters, from the outside.

Every test here proves a row of the gate B acceptance matrix in ``docs/agents/QA.md`` that
the engineers' own suites left without proof. Nothing here fixes product code and nothing
here reaches a provider: the Telnyx payloads are the recorded ones in
``docs/reference/api-surface.md``, the Meta payloads are the recorded fixtures under
``tests/fixtures/meta``, and every outbound call goes through ``MemorySms``,
``MemoryDelivery`` or ``FakeGraphClient``.

Two conventions are deliberate.

*Settings are passed in, never inherited.* ``Settings`` reads ``runtime/.env``, so a test
that leaves a credential unset inherits whatever the machine happens to hold. Every
``Settings(...)`` below states every field it depends on, including the empty ones.

*The signature is made here.* A replay is only a replay if the bytes that were signed are
the bytes that arrive, so each test signs the exact body it posts and the negative cases
change one thing about it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

REPO = Path(__file__).resolve().parents[2]
API_SURFACE = REPO / "docs" / "reference" / "api-surface.md"
WORKER_SOURCE = REPO / "edge" / "sms-worker" / "src" / "index.ts"
META_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "meta"

SMS_FROM = "+18885550100"
CALLER = "+19055550101"
OTHER_CALLER = "+14165550199"
STAFF_PHONE = "+19051112222"
EDGE_KEY = "edge-shared-key"

IG_USER_ID = "17841400000000000"
COMMENT_ID = "17900000000000001"
PAGE_ID = "1234567890"
IG_SECRET = "ig-app-secret"
FB_SECRET = "fb-app-secret"
VERIFY_TOKEN = "the-verify-token"


# ----- the recorded Telnyx webhook ------------------------------------------------------


def recorded_telnyx_event() -> dict:
    """The messaging webhook exactly as ``docs/reference/api-surface.md`` records it.

    Parsing the document rather than retyping it is the point: if the recorded shape and
    the parser ever drift apart, this fails instead of passing against a copy.
    """
    text = API_SURFACE.read_text(encoding="utf-8")
    heading = "### Telnyx messaging webhook"
    start = text.index(heading)
    block = re.search(r"```json\n(.*?)```", text[start:], re.DOTALL)
    assert block is not None, "the reference document no longer records a Telnyx payload"
    event = json.loads(block.group(1))
    assert event["data"]["event_type"] == "message.received"
    return event


def keypair() -> tuple[object, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return private, base64.b64encode(raw).decode()


def telnyx_headers(private, body: str, *, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    signature = base64.b64encode(private.sign(f"{ts}|{body}".encode())).decode()
    return {
        "Content-Type": "application/json",
        "telnyx-signature-ed25519": signature,
        "telnyx-timestamp": ts,
    }


def llm(*texts: str):
    from spatalk.brain.driver import FakeLLM, LLMResponse

    return FakeLLM([LLMResponse(text=t, tool_calls=[]) for t in texts])


async def build_text_app(sf, registry, fixed_clock, model, **settings_overrides):
    """The real app on memory ports, with a tenant that has a texting number."""
    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings

    cfg = await registry.get("skincentrix")
    await registry.import_config(cfg.model_copy(update={"sms_from_number": SMS_FROM}), "test")
    registry.invalidate("skincentrix")
    fields = {
        "secret_key": "s3cret",
        "edge_shared_key": "",
        "telnyx_public_key": "",
        "turnstile_secret_key": "",
        "slack_signing_secret": "",
        "slack_bot_token": "",
    }
    fields.update(settings_overrides)
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=Settings(**fields),
        sms=MemorySms(),
        llm=model,
    )
    return create_app(ctx, start_background=False), ctx


async def test_the_recorded_telnyx_webhook_is_replayed_and_answered(sf, registry, fixed_clock):
    from spatalk.models import Message

    private, public = keypair()
    app, ctx = await build_text_app(
        sf, registry, fixed_clock, llm("We open at ten today."), telnyx_public_key=public
    )
    body = json.dumps(recorded_telnyx_event())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        response = await c.post("/telnyx/sms", content=body, headers=telnyx_headers(private, body))

    assert response.status_code == 200
    assert ctx.sms.sent == [(SMS_FROM, CALLER, "We open at ten today.")]
    async with sf() as s:
        stored = [(m.role, m.text) for m in (await s.scalars(select(Message).order_by(Message.id)))]
    assert ("user", "How much is a facial?") in stored


async def test_the_recorded_telnyx_webhook_with_a_forged_signature_answers_nothing(
    sf, registry, fixed_clock
):
    from spatalk.models import Conversation, Message

    _, public = keypair()
    forger, _ = keypair()
    app, ctx = await build_text_app(
        sf, registry, fixed_clock, llm("We open at ten today."), telnyx_public_key=public
    )
    body = json.dumps(recorded_telnyx_event())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        response = await c.post("/telnyx/sms", content=body, headers=telnyx_headers(forger, body))

    assert response.status_code == 401
    assert ctx.sms.sent == []
    async with sf() as s:
        assert (await s.scalars(select(Conversation))).all() == []
        assert (await s.scalars(select(Message))).all() == []


async def test_a_recorded_webhook_altered_after_it_was_signed_is_refused(
    sf, registry, fixed_clock
):
    """The signature covers the body, so changing the caller after signing must not pass."""
    private, public = keypair()
    app, ctx = await build_text_app(
        sf, registry, fixed_clock, llm("We open at ten today."), telnyx_public_key=public
    )
    signed = json.dumps(recorded_telnyx_event())
    headers = telnyx_headers(private, signed)
    tampered = signed.replace(CALLER, "+16475550123")
    assert tampered != signed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        response = await c.post("/telnyx/sms", content=tampered, headers=headers)

    assert response.status_code == 401
    assert ctx.sms.sent == []


def test_the_edge_worker_reads_the_recorded_event_the_same_way_the_runtime_does():
    """The worker in front of the webhook must not disagree with the runtime about shape.

    Both read the message id, the destination number and the sender out of the same
    recorded payload; the worker's auto-reply is keyed on the destination, so a drift here
    would send a tenant's offline wording to the wrong number.
    """
    event = recorded_telnyx_event()
    payload = event["data"]["payload"]
    assert payload["id"] and payload["to"][0]["phone_number"] and payload["from"]["phone_number"]

    source = WORKER_SOURCE.read_text(encoding="utf-8")
    assert 'asString(data?.event_type) === "message.received"' in source
    assert 'asString(asRecord(asArray(payload?.to)?.[0])?.phone_number)' in source
    assert 'asString(asRecord(payload?.from)?.phone_number)' in source
    assert 'asString(payload?.id)' in source


# ----- STOP is per number ---------------------------------------------------------------


async def post_sms(c, body: dict) -> object:
    return await c.post(
        "/telnyx/sms",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "X-Edge-Key": EDGE_KEY},
    )


def sms_event(text: str, msg_id: str, sender: str = CALLER, to: str = SMS_FROM) -> dict:
    event = recorded_telnyx_event()
    payload = event["data"]["payload"]
    payload["id"] = msg_id
    payload["text"] = text
    payload["from"]["phone_number"] = sender
    payload["to"][0]["phone_number"] = to
    return event


async def test_a_stop_from_one_number_never_silences_another_number(sf, registry, fixed_clock):
    """An opt-out is that person's, not the tenant's: everyone else still gets answered."""
    app, ctx = await build_text_app(
        sf,
        registry,
        fixed_clock,
        llm("We open at ten today.", "We open at ten today."),
        edge_shared_key=EDGE_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        assert (await post_sms(c, sms_event("STOP", "m1"))).status_code == 200
        ctx.sms.sent.clear()
        # The number that opted out is silent from here.
        assert (await post_sms(c, sms_event("What time do you open?", "m2"))).status_code == 200
        assert ctx.sms.sent == []
        # A different number is untouched by it.
        other = sms_event("What time do you open?", "m3", sender=OTHER_CALLER)
        assert (await post_sms(c, other)).status_code == 200

    assert ctx.sms.sent == [(SMS_FROM, OTHER_CALLER, "We open at ten today.")]


# ----- one follow-up, ever --------------------------------------------------------------


async def test_only_one_followup_is_ever_sent_however_many_questions_follow(
    sf, registry, fixed_clock
):
    """The rule is one follow-up per conversation, not one per unanswered question."""
    from spatalk import jobs
    from spatalk.models import Conversation, Job
    from spatalk.text.service import TextConversationService

    app, ctx = await build_text_app(
        sf,
        registry,
        fixed_clock,
        None,
        edge_shared_key=EDGE_KEY,
    )
    service = TextConversationService(
        ctx, llm("Sure. What day works for you?", "And what time works for you?")
    )
    first = await service.handle_inbound(
        tenant_id="skincentrix",
        channel="sms",
        external_id=CALLER,
        sender=CALLER,
        text="I would like to book something.",
        provider_message_id="m1",
    )

    ctx.clock.advance(hours=2)
    assert await jobs.run_once(sf, ctx) == 1
    assert sum("Just checking in" in body for _, _, body in ctx.sms.sent) == 1

    # The customer comes back, the assistant asks another question, and time passes again.
    await service.handle_inbound(
        tenant_id="skincentrix",
        channel="sms",
        external_id=CALLER,
        sender=CALLER,
        text="Sorry, I was away.",
        provider_message_id="m2",
    )
    ctx.clock.advance(hours=3)
    while await jobs.run_once(sf, ctx):
        pass

    assert sum("Just checking in" in body for _, _, body in ctx.sms.sent) == 1
    async with sf() as s:
        conversation = await s.get(Conversation, first.conversation_id)
        pending = [
            job
            for job in (await s.scalars(select(Job).where(Job.kind == "text.followup")))
            if job.state == "queued"
        ]
    assert conversation.followup_sent_at is not None
    assert pending == []


# ----- the missed-call text-back is per number ------------------------------------------


async def voice_session(ctx, sf, caller: str):
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.conversations import start_conversation
    from spatalk.voice.session import VoiceSession

    cfg = await ctx.registry.get("skincentrix")
    conversation_id = await start_conversation(
        sf, "skincentrix", "voice", f"v3:call-{caller}", caller
    )
    ref = ConversationRef(
        conversation_id=conversation_id, tenant=cfg, channel="voice", caller_phone=caller
    )
    caps = TierCCapabilities(ledger=MemoryLedger(ctx.clock), sms=MemorySms(), clock=ctx.clock)
    return VoiceSession(ref=ref, cfg=cfg, caps=caps, clock=ctx.clock)


async def test_two_missed_callers_are_each_texted_once_on_the_same_day(
    sf, registry, fixed_clock
):
    """Once per number per day is per *number*: a second caller is not collateral damage."""
    from spatalk import jobs
    from spatalk.text.textback import schedule_missed_call_textback

    _, ctx = await build_text_app(sf, registry, fixed_clock, None)

    for caller in (CALLER, OTHER_CALLER):
        session = await voice_session(ctx, sf, caller)
        assert await schedule_missed_call_textback(
            ctx, session, had_user_speech=False, duration_s=5.0
        )
    while await jobs.run_once(sf, ctx):
        pass

    texted = [to for _, to, _ in ctx.sms.sent]
    assert sorted(texted) == sorted([CALLER, OTHER_CALLER])

    # Both call again an hour later; neither is texted a second time.
    ctx.clock.advance(hours=1)
    for caller in (CALLER, OTHER_CALLER):
        session = await voice_session(ctx, sf, caller)
        assert not await schedule_missed_call_textback(
            ctx, session, had_user_speech=False, duration_s=5.0
        )
    while await jobs.run_once(sf, ctx):
        pass
    assert [to for _, to, _ in ctx.sms.sent] == texted


# ----- takeover, through the real webhook ------------------------------------------------


async def test_a_person_taking_over_pauses_the_bot_on_the_sms_route_and_hand_back_resumes_it(
    sf, registry, fixed_clock
):
    """The pause and the resume are proved where a customer meets them: the webhook."""
    from spatalk.models import Conversation
    from spatalk.text import takeover

    app, ctx = await build_text_app(
        sf,
        registry,
        fixed_clock,
        llm("We open at ten today.", "The assistant must never say this.", "Ten o'clock."),
        edge_shared_key=EDGE_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        first = await post_sms(c, sms_event("What time do you open?", "m1"))
        assert first.status_code == 200
        conversation_id = first.json()["conversation_id"]
        assert ctx.sms.sent == [(SMS_FROM, CALLER, "We open at ten today.")]

        # A person answers: the assistant steps aside.
        await takeover.relay_from_staff(ctx, conversation_id, "On my way, calling her now", "U1")
        ctx.sms.sent.clear()

        assert (await post_sms(c, sms_event("Are you still there?", "m2"))).status_code == 200
        assert ctx.sms.sent == [], "the model answered while a person held the conversation"
        async with sf() as s:
            assert (await s.get(Conversation, conversation_id)).controller == "human"

        # The hand-back the Slack button performs, and then the assistant answers again.
        await takeover.hand_back(ctx, conversation_id, "dana", "Back to the assistant.")
        async with sf() as s:
            assert (await s.get(Conversation, conversation_id)).controller == "ai"

        assert (await post_sms(c, sms_event("What time do you open?", "m3"))).status_code == 200

    assert [text for _, _, text in ctx.sms.sent] == ["The assistant must never say this."]


# ----- the Meta webhooks: every recorded payload, both signatures ------------------------


def meta_fixture(name: str) -> dict:
    return json.loads((META_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def meta_signature(raw: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


async def build_social_app(sf, registry, fixed_clock, *, provider: str, external_id: str):
    from cryptography.fernet import Fernet

    from spatalk import jobs
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.meta_oauth import store_integration
    from spatalk.tenants.schema import SocialSettings

    cfg = await registry.get("skincentrix")
    await registry.import_config(
        cfg.model_copy(
            update={
                "social": SocialSettings(
                    comment_mode="keyword",
                    comment_keywords=["price", "how much", "book"],
                    public_reply_enabled=False,
                )
            }
        ),
        "test",
    )
    registry.invalidate("skincentrix")

    settings = Settings(
        secret_key="s3cret",
        public_base_url="https://api.example.com",
        instagram_app_id="IG_APP_ID",
        instagram_app_secret=IG_SECRET,
        facebook_app_id="FB_APP_ID",
        facebook_app_secret=FB_SECRET,
        instagram_webhook_verify_token=VERIFY_TOKEN,
        meta_token_encryption_key=Fernet.generate_key().decode(),
        edge_shared_key="",
        turnstile_secret_key="",
    )
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=settings,
        sms=MemorySms(),
        llm=llm("We open at ten today."),
        graph=FakeGraphClient(
            {
                f"/v21.0/{IG_USER_ID}/messages": {"message_id": "mid-out"},
                f"/v21.0/{PAGE_ID}/messages": {"message_id": "mid-out"},
                f"/v21.0/{COMMENT_ID}/replies": {"id": "reply-1"},
            }
        ),
    )
    await store_integration(
        sf,
        settings,
        fixed_clock,
        tenant_id="skincentrix",
        provider=provider,
        external_id=external_id,
        display_name="skincentrix",
        access_token="a-long-lived-token",
        connected_by="test",
    )
    return create_app(ctx, start_background=False), ctx


async def queued(sf, kind: str) -> list:
    from spatalk.models import Job

    async with sf() as s:
        return list((await s.scalars(select(Job).where(Job.kind == kind))).all())


async def recorded_events(sf) -> list:
    """Every accepted Meta event leaves a row, actionable or not: it is the dedup key."""
    from spatalk.social.models import MetaEvent

    async with sf() as s:
        return list((await s.scalars(select(MetaEvent))).all())


META_CHANNELS = {
    "instagram": {
        "path": "/instagram/webhook",
        "secret": IG_SECRET,
        "external_id": IG_USER_ID,
        "job": "social.ig_event",
        # name -> whether the adapter acts on it; every kind is still recorded.
        "fixtures": {"comment": True, "dm": True, "postback": False, "read": False},
    },
    "messenger": {
        "path": "/messenger/webhook",
        "secret": FB_SECRET,
        "external_id": PAGE_ID,
        "job": "social.fb_event",
        "fixtures": {"page_feed_comment": True, "page_message": True, "page_read": False},
    },
}


@pytest.mark.parametrize(
    "channel,name",
    [(channel, name) for channel, spec in META_CHANNELS.items() for name in spec["fixtures"]],
)
async def test_every_recorded_meta_payload_is_accepted_with_a_valid_signature(
    sf, registry, fixed_clock, channel, name
):
    spec = META_CHANNELS[channel]
    app, ctx = await build_social_app(
        sf, registry, fixed_clock, provider=channel, external_id=spec["external_id"]
    )
    raw = json.dumps(meta_fixture(name)).encode()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        response = await c.post(
            spec["path"],
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": meta_signature(raw, spec["secret"]),
            },
        )

    assert response.status_code == 200
    assert len(await recorded_events(sf)) == 1
    assert len(await queued(sf, spec["job"])) == (1 if spec["fixtures"][name] else 0)


@pytest.mark.parametrize(
    "channel,name",
    [(channel, name) for channel, spec in META_CHANNELS.items() for name in spec["fixtures"]],
)
async def test_every_recorded_meta_payload_is_refused_with_an_invalid_signature(
    sf, registry, fixed_clock, channel, name
):
    """One bit wrong in the digest and the event never becomes work."""
    spec = META_CHANNELS[channel]
    app, ctx = await build_social_app(
        sf, registry, fixed_clock, provider=channel, external_id=spec["external_id"]
    )
    raw = json.dumps(meta_fixture(name)).encode()
    forged = meta_signature(raw, "not-the-app-secret")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        response = await c.post(
            spec["path"],
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": forged},
        )

    assert response.status_code == 401
    assert await recorded_events(sf) == []
    assert await queued(sf, spec["job"]) == []
    assert ctx.graph.calls == []


@pytest.mark.parametrize("channel", sorted(META_CHANNELS))
async def test_a_recorded_meta_payload_altered_after_signing_is_refused(
    sf, registry, fixed_clock, channel
):
    spec = META_CHANNELS[channel]
    app, ctx = await build_social_app(
        sf, registry, fixed_clock, provider=channel, external_id=spec["external_id"]
    )
    name = next(iter(spec["fixtures"]))
    signed = json.dumps(meta_fixture(name)).encode()
    header = meta_signature(signed, spec["secret"])
    tampered = signed.replace(b"how much", b"HOW MUCH")
    assert tampered != signed
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        response = await c.post(
            spec["path"],
            content=tampered,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": header},
        )

    assert response.status_code == 401
    assert await recorded_events(sf) == []
    assert await queued(sf, spec["job"]) == []


# ----- the Graph endpoints the comment path calls ----------------------------------------


async def test_the_comment_to_private_reply_path_calls_only_the_documented_graph_endpoint(
    sf, registry, fixed_clock
):
    from spatalk import jobs

    app, ctx = await build_social_app(
        sf, registry, fixed_clock, provider="instagram", external_id=IG_USER_ID
    )
    raw = json.dumps(meta_fixture("comment")).encode()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        response = await c.post(
            "/instagram/webhook",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": meta_signature(raw, IG_SECRET),
            },
        )
    assert response.status_code == 200
    await jobs.run_once(sf, ctx)

    assert [(call.method, call.path) for call in ctx.graph.calls] == [
        ("POST", f"/v21.0/{IG_USER_ID}/messages")
    ]
    assert ctx.graph.calls[0].json["recipient"] == {"comment_id": COMMENT_ID}


async def test_the_graph_client_addresses_meta_at_the_documented_host_without_reaching_it(
    sf, registry, fixed_clock
):
    """The fake records a path; this proves what that path becomes on the wire.

    ``FakeGraphClient`` is what every other test asserts against, so the one thing no test
    covers is the URL the real client would build. It is built here against an httpx
    transport that answers locally: no socket is opened.
    """
    import httpx

    from spatalk.social.graph import HttpGraphClient
    from spatalk.social.handlers import GRAPH_BASE_FOR_CHANNEL

    assert GRAPH_BASE_FOR_CHANNEL["instagram"] == "https://graph.instagram.com"
    assert GRAPH_BASE_FOR_CHANNEL["messenger"] == "https://graph.facebook.com"

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message_id": "mid-out"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = HttpGraphClient(
            GRAPH_BASE_FOR_CHANNEL["instagram"], lambda: "a-long-lived-token", client=transport
        )
        await client.post(
            f"/v21.0/{IG_USER_ID}/messages",
            json={"recipient": {"comment_id": COMMENT_ID}, "message": {"text": "hi"}},
        )

    assert len(seen) == 1
    assert str(seen[0].url) == f"https://graph.instagram.com/v21.0/{IG_USER_ID}/messages"
    assert seen[0].headers["authorization"] == "Bearer a-long-lived-token"


# ----- the contract the portal is generated from -----------------------------------------


def test_the_committed_contract_and_the_portal_client_declare_the_same_paths():
    """The portal's client is generated from the committed contract; drift is a 404 in a page."""
    contract = json.loads(
        (REPO / "docs" / "contracts" / "runtime-internal.openapi.json").read_text(encoding="utf-8")
    )
    client = (REPO / "portal" / "src" / "runtime" / "client.ts").read_text(encoding="utf-8")

    for path in contract["paths"]:
        assert f'"{path}"' in client, f"the portal client has no entry for {path}"
    for name in contract.get("components", {}).get("schemas", {}):
        assert name in client, f"the portal client is missing the {name} schema"


def test_the_missed_call_and_followup_windows_are_the_documented_ones():
    """Two numbers the matrix names: 24 h between text-backs, one follow-up after 2 h."""
    from spatalk.text import service, textback

    assert textback.TEXTBACK_WINDOW == timedelta(hours=24)
    assert service.FOLLOWUP_DELAY == timedelta(hours=2)
