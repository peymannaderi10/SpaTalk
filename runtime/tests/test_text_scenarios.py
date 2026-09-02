"""Task B6: the text-channel half of the conversation regression suite.

`promptfoo` needs a real model key, so it runs only in QA gates and in CI when
`GOOGLE_API_KEY` is present. These tests are the deterministic half: they prove the two new
graders (`sms_brevity`, `chat_link_inline`) actually fail the things they claim to catch,
that the suite really carries the SMS and chat cases the plan lists, that every python
assert it names resolves to a function, and — the one behaviour the plan explicitly says
must be a pytest and not a promptfoo case — that STOP is handled before the brain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

RUNTIME = Path(__file__).resolve().parents[1]
CONFIG = RUNTIME / "scenarios" / "promptfooconfig.yaml"

SMS_FROM = "+18885550100"
CALLER = "+19055550101"
EDGE_KEY = "edge-shared-key"


def _suite() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _cases(channel: str) -> list[dict]:
    return [t for t in _suite()["tests"] if (t.get("vars") or {}).get("channel") == channel]


def _asserts(case: dict) -> list[str]:
    out = []
    for a in case.get("assert") or []:
        if a.get("type") == "python":
            out.append(a["value"].split(":")[-1])
    return out


def _out(**over):
    base = {
        "text": "The express treatment is $99.",
        "band": 1,
        "gate_reason": None,
        "tool_calls": [],
        "outcomes": [],
        "guard_blocked": False,
        "ended": False,
        "health_context": False,
        "items": [],
        "sms_sent": 0,
    }
    return base | over


# --- the two new graders ------------------------------------------------------


def test_sms_brevity_passes_a_short_plain_reply():
    import scenarios.asserts as a

    assert a.sms_brevity(_out(), {}) is True


def test_sms_brevity_fails_a_reply_over_three_hundred_characters():
    import scenarios.asserts as a

    long = "The express treatment is ninety nine dollars. " * 8
    bad = a.sms_brevity(_out(text=long), {})
    assert bad["pass"] is False and str(len(long)) in bad["reason"]


def test_sms_brevity_fails_a_reply_containing_markdown():
    import scenarios.asserts as a

    for markdown in (
        "Our **express treatment** is $99.",
        "Prices:\n- facial $199\n- express $99",
        "Book here: [facial](https://book.example.com/facial)",
        "## Prices\nExpress is $99.",
        "Use `express_treatment` to book.",
    ):
        bad = a.sms_brevity(_out(text=markdown), {})
        assert bad["pass"] is False, markdown
        assert "markdown" in bad["reason"]


def test_sms_brevity_fails_a_reply_that_claims_an_action():
    import scenarios.asserts as a

    bad = a.sms_brevity(_out(text="You're all set for Thursday."), {})
    assert bad["pass"] is False and "all set" in bad["reason"]


def test_chat_link_inline_passes_a_link_shown_in_the_conversation():
    import scenarios.asserts as a

    shown = _out(
        outcomes=["link_sent"],
        text="Here is the booking link for Signature Facial: https://book.example.com/facial",
    )
    assert a.chat_link_inline(shown, {}) is True


def test_chat_link_inline_fails_a_link_that_was_texted_instead():
    import scenarios.asserts as a

    texted = _out(
        outcomes=["link_sent"],
        sms_sent=1,
        text="I've just texted you the booking link for Signature Facial.",
    )
    bad = a.chat_link_inline(texted, {})
    assert bad["pass"] is False and "sms" in bad["reason"]


def test_chat_link_inline_fails_when_no_link_is_in_the_reply():
    import scenarios.asserts as a

    bad = a.chat_link_inline(_out(outcomes=["link_sent"], text="I'll get that link for you."), {})
    assert bad["pass"] is False


# --- the suite itself ---------------------------------------------------------


def test_the_suite_has_sms_cases_for_price_cancellation_and_clinical():
    cases = _cases("sms")
    graders = [_asserts(c) for c in cases]
    flat = {g for gs in graders for g in gs}
    assert len(cases) >= 3, "the plan lists a price, a cancellation and a clinical SMS case"
    assert "band1_answer" in flat and "sms_brevity" in flat
    assert "band2_captured" in flat
    assert "band3_gate" in flat
    # Every SMS case is graded for length and formatting except the fixed band-3 script,
    # which is the tenant's wording and is not the model's to shorten.
    assert sum("sms_brevity" in g for g in graders) >= 2


def test_the_suite_has_chat_cases_for_the_inline_link_and_contact_capture():
    cases = _cases("chat")
    flat = {g for c in cases for g in _asserts(c)}
    assert "chat_link_inline" in flat
    capture = [c for c in cases if "band2_captured" in _asserts(c)]
    assert capture, "the contact-capture chat case is missing"
    # Contact capture on chat has no caller id to fall back on, so it must span two turns.
    assert any(len(c["vars"].get("history") or []) >= 2 for c in capture)


def test_every_python_assert_in_the_suite_names_a_function_that_exists():
    import scenarios.asserts as a

    suite = _suite()
    named = {
        v["value"].split(":")[-1]
        for v in (suite["defaultTest"]["assert"] + [x for t in suite["tests"] for x in t["assert"]])
        if v.get("type") == "python"
    }
    missing = sorted(n for n in named if not callable(getattr(a, n, None)))
    assert missing == []


def test_the_suite_names_the_python_provider_and_passes_the_channel_through():
    suite = _suite()
    assert suite["providers"][0]["id"] == "file://provider.py"
    for case in _cases("sms") + _cases("chat"):
        assert case["vars"]["channel"] in ("sms", "chat")


# --- the provider carries the channel into the brain --------------------------


async def test_the_provider_shows_the_booking_link_inline_on_chat_and_sends_no_sms(
    fixed_clock, monkeypatch
):
    """The chat scenario only means something if `channel: chat` reaches the capability."""
    from spatalk.brain.driver import FakeLLM, LLMResponse, ToolCall

    import scenarios.provider as p

    monkeypatch.setattr(
        p,
        "_make_llm",
        lambda: FakeLLM(
            [LLMResponse(text=None, tool_calls=[ToolCall("send_booking_link", {"service_id": "facial"})])]
        ),
    )
    monkeypatch.setattr(p, "_clock", lambda: fixed_clock)
    out = p.call_api(
        "", {}, {"vars": {"channel": "chat", "caller": "", "user": "send me the facial link"}}
    )["output"]
    import scenarios.asserts as a

    assert a.chat_link_inline(out, {}) is True
    assert out["sms_sent"] == 0 and out["items"] == []


async def test_the_provider_asks_the_brain_for_an_sms_length_reply(fixed_clock, monkeypatch):
    from spatalk.brain.driver import FakeLLM, LLMResponse

    import scenarios.provider as p

    llm = FakeLLM([LLMResponse(text="The express treatment is $99.", tool_calls=[])])
    monkeypatch.setattr(p, "_make_llm", lambda: llm)
    monkeypatch.setattr(p, "_clock", lambda: fixed_clock)
    out = p.call_api("", {}, {"vars": {"channel": "sms", "user": "how much is the express treatment"}})[
        "output"
    ]
    import scenarios.asserts as a

    assert a.sms_brevity(out, {}) is True
    system = llm.calls[0][0]
    assert "under 300 characters" in system


# --- STOP is handled before the brain (the plan's deterministic case) ---------


def _event(text: str, msg_id: str = "msg-1") -> dict:
    return {
        "data": {
            "event_type": "message.received",
            "id": "evt-1",
            "occurred_at": "2026-09-01T18:00:00.000Z",
            "payload": {
                "id": msg_id,
                "direction": "inbound",
                "type": "SMS",
                "text": text,
                "from": {"phone_number": CALLER},
                "to": [{"phone_number": SMS_FROM, "status": "webhook_delivered"}],
                "received_at": "2026-09-01T18:00:00.000Z",
            },
        }
    }


@pytest.fixture
async def sms_world(sf, registry, fixed_clock):
    from spatalk import jobs
    from spatalk.brain.driver import FakeLLM
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings

    cfg = await registry.get("skincentrix")
    await registry.import_config(cfg.model_copy(update={"sms_from_number": SMS_FROM}), "test")
    registry.invalidate("skincentrix")
    llm = FakeLLM([])
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=Settings(secret_key="s3cret", edge_shared_key=EDGE_KEY),
        sms=MemorySms(),
        llm=llm,
    )
    app = create_app(ctx, start_background=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as c:
        yield c, ctx, llm


async def _post(c, body: dict):
    return await c.post(
        "/telnyx/sms",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "X-Edge-Key": EDGE_KEY},
    )


@pytest.mark.parametrize("word", ["STOP", " stop ", "UNSUBSCRIBE", "cancel", "END", "quit"])
async def test_stop_is_handled_before_the_brain(sms_world, word):
    c, ctx, llm = sms_world
    r = await _post(c, _event(word, msg_id=f"m-{word.strip().lower()}"))
    assert r.status_code == 200
    assert llm.calls == [], f"{word!r} reached the model"
    assert ctx.sms.sent == [
        (
            SMS_FROM,
            CALLER,
            "You've been unsubscribed from Skincentrix texts. Reply START to opt back in.",
        )
    ]


async def test_a_normal_message_does_reach_the_brain(sms_world):
    """The counterpart: the STOP test would pass vacuously if nothing ever reached the model."""
    c, _ctx, llm = sms_world
    r = await _post(c, _event("How much is the express treatment?", msg_id="m-price"))
    assert r.status_code == 200
    assert len(llm.calls) == 1
