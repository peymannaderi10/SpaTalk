# Voice-AI provider pricing — fetched 2026-09-01

USD unless noted. CAD assumes 1 USD = 1.37 CAD (my assumption). Target $0.030 CAD ≈ $0.022 USD/call-min; ceiling $0.040 CAD ≈ $0.029 USD. "n/s" = not stated on the fetched page. "UNVERIFIED" = primary page unfetchable/blank; number from secondary source or recollection.

## A. Telephony (inbound, Canadian local number)

| Provider | Product | Price | Unit | Floors | Concurrency caps | Data policy | Region / PoPs | Source |
|---|---|---|---|---|---|---|---|---|
| Telnyx | Call Control (Voice API) | $0.002 API fee + SIP inbound "starting at $0.0032" (≈$0.0052; a secondary cites $0.0075 for CA DIDs); WebSocket media streaming +$0.0035; recording +$0.002; local number "from $1"/mo | /min | none (PAYG) | none on Call Control | n/s | Canadian PoPs: Toronto, Montreal anchorsite (Mar 9 2026), Vancouver | telnyx.com/pricing/call-control; /pricing/numbers; /release-notes/montreal-canada-anchorsite |
| Telnyx | Elastic SIP Trunking (vs Call Control) | inbound local "from $0.0032", outbound $0.005, TF inbound $0.015; channels $12/mo (first 10); recording $0.002 | /min | none | concurrency = channels bought | n/s | same | telnyx.com/pricing/elastic-sip |
| Twilio | Programmable Voice CA | inbound local $0.0085; Media Streams +$0.0044; recording +$0.0025 (+$0.0005/min/mo storage); local $1.15/mo, TF $2.15/mo | /min | none | none stated | n/s | No Canadian edge (ashburn, umatilla, dublin, frankfurt, tokyo, singapore, sydney, sao-paulo) | twilio.com/en-us/voice/pricing/ca; twilio.com/docs/global-infrastructure/edge-locations |
| SignalWire | Voice | PSTN 10DLC inbound $0.0066, outbound $0.0080, SIP/WebRTC $0.0030; stream/tap $0.003, recording $0.002, local $0.50/mo, TF $0.80/mo (search snippets of signalwire.com/pricing) | /min | none stated | n/s | n/s | CA numbers/PoPs n/s | signalwire.com/pricing/voice; signalwire.com/pricing |
| Vonage | Voice API | UNVERIFIED (HTTP 403 on .com/.co.uk). Recollection: CA inbound ≈$0.0049/min, number ≈$0.90–1/mo, WebSocket ≈+$0.004/min | /min | | | | | vonage.com/communications-apis/voice/pricing/ (403) |
| Plivo | Voice CA | inbound local $0.0075; outbound $0.012; audio streaming + noise-cancel "Included"; recording $0.0000; local $0.75/mo, TF $1.00/mo | /min | none stated | n/s | n/s | CA numbers yes; PoPs n/s | plivo.com/voice/pricing/ca/ |

## B. Streaming STT

| Provider | Model | Price | Unit | Floors / free credit | Concurrency | Training / data policy | Region | Source |
|---|---|---|---|---|---|---|---|---|
| Deepgram | Nova-3 streaming | $0.0048 mono / $0.0058 multi (promo; regular $0.0077 / $0.0092) | /min | PAYG; $200 free | WSS up to 150 | Model Improvement Program ON by default; opt out per request `mip_opt_out=true`; pricing page silent on any opt-out surcharge (a competitor blog claims a forfeited 50% discount — unverified) | US servers; EU endpoint api.eu.deepgram.com | deepgram.com/pricing; developers.deepgram.com/docs/the-deepgram-model-improvement-partnership-program; deepgram.com/privacy |
| Deepgram | Flux (streaming + end-of-turn) | $0.0065 EN (regular $0.0077) / $0.0078 multi | /min | same | same | same | same | deepgram.com/pricing |
| AssemblyAI | Universal-Streaming EN & multilingual | $0.15/hr = $0.0025/min (+$0.04/hr keyterms, EN) | /hr | PAYG; $50 free | 100 new streams/min (free: 5) | Training ON by default; paid accounts opt out free in Data Controls; free tier cannot | US; EU endpoints same price | assemblyai.com/pricing; assemblyai.com/docs/faq/how-to-opt-out-of-data-sharing-for-our-model-improvement-program |
| Speechmatics | Real-time (Standard/Enhanced/Melia) | "$0.129" on Pro tier — page doesn't separate batch vs RT (≈$0.0022/min if RT; confirm in console) | /hr | $100 free, no card | Free 2 / Pro 50 RT sessions | "Realtime audio is never stored … never used to improve our models" unless opted into training-discount programme | "multi-region cloud options" | speechmatics.com/pricing |
| Gladia | Real-time | $0.75/hr = $0.0125/min | /hr | €50 free | Starter 30 | "data opt-out on every paid plan" | EU company; region n/s | gladia.io/pricing |
| Soniox | stt-rt-v5 | $0.12/hr = $0.002/min ($2/1M audio tokens) | /hr | no free credits for new signups | "hundreds of thousands" | "never used to improve Soniox models"; RT audio not stored | n/s (separate data-residency doc) | soniox.com/pricing; soniox.com/docs/security-and-privacy |
| Azure | Speech STT standard RT | $1/hr = $0.0167/min UNVERIFIED (page renders "$-") | /hr | 5 hr/mo free | n/s | Azure: no training on customer data (recollection) | Canada Central (recollection) | azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/ |
| Google | STT v2 streaming incl. Chirp 3 | $0.016/min (0–500K min) — page truncated; secondary verified Jul 2026 | /min | 60 min/mo | n/s | paid Cloud: no training (DPA) | us/eu endpoints; Montreal region UNVERIFIED | cloud.google.com/speech-to-text/pricing; costbench.com |
| OpenAI | gpt-4o-mini-transcribe / gpt-4o-transcribe / gpt-live-transcribe | $0.003 / $0.006 / $0.017 | /min | none | tiered rate limits | API data not used for training by default; ZDR on approval; 30-day abuse logs | residency incl. US, EU, Canada | developers.openai.com/api/docs/pricing; …/guides/your-data |

## C. Streaming TTS

| Provider | Model | Price | Floors | Concurrency | Training / data | Region | TTFB claim | Source |
|---|---|---|---|---|---|---|---|---|
| Deepgram | Aura-2 (Aura-1; Flux TTS) | $0.030/1k chars = $30/1M (Aura-1 $15/1M; Flux TTS free until 9/12 then $45/1M) | PAYG, $200 free | 45 | MIP as in B | US / EU endpoint | "as low as 80ms" | deepgram.com/pricing; deepgram.com/product/text-to-speech |
| Cartesia | Sonic-3.6 | Subscription only, no PAYG: Free 20K credits; Pro $5/mo 100K; Startup $49/mo 1.25M; Scale $299/mo 8M (1 credit/char ⇒ ≈$50→$37/1M) | $5/mo min | TTS 2/3/5/15 by tier | ZDR enterprise-only | n/s | "sub-90ms" | cartesia.ai/pricing; cartesia.ai/sonic |
| ElevenLabs | Flash / Turbo v2.5 (v3 conversational) | $0.05/1k = $50/1M PAYG (v3 / Multilingual v2 $0.10/1k); plans $6–$990/mo | PAYG "without subscription commitment" | 4 (Starter) → 40 (Business) | n/s | n/s | "~75ms" | elevenlabs.io/pricing/api; elevenlabs.io/blog/weve-lowered-api-agents-pricing-and-introduced-pay-as-you-go |
| Inworld | TTS-2 Flash / TTS-2 | $15 / $25 per 1M on-demand (Flash $10 Creator, $7 Growth) | none | 5 on-demand → 500 | ZDR workspace option; "never used for training" (STT doc) | n/s | 25ms Flash, <100ms TTS-2 (P99 server-side, WebSocket) | inworld.ai/pricing; inworld.ai/tts |
| Rime | Mist v3 / Coda | $0.03 / $0.05 per 1k = $30 / $50 per 1M | 3,000 free min; PAYG | 20 | no training unless agreed; default ZDR (privacy page via search) | n/s | Mist v3 TTFA 37ms P50 / 56ms P90 | rime.ai/pricing |
| OpenAI | gpt-4o-mini-tts | $0.60/1M input chars + $12/1M audio-output tokens (OpenAI's ≈$0.015/min estimate not on fetched page) | none | tiered | as B | as B | n/s | developers.openai.com/api/docs/pricing |
| Azure | Neural / Neural HD | $16 / $22 per 1M UNVERIFIED (page blank; secondary verified Jun 2026) | 0.5M chars/mo free | n/s | as B | Canada Central (recollection) | n/s | texttolab.com/blog/azure-text-to-speech-pricing |
| Google | Chirp 3 HD / Neural2 / WaveNet & Standard | $30 / $16 / $4 per 1M (page truncated; secondary verified Jun 2026) | 1M HD chars/mo free | n/s | as B | as B | n/s | texttolab.com/blog/google-cloud-tts-pricing |
| Amazon Polly | Neural / Generative / Standard | $16 / $30 / $4 per 1M | 12-mo free tier | n/s | AWS: no training on content (recollection) | ca-central-1 (recollection) | n/s | aws.amazon.com/polly/pricing/ |
| Hume | Octave | $0.12/1k = $120/1M Free/Starter → $50/1M Business | plan floors | n/s | n/s | n/s | n/s | hume.ai/pricing |
| PlayHT | — | UNVERIFIED: play.ht / play.ai do not resolve; reportedly acquired by Meta Jul 2025 and wound down | | | | | | — |
| Smallest.ai | Lightning v3.1 Pro | ≈$19.50/1M (search snippet); site shows "~$0.09/min" TTS layer | n/s | "20+ concurrent" | n/s | n/s | "sub-100ms" | smallest.ai/pricing; smallest.ai/text-to-speech |
| Kokoro-82M | open-source, Apache-2.0 | Replicate $0.65/1M (AA); self-host ≈$0.03–0.07/hr RTX 3060; A100 ≈50+ streams | none | self-hosted | yours | yours | n/s | github.com/hexgrad/kokoro; artificialanalysis.ai/text-to-speech |

## D. LLM (per 1M tokens: input / cached / output)

| Provider | Model | Price | TTFT (artificialanalysis.ai) | Training / residency | Source |
|---|---|---|---|---|---|
| Google | Gemini 2.5 Flash-Lite | $0.10 / $0.01 / $0.40 | 0.29 s | Paid tier: "doesn't use your prompts … to improve our products"; data may transit any Google country; Vertex regional endpoints | ai.google.dev/gemini-api/docs/pricing; ai.google.dev/gemini-api/terms |
| Google | Gemini 2.5 Flash | $0.30 / $0.03 / $2.50 | 0.43 s (non-reasoning) | same | same |
| Google | Gemini 3.1 Flash-Lite / 3.5 Flash-Lite | $0.25/$0.025/$1.50; $0.30/$0.03/$2.50 | 3.5 F-Lite 7.8 s (reasoning) | same | same |
| Google | Gemini 3.7 Flash | $0.75 / $0.075 / $3.75 (doubles Jan 1 2027) | ≈0.72 s (low) | same | same |
| OpenAI | gpt-5-nano / gpt-5-mini | $0.05/$0.005/$0.40; $0.25/$0.025/$2.00 | 72 s / 69 s at high reasoning (deprecated) | no training by default; ZDR; residency incl. Canada | developers.openai.com/api/docs/pricing |
| OpenAI | gpt-5.4-nano / gpt-5.4-mini | $0.20/$0.02/$1.25; $0.75/$0.075/$4.50 | 2.77 s / 3.50 s (xhigh) | same | same |
| OpenAI | gpt-4.1-nano / gpt-4.1-mini | $0.10/$0.025/$0.40; $0.40/$0.10/$1.60 | nano 0.70 s | same | same |
| Anthropic | Claude Haiku 4.5 | $1 / $0.10 read ($1.25 5m write) / $5 | 0.75 s | "will not use your inputs or outputs … to train"; ZDR; global default, `inference_geo: us` +10% | platform.claude.com/docs/en/about-claude/pricing; privacy.claude.com |
| Groq | llama-3.1-8b-instant; gpt-oss-20b; gpt-oss-120b; llama-3.3-70b; qwen3-32b | $0.05/$0.08; $0.075/$0.30; $0.15/$0.60; $0.59/$0.79; $0.29/$0.59 (groq.com/pricing JS-blank; pydantic genai-prices YAML; Llama reportedly moving enterprise-only Aug 26 2026) | gpt-oss-120b 0.70 s; 20b 0.78 s | DPA: no training; 30-day logs; ZDR self-serve; US GCP buckets | raw.githubusercontent.com/pydantic/genai-prices/main/prices/providers/groq.yml; console.groq.com/docs/your-data |
| Cerebras | gpt-oss-120b (only production model); gemma-4-31b | $0.35/$0.75; $0.99/$1.49 (page shows only "$5 free / $10 min top-up") | 0.47 s, 1,578 tok/s | "do not retain inputs and outputs"; US + other countries | cerebras.ai/pricing; …/cerebras.yml; cerebras.ai/privacy-policy |
| Mistral | Mistral Small 4; Ministral 3 3B / 8B | $0.15/$0.60; $0.10/$0.10; $0.15/$0.15; cache −90% | Small 4 0.82 s | training opt-out on all tiers; EU-hosted (recollection) | mistral.ai/pricing/api |

## E. Speech-to-speech

| Provider | Model | Price | ≈ per minute | Source |
|---|---|---|---|---|
| OpenAI | gpt-realtime / -2.1 | audio $32 in / $0.40 cached / $64 out per 1M; text $4 / $24 | ≈$0.019 in + $0.077 out (derived from OpenAI's historical ~600 in / ~1,200 out audio tok/min — ratio UNVERIFIED) | developers.openai.com/api/docs/pricing |
| OpenAI | gpt-realtime-mini / -2.1-mini | audio $10 / $0.30 / $20 | ≈$0.006 in + $0.024 out | same |
| Google | Gemini 3.1 Flash Live Preview | audio $3 in / $12 out per 1M | $0.005 in + $0.018 out (page-stated) | ai.google.dev/gemini-api/docs/pricing |
| Google | Gemini 2.5 Flash Native Audio | $3 / $12 | ≈ same | same |
| Amazon | Nova 2 Sonic | $3 speech-in / $12 speech-out per 1M (Bedrock page blank; secondary) | ≈$0.015 combined (secondary estimate) | rywalker.com/research/aws-nova-2-sonic |
| xAI | grok-voice-think-fast-2.0 | $0.08/min audio + $0.004 text input | $0.08 | docs.x.ai/docs/models |
| ElevenLabs | Agents | $0.08/min beyond plan bundle; LLM pass-through extra | $0.08 | elevenlabs.io/blog (above) |
| Hume | EVI | $0.07 → $0.04/min by plan | $0.04–0.07 | hume.ai/pricing |
| Deepgram | Voice Agent API (Standard) | $0.056/min promo → $0.075 after 9/12 | $0.056–0.075 | deepgram.com/pricing |

## F. Independent latency benchmarks

- LLM TTFT (artificialanalysis.ai, first-party APIs): Gemini 2.5 Flash-Lite 0.29 s; Gemini 2.5 Flash 0.43 s; GPT-4.1 nano 0.70 s; Haiku 4.5 0.75 s; gpt-oss-120b Cerebras 0.47 s / Groq 0.70 s; Mistral Small 4 0.82 s. GPT-5.x and Gemini 3.5 figures are reasoning-mode (2.8–72 s) — unusable for voice unless reasoning is off.
- STT (daily.co/blog/benchmarking-stt-for-voice-agents, Feb 13 2026, 1,000 English samples, median time-to-final): Deepgram Nova-3 247 ms; Soniox 249 ms; Speechmatics 495 ms. Vendor claims: Deepgram Flux end-of-turn <300 ms median; AssemblyAI P50 ≈150 ms after endpoint. Coval (benchmarks.coval.ai, Sep 1 2026, TTFT): AssemblyAI Universal 3.5 Pro 1,033 ms; Flux 1,086; Nova-3 1,431; Speechmatics 1,467; Soniox 1,532; Gladia 1,713.
- TTS TTFA P50 (Coval via gradium.ai/content/tts-latency-benchmark-2026, May 4 2026): Cartesia Sonic-3 188 ms (IQR 100); ElevenLabs Turbo 264, Flash 288; Deepgram Aura-2 313; Rime Mist-v3 337 (IQR 381); OpenAI TTS-1-HD 2,295. Inworld/Azure/Google/Polly/Smallest not covered.

## Sources actually fetched
telnyx.com/pricing/call-control · telnyx.com/pricing/elastic-sip · telnyx.com/pricing/numbers · telnyx.com/pricing/voice-api · telnyx.com/release-notes/montreal-canada-anchorsite · twilio.com/en-us/voice/pricing/ca · twilio.com/docs/global-infrastructure/edge-locations · signalwire.com/pricing/voice · signalwire.com/pricing · plivo.com/voice/pricing/ca/ · deepgram.com/pricing · deepgram.com/product/text-to-speech · deepgram.com/privacy · developers.deepgram.com/docs/the-deepgram-model-improvement-partnership-program · assemblyai.com/pricing · assemblyai.com/legal/privacy-policy · assemblyai.com/docs/faq/how-to-opt-out-of-data-sharing-for-our-model-improvement-program · speechmatics.com/pricing · speechmatics.com/security · gladia.io/pricing · soniox.com/pricing · soniox.com/docs/security-and-privacy · azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/ (prices blank) · cloud.google.com/speech-to-text/pricing (truncated) · cloud.google.com/text-to-speech/pricing (truncated) · developers.openai.com/api/docs/pricing · developers.openai.com/api/docs/guides/your-data · cartesia.ai/pricing · cartesia.ai/sonic · elevenlabs.io/pricing/api · elevenlabs.io/pricing · elevenlabs.io/blog/weve-lowered-api-agents-pricing-and-introduced-pay-as-you-go · inworld.ai/pricing · inworld.ai/tts · rime.ai/pricing · aws.amazon.com/polly/pricing/ · aws.amazon.com/bedrock/pricing/ (Nova absent) · aws.amazon.com/nova/pricing/ (blank) · hume.ai/pricing · smallest.ai/pricing · smallest.ai/text-to-speech · github.com/hexgrad/kokoro · ai.google.dev/gemini-api/docs/pricing · ai.google.dev/gemini-api/terms · platform.claude.com/docs/en/about-claude/pricing · privacy.claude.com/en/articles/7996868 · groq.com/pricing (blank) · groq.com/privacy-policy · console.groq.com/docs/your-data · cerebras.ai/pricing · cerebras.ai/privacy-policy · raw.githubusercontent.com/pydantic/genai-prices/…/groq.yml and cerebras.yml · mistral.ai/pricing · mistral.ai/pricing/api · docs.x.ai/docs/models · rywalker.com/research/aws-nova-2-sonic · artificialanalysis.ai/models, /leaderboards/models, /speech-to-text, /text-to-speech/models, /providers/groq, /providers/cerebras, /models/{gpt-5-mini,gpt-5-nano,gpt-5-4-mini,gpt-5-4-nano,gpt-4-1-nano,gemini-2-5-flash,gemini-3-5-flash-lite} · gradium.ai/content/tts-latency-benchmark-2026 · daily.co/blog/benchmarking-stt-for-voice-agents/ · benchmarks.coval.ai/models/universal-streaming · texttolab.com (Azure, Google TTS) · costbench.com (Google STT). Failed: vonage.com (403), play.ht/play.ai (DNS), telnyx.com/phone-numbers/canada (404).

## Cheapest viable per layer (USD per call-minute; ×1.37 for CAD)

- **Telephony:** Plivo CA $0.0075 all-in (streaming and recording included), no PoP statement. Telnyx ≈$0.0052–0.0095 + $0.0035 streaming ≈ $0.009–0.013, with Toronto/Montreal/Vancouver PoPs — best latency/residency story. Twilio $0.0129 and no Canadian edge. All are PAYG with no concurrency tiers.
- **STT:** Soniox $0.002 (no-training by default, RT not stored). AssemblyAI $0.0025 (opt-out required, paid only, US/EU). Speechmatics ≈$0.002 if the "$0.129/hr" is the RT rate. Deepgram Nova-3 $0.0048 promo, MIP on by default.
- **TTS** (≈500 chars agent speech per call-min): Inworld TTS-2 Flash $0.0075; Azure Neural / Google Neural2 / Polly Neural ≈$0.008; Rime Mist v3 and Deepgram Aura-2 $0.015; ElevenLabs Flash $0.025. Cartesia is subscription-only (fails the PAYG constraint). Kokoro self-host ≈$0.0003 + GPU.
- **LLM:** ≈$0.0005–0.001 with Gemini 2.5 Flash-Lite, GPT-4.1-nano or Groq gpt-oss-20b (≈3k mostly-cached input + 100 output tokens per turn); Haiku 4.5 ≈$0.004.
- **Chained total ≈ $0.019–0.022 USD ≈ $0.026–0.030 CAD** — on target. **Speech-to-speech:** Gemini Live $0.023 + telephony ≈ $0.032 USD ($0.044 CAD) exceeds the ceiling; gpt-realtime ≈ $0.10 USD; gpt-realtime-mini ≈ $0.03 USD + telephony; Nova 2 Sonic ≈ $0.015 + telephony ≈ $0.024 USD ($0.033 CAD) is the only S2S near target and its primary pricing page did not render. Chained wins on cost by ~30–75%.
