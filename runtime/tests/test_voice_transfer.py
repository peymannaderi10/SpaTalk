"""Live transfer to a staffed back-line (operations plan, Task E10).

Nothing here touches a network. The Telnyx call-control client is exercised through an
httpx MockTransport, and the pipeline side through `MemoryTransfer`, the fake that stands
in for the carrier the same way `MemorySms` stands in for the messaging API.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

BUNDLE = Path(__file__).resolve().parents[1] / "tenants" / "skincentrix"
# Tuesday 2026-09-01 14:00 Toronto = 18:00 UTC. Skincentrix is open 10:00-18:00 on Tuesday.
OPEN = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
# Tuesday 2026-09-01 23:30 UTC = 19:30 Toronto, half an hour after closing.
CLOSED = datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc)
BACK_LINE = "+19055557788"


def _cfg(transfer_number: str | None = BACK_LINE):
    from spatalk.tenants.bundle import load_bundle

    cfg = load_bundle(BUNDLE)
    return cfg.model_copy(update={"transfer_number": transfer_number})


# --- exposure: only when the tenant has a back-line and the clinic is open ----------------


def test_transfer_is_available_only_when_configured_and_open():
    from spatalk.voice.transfer import transfer_available

    assert transfer_available(_cfg(), OPEN) is True
    assert transfer_available(_cfg(), CLOSED) is False
    assert transfer_available(_cfg(None), OPEN) is False
    assert transfer_available(_cfg(None), CLOSED) is False


def test_shipped_bundle_has_no_back_line_so_the_tool_is_never_exposed_yet():
    """The clinic's back-line is unverified, so the bundle ships `transfer_number: null`."""
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.transfer import transfer_available

    assert load_bundle(BUNDLE).transfer_number is None
    assert transfer_available(load_bundle(BUNDLE), OPEN) is False


def test_tool_list_is_built_per_call_from_the_calendar_state():
    from spatalk.brain.tools import TOOL_NAMES, build_tools, tools_schema
    from spatalk.voice.transfer import TRANSFER_TOOL

    cfg = _cfg()
    closed = [t.name for t in build_tools(cfg)]
    assert closed == list(TOOL_NAMES) and TRANSFER_TOOL not in closed

    open_names = [t.name for t in build_tools(cfg, transfer_enabled=True)]
    assert open_names == list(TOOL_NAMES) + [TRANSFER_TOOL]
    assert TRANSFER_TOOL in [t.name for t in tools_schema(cfg, transfer_enabled=True).standard_tools]


def test_transfer_tool_has_no_free_text_parameters():
    from spatalk.brain.tools import build_tools
    from spatalk.voice.transfer import TRANSFER_TOOL

    tool = next(t for t in build_tools(_cfg(), transfer_enabled=True) if t.name == TRANSFER_TOOL)
    assert tool.properties == {} and tool.required == []


# --- the outcome and its wording ---------------------------------------------------------


def test_transferred_renders_the_tenants_transferring_script():
    from spatalk.brain.outcomes import Transferred
    from spatalk.brain.renderer import render

    cfg = _cfg()
    spoken = render(Transferred(number_masked="*****7788"), cfg, OPEN)
    assert spoken == cfg.scripts.transferring
    assert "One moment" in spoken


def test_transferred_is_part_of_the_outcome_union_and_masks_the_number():
    from spatalk.brain.outcomes import Outcome, Transferred
    from spatalk.voice.transfer import mask_number

    assert Transferred in Outcome.__args__
    assert Transferred(number_masked=mask_number(BACK_LINE)).kind == "transferred"
    assert mask_number(BACK_LINE) == "*******7788"
    assert BACK_LINE not in mask_number(BACK_LINE)


def test_tier_c_can_never_construct_a_transfer():
    """Tier C has no carrier leg, so it must not be able to name the outcome (spec §5)."""
    src = (Path(__file__).resolve().parents[1] / "spatalk" / "brain" / "tier_c.py").read_text(
        encoding="utf-8"
    )
    assert "Transferred" not in src

    import spatalk.brain.tier_c as tier_c

    assert not hasattr(tier_c, "Transferred")


async def test_tier_c_transfer_captures_an_urgent_callback(fixed_clock):
    from spatalk.brain.outcomes import Captured
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef, TransferRequest
    from spatalk.brain.tier_c import TierCCapabilities

    cfg = _cfg(None)
    ledger = MemoryLedger(fixed_clock)
    caps = TierCCapabilities(ledger=ledger, sms=MemorySms(), clock=fixed_clock)
    ref = ConversationRef(
        conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101"
    )
    out = await caps.transfer(ref, TransferRequest())
    assert isinstance(out, Captured)
    assert out.item_type == "escalation_human_request" and out.urgency == "urgent"
    assert ledger.items[0].contact.phone == "+19055550101"


# --- the carrier client (Option A: transfer the TeXML leg by call_control_id) -------------


async def test_telnyx_transfer_posts_the_call_control_transfer_action():
    import httpx

    from spatalk.voice.transfer import TelnyxTransfer

    seen = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"data": {"result": "ok"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    await TelnyxTransfer(api_key="k", http=http).transfer("v3:abc", BACK_LINE)
    assert seen["url"] == "https://api.telnyx.com/v2/calls/v3:abc/actions/transfer"
    assert seen["auth"] == "Bearer k"
    assert BACK_LINE in seen["body"]


async def test_telnyx_transfer_raises_when_the_carrier_refuses():
    import httpx

    from spatalk.voice.transfer import TelnyxTransfer

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(422, json={"errors": []}))
    )
    with pytest.raises(httpx.HTTPStatusError):
        await TelnyxTransfer(api_key="k", http=http).transfer("v3:abc", BACK_LINE)


async def test_attempt_transfer_reports_failure_instead_of_raising():
    from spatalk.voice.transfer import MemoryTransfer, attempt_transfer

    ok_port = MemoryTransfer()
    assert await attempt_transfer(ok_port, "v3:abc", BACK_LINE) is True
    assert ok_port.calls == [("v3:abc", BACK_LINE)]

    assert await attempt_transfer(MemoryTransfer(fail=True), "v3:abc", BACK_LINE) is False
    assert await attempt_transfer(None, "v3:abc", BACK_LINE) is False
    assert await attempt_transfer(ok_port, None, BACK_LINE) is False
    assert await attempt_transfer(ok_port, "v3:abc", None) is False


async def test_attempt_transfer_gives_up_on_a_carrier_that_never_answers():
    from spatalk.voice.transfer import MemoryTransfer, attempt_transfer

    slow = MemoryTransfer(delay=5.0)
    assert await attempt_transfer(slow, "v3:abc", BACK_LINE, timeout=0.01) is False


# --- the voice tool handler ---------------------------------------------------------------


class _FakeLLM:
    def __init__(self):
        self.registered = {}
        self.pushed = []

    def register_function(self, name, handler, **kw):
        self.registered[name] = handler

    async def push_frame(self, frame, direction=None):
        self.pushed.append(frame)


class _FakeWorker:
    def __init__(self):
        self.queued = []

    async def queue_frames(self, frames):
        self.queued.extend(frames)


def _session(fixed_clock, cfg, transfer_port, enabled=True):
    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.voice.session import VoiceSession

    ledger = MemoryLedger(fixed_clock)
    ref = ConversationRef(
        conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101"
    )
    session = VoiceSession(
        ref=ref,
        cfg=cfg,
        caps=TierCCapabilities(ledger=ledger, sms=MemorySms(), clock=fixed_clock),
        clock=fixed_clock,
        call_control_id="v3:abc",
        transfer=transfer_port,
        transfer_enabled=enabled,
    )
    session.worker = _FakeWorker()
    return session, ledger


class _Params:
    def __init__(self, llm, name, args):
        self.function_name, self.arguments, self.llm = name, args, llm
        self.results = []

    async def result_callback(self, result, properties=None):
        self.results.append((result, properties))


async def test_handler_is_registered_only_when_transfer_is_available(fixed_clock):
    from spatalk.brain.tools import TOOL_NAMES
    from spatalk.voice.handlers import register_tool_handlers
    from spatalk.voice.transfer import TRANSFER_TOOL, MemoryTransfer

    llm = _FakeLLM()
    session, _ = _session(fixed_clock, _cfg(None), MemoryTransfer(), enabled=False)
    register_tool_handlers(llm, session)
    assert set(llm.registered) == set(TOOL_NAMES)

    llm2 = _FakeLLM()
    session2, _ = _session(fixed_clock, _cfg(), MemoryTransfer(), enabled=True)
    register_tool_handlers(llm2, session2)
    assert set(llm2.registered) == set(TOOL_NAMES) | {TRANSFER_TOOL}


async def test_successful_transfer_speaks_the_script_and_leaves_the_leg_to_the_carrier(
    fixed_clock,
):
    from spatalk.voice.handlers import register_tool_handlers
    from spatalk.voice.transfer import TRANSFER_TOOL, MemoryTransfer

    cfg = _cfg()
    port = MemoryTransfer()
    llm = _FakeLLM()
    session, ledger = _session(fixed_clock, cfg, port)
    register_tool_handlers(llm, session)
    params = _Params(llm, TRANSFER_TOOL, {})
    await llm.registered[TRANSFER_TOOL](params)

    assert [f.text for f in llm.pushed] == [cfg.scripts.transferring]
    assert port.calls == [("v3:abc", BACK_LINE)]
    assert session.transferred is True and session.band == 3
    # No item: the caller reached a person, so there is nothing for the team to call back.
    assert ledger.items == []
    # An EndFrame here would make the serializer hang up the leg we just handed over.
    assert session.worker.queued == []
    assert params.results[0][0]["outcome"] == "transferred"
    assert params.results[0][1].run_llm is False


async def test_failed_transfer_falls_back_to_a_captured_urgent_callback(fixed_clock):
    from spatalk.voice.handlers import register_tool_handlers
    from spatalk.voice.transfer import TRANSFER_TOOL, MemoryTransfer

    cfg = _cfg()
    llm = _FakeLLM()
    session, ledger = _session(fixed_clock, cfg, MemoryTransfer(fail=True))
    register_tool_handlers(llm, session)
    params = _Params(llm, TRANSFER_TOOL, {})
    await llm.registered[TRANSFER_TOOL](params)

    spoken = [f.text for f in llm.pushed]
    assert spoken[0] == cfg.scripts.transferring
    assert spoken[1].startswith("Of course.") and "call you back" in spoken[1]
    assert session.transferred is False and session.band == 3
    assert ledger.items[0].type == "escalation_human_request"
    assert ledger.items[0].urgency == "urgent"
    assert params.results[0][0]["outcome"] == "captured"
    assert params.results[0][1].run_llm is False


async def test_transfer_that_hangs_falls_back_within_the_budget(fixed_clock, monkeypatch):
    from spatalk.voice import transfer as transfer_mod
    from spatalk.voice.handlers import register_tool_handlers
    from spatalk.voice.transfer import TRANSFER_TOOL, MemoryTransfer

    assert transfer_mod.TRANSFER_TIMEOUT_SECONDS == 20.0
    monkeypatch.setattr(transfer_mod, "TRANSFER_TIMEOUT_SECONDS", 0.01)
    llm = _FakeLLM()
    session, ledger = _session(fixed_clock, _cfg(), MemoryTransfer(delay=5.0))
    register_tool_handlers(llm, session)
    await llm.registered[TRANSFER_TOOL](_Params(llm, TRANSFER_TOOL, {}))

    assert session.transferred is False
    assert ledger.items[0].type == "escalation_human_request"
    assert "call you back" in llm.pushed[1].text


async def test_successful_transfer_switches_the_serializers_auto_hangup_off(fixed_clock):
    """The frame that ends our pipeline must not end the call the caller is now on."""
    from pipecat.serializers.telnyx import TelnyxFrameSerializer

    from spatalk.voice.handlers import register_tool_handlers
    from spatalk.voice.transfer import TRANSFER_TOOL, MemoryTransfer

    params = TelnyxFrameSerializer.InputParams()
    assert params.auto_hang_up is True
    llm = _FakeLLM()
    session, _ = _session(fixed_clock, _cfg(), MemoryTransfer())
    session.hangup_params = params
    register_tool_handlers(llm, session)
    await llm.registered[TRANSFER_TOOL](_Params(llm, TRANSFER_TOOL, {}))
    assert params.auto_hang_up is False


async def test_failed_transfer_leaves_auto_hangup_alone(fixed_clock):
    from pipecat.serializers.telnyx import TelnyxFrameSerializer

    from spatalk.voice.handlers import register_tool_handlers
    from spatalk.voice.transfer import TRANSFER_TOOL, MemoryTransfer

    params = TelnyxFrameSerializer.InputParams()
    llm = _FakeLLM()
    session, _ = _session(fixed_clock, _cfg(), MemoryTransfer(fail=True))
    session.hangup_params = params
    register_tool_handlers(llm, session)
    await llm.registered[TRANSFER_TOOL](_Params(llm, TRANSFER_TOOL, {}))
    assert params.auto_hang_up is True


async def test_a_transferred_caller_is_not_texted_back(sf, fixed_clock, registry):
    """The call was short because we handed it over, not because the caller was missed."""
    from spatalk import jobs
    from spatalk.settings import Settings
    from spatalk.text.textback import schedule_missed_call_textback
    from spatalk.voice.transfer import MemoryTransfer

    cfg = await registry.get("skincentrix")
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=None,
        delivery=None,
        settings=Settings(_env_file=None, secret_key="s"),
    )
    session, _ = _session(fixed_clock, cfg.model_copy(update={"transfer_number": BACK_LINE}),
                          MemoryTransfer())
    # Transferred first, so the "no" cannot be the already-queued check answering for it.
    session.transferred = True
    assert await schedule_missed_call_textback(ctx, session, True, 5.0) is False
    session.transferred = False
    assert await schedule_missed_call_textback(ctx, session, True, 5.0) is True


# --- Option A leaves the front door alone -------------------------------------------------


async def test_texml_still_streams_when_the_tenant_has_a_back_line(sf, fixed_clock):
    """Option A transfers the live leg over the API, so `/telnyx/texml` is unchanged.

    The `call_control_id` the transfer needs arrives on the media socket (Telnyx's stream
    start message), not in this form post, so nothing here has to carry it. Option B would
    replace this handler wholesale; see docs/runbooks/transfer.md.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from spatalk import jobs
    from spatalk.settings import Settings
    from spatalk.tenants.registry import TenantRegistry
    from spatalk.voice.texml import router

    reg = TenantRegistry(sf, fixed_clock)
    await reg.import_bundle(BUNDLE, created_by="test")
    await reg.add_number("+19055550100", "skincentrix", "voice")
    app = FastAPI()
    app.include_router(router)
    app.state.ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=reg,
        ledger=None,
        delivery=None,
        settings=Settings(_env_file=None, secret_key="s", media_ws_host="media.test"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        r = await c.post(
            "/telnyx/texml",
            data={"From": "+19055550101", "To": "+19055550100", "CallSid": "abc"},
        )
    assert '<Stream url="wss://media.test/ws/' in r.text and "<Dial" not in r.text
