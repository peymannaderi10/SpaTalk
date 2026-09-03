#!/usr/bin/env python
"""The voice pipeline behind Pipecat's eval transport (operations plan, Task E5).

    python scenarios/voice/eval_bot.py -t eval --port 7860

Production answers a Telnyx media stream inside FastAPI (`spatalk/voice/pipeline.py`); the
eval harness speaks RTVI over its own WebSocket and nothing else. This module is the second
transport for the same pipeline: the same `make_stt`, `make_llm` and `make_tts`, the same
rules gate and output guard in the same order, the same tenant prompt, scripts and tools.
If those diverge, the numbers the evals report stop being the numbers production produces.

Two deliberate differences, both because an eval is not a call:

* the ledger is in memory (`MemoryLedger`, `MemorySms`), so a scenario needs no database
  and files nothing into a real clinic's queue;
* there is no conversation row, no usage metering and no missed-call text-back, which are
  `_finalize`'s work and belong to a call that really happened.

The tenant is read from its bundle on disk, so this bot is as offline as a bot with three
provider keys can be.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RUNTIME))

from loguru import logger  # noqa: E402
from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa: E402
from pipecat.evals.transport import EvalTransportParams  # noqa: E402
from pipecat.frames.frames import TTSSpeakFrame  # noqa: E402
from pipecat.pipeline.pipeline import Pipeline  # noqa: E402
from pipecat.pipeline.worker import PipelineParams, PipelineWorker  # noqa: E402
from pipecat.processors.aggregators.llm_context import LLMContext  # noqa: E402
from pipecat.processors.aggregators.llm_response_universal import (  # noqa: E402
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frameworks.rtvi import RTVIObserver, RTVIProcessor  # noqa: E402
from pipecat.runner.utils import create_transport  # noqa: E402
from pipecat.turns.user_mute.mute_until_first_bot_complete_user_mute_strategy import (  # noqa: E402
    MuteUntilFirstBotCompleteUserMuteStrategy,
)
from pipecat.workers.runner import WorkerRunner  # noqa: E402

from spatalk.brain.ports import MemoryLedger, MemorySms  # noqa: E402
from spatalk.brain.prompt import build_system_prompt  # noqa: E402
from spatalk.brain.renderer import render_script  # noqa: E402
from spatalk.brain.requests import ConversationRef  # noqa: E402
from spatalk.brain.tier_c import TierCCapabilities  # noqa: E402
from spatalk.brain.tools import tools_schema  # noqa: E402
from spatalk.clock import SystemClock  # noqa: E402
from spatalk.settings import get_settings  # noqa: E402
from spatalk.tenants.bundle import load_bundle  # noqa: E402
from spatalk.voice.handlers import register_tool_handlers  # noqa: E402
from spatalk.voice.observers import TurnLatencyObserver, UsageObserver  # noqa: E402
from spatalk.voice.pipeline import make_llm, make_stt, make_tts  # noqa: E402
from spatalk.voice.processors import (  # noqa: E402
    FillerProcessor,
    OutputGuardProcessor,
    RulesGateProcessor,
)
from spatalk.voice.session import VoiceSession  # noqa: E402

# Which clinic the scenarios are written against. Overridable so a second tenant's wording
# can be evaluated without editing this file.
TENANT_BUNDLE = Path(os.environ.get("EVAL_TENANT_BUNDLE", RUNTIME / "tenants" / "skincentrix"))

# The caller the scenarios present as. Never a real number: nothing here texts anybody, but
# a bundle's own numbers are what the loop guard treats as one of ours.
EVAL_CALLER = "+15555550123"

transport_params = {
    "eval": lambda: EvalTransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


def build_session(cfg, clock) -> VoiceSession:
    """A voice session on memory ports: no database, no delivery, no real ledger."""
    ref = ConversationRef(
        conversation_id=uuid.uuid4(), tenant=cfg, channel="voice", caller_phone=EVAL_CALLER
    )
    caps = TierCCapabilities(ledger=MemoryLedger(clock), sms=MemorySms(), clock=clock)
    return VoiceSession(
        ref=ref, cfg=cfg, caps=caps, clock=clock, started_at=datetime.now(timezone.utc)
    )


async def bot(runner_args) -> None:
    """The entry point `pipecat.runner` calls with `-t eval`."""
    settings = get_settings()
    clock = SystemClock()
    cfg = load_bundle(TENANT_BUNDLE)
    session = build_session(cfg, clock)
    now = clock.now()

    transport = await create_transport(runner_args, transport_params)
    rtvi = RTVIProcessor(transport=transport)
    context = LLMContext(
        messages=[{"role": "system", "content": build_system_prompt(cfg, "voice", now)}],
        tools=tools_schema(cfg),
    )
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()],
        ),
    )
    stt, tts, llm = make_stt(settings), make_tts(settings), make_llm(settings)
    # The production order, with the RTVI processor added so the harness can hear what the
    # bot does: transport in -> STT -> rules gate -> user aggregator -> filler -> LLM
    #           -> output guard -> TTS -> transport out -> assistant aggregator
    pipeline = Pipeline(
        [
            transport.input(),
            rtvi,
            stt,
            RulesGateProcessor(session),
            user_agg,
            FillerProcessor(session),
            llm,
            OutputGuardProcessor(session),
            tts,
            transport.output(),
            assistant_agg,
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[RTVIObserver(rtvi), UsageObserver(session), TurnLatencyObserver(session)],
    )
    session.worker = worker
    register_tool_handlers(llm, session)
    runner = WorkerRunner(handle_sigint=getattr(runner_args, "handle_sigint", False))
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_connected(_transport, _client):
        await worker.queue_frames(
            [
                TTSSpeakFrame(
                    text=render_script("disclosure", cfg, now, urgent=False),
                    append_to_context=True,
                )
            ]
        )

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(_transport, _client):
        await runner.cancel()

    await runner.run()
    stages = {k: v for k, v in session.stage_ttfb_ms.items() if v}
    logger.info("eval call finished: turns={} stages={}", len(session.latencies_ms), stages)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
