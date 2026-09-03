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
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
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
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (
    MinWordsUserTurnStartStrategy,
)
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from spatalk.brain.audio_tags import strip_audio_tags
from spatalk.brain.capabilities import load_capabilities
# Operations plan, Task E6: the vendor a model string names.
from spatalk.brain.driver import OPENAI, gemini_thinking_kwargs, model_name, provider_for
from spatalk.brain.prompt import build_system_prompt
from spatalk.brain.renderer import render_script
from spatalk.brain.requests import ConversationRef
from spatalk.brain.tools import tools_schema
from spatalk.conversations import append_message, end_conversation, record_usage
# Operations plan, Task E5: the call's per-stage p95, written at the end of the call.
from spatalk.ops.latency import session_stage_ms
from spatalk.text.textback import schedule_missed_call_textback
from spatalk.voice.handlers import register_tool_handlers
from spatalk.voice.observers import TurnLatencyObserver, UsageObserver
from spatalk.voice.processors import FillerProcessor, OutputGuardProcessor, RulesGateProcessor
from spatalk.voice.session import VoiceSession
from spatalk.voice.tokens import verify_stream_token
# Operations plan, Task E10: live transfer to a staffed back-line, Option A (the leg the
# TeXML application created is transferred through the Call Control API by its id).
from spatalk.voice.transfer import make_transfer, transfer_available


# --- end of turn ------------------------------------------------------------------------
# Pipecat's default is Smart Turn v3 with a three-second fallback: when the model judges an
# utterance unfinished it waits up to 3 s of silence before handing over. Interrupted speech
# is usually fragmentary, so every barge-in cost the caller about three seconds (founder call
# 2026-09-03). The model stays, so a complete sentence still ends the turn at once; the wait
# for an unfinished one is capped at what a person tolerates.
TURN_END_FALLBACK_SECS = 1.0
TURN_PRE_SPEECH_MS = 300
# While the assistant is talking, a caller has to say this many words before it yields.
# Pipecat's default yields on 200 ms of any sound, so a "mm-hm", a cough or a word of
# agreement cut every answer short (founder call 2026-09-03). When the assistant is silent
# a single word still starts the turn, so nothing gets slower.
INTERRUPT_MIN_WORDS = 3


def user_turn_params() -> LLMUserAggregatorParams:
    """How the pipeline decides the caller has finished speaking, and when it may listen."""
    analyzer = LocalSmartTurnAnalyzerV3(
        params=SmartTurnParams(stop_secs=TURN_END_FALLBACK_SECS, pre_speech_ms=TURN_PRE_SPEECH_MS)
    )
    return LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(),
        user_turn_strategies=UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=INTERRUPT_MIN_WORDS, use_interim=True)],
            stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=analyzer)],
        ),
        # The disclosure cannot be talked over: the caller must hear that this is an AI.
        user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()],
    )


def make_stt(settings):
    if settings.stt_provider == "deepgram_flux":
        from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService

        # Deepgram trains on audio unless told not to; the runbook promises we tell it.
        return DeepgramFluxSTTService(api_key=settings.deepgram_api_key, mip_opt_out=True)
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
    if settings.tts_provider == "soniox":
        # Single-vendor speech (founder decision 2026-09-02): the same Soniox key drives
        # both stages. tts-rt-v2 is Soniox's real-time model; the voice is an env choice.
        from pipecat.services.soniox.tts import SonioxTTSService, SonioxTTSSettings

        return SonioxTTSService(
            api_key=settings.soniox_api_key,
            settings=SonioxTTSSettings(model="tts-rt-v2", voice=settings.soniox_voice),
        )
    from pipecat.services.inworld.tts import InworldTTSService

    return InworldTTSService(
        api_key=settings.inworld_api_key,
        settings=InworldTTSService.Settings(
            voice=settings.inworld_voice, model=settings.inworld_model
        ),
    )


# --- second LLM vendor (operations plan, Task E6) ----------------------------------------
# One temperature for both vendors, so a swap drill compares models and not settings.
LLM_TEMPERATURE = 0.3


def make_llm(settings):
    """The conversational LLM for a call. `LLM_MODEL` names the vendor as well as the model.

    A bare name is Google; `openai:<model>` is OpenAI (spec §10 weakness 3: the swap has to
    be an environment change, because the vendor decides when the model retires).
    """
    if provider_for(settings.llm_model) == OPENAI:
        from pipecat.services.openai.llm import OpenAILLMService

        key = getattr(settings, "openai_api_key", "")
        if not key:
            # The alternative is a service that constructs cleanly and 401s on the first
            # turn of a real call, which is the worst moment to find out.
            raise ValueError(
                f"LLM_MODEL={settings.llm_model!r} selects OpenAI but OPENAI_API_KEY is not set"
            )
        return OpenAILLMService(
            api_key=key,
            settings=OpenAILLMService.Settings(
                model=model_name(settings.llm_model),
                temperature=LLM_TEMPERATURE,
            ),
        )
    return GoogleLLMService(
        api_key=settings.google_api_key,
        settings=GoogleLLMService.Settings(
            model=settings.llm_model,
            temperature=LLM_TEMPERATURE,
            thinking=GoogleLLMService.ThinkingConfig(
                **gemini_thinking_kwargs(settings.llm_model, 0)
            ),
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
    # Held rather than defaulted so a successful transfer can switch `auto_hang_up` off on
    # this exact object (operations plan, Task E10); the serializer keeps the instance.
    serializer_params = TelnyxFrameSerializer.InputParams()
    serializer = TelnyxFrameSerializer(
        stream_id=call_data["stream_id"],
        call_control_id=call_data["call_id"],
        outbound_encoding=call_data.get("outbound_encoding") or "PCMU",
        inbound_encoding="PCMU",
        api_key=settings.telnyx_api_key,
        params=serializer_params,
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
    now = ctx.clock.now()
    # --- live transfer (operations plan, Task E10) ---
    # Decided once, here, for this call: the model is offered `transfer_to_human` only when
    # the tenant has a staffed back-line and the clinic is open at this moment. The leg id
    # is the one Telnyx put in the stream start message, which is also what the serializer
    # uses to hang up, so both halves of the call agree on which call this is.
    can_transfer = transfer_available(cfg, now)
    session = VoiceSession(
        ref=ref,
        cfg=cfg,
        caps=caps,
        clock=ctx.clock,
        started_at=datetime.now(timezone.utc),
        call_control_id=call_data["call_id"],
        transfer=make_transfer(settings) if can_transfer else None,
        transfer_enabled=can_transfer,
        hangup_params=serializer_params,
    )

    context = LLMContext(
        messages=[{"role": "system", "content": build_system_prompt(cfg, "voice", now)}],
        tools=tools_schema(cfg, transfer_enabled=can_transfer),
    )
    user_agg, assistant_agg = LLMContextAggregatorPair(context, user_params=user_turn_params())
    stt, tts, llm = make_stt(settings), make_tts(settings), make_llm(settings)
    pipeline = Pipeline(
        [
            transport.input(),
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
        # Delivery tags were for the voice, not the record (spatalk.brain.audio_tags).
        await append_message(ctx.sf, cid, role, strip_audio_tags(text) if role == "assistant" else text)
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
        # Operations plan, Task E5: the call's own per-stage p95, stored by the call rather
        # than recomputed later, because retention takes the transcript long before this.
        stage_ms=session_stage_ms(session) or None,
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
