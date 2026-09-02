"""One phone call, end to end, as a Pipecat 1.8 `PipelineWorker`.

`make_stt`, `make_tts` and `make_llm` are the provider swap points: nothing else in the
runtime names a voice vendor. Order of the pipeline matters and is the spec's:

    transport in -> STT -> rules gate -> user aggregator -> LLM
                 -> output guard -> TTS -> transport out -> assistant aggregator
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import WebSocket
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.telnyx import TelnyxFrameSerializer
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.turns.user_mute.mute_until_first_bot_complete_user_mute_strategy import (
    MuteUntilFirstBotCompleteUserMuteStrategy,
)
from pipecat.workers.runner import WorkerRunner

from spatalk.brain.capabilities import load_capabilities
from spatalk.brain.prompt import build_system_prompt
from spatalk.brain.renderer import render_script
from spatalk.brain.requests import ConversationRef
from spatalk.brain.tools import tools_schema
from spatalk.conversations import append_message, end_conversation, record_usage
from spatalk.text.textback import schedule_missed_call_textback
from spatalk.voice.handlers import register_tool_handlers
from spatalk.voice.observers import TurnLatencyObserver, UsageObserver
from spatalk.voice.processors import OutputGuardProcessor, RulesGateProcessor
from spatalk.voice.session import VoiceSession
from spatalk.voice.tokens import verify_stream_token


def make_stt(settings):
    if settings.stt_provider == "deepgram_flux":
        from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService

        return DeepgramFluxSTTService(api_key=settings.deepgram_api_key)
    from pipecat.services.soniox.stt import SonioxSTTService

    return SonioxSTTService(
        api_key=settings.soniox_api_key,
        settings=SonioxSTTService.Settings(model="stt-rt-v5"),
    )


def make_tts(settings):
    if settings.tts_provider == "deepgram_aura2":
        from pipecat.services.deepgram.tts import DeepgramTTSService

        return DeepgramTTSService(
            api_key=settings.deepgram_api_key,
            settings=DeepgramTTSService.Settings(voice="aura-2-thalia-en"),
        )
    from pipecat.services.inworld.tts import InworldTTSService

    return InworldTTSService(
        api_key=settings.inworld_api_key,
        settings=InworldTTSService.Settings(
            voice=settings.inworld_voice, model=settings.inworld_model
        ),
    )


def make_llm(settings):
    return GoogleLLMService(
        api_key=settings.google_api_key,
        settings=GoogleLLMService.Settings(
            model=settings.llm_model,
            temperature=0.3,
            thinking=GoogleLLMService.ThinkingConfig(thinking_budget=0),
        ),
    )


async def run_call(websocket: WebSocket, token: str, ctx) -> None:
    settings = ctx.settings
    claim = verify_stream_token(settings.secret_key, token)
    await websocket.accept()
    transport_type, call_data = await parse_telephony_websocket(websocket)
    if transport_type != "telnyx":
        logger.error("unexpected transport {}", transport_type)
        await websocket.close()
        return
    cfg = await ctx.registry.get(claim.tenant_id)
    serializer = TelnyxFrameSerializer(
        stream_id=call_data["stream_id"],
        call_control_id=call_data["call_id"],
        outbound_encoding=call_data.get("outbound_encoding") or "PCMU",
        inbound_encoding="PCMU",
        api_key=settings.telnyx_api_key,
    )
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )
    ref = ConversationRef(
        conversation_id=claim.conversation_id,
        tenant=cfg,
        channel="voice",
        caller_phone=claim.caller,
    )
    caps = load_capabilities(cfg, ctx.ledger, ctx.sms, ctx.clock)
    session = VoiceSession(
        ref=ref, cfg=cfg, caps=caps, clock=ctx.clock, started_at=datetime.now(timezone.utc)
    )

    now = ctx.clock.now()
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
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            RulesGateProcessor(session),
            user_agg,
            llm,
            OutputGuardProcessor(session),
            tts,
            transport.output(),
            assistant_agg,
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[UsageObserver(session), TurnLatencyObserver(session)],
        idle_timeout_secs=45,
        cancel_on_idle_timeout=False,
    )
    session.worker = worker
    register_tool_handlers(llm, session)
    runner = WorkerRunner(handle_sigint=False)
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

    @worker.event_handler("on_idle_timeout")
    async def on_idle(_worker):
        session.ended = True
        await worker.queue_frames(
            [TTSSpeakFrame(text=render_script("goodbye", cfg, now, urgent=False)), EndFrame()]
        )

    try:
        await runner.run()
    finally:
        await _finalize(ctx, session, context)


async def _finalize(ctx, session: VoiceSession, context: LLMContext) -> None:
    cid, tenant_id = session.ref.conversation_id, session.cfg.id
    # Whether the caller ever said anything: the missed-call decision below turns on it.
    had_user_speech = False
    for m in context.messages:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        if role not in ("user", "assistant") or content is None:
            continue
        text = (
            content
            if isinstance(content, str)
            else " ".join(
                (p.get("text", "") if isinstance(p, dict) else str(getattr(p, "text", "")))
                for p in content
            )
        )
        had_user_speech = had_user_speech or (role == "user" and bool(text.strip()))
        await append_message(ctx.sf, cid, role, text)
    seconds = (
        (datetime.now(timezone.utc) - session.started_at).total_seconds()
        if session.started_at
        else 0
    )
    await record_usage(ctx.sf, tenant_id, cid, "voice", "telnyx", "telephony_seconds", seconds)
    await record_usage(ctx.sf, tenant_id, cid, "voice", ctx.settings.stt_provider, "stt_seconds", seconds)
    await record_usage(
        ctx.sf, tenant_id, cid, "voice", ctx.settings.tts_provider, "tts_chars",
        session.usage["tts_chars"],
    )
    await record_usage(
        ctx.sf, tenant_id, cid, "voice", ctx.settings.llm_model, "llm_input_tokens",
        session.usage["llm_input_tokens"],
    )
    await record_usage(
        ctx.sf, tenant_id, cid, "voice", ctx.settings.llm_model, "llm_cached_tokens",
        session.usage["llm_cached_tokens"],
    )
    await record_usage(
        ctx.sf, tenant_id, cid, "voice", ctx.settings.llm_model, "llm_output_tokens",
        session.usage["llm_output_tokens"],
    )
    await end_conversation(
        ctx.sf, cid, band=session.band, latency_ms=session.latencies_ms,
        health_context=session.ref.health_context,
    )
    # Missed-call text-back (text-channels plan, Task B3). Last, so a caller who hung up
    # early is offered a text only after the call itself is fully recorded.
    await schedule_missed_call_textback(ctx, session, had_user_speech, seconds)
    if session.latencies_ms:
        s = sorted(session.latencies_ms)
        logger.info(
            "call {} turns={} p50={}ms p95={}ms guard_blocks={}",
            cid, len(s), s[len(s) // 2], s[min(len(s) - 1, int(len(s) * 0.95))], session.guard_blocks,
        )
