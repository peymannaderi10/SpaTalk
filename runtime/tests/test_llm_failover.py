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
