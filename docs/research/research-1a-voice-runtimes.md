# Research 1a: Open-source voice agent runtimes (as of 2026-09-01)

All facts come from the URLs under "Sources actually fetched"; unverified items are marked UNVERIFIED.

## Comparison table

| | Dograh | Pipecat | LiveKit Agents |
|---|---|---|---|
| What it is | Full platform (Next.js UI + FastAPI + DB) on a vendored Pipecat submodule; "self-hosted alternative to Vapi & Retell" | Python pipeline framework | Python/Node agent SDK; agent joins a LiveKit WebRTC room |
| Licence | BSD-2-Clause (Zansat Technologies) | BSD-2-Clause | Apache-2.0; turn-detector model is "LiveKit Model License" (not permissive) |
| Version / activity | 1.45.0 (2026-08-11); pushed 2026-09-01; 5,553 stars; 73 contributors, top 2 = ~90% of commits | 1.8.1 (2026-08-27); pushed 2026-09-01; 15,104 stars | 1.7.1 (2026-08-27); pushed 2026-09-01; 13,946 stars |
| Telephony without a SIP server | Twilio, Telnyx, Plivo, Vonage, Vobiz (WS); also Cloudonix SIP, Asterisk ARI | WS serializers: Twilio, Telnyx, Plivo, Exotel, Genesys, Vonage; SIP only via Daily or LiveKit transports | No; SIP only, via LiveKit SIP service (Cloud or self-hosted) |
| Self-host moving parts | Postgres (pgvector/pg17), Redis 7, MinIO, api, ui, nginx, coturn; ARQ workers, Helm/KEDA | One Python process per bot; no DB/broker required | LiveKit server + SIP server + Redis + agent worker + TURN/TLS |
| Documented footprint | UNVERIFIED | Not in docs; Cerebrium example: "~0.5 CPUs" per process, 10 CPU / 8 GB = 20 calls | Turn-detector < 500 MB RAM; server "bound by CPU and bandwidth" |
| Tool calling | Workflow-node tools, HTTP tools, MCP | Direct functions or FunctionSchema; provider-agnostic; parallel/async/cancel options | `@function_tool`, RunContext, toolsets, native MCP |
| Structured states | Visual workflow (start/agent/tools/transitions/end) | Flows in core: NodeConfig with per-node task_messages + functions | Agent handoffs; no node graph |
| Per-session metrics | UNVERIFIED | TTFB, TTFA, TTFAT, LLM tokens, TTS chars; observers, OpenTelemetry, Sentry | STT/LLM(ttft)/TTS(ttfb)/EOU/VAD metrics; `session.usage` |
| Turn detection | Inherits Pipecat | Silero VAD; Smart Turn v3.2 (BSD-2, 8 MB, 10-100 ms CPU); Deepgram Flux native EOT | Silero VAD + LiveKit turn-detector (restricted licence) |
| Tenant/config model | Opinionated: orgs, telephony configs, number->Inbound workflow, campaigns, JWT | None | None (rooms, trunks, dispatch rules) |

## Per-candidate notes

### 1. Dograh
- Built on Pipecat: repo carries a `pipecat` git submodule. Licence BSD-2-Clause, copyright "Zansat Technologies Private Limited"; repo created 2025-09-09.
- Orientation: visual workflow builder plus outbound **campaigns** (CSV upload, start/pause/resume APIs) and inbound. Inbound: "Dograh resolves the org from the webhook's account credentials and the agent from the called number's Inbound workflow assignment"; Telnyx and Twilio have integration pages. "Dograh does not sell phone numbers or minutes."
- Multi-tenant: an **org** concept exists ("multiple configurations ... per org"; "Provision SIP endpoints as part of org bootstrap"), but docs have no multi-tenancy/teams pages; README's "enterprise multi-tenant" claim is otherwise UNVERIFIED.
- Activity: 802 commits, last 2026-09-01; a6kme (487) and chewwbaka (201) dominate 73 contributors.
- Adds over Pipecat: UI, workflow schema, telephony credential store, campaigns, dispositions, Python/Node SDKs, Helm chart with KEDA autoscaling, PostHog telemetry on by default. Locks you into its Postgres schema, "Workflow Definition Schema", JWT auth (`OSS_JWT_SECRET`), UI, and a pinned Pipecat submodule.

### 2. Pipecat
- BSD-2-Clause; v1.8.1 (2026-08-27); Python >= 3.11.
- Telephony: `FastAPIWebsocketTransport` + serializers. `TwilioFrameSerializer` (8 kHz mu-law, `auto_hang_up` via call_sid/account_sid/auth_token). `TelnyxFrameSerializer` (PCMU or PCMA, 8 kHz, `call_control_id` + API key for hang-up, DTMF -> `InputDTMFFrame`). `parse_telephony_websocket()` extracts stream_id/call_control_id/from/to. SIP via Daily (`provider="daily"`, metered) or LiveKit transport; docs position WebSocket for "simple telephony workflows", SIP for transfers/multi-party.
- Services (all listed): STT AssemblyAI, Deepgram (+ `DeepgramFluxSTTService`, which "defines turn boundaries directly"), Gladia, Soniox, Speechmatics, Azure, Google, OpenAI, Groq; TTS Cartesia, ElevenLabs, Deepgram, Inworld, Rime, Azure, Google, OpenAI, Groq; LLM OpenAI, Anthropic, Gemini, Groq, Cerebras, Azure, Ollama, OpenRouter and ~20 more. `LLMSwitcher` keeps one tool set across providers.
- Tool calling: "The preferred way to define a tool is with a direct function"; `FunctionSchema`/`ToolsSchema` for strict schemas; `FunctionCallParams` with `result_callback`; `run_in_parallel` (default True); `@tool_options(cancel_on_interruption=False)` for async tools.
- Flows: in core since v1.5.0 (standalone repo archived 2026-07-05). `FlowManager` + `NodeConfig` (role_messages, task_messages, functions, pre/post_actions, respond_immediately); static or dynamic. Flows "manages context and tools as it moves from one state to the next"; "each node should focus on a single task with only the tools it needs". Per-node tool scoping; transitions are still LLM function calls, not a hard state machine.
- Metrics: `enable_metrics`/`enable_usage_metrics`; TTFB, TTFA (TTS), TTFAT (LLM), processing time, LLM tokens, TTS characters; `MetricsFrame`, `MetricsLogObserver`, `UserBotLatencyObserver`, `TurnTrackingObserver`; OpenTelemetry and Sentry.
- Turn detection: Silero VAD; Smart Turn v3.2 (~8M params, BSD-2, "as little as 10ms on some CPUs, under 100ms on most cloud instances", `LocalSmartTurnAnalyzerV3`); Krisp VIVA; Deepgram Flux.
- Footprint: deployment docs give no numbers ("A Pipecat bot is a Python process"). Only third-party data: Cerebrium's Twilio example, "Each process uses ~0.5 CPUs", "10 CPU instance handles 20 concurrent calls", 8 GB.

### 3. LiveKit Agents
- Apache-2.0; 1.7.1 (2026-08-27); Python 3.10-3.14. Turn-detector: "LiveKit Model License", CPU ONNX, < 500 MB; docs recommend compute-optimized instances.
- Telephony only via LiveKit SIP (trunks + dispatch rules; tested with Twilio, Telnyx, Exotel, Plivo). Self-hosting: LiveKit server (7880/7881, UDP 50000-60000, TURN 5349/443, domain + TLS cert, Redis "recommended" for multi-node) plus separate SIP server (Redis required, 5060 + RTP 10000-20000 public) plus agent worker.
- Tools: `@function_tool`, RunContext, toolsets, RPC to frontend, native MCP; provider tools for OpenAI/Gemini/Anthropic.
- Plugins: STT Deepgram, AssemblyAI, Speechmatics, Gladia, Soniox, Azure, Google, OpenAI, Groq; TTS Cartesia, ElevenLabs, Deepgram, Inworld, Rime, Azure, Google, OpenAI, Groq; LLM OpenAI, Anthropic, Gemini, Groq, Cerebras, Azure, Bedrock, Ollama, Fireworks, Together. "LiveKit Inference" is Cloud-only.
- Metrics: STTMetrics, LLMMetrics (ttft), TTSMetrics (ttfb), EOUMetrics (end_of_utterance_delay, transcription_delay), VADMetrics; `session.usage` (UsageCollector deprecated).
- Cloud pricing: Build $0 (1,000 agent min, 1,000 SIP min, **5 concurrent agent sessions**); Ship $50/mo (5,000 min, **20 concurrent**, $0.01/min overage, US inbound SIP $0.01/min); Scale $500/mo (50,000 min, "Up to 600 (Starts at 50)"); third-party SIP $0.004/min. Plan fees are the monthly minimums.

### 4. Others
- **Vocode** (MIT, 3.8k stars): last commit 2024-11-15; effectively unmaintained.
- **Bolna** (MIT, 746 stars): active (2026-09-01), Twilio + Plivo, Redis-backed, config-driven agents via LiteLLM. Small community; own config model.
- **TEN Framework** (11.1k stars): core is Apache-2.0 "with additional restrictions"; C++/Go/Python graph runtime; SIP/Twilio example. Heavy; licence not cleanly permissive.
- **Flowcat** (Apache-2.0, 110 stars, pre-1.0): new 2026 Rust runtime, "pipecat-compatible" FrameProcessor model, in-process SIP/RTP plus Twilio/Telnyx/Plivo WS serializers, ~19.6 KB idle/session. Too immature for an MVP.
- **OpenAI Agents SDK** (MIT): `VoicePipeline`, no telephony transport. **Deepgram** ships only example bridges to its proprietary Voice Agent API. **Twilio ConversationRelay**: proprietary service (UNVERIFIED beyond search snippets).

### Telnyx / Twilio direct WebSocket check
- **Telnyx**: yes. `"stream_bidirectional_mode":"rtp"` on dial/answer/streaming_start with a `wss://` `stream_url`; codecs PCMU/PCMA/G722/OPUS/AMR-WB/L16; no SIP server. TeXML inbound: `<Connect><Stream url="wss://..." bidirectionalMode="rtp"/></Connect>`. Pipecat serializer supports PCMU/PCMA (L16 UNVERIFIED).
- **Twilio**: yes, via TwiML `<Connect><Stream>` (the REST Stream resource cannot start bidirectional). `audio/x-mulaw` 8000 Hz base64; server sends `media`/`mark`/`clear`. Pipecat has `TwilioFrameSerializer`.

## Sources actually fetched
https://github.com/dograh-hq/dograh
https://api.github.com/repos/dograh-hq/dograh
https://api.github.com/repos/dograh-hq/dograh/contributors?per_page=100
https://github.com/dograh-hq/dograh/commits/main
https://raw.githubusercontent.com/dograh-hq/dograh/main/docker-compose.yaml
https://raw.githubusercontent.com/dograh-hq/dograh/main/LICENSE
https://raw.githubusercontent.com/dograh-hq/dograh/main/README.md
https://github.com/dograh-hq/dograh/blob/main/CHANGELOG.md
https://docs.dograh.com/
https://docs.dograh.com/llms.txt
https://docs.dograh.com/integrations/telephony/overview
https://github.com/pipecat-ai/pipecat
https://api.github.com/repos/pipecat-ai/pipecat
https://pypi.org/project/pipecat-ai/
https://github.com/pipecat-ai/pipecat/releases
https://docs.pipecat.ai/server/services/supported-services
https://docs.pipecat.ai/guides/learn/function-calling
https://docs.pipecat.ai/guides/features/pipecat-flows
https://docs.pipecat.ai/pipecat-flows/guides/nodes-and-messages
https://reference-flows.pipecat.ai/en/latest/api/pipecat_flows.types.html
https://github.com/pipecat-ai/pipecat-flows
https://docs.pipecat.ai/guides/fundamentals/metrics
https://github.com/pipecat-ai/smart-turn
https://docs.pipecat.ai/server/services/transport/fastapi-websocket
https://docs.pipecat.ai/server/services/serializers/telnyx
https://docs.pipecat.ai/server/services/serializers/twilio
https://docs.pipecat.ai/guides/telephony/telnyx-websockets
https://reference-server.pipecat.ai/en/latest/api/pipecat.services.deepgram.flux.stt.html
https://docs.pipecat.ai/pipecat/deployment/overview
https://github.com/pipecat-ai/pipecat/issues/3987
https://cerebrium.ai/docs/v4/examples/twilio-voice-agent
https://github.com/livekit/agents
https://api.github.com/repos/livekit/agents
https://pypi.org/project/livekit-agents/
https://github.com/livekit/agents/releases
https://docs.livekit.io/sip/
https://docs.livekit.io/home/self-hosting/sip-server/
https://docs.livekit.io/home/self-hosting/deployment/
https://docs.livekit.io/agents/build/tools/
https://docs.livekit.io/agents/ops/logging/
https://docs.livekit.io/agents/models/
https://docs.livekit.io/agents/models/stt/
https://docs.livekit.io/agents/models/tts/
https://docs.livekit.io/agents/models/llm/
https://huggingface.co/livekit/turn-detector
https://livekit.com/pricing
https://livekit.com/pricing.md
https://developers.telnyx.com/docs/voice/programmable-voice/media-streaming
https://www.twilio.com/docs/voice/media-streams
https://www.twilio.com/docs/voice/media-streams/websocket-messages
https://github.com/vocodedev/vocode-core
https://github.com/vocodedev/vocode-core/commits/main
https://github.com/bolna-ai/bolna
https://github.com/bolna-ai/bolna/commits/master
https://github.com/TEN-framework/ten-framework
https://github.com/AreevAI/flowcat
https://github.com/openai/openai-agents-python
https://techsy.io/en/blog/best-open-source-voice-agent-frameworks
Not fetchable (404/403): docs.pipecat.ai function-calling, smart-turn-overview, deepgram-flux pages; HackerNoon Dograh article.

## Recommendation for this use case
Build directly on **Pipecat** (BSD-2, v1.8.1, most active of the three) with `FastAPIWebsocketTransport` + `TelnyxFrameSerializer`, keeping `TwilioFrameSerializer` as the config-swappable alternative. It alone meets every constraint: Telnyx and Twilio both stream bidirectional audio straight to your WSS endpoint with no SIP server, so the MVP is one Python process per call on one VPS (Cerebrium's ~0.5 CPU/call implies 3 calls on 2 vCPU and 25 calls on ~12-16 vCPU at month 18); every metered provider is a one-line service swap behind the same tool schema; tool calling is deterministic enough (per-node tool scoping via Flows, strict `FunctionSchema`, parallel/async control); and per-service TTFB/usage metrics ship in the box. Use Silero + Smart Turn v3 (BSD-2, CPU) or Deepgram Flux for endpointing; both are permissively licensed, unlike LiveKit's turn-detector. Tenancy stays in your own layer because Pipecat imposes no DB, config, or UI model. **LiveKit Agents** is a strong runtime, but its telephony path requires the SIP service: self-hosting means LiveKit server + SIP + Redis + TURN + TLS on a "cheap VPS", while LiveKit Cloud caps you at 20 concurrent for $50/mo (50+ only at $500/mo) and reintroduces a metered vendor you cannot swap by config. **Dograh** fits only if you want its UI, campaigns, and org/telephony-config model as-is; it hands you a Postgres schema, workflow schema, JWT auth, a pinned Pipecat submodule and a two-person bus factor, conflicting with the "no opinionated tenant/config model" requirement. Mine it for patterns (inbound org resolution, credential store, KEDA scaling) rather than adopting it. Revisit **Flowcat** in 6-12 months if Python per-call overhead bites.
