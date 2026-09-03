"""Thinking configuration per Gemini generation (founder call 2026-09-03).

The runtime was built against Gemini 2.5 Flash, which takes ``thinking_budget=0`` to answer
without a hidden reasoning step. The founder's paid project serves the 3.x generation and the
``-latest`` aliases, which reject that field with ``400 INVALID_ARGUMENT`` and want
``thinking_level`` instead. Every model call went 400 and the caller heard silence after the
greeting. One helper decides the right field for the model in play; voice and text share it.
"""


def test_a_2_5_model_keeps_the_budget_field():
    from spatalk.brain.driver import gemini_thinking_kwargs

    assert gemini_thinking_kwargs("gemini-2.5-flash", 0) == {"thinking_budget": 0}
    assert gemini_thinking_kwargs("gemini-2.5-flash-lite", 0) == {"thinking_budget": 0}
    # The nightly audit's judge asks for unbounded reasoning.
    assert gemini_thinking_kwargs("gemini-2.5-flash", -1) == {"thinking_budget": -1}


def test_newer_models_and_aliases_get_a_thinking_level():
    from spatalk.brain.driver import gemini_thinking_kwargs

    for model in ("gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.5-flash-lite",
                  "gemini-3-flash-preview", "gemini-3.8-flash"):
        assert gemini_thinking_kwargs(model, 0) == {"thinking_level": "minimal"}, model
    assert gemini_thinking_kwargs("gemini-3.5-flash", -1) == {"thinking_level": "high"}
    assert gemini_thinking_kwargs("gemini-3.5-flash", 2048) == {"thinking_level": "medium"}


def test_the_voice_llm_carries_the_right_thinking_field_for_its_model():
    from spatalk.settings import Settings
    from spatalk.voice.pipeline import make_llm

    lite = make_llm(Settings(_env_file=None, secret_key="s", google_api_key="k", llm_model="gemini-flash-lite-latest"))
    assert lite._settings.thinking.thinking_level == "minimal"
    assert lite._settings.thinking.thinking_budget is None

    legacy = make_llm(Settings(_env_file=None, secret_key="s", google_api_key="k", llm_model="gemini-2.5-flash"))
    assert legacy._settings.thinking.thinking_budget == 0
    assert legacy._settings.thinking.thinking_level is None
