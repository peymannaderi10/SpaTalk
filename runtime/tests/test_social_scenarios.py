"""Task D5: the social half of the conversation regression suite, and its runbook.

`promptfoo` needs a real model key, so the Instagram DM cases run only in QA gates and in
CI when `GOOGLE_API_KEY` is present. These tests are the deterministic half:

* the new grader (`social_brevity`) really fails the things it claims to catch, including
  an emoji the customer never used;
* the suite really carries the Instagram cases the plan lists, and passes the channel
  through to the provider;
* the comment path — which arrives as a webhook, not as a turn, and so cannot be a
  promptfoo case at all — is replayed end to end here, and the reply that goes out to
  Meta is graded by the same rule the DM cases use;
* CI runs the social tests inside the runtime job, with no Meta secret;
* the Meta setup runbook carries the steps a founder cannot guess.

Test names are the behaviours the plan lists for this task.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(__file__).resolve().parents[1]
CONFIG = RUNTIME / "scenarios" / "promptfooconfig.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "meta"

IG_USER_ID = "17841400000000000"
SENDER_ID = "9000000000000001"
COMMENT_ID = "17900000000000001"
IG_SECRET = "ig-app-secret"
FB_SECRET = "fb-app-secret"
VERIFY_TOKEN = "the-verify-token"
MESSAGES_PATH = f"/v21.0/{IG_USER_ID}/messages"
PUBLIC_REPLY_PATH = f"/v21.0/{COMMENT_ID}/replies"
GREETING = "Hi, this is Skincentrix's assistant."


def _suite() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _cases(channel: str) -> list[dict]:
    return [t for t in _suite()["tests"] if (t.get("vars") or {}).get("channel") == channel]


def _asserts(case: dict) -> list[str]:
    return [
        a["value"].split(":")[-1] for a in (case.get("assert") or []) if a.get("type") == "python"
    ]


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


# --- the new grader -----------------------------------------------------------


def test_social_brevity_passes_a_short_plain_reply():
    import scenarios.asserts as a

    assert a.social_brevity(_out(), {"vars": {"user": "how much is the express treatment?"}}) is True


def test_social_brevity_fails_a_reply_over_five_hundred_characters():
    import scenarios.asserts as a

    long = "The express treatment is ninety nine dollars. " * 12
    bad = a.social_brevity(_out(text=long), {"vars": {"user": "how much?"}})
    assert bad["pass"] is False and str(len(long)) in bad["reason"]


def test_social_brevity_fails_an_emoji_the_customer_never_used():
    import scenarios.asserts as a

    bad = a.social_brevity(_out(text="The express treatment is $99! \U0001f60a"), {"vars": {"user": "how much?"}})
    assert bad["pass"] is False and "emoji" in bad["reason"]


def test_social_brevity_allows_an_emoji_when_the_customer_used_one_first():
    import scenarios.asserts as a

    context = {"vars": {"user": "how much is the express treatment? \U0001f60d"}}
    assert a.social_brevity(_out(text="It's $99 \U0001f60a"), context) is True


def test_social_brevity_reads_the_customers_emoji_out_of_the_history_too():
    import scenarios.asserts as a

    context = {
        "vars": {
            "history": [{"role": "user", "content": "hey \U0001f44b"}],
            "user": "how much is the express treatment?",
        }
    }
    assert a.social_brevity(_out(text="It's $99 \U0001f60a"), context) is True


def test_social_brevity_fails_a_reply_containing_markdown():
    import scenarios.asserts as a

    for markdown in (
        "Our **express treatment** is $99.",
        "Prices:\n- facial $199\n- express $99",
        "Book here: [facial](https://book.example.com/facial)",
    ):
        bad = a.social_brevity(_out(text=markdown), {"vars": {"user": "how much?"}})
        assert bad["pass"] is False and "markdown" in bad["reason"], markdown


def test_social_brevity_fails_a_reply_that_claims_an_action():
    import scenarios.asserts as a

    bad = a.social_brevity(_out(text="You're all set for Thursday."), {"vars": {"user": "book me"}})
    assert bad["pass"] is False and "all set" in bad["reason"]


def test_the_inline_link_grader_is_shared_with_the_chat_case_unchanged():
    """`link_inline` is the general rule; `chat_link_inline` is the name Task B6 uses."""
    import scenarios.asserts as a

    shown = _out(
        outcomes=["link_sent"],
        text="Here is the booking link for Signature Facial: https://book.example.com/facial",
    )
    assert a.link_inline(shown, {}) is True
    assert a.chat_link_inline(shown, {}) is True
    texted = _out(outcomes=["link_sent"], sms_sent=1, text="I've just texted you the link.")
    assert a.link_inline(texted, {})["pass"] is False
    assert a.chat_link_inline(texted, {})["pass"] is False


# --- the suite itself ---------------------------------------------------------


def test_the_suite_has_instagram_cases_for_price_clinical_and_the_booking_link():
    cases = _cases("instagram")
    flat = {g for c in cases for g in _asserts(c)}
    assert len(cases) >= 3, "the plan lists a DM price question, a clinical DM and a link request"
    assert "band1_answer" in flat, "no price case"
    assert "band3_gate" in flat, "no clinical case"
    assert "link_inline" in flat, "no booking-link case"


def test_every_instagram_case_carries_no_phone_number_for_the_brain_to_fall_back_on():
    """There is no caller id on Instagram: the scenarios must not smuggle one in."""
    for case in _cases("instagram"):
        assert case["vars"].get("caller") == "", case["description"]


def test_the_instagram_cases_the_model_writes_are_graded_for_length_and_emoji():
    """Every case whose reply comes from the model is graded; the fixed band-3 script is not."""
    for case in _cases("instagram"):
        graders = _asserts(case)
        if "band3_gate" in graders:
            continue
        assert "social_brevity" in graders, case["description"]


def test_the_suite_passes_the_instagram_channel_through_to_the_provider():
    suite = _suite()
    assert suite["providers"][0]["id"] == "file://provider.py"
    assert _cases("instagram"), "no instagram case reaches the provider"


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


# --- the provider carries the Instagram channel into the brain ----------------


async def test_the_provider_puts_the_instagram_channel_rule_in_the_prompt(fixed_clock, monkeypatch):
    from spatalk.brain.driver import FakeLLM, LLMResponse

    import scenarios.asserts as a
    import scenarios.provider as p

    llm = FakeLLM([LLMResponse(text="The express treatment is $99.", tool_calls=[])])
    monkeypatch.setattr(p, "_make_llm", lambda: llm)
    monkeypatch.setattr(p, "_clock", lambda: fixed_clock)
    vars_ = {"channel": "instagram", "caller": "", "user": "how much is the express treatment?"}
    out = p.call_api("", {}, {"vars": vars_})["output"]

    system = llm.calls[0][0]
    assert "under 500 characters" in system and "no emoji" in system
    assert a.social_brevity(out, {"vars": vars_}) is True


async def test_the_provider_shows_the_booking_link_in_the_dm_and_sends_no_sms(
    fixed_clock, monkeypatch
):
    from spatalk.brain.driver import FakeLLM, LLMResponse, ToolCall

    import scenarios.asserts as a
    import scenarios.provider as p

    monkeypatch.setattr(
        p,
        "_make_llm",
        lambda: FakeLLM(
            [
                LLMResponse(
                    text=None, tool_calls=[ToolCall("send_booking_link", {"service_id": "facial"})]
                )
            ]
        ),
    )
    monkeypatch.setattr(p, "_clock", lambda: fixed_clock)
    out = p.call_api(
        "",
        {},
        {"vars": {"channel": "instagram", "caller": "", "user": "send me the link to book a facial"}},
    )["output"]

    assert a.link_inline(out, {}) is True
    assert out["sms_sent"] == 0 and out["items"] == []


async def test_a_clinical_dm_is_gated_and_files_an_urgent_item_without_a_phone_number(
    fixed_clock, monkeypatch
):
    """The clinical scenario: the gate runs before the model, so no key is needed to prove it."""
    from spatalk.brain.driver import FakeLLM

    import scenarios.asserts as a
    import scenarios.provider as p

    llm = FakeLLM([])
    monkeypatch.setattr(p, "_make_llm", lambda: llm)
    monkeypatch.setattr(p, "_clock", lambda: fixed_clock)
    vars_ = {
        "channel": "instagram",
        "caller": "",
        "user": "I have a rash and some swelling after my laser session yesterday",
        "expect_reason": "clinical",
    }
    out = p.call_api("", {}, {"vars": vars_})["output"]

    assert llm.calls == [], "a clinical DM reached the model"
    assert a.band3_gate(out, {"vars": vars_}) is True
    assert out["items"][0]["type"] == "escalation_clinical"
    assert "911" not in out["text"] and "clinical team" in out["text"]


# --- the comment path, deterministic (the plan says this one is not a promptfoo case) ---


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def sign(raw: bytes, secret: str = IG_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


async def _build(sf, registry, fixed_clock, *, reply: str, public_reply: bool = False):
    from cryptography.fernet import Fernet

    from spatalk import jobs
    from spatalk.brain.driver import FakeLLM, LLMResponse
    from spatalk.brain.ports import MemorySms
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger
    from spatalk.settings import Settings
    from spatalk.social.graph import FakeGraphClient
    from spatalk.social.meta_oauth import store_integration
    from spatalk.tenants.schema import SocialSettings

    settings = Settings(
        _env_file=None,
        secret_key="s3cret",
        public_base_url="https://api.example.com",
        instagram_app_id="IG_APP_ID",
        instagram_app_secret=IG_SECRET,
        facebook_app_id="FB_APP_ID",
        facebook_app_secret=FB_SECRET,
        instagram_webhook_verify_token=VERIFY_TOKEN,
        meta_token_encryption_key=Fernet.generate_key().decode(),
    )
    cfg = await registry.get("skincentrix")
    social = SocialSettings(
        comment_mode="keyword",
        comment_keywords=["price", "how much", "book"],
        public_reply_enabled=public_reply,
    )
    await registry.import_config(cfg.model_copy(update={"social": social}), "test")
    registry.invalidate("skincentrix")
    llm = FakeLLM([LLMResponse(text=reply, tool_calls=[])])
    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=settings,
        sms=MemorySms(),
        llm=llm,
        graph=FakeGraphClient(
            {MESSAGES_PATH: {"message_id": "mid-out"}, PUBLIC_REPLY_PATH: {"id": "reply-1"}}
        ),
    )
    await store_integration(
        sf,
        settings,
        fixed_clock,
        tenant_id="skincentrix",
        provider="instagram",
        external_id=IG_USER_ID,
        display_name="skincentrix",
        access_token="IG-long-lived-token",
        connected_by="test",
    )
    return create_app(ctx, start_background=False), ctx


def promo_comment(text: str = "how much?") -> dict:
    """The recorded comment payload, re-worded to the promo-post question the plan names."""
    body = fixture("comment")
    body["entry"][0]["changes"][0]["value"]["text"] = text
    return body


async def _deliver(app, ctx, body: dict):
    from spatalk import jobs

    raw = json.dumps(body).encode()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.example.com"
    ) as c:
        r = await c.post(
            "/instagram/webhook",
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sign(raw)},
        )
    assert r.status_code == 200, r.text
    await jobs.run_once(ctx.sf, ctx)


def _sends(ctx, path: str = MESSAGES_PATH) -> list:
    return [call for call in ctx.graph.calls if call.path == path]


@pytest.fixture
async def promo_world(sf, registry, fixed_clock):
    app, ctx = await _build(
        sf, registry, fixed_clock, reply="The express treatment is $99 and a facial is $199."
    )
    return app, ctx


async def test_a_how_much_comment_on_a_promo_post_is_answered_by_a_private_reply(promo_world):
    app, ctx = promo_world
    await _deliver(app, ctx, promo_comment())

    calls = _sends(ctx)
    assert len(calls) == 1
    assert calls[0].json["recipient"] == {"comment_id": COMMENT_ID}
    assert calls[0].json["message"]["text"] == (
        f"{GREETING} The express treatment is $99 and a facial is $199."
    )
    # Public reply is off for this tenant, and nothing is texted to anyone.
    assert _sends(ctx, PUBLIC_REPLY_PATH) == []
    assert ctx.sms.sent == []


async def test_the_comment_reply_is_graded_by_the_same_rule_as_a_dm(promo_world):
    """The scenario grade, applied to what actually left for Meta."""
    import scenarios.asserts as a

    app, ctx = promo_world
    await _deliver(app, ctx, promo_comment())

    text = _sends(ctx)[0].json["message"]["text"]
    assert a.social_brevity(_out(text=text), {"vars": {"user": "how much?"}}) is True


async def test_the_comment_turn_reaches_the_brain_with_the_instagram_channel_rule(promo_world):
    app, ctx = promo_world
    await _deliver(app, ctx, promo_comment())

    assert len(ctx.llm.calls) == 1
    system = ctx.llm.calls[0][0]
    assert "under 500 characters" in system and "no emoji" in system
    assert ctx.llm.calls[0][1][-1]["content"] == "how much?"


async def test_a_price_comment_files_nothing_for_the_team(promo_world):
    """A band-1 answer is the whole outcome: no item, no free text, nothing for a human."""
    from spatalk.models import Item

    app, ctx = promo_world
    await _deliver(app, ctx, promo_comment())

    async with ctx.sf() as s:
        assert list((await s.scalars(select(Item))).all()) == []


async def test_the_public_reply_is_the_tenants_fixed_wording_when_it_is_enabled(
    sf, registry, fixed_clock
):
    app, ctx = await _build(
        sf, registry, fixed_clock, reply="The express treatment is $99.", public_reply=True
    )
    await _deliver(app, ctx, promo_comment())

    public = _sends(ctx, PUBLIC_REPLY_PATH)
    assert len(public) == 1
    assert public[0].json == {"message": "Thanks! Check your DMs."}


# --- CI runs the social tests, with no Meta secret ----------------------------


def test_ci_runs_the_social_tests_in_the_runtime_job_without_extra_secrets():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    test_job = workflow["jobs"]["test"]
    runs = [s.get("run", "") for s in test_job["steps"]]
    pytest_steps = [r for r in runs if "uv run pytest" in r]
    assert pytest_steps, "the runtime job does not run pytest"
    # The whole suite, unfiltered: no -k, no --ignore, no deselect can hide the social tests.
    for step in pytest_steps:
        for flag in (" -k", "--ignore", "--deselect"):
            assert flag not in step, f"the runtime pytest step filters tests: {step!r}"
    secrets_used = json.dumps(test_job.get("env", {}))
    for name in ("INSTAGRAM", "FACEBOOK", "META_"):
        assert name not in secrets_used, f"the runtime job asks for a Meta secret ({name})"


def test_the_social_tests_are_collected_by_the_runtime_suite():
    """The counterpart: the CI assertion above is vacuous if these files are not there."""
    names = {p.name for p in (RUNTIME / "tests").glob("test_social_*.py")}
    assert {
        "test_social_crypto.py",
        "test_social_oauth.py",
        "test_social_instagram.py",
        "test_social_messenger.py",
        "test_social_integrations_api.py",
        "test_social_scenarios.py",
    } <= names


# --- the runbook --------------------------------------------------------------


def test_the_meta_setup_runbook_carries_the_app_review_checklist():
    runbook = (ROOT / "docs" / "runbooks" / "meta-setup.md").read_text(encoding="utf-8").lower()
    for needed in (
        "INSTAGRAM_APP_ID",
        "INSTAGRAM_APP_SECRET",
        "FACEBOOK_APP_SECRET",
        "INSTAGRAM_WEBHOOK_VERIFY_TOKEN",
        "META_TOKEN_ENCRYPTION_KEY",
        "/instagram/webhook",
        "/instagram/callback",
        "/instagram/deauthorize",
        "/instagram/delete",
        "/messenger/webhook",
        "Standard Access",
        "Advanced Access",
        "Instagram Tester",
        "App Review",
        "screencast",
        "Settings",  # the tenant-facing connect path in the portal
        "Integrations",
    ):
        assert needed.lower() in runbook, f"the meta setup runbook is missing {needed!r}"


def test_meta_is_in_the_subprocessor_register():
    """Adding a provider is a register entry, not just a config change (spec §7)."""
    spec = (
        ROOT / "docs" / "superpowers" / "specs"
        / "2026-09-01-ai-front-desk-architecture-design.md"
    ).read_text(encoding="utf-8")
    register = spec.split("**Initial subprocessor register:**")[1].split("Adding any provider")[0]
    assert "Meta" in register, "Meta is not in the subprocessor register"
