import importlib

import pytest

MODULES = [
    "pipecat.pipeline.pipeline",
    "pipecat.pipeline.worker",
    "pipecat.workers.runner",
    "pipecat.processors.aggregators.llm_context",
    "pipecat.processors.aggregators.llm_response_universal",
    "pipecat.transports.websocket.fastapi",
    "pipecat.serializers.telnyx",
    "pipecat.runner.utils",
    "pipecat.services.soniox.stt",
    "pipecat.services.inworld.tts",
    "pipecat.services.google.llm",
    "pipecat.audio.vad.silero",
    "pipecat.audio.turn.smart_turn.local_smart_turn_v3",
    "pipecat.turns.user_mute.mute_until_first_bot_complete_user_mute_strategy",
    "pipecat.adapters.schemas.function_schema",
    "pipecat.adapters.schemas.tools_schema",
    "pipecat.frames.frames",
    "pipecat.tests.utils",
    "pipecat.observers.base_observer",
    "pipecat.metrics.metrics",
]


@pytest.mark.parametrize("module", MODULES)
def test_pipecat_module_imports(module):
    importlib.import_module(module)


def test_pipecat_symbols():
    from pipecat.frames.frames import (EndFrame, FunctionCallResultProperties, LLMRunFrame,
                                       LLMTextFrame, TTSSpeakFrame, TranscriptionFrame)
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair, LLMUserAggregatorParams)
    from pipecat.serializers.telnyx import TelnyxFrameSerializer
    from pipecat.services.google.llm import GoogleLLMService
    from pipecat.services.llm_service import FunctionCallParams
    from pipecat.workers.runner import WorkerRunner
    assert all([EndFrame, FunctionCallResultProperties, LLMRunFrame, LLMTextFrame, TTSSpeakFrame,
                TranscriptionFrame, PipelineParams, PipelineWorker, LLMContext,
                LLMContextAggregatorPair, LLMUserAggregatorParams, TelnyxFrameSerializer,
                GoogleLLMService, FunctionCallParams, WorkerRunner])
    assert hasattr(GoogleLLMService, "Settings") and hasattr(GoogleLLMService, "ThinkingConfig")
    # Task 13 relies on this exact class; if the name differs, list the module's classes and fix Task 13's import.
    from pipecat.turns.user_mute.mute_until_first_bot_complete_user_mute_strategy import (
        MuteUntilFirstBotCompleteUserMuteStrategy)
    assert MuteUntilFirstBotCompleteUserMuteStrategy


def test_settings_load(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash-lite")
    from spatalk.settings import Settings
    assert Settings(_env_file=None).llm_model == "gemini-2.5-flash-lite"
