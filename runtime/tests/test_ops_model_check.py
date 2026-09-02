"""Operations plan, Task E6: a second LLM vendor, the weekly model check, the swap drill.

Spec §10 weakness 3 is model deprecation: the runtime's whole conversation runs on one
model at one vendor, and that vendor retires models on its own schedule. Three things make
that survivable and each one is tested here.

1. `LLM_MODEL` names the vendor as well as the model, so a swap is an environment change
   and not a code change: `gemini-2.5-flash` is Google, `openai:gpt-4.1-nano` is OpenAI, in
   voice (`make_llm` → a Pipecat service) and in text (`make_text_llm` → an `LLMClient`).
2. `OpenAIClient` speaks the same `LLMClient` protocol as `GeminiClient`, tool calls
   included, so nothing above the client knows which vendor answered.
3. `spatalk.ops.model_check` asks the provider what models it actually has and fails when
   the configured one is missing or marked deprecated — and never reports "fine" when it
   could not ask, because a check that passes on an empty answer is a green tick over
   nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"


def _settings(**kw):
    from spatalk.settings import Settings

    return Settings(_env_file=None, **kw)


# --- the model string names the vendor --------------------------------------------------


def test_a_bare_model_name_is_google():
    from spatalk.brain.driver import model_name, provider_for

    assert provider_for("gemini-2.5-flash") == "google"
    assert model_name("gemini-2.5-flash") == "gemini-2.5-flash"


def test_the_openai_prefix_selects_openai_and_is_stripped_from_the_model():
    from spatalk.brain.driver import model_name, provider_for

    assert provider_for("openai:gpt-4.1-nano") == "openai"
    assert model_name("openai:gpt-4.1-nano") == "gpt-4.1-nano"


def test_the_prefix_survives_the_shapes_a_dotenv_file_produces():
    """`LLM_MODEL = OpenAI: gpt-4.1-nano` in a .env is the same configuration."""
    from spatalk.brain.driver import model_name, provider_for

    for raw in ("OpenAI:gpt-4.1-nano", " openai: gpt-4.1-nano ", "OPENAI:gpt-4.1-nano"):
        assert provider_for(raw) == "openai", raw
        assert model_name(raw) == "gpt-4.1-nano", raw


def test_a_prefix_with_no_model_after_it_is_a_configuration_error():
    """`LLM_MODEL=openai:` must not quietly become somebody's default model."""
    from spatalk.brain.driver import model_name

    with pytest.raises(ValueError) as e:
        model_name("openai:")
    assert "LLM_MODEL" in str(e.value)


# --- voice: make_llm picks the class, with no network -----------------------------------


def test_make_llm_returns_the_google_service_for_a_bare_model():
    from pipecat.services.google.llm import GoogleLLMService

    from spatalk.voice.pipeline import make_llm

    llm = make_llm(_settings(google_api_key="k", llm_model="gemini-2.5-flash"))
    assert isinstance(llm, GoogleLLMService)


def test_make_llm_returns_the_openai_service_for_the_openai_prefix():
    from pipecat.services.openai.llm import OpenAILLMService

    from spatalk.voice.pipeline import make_llm

    llm = make_llm(_settings(openai_api_key="k", llm_model="openai:gpt-4.1-nano"))
    assert isinstance(llm, OpenAILLMService)
    # `_settings` is where Pipecat 1.8 keeps a configured service's model until the first
    # request; `get_full_model_name()` is empty before one and Google has no such method.
    assert llm._settings.model == "gpt-4.1-nano", "the prefix must not reach the provider"


def test_the_openai_voice_service_runs_at_the_same_temperature_as_google():
    from spatalk.voice.pipeline import LLM_TEMPERATURE, make_llm

    openai_llm = make_llm(_settings(openai_api_key="k", llm_model="openai:gpt-4.1-nano"))
    google_llm = make_llm(_settings(google_api_key="k", llm_model="gemini-2.5-flash"))
    assert openai_llm._settings.temperature == google_llm._settings.temperature
    assert openai_llm._settings.temperature == LLM_TEMPERATURE == 0.3


def test_selecting_openai_without_its_key_fails_at_start_up_not_mid_call():
    from spatalk.voice.pipeline import make_llm

    with pytest.raises(ValueError) as e:
        make_llm(_settings(google_api_key="k", llm_model="openai:gpt-4.1-nano"))
    assert "OPENAI_API_KEY" in str(e.value)


# --- text: the same environment variable swaps the text channels too --------------------


def test_make_text_llm_follows_the_same_prefix():
    from spatalk.brain.driver import GeminiClient, OpenAIClient
    from spatalk.text.service import make_text_llm

    google = make_text_llm(_settings(google_api_key="k", llm_model="gemini-2.5-flash"))
    assert isinstance(google, GeminiClient)
    openai_client = make_text_llm(_settings(openai_api_key="k", llm_model="openai:gpt-4.1-nano"))
    assert isinstance(openai_client, OpenAIClient)


def test_make_text_llm_is_none_when_the_selected_vendors_key_is_missing():
    """A Google key configured while LLM_MODEL names OpenAI is not an OpenAI client."""
    from spatalk.text.service import make_text_llm

    assert make_text_llm(_settings(google_api_key="k", llm_model="openai:gpt-4.1-nano")) is None
    assert make_text_llm(_settings(openai_api_key="k", llm_model="gemini-2.5-flash")) is None


def test_the_promptfoo_provider_follows_the_same_prefix(monkeypatch):
    """Step 3 of the swap drill runs the adversarial scenarios against the candidate. If
    the provider ignored the prefix it would grade the incumbent and report the swap safe."""
    import scenarios.provider as p
    from spatalk.brain.driver import GeminiClient, OpenAIClient

    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("LLM_MODEL", "openai:gpt-4.1-nano")
    assert isinstance(p._make_llm(), OpenAIClient)
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    assert isinstance(p._make_llm(), GeminiClient)


# --- OpenAIClient parses what the vendor actually sends back ----------------------------


def _completion(message: dict) -> object:
    """A recorded Chat Completions response, validated by the installed SDK's own model."""
    from openai.types.chat import ChatCompletion

    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-Bq3recorded",
            "object": "chat.completion",
            "created": 1756800000,
            "model": "gpt-4.1-nano-2025-04-14",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            "usage": {"prompt_tokens": 412, "completion_tokens": 19, "total_tokens": 431},
        }
    )


RECORDED_TOOL_CALL = {
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call_9xQk",
            "type": "function",
            "function": {
                "name": "escalate",
                "arguments": '{"reason": "human_request"}',
            },
        }
    ],
}


def test_the_openai_client_parses_a_recorded_tool_call():
    from spatalk.brain.driver import parse_chat_completion

    resp = parse_chat_completion(_completion(RECORDED_TOOL_CALL))
    assert resp.text is None
    assert [(tc.name, tc.arguments) for tc in resp.tool_calls] == [
        ("escalate", {"reason": "human_request"})
    ]


def test_the_openai_client_parses_a_recorded_plain_answer():
    from spatalk.brain.driver import parse_chat_completion

    resp = parse_chat_completion(
        _completion({"role": "assistant", "content": "The express treatment is $99."})
    )
    assert resp.text == "The express treatment is $99." and resp.tool_calls == []


def test_text_and_a_tool_call_in_one_answer_both_survive():
    from spatalk.brain.driver import parse_chat_completion

    message = dict(RECORDED_TOOL_CALL, content="One moment.")
    resp = parse_chat_completion(_completion(message))
    assert resp.text == "One moment."
    assert [tc.name for tc in resp.tool_calls] == ["escalate"]


def test_an_answer_with_no_content_at_all_is_none_not_an_empty_string():
    """`text=""` reads downstream as "the model said nothing worth guarding"; so does None,
    and only one of them is what the Gemini client returns. They must agree."""
    from spatalk.brain.driver import parse_chat_completion

    resp = parse_chat_completion(_completion({"role": "assistant", "content": "   "}))
    assert resp.text is None


def test_unparseable_tool_arguments_still_produce_the_call_with_no_arguments():
    """The same shape `GeminiClient` produces for absent args: the tool still runs and
    `dispatch_tool` rejects the missing fields honestly. Losing the call entirely would
    leave a voice caller with silence."""
    from spatalk.brain.driver import parse_chat_completion

    broken = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_bad",
                "type": "function",
                "function": {"name": "capture_request", "arguments": "{not json"},
            }
        ],
    }
    resp = parse_chat_completion(_completion(broken))
    assert [(tc.name, tc.arguments) for tc in resp.tool_calls] == [("capture_request", {})]


class _FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.kwargs: dict = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeCompletions(response)


def _tools():
    from spatalk.brain.tools import build_tools
    from spatalk.tenants.bundle import load_bundle

    return build_tools(load_bundle(RUNTIME / "tenants" / "skincentrix"))


async def test_the_request_carries_the_system_prompt_the_history_and_the_tools():
    from spatalk.brain.driver import OpenAIClient

    fake = _FakeClient(_completion({"role": "assistant", "content": "hi"}))
    client = OpenAIClient(api_key="k", model="gpt-4.1-nano", client=fake)
    await client.complete("SYSTEM", [{"role": "user", "content": "hello"}], _tools())
    sent = fake.chat.completions.kwargs
    assert sent["model"] == "gpt-4.1-nano" and sent["temperature"] == 0.3
    assert sent["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert sent["messages"][1] == {"role": "user", "content": "hello"}
    names = [t["function"]["name"] for t in sent["tools"]]
    assert "escalate" in names and all(t["type"] == "function" for t in sent["tools"])
    schema = next(t for t in sent["tools"] if t["function"]["name"] == "escalate")["function"]
    assert schema["parameters"]["type"] == "object" and "properties" in schema["parameters"]


async def test_a_history_turn_from_the_assistant_keeps_its_role():
    from spatalk.brain.driver import OpenAIClient

    fake = _FakeClient(_completion({"role": "assistant", "content": "hi"}))
    client = OpenAIClient(api_key="k", model="gpt-4.1-nano", client=fake)
    history = [
        {"role": "user", "content": "how much?"},
        {"role": "assistant", "content": "$99."},
        {"role": "user", "content": "thanks"},
    ]
    await client.complete("SYSTEM", history, _tools())
    assert [m["role"] for m in fake.chat.completions.kwargs["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


async def test_a_caller_with_no_tools_sends_no_tools_key_at_all():
    """The nightly audit's judge classifies and must not be able to act; OpenAI rejects an
    empty `tools` list outright, so the key has to be absent, not empty."""
    from spatalk.brain.driver import OpenAIClient

    fake = _FakeClient(_completion({"role": "assistant", "content": '{"band": 3}'}))
    client = OpenAIClient(api_key="k", model="gpt-4.1-nano", client=fake)
    await client.complete("SYSTEM", [{"role": "user", "content": "judge this"}], [])
    assert "tools" not in fake.chat.completions.kwargs


def test_the_openai_client_satisfies_the_llm_client_protocol():
    """Structurally, because `LLMClient` is a plain Protocol: the Brain calls `complete`
    with the same three arguments whichever vendor answered."""
    import inspect

    from spatalk.brain.driver import GeminiClient, LLMClient, OpenAIClient

    assert inspect.signature(OpenAIClient.complete) == inspect.signature(GeminiClient.complete)
    assert set(inspect.signature(LLMClient.complete).parameters) <= set(
        inspect.signature(OpenAIClient.complete).parameters
    )
    assert inspect.iscoroutinefunction(OpenAIClient.complete)


# --- the weekly model check -------------------------------------------------------------


def _models(*specs):
    """`"name"` or `("name", "description")`, as the provider's listing would give them."""
    from spatalk.ops.model_check import ModelInfo

    out = []
    for spec in specs:
        name, description = spec if isinstance(spec, tuple) else (spec, "")
        out.append(ModelInfo(name=name, description=description))
    return out


def test_a_configured_model_the_provider_lists_is_ok():
    from spatalk.ops.model_check import evaluate

    result = evaluate(_models("gemini-2.5-flash", "gemini-2.5-pro"), "gemini-2.5-flash")
    assert result.ok and result.model == "gemini-2.5-flash" and result.checked == 2


def test_googles_models_prefix_does_not_hide_the_model():
    from spatalk.ops.model_check import evaluate

    result = evaluate(_models("models/gemini-2.5-flash"), "gemini-2.5-flash")
    assert result.ok


def test_a_model_the_provider_no_longer_lists_fails_and_says_so():
    from spatalk.ops.model_check import evaluate

    result = evaluate(_models("gemini-3.0-flash"), "gemini-2.5-flash")
    assert not result.ok
    assert "gemini-2.5-flash" in result.reason and "not" in result.reason.lower()


def test_a_model_the_provider_marks_deprecated_fails_while_it_still_answers():
    """The whole point of the weekly check: catch the retirement before the call does."""
    from spatalk.ops.model_check import evaluate

    listed = _models(("gemini-2.5-flash", "Deprecated on 2026-11-01; use gemini-3.0-flash"))
    result = evaluate(listed, "gemini-2.5-flash")
    assert not result.ok and "deprecat" in result.reason.lower()


def test_no_longer_available_counts_as_deprecated():
    from spatalk.ops.model_check import evaluate

    listed = _models(("gemini-2.5-pro", "This model is no longer available to new users"))
    assert not evaluate(listed, "gemini-2.5-pro").ok


def test_an_empty_model_list_is_a_failure_not_a_pass():
    from spatalk.ops.model_check import evaluate

    result = evaluate([], "gemini-2.5-flash")
    assert not result.ok and result.checked == 0


def test_the_openai_prefix_is_stripped_before_the_names_are_compared():
    from spatalk.ops.model_check import evaluate

    assert evaluate(_models("gpt-4.1-nano"), "openai:gpt-4.1-nano").ok
    assert evaluate(_models("gpt-4.1-nano"), "openai:gpt-4o-mini").ok is False


async def test_the_check_reports_the_provider_it_asked():
    from spatalk.ops import model_check

    async def fake_list(settings, provider):
        assert provider == "openai"
        return _models("gpt-4.1-nano")

    result = await model_check.check_configured_model(
        _settings(openai_api_key="k", llm_model="openai:gpt-4.1-nano"), lister=fake_list
    )
    assert result.ok and result.provider == "openai"


async def test_a_provider_error_is_a_failure_that_names_the_error():
    from spatalk.ops import model_check

    async def boom(settings, provider):
        raise RuntimeError("503 upstream")

    result = await model_check.check_configured_model(
        _settings(google_api_key="k", llm_model="gemini-2.5-flash"), lister=boom
    )
    assert not result.ok and "503 upstream" in result.reason


async def test_with_no_key_nothing_is_checked_and_it_does_not_report_ok():
    from spatalk.ops import model_check

    result = await model_check.check_configured_model(
        _settings(llm_model="gemini-2.5-flash"), lister=None
    )
    assert not result.ok and result.checked == 0 and "GOOGLE_API_KEY" in result.reason


def test_main_exit_codes_separate_a_finding_from_an_unaskable_question(monkeypatch, capsys):
    """0 the model is there, 1 it is gone or deprecated, 2 the question could not be asked.
    A weekly job that cannot reach the provider must not be indistinguishable from a pass."""
    from spatalk.ops import model_check

    def run_with(models_or_error, model, **settings_kw):
        async def lister(settings, provider):
            if isinstance(models_or_error, Exception):
                raise models_or_error
            return models_or_error

        monkeypatch.setattr(model_check, "list_models", lister)
        return model_check.main(["--model", model], settings=_settings(**settings_kw))

    listed = _models("gpt-4.1-nano")
    assert run_with(listed, "openai:gpt-4.1-nano", openai_api_key="k") == 0
    assert run_with(_models("gpt-4o"), "openai:gpt-4.1-nano", openai_api_key="k") == 1
    assert run_with(RuntimeError("no network"), "openai:gpt-4.1-nano", openai_api_key="k") == 2
    assert run_with(listed, "openai:gpt-4.1-nano") == 2
    out = capsys.readouterr().out
    assert "gpt-4.1-nano" in out and "OPENAI_API_KEY" in out


# --- the dependency, the workflow and the runbook ---------------------------------------


def test_the_second_vendor_is_a_declared_dependency():
    """`openai:` in LLM_MODEL must not depend on a package that happens to be transitive."""
    text = (RUNTIME / "pyproject.toml").read_text(encoding="utf-8")
    assert '"openai>=' in text, "the openai SDK is not a declared runtime dependency"
    pipecat = next(line for line in text.splitlines() if "pipecat-ai[" in line)
    assert "openai" in pipecat.split("[", 1)[1].split("]", 1)[0]


def test_the_model_check_workflow_runs_weekly_and_never_looks_green_without_a_key():
    raw = (REPO / ".github" / "workflows" / "model-check.yml").read_text(encoding="utf-8")
    cfg = yaml.safe_load(raw)
    triggers = cfg.get("on", cfg.get(True))
    crons = [s["cron"] for s in triggers["schedule"]]
    assert crons and all(len(c.split()) == 5 for c in crons)
    assert any(c.split()[4] not in ("*", "?") for c in crons), "not a weekly schedule"
    assert "workflow_dispatch" in triggers
    job = next(iter(cfg["jobs"].values()))
    runs = [s for s in job["steps"] if "run" in s and "model_check" in s["run"]]
    assert runs, "the workflow never runs the check"
    assert all("if" in s for s in runs), "the check runs unguarded by a key"


def test_the_swap_runbook_documents_the_drill_the_rollback_and_this_machines_promptfoo():
    text = (REPO / "docs" / "runbooks" / "model-swap.md").read_text(encoding="utf-8")
    low = text.lower()
    for needle in ("openai:gpt-4.1-nano", "llm_model", "rollback", "promptfoo", "pytest"):
        assert needle in low, f"the runbook never mentions {needle}"
    assert "node@24" in text, "promptfoo's Node requirement on this machine is not recorded"


def test_the_environment_example_lists_the_second_vendors_key():
    """And with an empty value, not an inline comment (QA gate B, finding on .env.example)."""
    from dotenv import dotenv_values

    values = dotenv_values(RUNTIME / ".env.example")
    assert "OPENAI_API_KEY" in values
    assert (values["OPENAI_API_KEY"] or "") == ""
