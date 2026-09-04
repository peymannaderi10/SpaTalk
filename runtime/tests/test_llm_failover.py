"""One vendor being down must not take the front desk down.

Founder decision 2026-09-03 ~21:20, after Google answered every request with 503 for twenty
minutes: every conversational turn gets a primary model and a secondary model from a
different vendor. Two pieces do it, and both are proved here with fakes and no network.

* :class:`~spatalk.brain.breaker.VendorBreaker` — a process-wide count of recent failures
  per vendor. Enough of them inside the window opens the breaker, a cooldown closes it, and
  while it is open the runtime stops paying a dead vendor's latency on every turn.
* :class:`~spatalk.brain.driver.FailoverLLMClient` — the text-channel half: one turn, the
  active vendor first, the other vendor once if the first raises, and the exception only if
  both did. A tool call from either vendor is returned untouched, because the ledger, not
  the model, decides what happened.

The vendor is never named by this code: `LLM_MODEL` and `LLM_MODEL_FALLBACK` name it, in the
same `vendor:model` syntax (CLAUDE.md non-negotiable 4).
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"


def _settings(**kw):
    from spatalk.settings import Settings

    return Settings(_env_file=None, **kw)


class _FakeMonotonic:
    """A monotonic clock the test moves by hand. Never `time.sleep` in a breaker test."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# --- the breaker ------------------------------------------------------------------------


def test_the_breaker_opens_on_the_third_failure_in_the_window_and_not_on_two():
    from spatalk.brain.breaker import VendorBreaker

    clock = _FakeMonotonic()
    breaker = VendorBreaker(failures=3, window_secs=60, cooldown_secs=300, monotonic=clock)

    breaker.record_failure("google")
    assert not breaker.is_open("google")
    clock.advance(1.0)
    breaker.record_failure("google")
    assert not breaker.is_open("google"), "two failures are a bad minute, not a dead vendor"
    clock.advance(1.0)
    breaker.record_failure("google")
    assert breaker.is_open("google")
    # One vendor's failures say nothing about the other's.
    assert not breaker.is_open("openai")


def test_failures_spread_wider_than_the_window_never_open_it():
    from spatalk.brain.breaker import VendorBreaker

    clock = _FakeMonotonic()
    breaker = VendorBreaker(failures=3, window_secs=60, cooldown_secs=300, monotonic=clock)

    for _ in range(5):
        breaker.record_failure("google")
        clock.advance(61.0)
    assert not breaker.is_open("google")


def test_the_breaker_closes_after_the_cooldown():
    from spatalk.brain.breaker import VendorBreaker

    clock = _FakeMonotonic()
    breaker = VendorBreaker(failures=2, window_secs=60, cooldown_secs=300, monotonic=clock)

    breaker.record_failure("google")
    breaker.record_failure("google")
    assert breaker.is_open("google")
    clock.advance(299.0)
    assert breaker.is_open("google")
    clock.advance(2.0)
    assert not breaker.is_open("google"), "the cooldown is over; the vendor gets another turn"
    # And the failures that opened it are gone, so one more failure does not re-open it.
    breaker.record_failure("google")
    assert not breaker.is_open("google")


def test_a_success_closes_the_breaker_and_clears_the_count():
    from spatalk.brain.breaker import VendorBreaker

    clock = _FakeMonotonic()
    breaker = VendorBreaker(failures=3, window_secs=60, cooldown_secs=300, monotonic=clock)

    breaker.record_failure("google")
    breaker.record_failure("google")
    breaker.record_success("google")
    assert not breaker.is_open("google")
    breaker.record_failure("google")
    breaker.record_failure("google")
    assert not breaker.is_open("google"), "the count restarted at the success"


def test_open_until_reports_the_deadline_and_nothing_when_the_breaker_is_shut():
    from spatalk.brain.breaker import VendorBreaker

    clock = _FakeMonotonic(now=1000.0)
    breaker = VendorBreaker(failures=1, window_secs=60, cooldown_secs=300, monotonic=clock)

    assert breaker.open_until("google") is None
    breaker.record_failure("google")
    assert breaker.open_until("google") == pytest.approx(1300.0)
    clock.advance(301.0)
    assert breaker.open_until("google") is None


def test_active_prefers_the_primary_and_moves_to_the_secondary_only_when_the_primary_is_open():
    from spatalk.brain.breaker import VendorBreaker

    clock = _FakeMonotonic()
    breaker = VendorBreaker(failures=1, window_secs=60, cooldown_secs=300, monotonic=clock)

    assert breaker.active("google", "openai") == "google"
    breaker.record_failure("google")
    assert breaker.active("google", "openai") == "openai"
    clock.advance(301.0)
    assert breaker.active("google", "openai") == "google", "the cooldown returns the primary"


def test_active_stays_on_the_primary_when_both_breakers_are_open():
    """Both vendors look dead, so the choice is between two bad options. The primary is the
    least bad one: it is the model the prompts and the scenarios were graded against, and a
    turn has to be sent somewhere."""
    from spatalk.brain.breaker import VendorBreaker

    clock = _FakeMonotonic()
    breaker = VendorBreaker(failures=1, window_secs=60, cooldown_secs=300, monotonic=clock)

    breaker.record_failure("google")
    breaker.record_failure("openai")
    assert breaker.is_open("google") and breaker.is_open("openai")
    assert breaker.active("google", "openai") == "google"


def test_active_with_no_secondary_is_always_the_primary():
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(failures=1, window_secs=60, cooldown_secs=300)
    breaker.record_failure("google")
    assert breaker.active("google", None) == "google"


def test_the_process_wide_breaker_takes_its_numbers_from_the_settings():
    from spatalk.brain import breaker as breaker_module

    original = (
        breaker_module.BREAKER.failures,
        breaker_module.BREAKER.window_secs,
        breaker_module.BREAKER.cooldown_secs,
    )
    try:
        breaker_module.configure(
            _settings(
                llm_breaker_failures=7, llm_breaker_window_secs=11, llm_breaker_cooldown_secs=13
            )
        )
        assert breaker_module.BREAKER.failures == 7
        assert breaker_module.BREAKER.window_secs == 11
        assert breaker_module.BREAKER.cooldown_secs == 13
    finally:
        breaker_module.BREAKER.reconfigure(*original)
        breaker_module.BREAKER.reset()


def test_the_module_level_breaker_needs_no_settings_to_exist():
    """It is built at import time with the defaults, so importing the breaker never drags
    a settings object (and a dotenv read) into a module that only wants to count failures."""
    import inspect

    from spatalk.brain import breaker as breaker_module

    assert isinstance(breaker_module.BREAKER, breaker_module.VendorBreaker)
    source = inspect.getsource(breaker_module)
    assert "from spatalk.settings import" not in source
    assert "import spatalk.settings" not in source


# --- the text-channel failover client ---------------------------------------------------


class _ScriptedLLM:
    """An `LLMClient` that answers with what it was given, or raises what it was given."""

    def __init__(self, answer=None, raises: Exception | None = None):
        self._answer, self._raises = answer, raises
        self.calls: list[tuple[str, list[dict]]] = []

    async def complete(self, system, history, tools):
        self.calls.append((system, list(history)))
        if self._raises is not None:
            raise self._raises
        return self._answer


def _response(text=None, tool_calls=()):
    from spatalk.brain.driver import LLMResponse

    return LLMResponse(text=text, tool_calls=list(tool_calls))


def _failover(primary, secondary, breaker=None, vendors=("google", "openai")):
    from spatalk.brain.breaker import VendorBreaker
    from spatalk.brain.driver import FailoverLLMClient

    return FailoverLLMClient(
        primary, secondary, breaker or VendorBreaker(monotonic=_FakeMonotonic()), vendors
    )


async def test_the_primary_answers_and_the_secondary_is_never_called():
    primary = _ScriptedLLM(answer=_response(text="The express treatment is $99."))
    secondary = _ScriptedLLM(answer=_response(text="never spoken"))
    client = _failover(primary, secondary)

    resp = await client.complete("SYSTEM", [{"role": "user", "content": "how much?"}], [])
    assert resp.text == "The express treatment is $99."
    assert len(primary.calls) == 1 and secondary.calls == []


async def test_the_secondary_answers_the_same_turn_when_the_primary_raises():
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(failures=3, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic())
    primary = _ScriptedLLM(raises=RuntimeError("503 UNAVAILABLE: the model is overloaded"))
    secondary = _ScriptedLLM(answer=_response(text="The express treatment is $99."))
    client = _failover(primary, secondary, breaker)

    history = [{"role": "user", "content": "how much?"}]
    resp = await client.complete("SYSTEM", history, [])
    assert resp.text == "The express treatment is $99."
    # The same turn, not a new one: the secondary saw the system prompt and the history.
    assert secondary.calls == [("SYSTEM", history)]
    assert breaker.failure_count("google") == 1 and breaker.failure_count("openai") == 0


async def test_a_tool_call_from_the_secondary_comes_back_untouched():
    """The failover must not swallow a tool call: the ledger row is the product."""
    from spatalk.brain.driver import ToolCall

    call = ToolCall("escalate", {"reason": "human_request"})
    primary = _ScriptedLLM(raises=RuntimeError("503"))
    secondary = _ScriptedLLM(answer=_response(text="One moment.", tool_calls=[call]))
    client = _failover(primary, secondary)

    resp = await client.complete("SYSTEM", [], [])
    assert resp.text == "One moment."
    assert [(tc.name, tc.arguments) for tc in resp.tool_calls] == [
        ("escalate", {"reason": "human_request"})
    ]


async def test_both_vendors_failing_raises_and_records_both_failures():
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(failures=3, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic())
    primary = _ScriptedLLM(raises=RuntimeError("google 503"))
    secondary = _ScriptedLLM(raises=RuntimeError("openai 500"))
    client = _failover(primary, secondary, breaker)

    with pytest.raises(RuntimeError) as e:
        await client.complete("SYSTEM", [], [])
    assert "openai 500" in str(e.value)
    assert breaker.failure_count("google") == 1 and breaker.failure_count("openai") == 1


async def test_a_success_after_a_failover_clears_the_secondarys_count():
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(failures=3, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic())
    primary = _ScriptedLLM(raises=RuntimeError("503"))
    secondary = _ScriptedLLM(answer=_response(text="hi"))
    await _failover(primary, secondary, breaker).complete("SYSTEM", [], [])
    assert breaker.failure_count("openai") == 0


async def test_while_the_primarys_breaker_is_open_the_turn_starts_at_the_secondary():
    """The cooling-off period: a dead vendor is not tried again on every single turn."""
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(failures=1, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic())
    breaker.record_failure("google")
    primary = _ScriptedLLM(answer=_response(text="the primary is back"))
    secondary = _ScriptedLLM(answer=_response(text="the secondary answered"))
    client = _failover(primary, secondary, breaker)

    resp = await client.complete("SYSTEM", [], [])
    assert resp.text == "the secondary answered"
    assert primary.calls == []


async def test_with_the_primary_open_and_the_secondary_failing_the_primary_still_gets_the_turn():
    """A caller is waiting: the last option is tried once rather than the turn abandoned."""
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(failures=1, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic())
    breaker.record_failure("google")
    primary = _ScriptedLLM(answer=_response(text="the primary answered"))
    secondary = _ScriptedLLM(raises=RuntimeError("openai 500"))
    client = _failover(primary, secondary, breaker)

    resp = await client.complete("SYSTEM", [], [])
    assert resp.text == "the primary answered"
    assert len(primary.calls) == 1


async def test_two_models_at_the_same_vendor_are_still_two_clients():
    """`LLM_MODEL_FALLBACK` may name a second model at the same vendor. The breaker cannot
    tell them apart, but the client must never collapse them into one."""
    primary = _ScriptedLLM(raises=RuntimeError("400 the model was retired"))
    secondary = _ScriptedLLM(answer=_response(text="the other model answered"))
    client = _failover(primary, secondary, vendors=("google", "google"))

    resp = await client.complete("SYSTEM", [], [])
    assert resp.text == "the other model answered"


def test_the_failover_client_satisfies_the_llm_client_protocol():
    import inspect

    from spatalk.brain.driver import FailoverLLMClient, GeminiClient, LLMClient

    assert inspect.signature(FailoverLLMClient.complete) == inspect.signature(
        GeminiClient.complete
    )
    assert set(inspect.signature(LLMClient.complete).parameters) <= set(
        inspect.signature(FailoverLLMClient.complete).parameters
    )
    assert inspect.iscoroutinefunction(FailoverLLMClient.complete)


# --- make_text_llm ----------------------------------------------------------------------


def test_make_text_llm_is_the_plain_client_when_no_fallback_is_configured():
    from spatalk.brain.driver import FailoverLLMClient, GeminiClient
    from spatalk.text.service import make_text_llm

    client = make_text_llm(_settings(google_api_key="k", llm_model="gemini-2.5-flash"))
    assert isinstance(client, GeminiClient) and not isinstance(client, FailoverLLMClient)


def test_make_text_llm_builds_the_failover_client_when_the_fallback_is_set():
    from spatalk.brain.driver import FailoverLLMClient, GeminiClient, OpenAIClient
    from spatalk.text.service import make_text_llm

    client = make_text_llm(
        _settings(
            google_api_key="k",
            openai_api_key="o",
            llm_model="gemini-2.5-flash",
            llm_model_fallback="openai:gpt-4.1-nano",
        )
    )
    assert isinstance(client, FailoverLLMClient)
    assert isinstance(client.primary, GeminiClient)
    assert isinstance(client.secondary, OpenAIClient)
    assert client.vendors == ("google", "openai")


def test_make_text_llm_falls_back_to_the_plain_client_when_the_second_vendor_has_no_key():
    """A fallback nobody configured a key for is not a failover; it is one vendor and a
    misleading log line. The primary answers as it did before."""
    from spatalk.brain.driver import FailoverLLMClient, GeminiClient
    from spatalk.text.service import make_text_llm

    client = make_text_llm(
        _settings(
            google_api_key="k",
            llm_model="gemini-2.5-flash",
            llm_model_fallback="openai:gpt-4.1-nano",
        )
    )
    assert isinstance(client, GeminiClient) and not isinstance(client, FailoverLLMClient)


def test_make_text_llm_is_still_none_when_the_primary_vendor_has_no_key():
    from spatalk.text.service import make_text_llm

    assert (
        make_text_llm(
            _settings(llm_model="gemini-2.5-flash", llm_model_fallback="openai:gpt-4.1-nano")
        )
        is None
    )


def test_the_fallback_alone_answers_when_the_primary_vendor_has_no_key():
    """`LLM_MODEL` naming a vendor whose key was removed is a configuration the runtime can
    still serve: the fallback is a working client and text channels keep answering."""
    from spatalk.brain.driver import FailoverLLMClient, OpenAIClient
    from spatalk.text.service import make_text_llm

    client = make_text_llm(
        _settings(
            openai_api_key="o",
            llm_model="gemini-2.5-flash",
            llm_model_fallback="openai:gpt-4.1-nano",
        )
    )
    assert isinstance(client, OpenAIClient) and not isinstance(client, FailoverLLMClient)


# --- settings and documentation ---------------------------------------------------------


def test_the_settings_carry_the_fallback_and_the_breaker_numbers_with_their_env_names():
    from spatalk.settings import Settings

    s = _settings()
    assert s.llm_model_fallback == "", "no failover until the founder configures one"
    assert (s.llm_breaker_failures, s.llm_breaker_window_secs, s.llm_breaker_cooldown_secs) == (
        3,
        60,
        300,
    )
    for field in (
        "llm_model_fallback",
        "llm_breaker_failures",
        "llm_breaker_window_secs",
        "llm_breaker_cooldown_secs",
    ):
        assert field in Settings.model_fields


def test_the_fallback_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_FALLBACK", "openai:gpt-4.1-mini")
    monkeypatch.setenv("LLM_BREAKER_FAILURES", "5")
    s = _settings()
    assert s.llm_model_fallback == "openai:gpt-4.1-mini" and s.llm_breaker_failures == 5


def test_the_reference_documents_the_new_environment_variables():
    text = (REPO / "docs" / "reference" / "api-surface.md").read_text(encoding="utf-8")
    for name in (
        "LLM_MODEL_FALLBACK",
        "LLM_BREAKER_FAILURES",
        "LLM_BREAKER_WINDOW_SECS",
        "LLM_BREAKER_COOLDOWN_SECS",
    ):
        assert name in text, f"api-surface.md does not list {name}"


def test_the_environment_example_lists_the_fallback_with_an_empty_value():
    from dotenv import dotenv_values

    values = dotenv_values(RUNTIME / ".env.example")
    assert "LLM_MODEL_FALLBACK" in values
    assert (values["LLM_MODEL_FALLBACK"] or "") == "", "shipping a fallback on by default"


# --- the vendor table (addendum, founder decision 2026-09-03 ~21:40) ---------------------
# The founder wants the cheapest model to be reachable by an environment value alone, so
# every OpenAI-compatible host is a vendor. The table is the only place a vendor is named.

EXPECTED_VENDORS = {
    "openai": ("https://api.openai.com/v1", "openai_api_key"),
    "openrouter": ("https://openrouter.ai/api/v1", "openrouter_api_key"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek_api_key"),
    "xai": ("https://api.x.ai/v1", "xai_api_key"),
    "groq": ("https://api.groq.com/openai/v1", "groq_api_key"),
    "together": ("https://api.together.xyz/v1", "together_api_key"),
    "fireworks": ("https://api.fireworks.ai/inference/v1", "fireworks_api_key"),
    # Alibaba's Qwen. The US endpoint, not the Singapore one: measured from the founder's
    # laptop 2026-09-03, dashscope-us connects as fast as Google's endpoint and
    # dashscope-intl took 1.2 s (coordinator note, same night).
    "dashscope": ("https://dashscope-us.aliyuncs.com/compatible-mode/v1", "dashscope_api_key"),
    # The escape hatch: any other OpenAI-compatible host, its URL from the environment.
    "compat": ("", "compat_api_key"),
}


def test_every_prefix_in_the_table_names_its_vendor_and_is_stripped_from_the_model():
    from spatalk.brain.driver import VENDORS, model_name, provider_for

    assert set(VENDORS) == set(EXPECTED_VENDORS)
    for vendor, (base_url, key_field) in EXPECTED_VENDORS.items():
        assert provider_for(f"{vendor}:some-model") == vendor
        assert model_name(f"{vendor}:some-model") == "some-model"
        assert VENDORS[vendor].base_url == base_url
        assert VENDORS[vendor].key_field == key_field


def test_a_prefix_survives_the_shapes_a_dotenv_file_produces():
    from spatalk.brain.driver import model_name, provider_for

    for raw in ("OpenRouter:qwen/qwen3-30b", " openrouter: qwen/qwen3-30b ", "OPENROUTER:qwen/qwen3-30b"):
        assert provider_for(raw) == "openrouter", raw
        assert model_name(raw) == "qwen/qwen3-30b", raw


def test_a_bare_name_is_still_google_and_google_is_not_in_the_table():
    """Google is not OpenAI-compatible: it is the one vendor with its own client."""
    from spatalk.brain.driver import GOOGLE, VENDORS, model_name, provider_for

    assert provider_for("gemini-2.5-flash") == GOOGLE
    assert model_name("gemini-2.5-flash") == "gemini-2.5-flash"
    assert GOOGLE not in VENDORS


def test_a_prefix_with_no_model_after_it_is_a_configuration_error():
    from spatalk.brain.driver import model_name

    for raw in ("openai:", "groq: ", "compat:"):
        with pytest.raises(ValueError) as e:
            model_name(raw)
        assert "LLM_MODEL" in str(e.value)


def test_every_key_field_and_base_url_field_exists_on_the_settings():
    from spatalk.brain.driver import VENDORS
    from spatalk.settings import Settings

    for vendor in VENDORS.values():
        assert vendor.key_field in Settings.model_fields, vendor.key_field
        assert vendor.base_url_field in Settings.model_fields, vendor.base_url_field
        assert Settings.model_fields[vendor.key_field].default == ""
        assert Settings.model_fields[vendor.base_url_field].default == ""


def test_a_vendors_base_url_is_an_environment_value_too(monkeypatch):
    """A region change must not be a code change: `LLM_<VENDOR>_BASE_URL` wins over the
    table's default (coordinator note 2026-09-03: dashscope-intl was 1.2 s away)."""
    from spatalk.brain.driver import base_url_for

    default = base_url_for(_settings(), "dashscope")
    assert default == "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
    monkeypatch.setenv("LLM_DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    assert base_url_for(_settings(), "dashscope").startswith("https://dashscope-intl.")


def test_the_generic_compat_vendor_has_no_url_until_the_environment_gives_it_one():
    from spatalk.brain.driver import base_url_for

    with pytest.raises(ValueError) as e:
        base_url_for(_settings(), "compat")
    assert "LLM_COMPAT_BASE_URL" in str(e.value)
    assert base_url_for(_settings(llm_compat_base_url="http://localhost:11434/v1"), "compat") == (
        "http://localhost:11434/v1"
    )


def test_the_breaker_tells_two_openai_compatible_vendors_apart():
    """They speak the same protocol; they are not the same company and do not fail together."""
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(failures=1, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic())
    breaker.record_failure("openrouter")
    assert breaker.is_open("openrouter") and not breaker.is_open("openai")
    assert breaker.active("openai", "openrouter") == "openai"
    assert breaker.active("openrouter", "openai") == "openai"


def test_make_text_llm_builds_a_compat_client_pointed_at_the_configured_host():
    from spatalk.brain.driver import OpenAIClient
    from spatalk.text.service import make_text_llm

    client = make_text_llm(
        _settings(
            compat_api_key="k",
            llm_compat_base_url="http://localhost:11434/v1",
            llm_model="compat:qwen3:8b",
        )
    )
    assert isinstance(client, OpenAIClient)
    assert client.base_url == "http://localhost:11434/v1"
    assert client.model == "qwen3:8b", "the prefix must not reach the provider"


def test_make_text_llm_is_none_when_the_named_vendor_has_no_key():
    from spatalk.text.service import make_text_llm

    assert make_text_llm(_settings(google_api_key="k", llm_model="groq:llama-3.3-70b")) is None


def test_a_failover_across_two_openai_compatible_vendors_is_two_clients_and_two_hosts():
    from spatalk.brain.driver import FailoverLLMClient
    from spatalk.text.service import make_text_llm

    client = make_text_llm(
        _settings(
            groq_api_key="g",
            deepseek_api_key="d",
            llm_model="groq:llama-3.3-70b-versatile",
            llm_model_fallback="deepseek:deepseek-chat",
        )
    )
    assert isinstance(client, FailoverLLMClient)
    assert client.vendors == ("groq", "deepseek")
    assert client.primary.base_url == "https://api.groq.com/openai/v1"
    assert client.secondary.base_url == "https://api.deepseek.com/v1"


def test_the_reference_documents_every_vendor_key_and_base_url():
    text = (REPO / "docs" / "reference" / "api-surface.md").read_text(encoding="utf-8")
    for name in (
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "XAI_API_KEY",
        "GROQ_API_KEY",
        "TOGETHER_API_KEY",
        "FIREWORKS_API_KEY",
        "DASHSCOPE_API_KEY",
        "COMPAT_API_KEY",
        "LLM_COMPAT_BASE_URL",
        "LLM_DASHSCOPE_BASE_URL",
    ):
        assert name in text, f"api-surface.md does not list {name}"


def test_the_accounts_runbook_says_where_each_vendors_key_comes_from():
    text = (REPO / "docs" / "runbooks" / "accounts-and-env.md").read_text(encoding="utf-8")
    for needle in ("openrouter.ai", "deepseek", "x.ai", "groq", "together", "fireworks", "dashscope"):
        assert needle in text.lower(), f"the runbook never says where the {needle} key comes from"
    # The data-handling note the addendum asks for, in the runbook rather than in code.
    assert "North America" in text


# =========================================================================================
# Task F2: the voice router
# =========================================================================================
#
# On the phone there is no `await` to wrap: the model is a Pipecat service inside a running
# pipeline. `LLMRouter` holds both services as its own children, sends each turn's
# `LLMContextFrame` to the active one, and when that one answers with an `ErrorFrame` it
# sends the *same* context to the other service at once, so the caller waits about one extra
# model call and then hears an answer instead of an apology. Only when both have failed does
# the error reach the pipeline and the caller hear anything about it.

from pipecat.frames.frames import (  # noqa: E402
    ErrorFrame,
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor  # noqa: E402
from pipecat.tests.utils import run_test  # noqa: E402

BUNDLE = RUNTIME / "tenants" / "skincentrix"
# `run_test` waits this long for the pipeline to report started. Its default of 1.0 s is
# exceeded by a cold first run on this machine (QA gate A), so every call passes 10.0, as
# every other pipeline test in this repository does.
START_TIMEOUT = 10.0


class _FakeLLMService(FrameProcessor):
    """A Pipecat service that either answers with fixed text or fails, on demand.

    Deliberately a plain `FrameProcessor` and not an `LLMService`: the router must hold
    whatever `make_llm` returns without knowing anything about the vendor behind it, and no
    test here may reach a provider.
    """

    def __init__(self, name: str, reply: str | None = None, error: str | None = None):
        super().__init__(name=name)
        self.contexts: list[LLMContextFrame] = []
        self.functions: dict[str, object] = {}
        self._reply, self._error = reply, error

    def register_function(self, function_name, handler, **kwargs):
        self.functions[function_name] = handler

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            self.contexts.append(frame)
            await self.push_frame(LLMFullResponseStartFrame())
            if self._error is not None:
                await self.push_error(self._error)
            else:
                await self.push_frame(LLMTextFrame(self._reply or ""))
            await self.push_frame(LLMFullResponseEndFrame())
            return
        await self.push_frame(frame, direction)


def _context_frame():
    from pipecat.processors.aggregators.llm_context import LLMContext

    return LLMContextFrame(
        LLMContext(messages=[{"role": "user", "content": "how much is the express treatment?"}])
    )


def _router(primary, secondary, breaker=None, vendors=("google", "openai")):
    from spatalk.brain.breaker import VendorBreaker
    from spatalk.voice.llm_router import LLMRouter

    return LLMRouter(
        primary, secondary, breaker or VendorBreaker(monotonic=_FakeMonotonic()), vendors
    )


async def test_a_turn_the_primary_answers_never_reaches_the_secondary():
    primary = _FakeLLMService("primary", reply="The express treatment is $99.")
    secondary = _FakeLLMService("secondary", reply="never spoken")

    down, _ = await run_test(
        _router(primary, secondary),
        frames_to_send=[_context_frame()],
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        expected_up_frames=[],
        start_timeout=START_TIMEOUT,
    )
    assert [f.text for f in down if isinstance(f, LLMTextFrame)] == [
        "The express treatment is $99."
    ]
    assert len(primary.contexts) == 1 and secondary.contexts == []


async def test_the_secondary_answers_the_same_turn_and_nothing_downstream_hears_the_error():
    """The whole point: the caller waits one extra model call and then hears an answer."""
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(
        failures=3, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic()
    )
    primary = _FakeLLMService("primary", error="503 UNAVAILABLE: the model is overloaded")
    secondary = _FakeLLMService("secondary", reply="The express treatment is $99.")

    frame = _context_frame()
    down, up = await run_test(
        _router(primary, secondary, breaker),
        frames_to_send=[frame],
        expected_up_frames=[],
        start_timeout=START_TIMEOUT,
    )
    # The same context, exactly once, and only to the vendor that had not already failed it.
    assert [c.context for c in secondary.contexts] == [frame.context]
    assert len(primary.contexts) == 1
    assert [f.text for f in down if isinstance(f, LLMTextFrame)] == [
        "The express treatment is $99."
    ]
    assert not [f for f in up if isinstance(f, ErrorFrame)], "the caller must not hear about this"
    assert breaker.failure_count("google") == 1 and breaker.failure_count("openai") == 0


async def test_both_vendors_failing_surfaces_exactly_one_error_for_the_pipeline_to_answer():
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(
        failures=3, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic()
    )
    primary = _FakeLLMService("primary", error="google 503")
    secondary = _FakeLLMService("secondary", error="openai 500")

    down, up = await run_test(
        _router(primary, secondary, breaker),
        frames_to_send=[_context_frame()],
        expected_up_frames=[ErrorFrame],
        start_timeout=START_TIMEOUT,
    )
    assert "openai 500" in up[0].error
    assert breaker.failure_count("google") == 1 and breaker.failure_count("openai") == 1
    assert not [f for f in down if isinstance(f, LLMTextFrame)]


async def test_the_turn_after_a_failover_starts_at_the_secondary_while_the_breaker_is_open():
    """The cooling-off period on the phone: a dead vendor is not tried again every turn."""
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(
        failures=1, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic()
    )
    breaker.record_failure("google")
    primary = _FakeLLMService("primary", reply="the primary is back")
    secondary = _FakeLLMService("secondary", reply="the secondary answered")

    down, _ = await run_test(
        _router(primary, secondary, breaker),
        frames_to_send=[_context_frame()],
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        start_timeout=START_TIMEOUT,
    )
    assert [f.text for f in down if isinstance(f, LLMTextFrame)] == ["the secondary answered"]
    assert primary.contexts == []


async def test_an_answered_turn_clears_the_vendors_failure_count():
    from spatalk.brain.breaker import VendorBreaker

    breaker = VendorBreaker(
        failures=3, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic()
    )
    breaker.record_failure("google")
    await run_test(
        _router(
            _FakeLLMService("primary", reply="The express treatment is $99."),
            _FakeLLMService("secondary", reply="never spoken"),
            breaker,
        ),
        frames_to_send=[_context_frame()],
        start_timeout=START_TIMEOUT,
    )
    assert breaker.failure_count("google") == 0


async def test_a_frame_that_is_not_a_context_still_reaches_the_next_processor():
    """Everything the pipeline sends through the LLM's place has to behave as it did."""
    down, _ = await run_test(
        _router(_FakeLLMService("primary", reply="hi"), _FakeLLMService("secondary", reply="hi")),
        frames_to_send=[TTSSpeakFrame(text="Thanks, the team has it.")],
        expected_down_frames=[TTSSpeakFrame],
        start_timeout=START_TIMEOUT,
    )
    assert down[0].text == "Thanks, the team has it."


def test_tool_handlers_are_registered_on_both_services(fixed_clock):
    """A turn the secondary answers must be able to file an item; a model whose tool is not
    registered finds nothing there and the caller is promised something that never happens."""
    from spatalk.brain.tools import TOOL_NAMES
    from spatalk.voice.handlers import register_tool_handlers

    session, _ = _voice_session(fixed_clock)
    primary, secondary = _FakeLLMService("primary"), _FakeLLMService("secondary")
    register_tool_handlers(_router(primary, secondary), session)
    assert set(primary.functions) == set(TOOL_NAMES)
    assert set(secondary.functions) == set(TOOL_NAMES)


# --- make_llm and the pipeline stage ----------------------------------------------------


def test_make_llm_returns_a_pair_and_the_second_is_none_without_a_fallback():
    from pipecat.services.google.llm import GoogleLLMService

    from spatalk.voice.pipeline import make_llm

    primary, secondary = make_llm(_settings(google_api_key="k", llm_model="gemini-2.5-flash"))
    assert isinstance(primary, GoogleLLMService) and secondary is None


def test_make_llm_builds_the_second_vendors_service_when_the_fallback_is_set():
    from pipecat.services.google.llm import GoogleLLMService
    from pipecat.services.openai.llm import OpenAILLMService

    from spatalk.voice.pipeline import LLM_TEMPERATURE, make_llm

    primary, secondary = make_llm(
        _settings(
            google_api_key="k",
            openai_api_key="o",
            llm_model="gemini-2.5-flash",
            llm_model_fallback="openai:gpt-4.1-mini",
        )
    )
    assert isinstance(primary, GoogleLLMService)
    assert isinstance(secondary, OpenAILLMService)
    assert secondary._settings.model == "gpt-4.1-mini", "the prefix must not reach the provider"
    # One temperature for both vendors, so a failover changes the model and nothing else.
    assert secondary._settings.temperature == LLM_TEMPERATURE


def test_a_fallback_with_no_key_leaves_the_call_on_one_vendor_rather_than_failing_it():
    """A misconfigured optional feature must not take the phone line down."""
    from spatalk.voice.pipeline import make_llm

    primary, secondary = make_llm(
        _settings(
            google_api_key="k",
            llm_model="gemini-2.5-flash",
            llm_model_fallback="openai:gpt-4.1-mini",
        )
    )
    assert primary is not None and secondary is None


def test_make_llm_builds_a_compat_service_pointed_at_the_configured_host():
    from pipecat.services.openai.llm import OpenAILLMService

    from spatalk.voice.pipeline import make_llm

    primary, _ = make_llm(
        _settings(
            compat_api_key="k",
            llm_compat_base_url="http://localhost:11434/v1",
            llm_model="compat:qwen3-8b",
        )
    )
    assert isinstance(primary, OpenAILLMService)
    assert str(primary._client.base_url).rstrip("/") == "http://localhost:11434/v1"
    assert primary._settings.model == "qwen3-8b"


def test_selecting_a_vendor_without_its_key_still_fails_at_start_up_not_mid_call():
    from spatalk.voice.pipeline import make_llm

    with pytest.raises(ValueError) as e:
        make_llm(_settings(google_api_key="k", llm_model="groq:llama-3.3-70b-versatile"))
    assert "GROQ_API_KEY" in str(e.value)


def test_the_pipeline_has_no_router_at_all_when_no_fallback_is_configured():
    """With `LLM_MODEL_FALLBACK` empty the call is exactly the call it was yesterday."""
    from spatalk.voice.pipeline import llm_stage

    primary = _FakeLLMService("primary")
    assert llm_stage(primary, None, _settings(llm_model="gemini-2.5-flash")) is primary


def test_the_pipeline_puts_the_router_where_the_llm_was_when_a_fallback_exists():
    from spatalk.voice.llm_router import LLMRouter
    from spatalk.voice.pipeline import llm_stage

    stage = llm_stage(
        _FakeLLMService("primary"),
        _FakeLLMService("secondary"),
        _settings(llm_model="gemini-2.5-flash", llm_model_fallback="groq:llama-3.3-70b-versatile"),
    )
    assert isinstance(stage, LLMRouter)
    assert stage.vendors == ("google", "groq")


def test_run_call_builds_the_stage_and_registers_the_tools_on_it():
    """Source-level, because the alternative is a live websocket and a paid provider."""
    import inspect

    from spatalk.voice import pipeline as pipeline_module

    source = inspect.getsource(pipeline_module.run_call)
    assert "primary, secondary = make_llm(settings)" in source
    assert "llm_stage(primary, secondary, settings)" in source
    assert "register_tool_handlers(llm, session)" in source


# --- what the caller hears when both vendors are down -----------------------------------


def _voice_session(fixed_clock):
    import uuid

    from spatalk.brain.ports import MemoryLedger, MemorySms
    from spatalk.brain.requests import ConversationRef
    from spatalk.brain.tier_c import TierCCapabilities
    from spatalk.tenants.bundle import load_bundle
    from spatalk.voice.session import VoiceSession

    cfg = load_bundle(BUNDLE)
    session = VoiceSession(
        ref=ConversationRef(
            conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone="+19055550101"
        ),
        cfg=cfg,
        caps=TierCCapabilities(MemoryLedger(fixed_clock), MemorySms(), fixed_clock),
        clock=fixed_clock,
    )
    return session, cfg


def test_two_failed_turns_in_a_row_end_the_call_on_the_clinics_own_number(fixed_clock):
    """A loop of apologies is worse than an honest ending: the second failed turn hands the
    caller the number of a human being and hangs up."""
    from spatalk.brain.renderer import render_script
    from spatalk.voice.resilience import apology_for_error, error_frames

    session, cfg = _voice_session(fixed_clock)
    now = fixed_clock.now()

    first = apology_for_error(session, cfg, now, "503", at=100.0)
    assert first.text == render_script("model_unavailable", cfg, now, urgent=False)
    assert session.model_failures == 1 and session.ended is False

    # The next turn began: the model was asked again and failed again.
    session.model_turn_open = True
    frames = error_frames(session, cfg, now, "503 again", at=101.0)
    assert [type(f).__name__ for f in frames] == ["TTSSpeakFrame", "EndFrame"]
    assert frames[0].text == render_script("model_down", cfg, now, urgent=False)
    assert session.ended is True
    # And after the goodbye, nothing more is said.
    assert error_frames(session, cfg, now, "503 once more", at=102.0) == []


def test_a_turn_the_model_answered_in_between_resets_the_count(fixed_clock):
    from spatalk.brain.renderer import render_script
    from spatalk.voice.resilience import apology_for_error

    session, cfg = _voice_session(fixed_clock)
    now = fixed_clock.now()

    apology_for_error(session, cfg, now, "503", at=100.0)
    assert session.model_failures == 1
    # What the output guard does when the model actually answered a turn.
    session.model_failures = 0
    session.model_turn_open = True
    second = apology_for_error(session, cfg, now, "503 later", at=101.0)
    assert second.text == render_script("model_unavailable", cfg, now, urgent=False)
    assert session.ended is False


def test_a_burst_of_errors_inside_one_turn_is_still_one_apology(fixed_clock):
    """The SDK's retries and the aggregator's re-sends raise several errors for one turn."""
    from spatalk.voice.resilience import apology_for_error

    session, cfg = _voice_session(fixed_clock)
    now = fixed_clock.now()
    assert apology_for_error(session, cfg, now, "503", at=100.0) is not None
    assert apology_for_error(session, cfg, now, "503", at=100.5) is None
    assert apology_for_error(session, cfg, now, "503", at=101.0) is None
    assert session.model_failures == 1, "one turn failed, not three"


def test_the_error_frames_of_an_ordinary_apology_do_not_end_the_call(fixed_clock):
    from spatalk.voice.resilience import error_frames

    session, cfg = _voice_session(fixed_clock)
    frames = error_frames(session, cfg, fixed_clock.now(), "503", at=100.0)
    assert [type(f).__name__ for f in frames] == ["TTSSpeakFrame"]
    assert session.ended is False


async def test_the_output_guard_marks_a_new_turn_and_a_model_that_answered(fixed_clock):
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _voice_session(fixed_clock)
    session.model_failures = 1
    await run_test(
        OutputGuardProcessor(session),
        frames_to_send=[
            LLMFullResponseStartFrame(),
            LLMTextFrame("The express treatment is $99."),
            LLMFullResponseEndFrame(),
        ],
        expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame],
        start_timeout=START_TIMEOUT,
    )
    assert session.model_turn_open is True, "a fresh attempt began"
    assert session.model_failures == 0, "the model answered, so the run of failures is over"


async def test_a_turn_that_produced_no_words_does_not_clear_the_failure_count(fixed_clock):
    """A failed turn still pushes a start and an end frame around nothing at all: pipecat's
    `base_llm.process_frame` pushes the end frame in a `finally`. If that cleared the count,
    two dead turns in a row would never be recognised and the caller would loop forever."""
    from spatalk.voice.processors import OutputGuardProcessor

    session, _ = _voice_session(fixed_clock)
    session.model_failures = 1
    await run_test(
        OutputGuardProcessor(session),
        frames_to_send=[LLMFullResponseStartFrame(), LLMFullResponseEndFrame()],
        expected_down_frames=[LLMFullResponseStartFrame, LLMFullResponseEndFrame],
        start_timeout=START_TIMEOUT,
    )
    assert session.model_failures == 1


def test_the_model_down_line_is_config_gives_the_clinics_number_and_claims_nothing():
    from spatalk.tenants.bundle import load_bundle
    from spatalk.tenants.schema import Scripts

    cfg = load_bundle(BUNDLE)
    assert "{phone}" in Scripts.model_fields["model_down"].default
    rendered = cfg.scripts.model_down.format(phone=cfg.public_phone)
    assert cfg.public_phone and cfg.public_phone in rendered
    for claim in ("sent", "booked", "confirmed", "passed it", "filed"):
        assert claim not in cfg.scripts.model_down


def test_the_model_down_line_is_in_the_reference_and_in_the_bundle():
    import yaml

    doc = (REPO / "docs" / "reference" / "tenant-config.md").read_text(encoding="utf-8")
    assert "model_down:" in doc
    bundle = yaml.safe_load((BUNDLE / "scripts.yaml").read_text(encoding="utf-8"))
    assert "model_down" in bundle


# --- /healthz says which vendor is answering --------------------------------------------


def test_llm_health_reports_the_pair_the_active_vendor_and_no_deadline_when_all_is_well():
    from datetime import datetime, timezone

    from spatalk.brain.breaker import VendorBreaker, llm_health

    now = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
    breaker = VendorBreaker(
        failures=1, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic()
    )
    settings = _settings(llm_model="gemini-2.5-flash", llm_model_fallback="openai:gpt-4.1-mini")
    assert llm_health(settings, now, breaker) == {
        "primary": "google",
        "secondary": "openai",
        "active": "google",
        "breaker_open_until": None,
    }


def test_llm_health_names_the_vendor_now_answering_and_when_the_primary_is_tried_again():
    from datetime import datetime, timezone

    from spatalk.brain.breaker import VendorBreaker, llm_health

    now = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
    breaker = VendorBreaker(
        failures=1, window_secs=60, cooldown_secs=300, monotonic=_FakeMonotonic()
    )
    breaker.record_failure("google")
    health = llm_health(
        _settings(llm_model="gemini-2.5-flash", llm_model_fallback="openai:gpt-4.1-mini"),
        now,
        breaker,
    )
    assert health["active"] == "openai"
    assert health["breaker_open_until"] == "2026-09-03T20:05:00+00:00"


def test_llm_health_on_a_runtime_with_no_fallback_says_so():
    from datetime import datetime, timezone

    from spatalk.brain.breaker import VendorBreaker, llm_health

    health = llm_health(
        _settings(llm_model="gemini-2.5-flash"),
        datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc),
        VendorBreaker(monotonic=_FakeMonotonic()),
    )
    assert health["secondary"] is None and health["active"] == "google"


async def test_healthz_publishes_the_llm_block(sf, registry, fixed_clock):
    from httpx import ASGITransport, AsyncClient

    from spatalk import jobs
    from spatalk.http.app import create_app
    from spatalk.ledger.delivery import MemoryDelivery
    from spatalk.ledger.items import PgLedger

    ctx = jobs.JobContext(
        sf=sf,
        clock=fixed_clock,
        registry=registry,
        ledger=PgLedger(sf, fixed_clock),
        delivery=MemoryDelivery(),
        settings=_settings(secret_key="s", llm_model="gemini-2.5-flash"),
    )
    app = create_app(ctx, start_background=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/healthz")).json()
    assert body["llm"] == {
        "primary": "google",
        "secondary": None,
        "active": "google",
        "breaker_open_until": None,
    }


def test_the_reference_documents_the_healthz_llm_block():
    text = (REPO / "docs" / "reference" / "api-surface.md").read_text(encoding="utf-8")
    assert "breaker_open_until" in text
