# AI Front Desk: Architecture and Stack Recommendation

**Status:** revised 2026-09-01 after founder review. Dashboard is in scope, open source is adopted aggressively, MVP target is measured in days. Awaiting go on the implementation plan.
**Date:** 2026-09-01
**Inputs:** product brief (Multi-Channel AI Front Desk), Skincentrix client facts, founder's suggested stack
**Evidence:** five research notes in `docs/research/` with every price and repo fact traced to a URL fetched on 2026-09-01. Anything not confirmed on a primary page is marked *unverified* here as well.

---

## 0. The short version

Two apps on one OVH Beauharnois VPS: a Python **runtime** on Pipecat (voice, SMS, chat, ledger) and a TypeScript **portal** cloned from open-saas (agency admin, client dashboards, auth, billing). Every metered provider sits behind a config-swappable adapter. Clone and take from Pipecat's examples, open-saas, openreply and deep-chat; do not run Dograh, Chatwoot or Langfuse. Structural honesty is enforced by a closed outcome type, a template renderer, and a lexical output guard, not by prompts.

**Brief change, founder decision 2026-09-01:** §4.3 "No admin dashboard in MVP" is reversed. The portal serves the agency (all tenants, usage, revenue) and each client (their AI's conversations, tracked items, usage). Staff still receive items in Slack and email; the portal is for owners and for us.

| Layer | Recommendation | Why this and not the suggestion |
|---|---|---|
| Voice runtime | **Pipecat 1.8.1** (BSD-2), direct, with Pipecat Flows | Dograh is a product on a pinned Pipecat submodule with its own DB schema, workflow schema, JWT auth and two-person bus factor. Use it for patterns only. |
| Telephony | **Telnyx Call Control + WebSocket media** (Plivo as the swappable alternative) | No SIP server needed. Toronto and Montreal media anchors. All-in is $0.009 to $0.013 USD per minute, not $0.005. |
| STT | **Soniox stt-rt-v5** ($0.002 per minute, no training by default) with **Smart Turn v3** for endpointing; Deepgram Flux as the config alternative | Deepgram trains on your audio by default on pay-as-you-go. Opting out is per request and may forfeit the promo price. Soniox is a quarter of the price and matches Nova-3 on time-to-final in Daily's benchmark. |
| TTS | **Inworld TTS-2 Flash** ($15 per million characters, no training) | Half the price of Aura-2 and the lowest vendor-claimed first-byte latency. Cartesia has no pay-as-you-go tier at all. |
| LLM | **Gemini 2.5 Flash** (thinking off) for conversation; **Gemini 2.5 Flash-Lite** as the cheaper/faster fallback; nightly audit on a stronger model | Lowest measured time-to-first-token of any current small model. Gemini 3.x and GPT-5.x small models are reasoning-first and unusable for voice unless thinking is disabled. |
| SMS | **Canadian toll-free number per tenant, verified, on Telnyx** (voice stays on a separate local number) | Canadian carriers filter unregistered long codes. Toll-free voice inbound costs three times local, so keep the channels on separate numbers. |
| Web chat | **Own widget** (vanilla JS or deep-chat, MIT) over WebSocket | Chatwoot is a second dashboard on a 4 to 8 GB box, and its SMS only speaks Twilio and Bandwidth. |
| Ledger delivery | **Slack Block Kit buttons + Amazon SES email with confirm-then-POST magic links** + webhook | Slack callbacks are free and real. SES is the only email provider with no monthly floor. Teams and Google Chat webhooks cannot call back. |
| Hosting | **OVH VPS-2 2027, Beauharnois** (4 vCPU, 8 GB, CA$13.70/month), Postgres in Compose with WAL-G to R2 | Cheapest Canadian option by a wide margin. Hetzner tripled US prices in June 2026 and has no Canadian region. |
| Observability | Traces and usage events in **our own Postgres**; promptfoo + Pipecat evals in CI | Langfuse self-host is six containers and 16 GiB. Phase 2. |
| Tenant config | **Postgres, edited in the portal, every save versioned**; a YAML bundle per tenant as import/export and as the CI snapshot | Zero deploys either way. The bundle is how Skincentrix is onboarded on day one without waiting for forms, and how CI gets a snapshot to test. |
| Portal | **open-saas** (Wasp 0.25, MIT) cloned and stripped: auth, Stripe, admin analytics, email, jobs; add an Organization model | Current (no Wasp lag), active, ships the admin dashboard with charts. Per-user only, so tenancy is one added model. Owns no business logic. |
| Instagram, Messenger | **Adapter built from openreply's Meta plumbing** (MIT, active): Instagram Business Login, webhook verification, comment-to-DM, token refresh | opensetter is a dead fork; openreply is the maintained upstream. Standard Access serves the pilot's own account without App Review; Advanced Access (about 20 days reported) for the rest. |

**Cost at the recommended stack** (CAD, exchange rate 1.3896, Bank of Canada 2026-09-01):

| Unit | Model result | Brief target / ceiling | Status |
|---|---|---|---|
| Voice, per call-minute | **0.025 to 0.031** (range depends on Telnyx's unpublished Canadian inbound rate) | 0.030 / 0.040 | On or just over target, under ceiling |
| SMS conversation | **0.14** | 0.15 / 0.25 | On target |
| Web-chat conversation | **0.003** | 0.15 / 0.25 | Far under |
| Single outbound SMS | **0.017** | 0.01 / 0.02 | **Brief target not achievable in Canada**, see §6.3 |
| Fixed, 1 / 10 / 25 tenants | **25 / 72 / 216** | 60 / 150 / 400 | Under, and sublinear |
| Gross margin at $999, tenant 1 / 3 | **92% / 94%** | 65% / 80% | Pass |

Your suggested voice stack priced at today's real rates comes to **0.048 CAD per minute**, over the hard ceiling. Three lines cause it: the Telnyx media-streaming surcharge you did not have, Deepgram at regular price once you opt out of training, and Aura-2 at $30 per million characters.

**Five things to verify before committing, in order of money at stake:**

1. Telnyx Canadian inbound per-minute rate and Canadian SMS carrier pass-through fees, in the portal. Both are unpublished and are the two largest cost lines.
2. A week-one latency bake-off: Soniox + Smart Turn vs Deepgram Flux, and Inworld vs Aura-2, on real forwarded calls. Vendor latency claims are not measurements.
3. TELUS Business Connect forwarding preserves original caller ID (the setting is "Incoming Caller ID" vs "Dialed Number"). One test call settles it.
4. Skincentrix has, or can create, a back-line number that does not forward, or live transfer will loop.
5. Submit Canadian toll-free verification on day one. It takes about five business days and Canada requires double opt-in.

---

## 1. Assumptions made in your absence

You were not available to answer questions, so these are stated rather than asked. Any of them can be overturned.

- **Hosting does not need to be in Canada, but we make it Canadian anyway** because OVH Beauharnois is also the cheapest option and "your data rests in Canada" is a free sales line for a PHIPA-adjacent buyer. Processing by STT, TTS and LLM providers happens in the US under no-training terms, and that is stated in the subprocessor register.
- **Call shape:** 3 minutes average, agent speaking half the time at 825 characters per spoken minute, 3 model turns per minute, 5,000 cached and 600 uncached input tokens per turn, 60 output tokens. Text: 5 model turns, 4 outbound and 4 inbound messages per SMS conversation.
- **Volume per tenant:** 250 calls, 150 SMS conversations, 100 web-chat conversations, 300 outbound messages per month, matching the brief's 500 enquiries.
- **Recording is off by default;** transcript only. A health information custodian does not want a third party holding voice recordings it did not ask for. Per-tenant switch.
- **One language.** Everything below is English-only.
- **The founder is the only operator** for the first several tenants. Every choice below optimises for one person's on-call load, not for a team.

---

## 2. Verdict on the suggested repos

| Repo | Verdict | Reason (verified 2026-09-01) |
|---|---|---|
| dograh-hq/dograh | **Do not adopt; mine for patterns** | Next.js + FastAPI + Postgres + Redis + MinIO + coturn on a vendored Pipecat submodule. Opinionated orgs, telephony configs, campaigns, JWT auth, PostHog telemetry on by default. Two contributors hold 90% of commits. Its inbound org-resolution and credential-store patterns are worth copying. |
| wasp-lang/open-saas | **Adopt as the portal** (revised) | With the dashboard in scope it is the right boilerplate: Wasp 0.25 with no version lag, email auth with Google and others one uncomment away, Stripe or Polar or Lemon Squeezy, admin analytics on ApexCharts, PgBoss jobs, React 19 and shadcn. Per-user only, so we add Organization and Membership. Wasp lock-in is accepted because the portal owns no business logic. |
| knadh/listmonk | **Phase 3 only** | Good transactional and campaign email over its API. AGPL is a non-issue when used unmodified. SMS only via a self-written messenger webhook. Not needed before outbound campaigns. |
| xbirimensah/opensetter | **Skip the fork, take from upstream openreply** | opensetter is a zero-star fork abandoned after three days. diwenne/openreply (MIT, 1.9k stars, pushed 2026-08-30) has the Meta plumbing we copy: Instagram Business Login, HMAC webhook verification, comment-to-private-reply, long-lived token refresh. Instagram only; Messenger needs Page webhooks added. |
| calcom/cal.diy | **Your own demo scheduling only** | It is the original Cal.com repo renamed and relicensed MIT in April 2026, with teams, orgs, workflows and routing forms stripped out. Irrelevant to the product. |
| langfuse/langfuse | **Phase 2** | MIT core, but self-host is web + worker + Postgres + ClickHouse + Redis + S3, 16 GiB recommended. At MVP, traces go to our Postgres. If a trace UI is wanted, Phoenix runs as one container on SQLite (Elastic 2.0, fine for internal use). |

Additional tools adopted: **promptfoo** (MIT) for the CI scenario suite, **Pipecat's built-in evals** for audio-mode and latency checks, **deep-chat** (MIT) as an optional widget shell, **WAL-G** for Postgres archiving.

Tools considered and rejected: Chatwoot (dashboard, heavy), Grafana OnCall (archived March 2026), Keep (alert console, wrong model), NocoDB (left AGPL for a non-OSI licence in January 2026), LiveKit Agents (excellent runtime, but telephony requires the LiveKit SIP service, and LiveKit Cloud caps concurrency at 20 for $50/month), Vocode (unmaintained since November 2024), Cartesia (subscription only), Wasabi (1 TB minimum). Portal fallbacks if Wasp bites: boxyhq/saas-starter-kit (teams built in, but only dependabot commits since May 2026) or nextjs/saas-starter (teams, small, last feature commit June 2025).

### 2.1 Clone-and-take list

The rule: clone code we will own afterwards; never run someone else's product with its own opinions. Paths verified 2026-09-01.

| Repo | Take | Leave behind |
|---|---|---|
| `pipecat-ai/pipecat` (pip) | the library; `pipecat.runner.utils.parse_telephony_websocket`, `TelnyxFrameSerializer`, `FastAPIWebsocketTransport`; `pipecat.flows.FlowManager` and `NodeConfig`; `SonioxSTTService`; `InworldTTSService`; `LLMSwitcher`; metrics observers | nothing, it is a library |
| `pipecat-ai/pipecat-examples/telnyx-chatbot/inbound` | the bot skeleton and the TeXML `<Connect><Stream>` pattern | its TeXML bin; we serve our own webhook that puts a tenant token in `/ws/{token}` |
| `pipecat/examples/flows/` | `patient_intake.py` (structured capture with per-node tools), `warm_transfer.py` (live transfer), `food_ordering.py` (per-node function scoping) | the domains |
| `dograh-hq/dograh` | read only: called-number to tenant resolution, telephony credential model, the Helm and KEDA scaling later | everything that runs |
| `wasp-lang/open-saas` (clone `template/app`) | `src/auth`, `src/payment` (Stripe), `src/admin` (analytics page, users list, ApexCharts), `src/server` jobs (PgBoss), email sending, shadcn UI, `e2e-tests` | `src/demo-ai-app`, `src/landing-page`, `template/blog`, `src/file-upload` and S3, `ContactFormMessage`, unused payment providers, Plausible and GA |
| `diwenne/openreply` | `lib/meta/oauth.ts` (Instagram Business Login, scopes), `lib/meta/client.ts` (long-lived token refresh, `/{ig-id}/messages` private reply, `/{comment-id}/replies`), `app/api/webhook/route.ts` (verify handshake, HMAC-SHA256 signature, event parsing), `docs/setup.md` (permissions, Live mode, testers) | its UI, Prisma models, BullMQ and Redis (our jobs table replaces it), its workspace model |
| `OvidijusParsiunas/deep-chat` (MIT) | the web component as the widget shell, wired to our WebSocket | its provider integrations |
| `promptfoo`, `WAL-G`, `Caddy` | as tools | |

What we write ourselves, because nothing trusted exists for it: the capability layer and outcome types, the renderer and guard, the rules gate, the ledger and business-hours SLA, the Slack and SES delivery with acknowledge and resolve, the tenant config schema and versioning, usage events, the runtime's internal API, and the portal's Organization model and client pages.

---

## 3. Architecture

One deployable service, one Postgres, one object store. Everything else is a metered provider behind an adapter.

```
   Phone (forwarded)        SMS (toll-free)         Website (Squarespace)
        |                        |                        |
   Telnyx WS media          Telnyx webhook          widget WebSocket
        |                        |                        |
 +------v-------+       +--------v--------+       +-------v--------+
 | voice adapter|       |  SMS adapter    |       | chat adapter   |     one adapter per channel
 | Pipecat:     |       |  (edge worker   |       |                |     produces Turn, consumes Reply
 | STT/TTS/VAD  |       |   in front)     |       |                |
 +------+-------+       +--------+--------+       +-------+--------+
        |   Turn(tenant, conversation, channel, text, meta)   |
        v                        v                            v
 +-------------------------------------------------------------------+
 |  conversation core                                                 |
 |   tenant bundle -> prompt (cached static prefix + dynamic suffix)  |
 |   band gate: deterministic rules first, then model                 |
 |   LLM with tools -> capability requests                            |
 |   outcome renderer (templates) -> the words actually said          |
 |   output guard (lexical, deterministic)                            |
 +-----------------------------------+-------------------------------+
                                     |
 +-----------------------------------v-------------------------------+
 |  capability layer: one interface for every tier                    |
 |   request_appointment_change | send_booking_link | capture_request |
 |   escalate | transfer_to_human | end_conversation                  |
 |   Tier C impl: capture only     Tier A impl: platform adapter      |
 +-----------------------------------+-------------------------------+
                                     |
 +-----------------------------------v-------------------------------+
 |  ledger: tracked items, business-hours SLA clock, escalation,      |
 |  delivery (Slack buttons, SES email, webhook), ack/resolve inbound |
 +-------------------------------------------------------------------+
 |  tenant registry | usage events | audit log | retention | jobs     |
 +-------------------------------------------------------------------+
```

**Control plane and data plane.** The diagram is the data plane, the runtime. The portal (open-saas) is the control plane: it owns users, organisations, memberships, subscriptions and billing in the `public` Postgres schema via Prisma, and it edits tenant configuration and reads usage, conversations and items through the runtime's internal HTTP API (shared secret, same VPS). The runtime owns the `runtime` schema via Alembic. Two apps, two migration tools, zero shared tables: the only join is `Organization.runtime_tenant_id`. The portal runs as one more container in the same Compose file and adds nothing to fixed cost.

**Runtime:** Python 3.11+, FastAPI for webhooks and the chat WebSocket, Pipecat for the voice pipeline (one asyncio process per call, roughly half a CPU each per Cerebrium's published Twilio example), Postgres 16, Caddy for TLS, Docker Compose. No Redis: a `jobs` table drained with `SELECT ... FOR UPDATE SKIP LOCKED` and `NOTIFY` as the wake-up handles post-call work, SMS sends and webhook retries.

**Network:** Cloudflare free in front of the HTTP API and widget. The media WebSocket hostname is DNS-only (not proxied) and points straight at the VPS to keep audio off the proxy path. Cloudflare Tunnel for any admin access.

**Capacity:** VPS-2 (4 vCPU) runs 6 to 8 concurrent calls plus Postgres and the API, against an MVP need of 3. At 25 concurrent calls, two VPS-4 nodes. No load balancer is required: Telnyx calls one webhook, and that handler returns the media-stream URL of whichever node has capacity, with Telnyx's failover URL pointing at the second node.

**Adding things:** a channel is one adapter. A booking platform is one fulfilment implementation. A tenant is one bundle directory. None of these touches the others.

---

## 4. The eight open decisions

**12.1 Build or adopt the voice pipeline?** Adopt Pipecat as a library, not a product. It is BSD-2, released 2026-08-27, the most active of the three candidates, and has first-party serializers for Telnyx and Twilio bidirectional WebSocket streams, so there is no SIP server. It imposes no database, config or UI model, so tenancy stays in our layer. Every STT, TTS and LLM in the comparison is a one-line service swap behind the same tool schema, and per-service first-byte and usage metrics ship in the box. LiveKit Agents was the runner-up and lost only on the telephony path.

**12.2 Speech-to-speech or chained?** Chained. On cost: Gemini Live is about $0.023 USD per minute before telephony, which lands at $0.044 CAD, over the ceiling. OpenAI gpt-realtime is about $0.10 USD. Amazon Nova 2 Sonic is the only speech-to-speech model near target and its primary pricing page did not render. On the brief's terms: chained gives a text record for the audit log, deterministic tool results for §7.2, and independent provider swapping, which the brief demands at §8.3. Chained wins on both axes, by 30 to 75 percent on cost.

**12.3 How is structural honesty enforced?** Three mechanical layers, detailed in §5. In one sentence: the Tier C code cannot construct a "completed" outcome, the sentence describing any outcome is rendered from a template rather than generated, and a lexical guard blocks completion language in any free-form utterance that lacks a completed outcome.

**12.4 Where does tenant configuration live?** (Revised for the dashboard.) In Postgres, in the runtime schema, as a versioned document per tenant: every save writes a new `tenant_config_versions` row and the runtime hot-reloads on version change, so rollback is one click. The portal edits it through the runtime's internal API, which is where validation lives. A YAML bundle per tenant (`tenant.yaml`, `services.yaml`, `knowledge.md`, `scripts.yaml`, `guard.yaml`) is the import and export format: it is how Skincentrix is onboarded on day one without waiting for portal forms, and how CI exports a snapshot to run the scenario suite against before a change goes live. Zero deploys on either path.

**12.5 Shared or isolated?** Shared, with a cell boundary for later. One app, one Postgres, `tenant_id` on every row with row-level security as the safety net, per-tenant object-storage prefix, per-tenant retention job, per-tenant jurisdiction field. The isolation unit is a cell (a full stack in one region), and the registry maps tenant to cell. MVP runs one cell in Beauharnois. A tenant that needs a different jurisdiction gets a second cell without re-architecture. Per-tenant VMs would break the fixed-cost curve for no compliance gain that PHIPA asks for.

**12.6 Cost attribution granularity.** Per conversation, to within a few percent. Every provider call emits a `usage_event` (conversation, tenant, channel, provider, unit, quantity). A versioned rates table prices them. Monthly reconciliation against provider invoices catches drift. This is cheap because Pipecat already emits per-service usage metrics per session; the SMS and chat paths add two counters.

**12.7 Failure mode when the platform is down.** It lives at the carrier and the edge, not on our servers. Voice: Telnyx's failover URL points at a Telnyx-hosted TeXML bin that plays a fixed message and records voicemail (or forwards to the clinic's own voicemail). Telnyx tries the failover after two consecutive failed deliveries. SMS: the inbound webhook target is a Cloudflare Worker (free tier, 100k requests per day), which relays to us and, if we are unreachable, auto-replies with the tenant's fixed "we will be in touch" text and holds the message for replay. Web chat: the widget degrades to a contact form posting to the same Worker. An external uptime monitor pages the founder.

**12.8 Catching conversation regressions.** A promptfoo suite (MIT) per tenant bundle: multi-turn scenarios using the simulated-user provider, with Python asserts on which tools were called, which outcome types were produced, whether the guard fired, whether a ledger item was created with the right type, urgency and due time, plus an LLM-judge rubric for tone and brevity. Runs in CI on any change to code, prompts or bundles. Pipecat's native `pipecat eval run` covers audio mode and per-event latency nightly. Anonymised production transcripts become new scenarios. This suite must exist before the first model swap, because a model swap inside 18 months is certain (§10).

---

## 5. Structural honesty in detail

This is the design question the brief calls the most important, so it gets its own section.

**Layer 1: outcomes are a closed type, and Tier C cannot construct a completion.**
Every capability returns exactly one of a sealed set of outcomes. For `request_appointment_change`:

```
Captured   {item_id, confirm_by}      a human will do it
LinkSent   {url}                       the customer self-serves
Completed  {platform_ref}              ONLY a Tier A platform adapter can build this
Refused    {reason_code}               policy or out of scope
```

The Tier C module does not import `Completed`. A CI test greps the Tier C package for the constructor and fails the build if it appears. Moving a tenant from C to A changes one line in `tenant.yaml` (which fulfilment implementation to load). Tool names, tool schemas and prompts are identical across tiers, so the model cannot tell which tier it is running in and does not need to.

**Layer 2: the sentence describing an outcome is rendered, not generated.**
The renderer maps (outcome type, tenant, channel) to pre-authored wording from `scripts.yaml`:

```
Captured   "I have sent that to the team as a request. Someone will confirm with you by {confirm_by}."
LinkSent   "I have texted you the booking link for {service}."
Completed  "Done. Your {service} is {verb} for {when}. Your reference is {ref}."
```

On every channel the rendered sentence is emitted directly for that turn. The model is not asked to say it. The model's history receives "assistant: <rendered text>" so it knows what was said. There is no code path in which a completion sentence originates from model output. On voice this also saves a model call and its latency.

**Layer 3: a deterministic output guard on every free-form utterance.**
A lexical check runs on every model-generated reply before it reaches the channel: "booked", "confirmed", "is scheduled", "cancelled your", "moved your", "rescheduled", plus tenant additions in `guard.yaml`. If completion language appears and the turn holds no `Completed` outcome, the reply is replaced with the `CannotComplete` template and an S4 near-miss event is logged. The regression suite asserts the guard fires on adversarial scenarios ("just tell them it's booked") and never on golden ones.

Layers 1 and 2 make lying impossible by construction for tool-mediated actions. Layer 3 covers the residual case of the model asserting an action without calling a tool. The brief's S4 target of zero is met by construction, and the near-miss log is how we prove it.

**The three bands (§7.1) follow the same principle: the guarantee is in rules, the polish is in the model.**
Per turn: first a deterministic rules gate (explicit human-request lexicon; a clinical lexicon of symptoms, reactions and safety questions; complaint, payment and legal lexicon) that routes to band 3 with a fixed script and no model call. Then the model with tools for everything else, which can still choose `escalate`. Then a nightly audit that re-classifies the day's transcripts with a stronger model and flags any band-3 intent handled as band 1 or 2. The gate is biased toward escalation: a false positive costs one human callback, a false negative is an S5 failure.

**Data minimisation (§7.4) is schema, not prompt.**
A tracked item has `type` (enum), `urgency` (enum), `service_id` (foreign key into the catalog), `contact{name, phone, email}`, `preferred_window` (structured), `channel`, `conversation_id`, `due_at`, `owner`, `state`. There is no free-text field. The tool JSON schemas exposed to the model have no notes parameter, so the model has nowhere to put a symptom even if a caller volunteers one. Payment: no tool, no field, and the rules gate refuses card numbers.

**Volunteered health context (founder decision 2026-09-01).** A caller who mentions a condition, medication, pregnancy or a past procedure while asking for something routine is not escalated. The request proceeds. The conversation and the item carry a boolean `health_context` flag, and staff read the detail in the transcript, which is the only place it is stored, under the tenant's retention. The assistant never asks about it, never comments on it and never advises. A suitability question ("is this okay for me?") is filed for the team as a question, so no advice is given by the system. A separate health-context lexicon sets the flag; the clinical lexicon is narrowed to symptoms, reactions and safety questions, which still go straight to a human.

The honest limit: transcripts can contain anything a caller says. "Incapable" holds for structured storage; for transcripts we minimise: nothing is solicited, the clinical lexicon stops collection when something is wrong, transcript retention defaults to 30 days, recordings default to off, all per tenant. This limit should be stated to the client.

---

## 6. Cost model

The model is `docs/research/costmodel.py` with `rates.json`. It exits non-zero if a recommended stack breaches a ceiling, so it can run in CI whenever a rate changes.

### 6.1 Voice, per call-minute (USD breakdown, CAD total)

| Stack | Telephony | STT | TTS | LLM | CAD/min | vs 0.030 / 0.040 |
|---|---|---|---|---|---|---|
| Your suggestion at real prices: Telnyx + Flux + Aura-2 + Gemini Flash | 0.0130 | 0.0077 | 0.0124 | 0.0014 | **0.048** | breach |
| **Recommended:** Telnyx + Soniox + Inworld Flash + Gemini 2.5 Flash | 0.0130 | 0.0020 | 0.0062 | 0.0014 | **0.031** | over target, under ceiling |
| Same, if Telnyx Canadian inbound is at its "from $0.0032" rate | 0.0087 | 0.0020 | 0.0062 | 0.0014 | **0.025** | under target |
| Same with Deepgram Flux instead of Soniox | 0.0130 | 0.0077 | 0.0062 | 0.0014 | 0.039 | just under ceiling |
| Same with Gemini 2.5 Flash-Lite | 0.0130 | 0.0020 | 0.0062 | 0.0004 | 0.030 | on target |
| Cheapest: Plivo + Soniox + Inworld + Flash-Lite | 0.0075 | 0.0020 | 0.0062 | 0.0004 | 0.022 | well under |
| Expensive reference: Twilio + Nova-3 + ElevenLabs + Haiku 4.5 | 0.0129 | 0.0077 | 0.0206 | 0.0042 | 0.063 | breach |

Telephony assumptions for Telnyx: $0.002 Call Control API fee + inbound ($0.0075 per a secondary source for Canadian numbers; Telnyx's own page says "from $0.0032") + $0.0035 WebSocket media streaming. Recording off. The brief is right that wall-clock cost dominates: telephony plus STT are metered on duration and are 55 to 65 percent of the recommended stack. Every second shaved off a call is worth more than any token optimisation.

**Two further levers if the Telnyx rate comes in high:** Plivo Canada is $0.0075 inbound with streaming included, but publishes no point-of-presence information, so it needs a latency test. SIP trunking into a self-hosted SIP endpoint would remove the $0.0035 streaming surcharge, but adds a SIP server to operate. At 25 tenants that surcharge is about $65 USD per month, which is not worth a SIP server yet.

### 6.2 Text

| Unit | Telnyx toll-free | Twilio toll-free | Target / ceiling |
|---|---|---|---|
| SMS conversation (4 out, 4 in, 5 model turns) | **0.14 CAD** | 0.22 CAD | 0.15 / 0.25 |
| Web-chat conversation | 0.003 CAD | 0.003 CAD | 0.15 / 0.25 |
| Single outbound SMS | **0.017 CAD** | 0.023 CAD | 0.01 / 0.02 |

Telnyx's Canadian SMS carrier fee is not published; the model assumes $0.007, matching Twilio's published Canadian outbound pass-through average. Twilio's published inbound pass-through fees for Bell and Rogers are high enough that Twilio breaches the outbound ceiling and nearly breaches the conversation ceiling.

### 6.3 Two brief targets need revising

1. **Outbound message at $0.01 CAD is not achievable for Canadian SMS on any carrier**, because Canadian carrier pass-through fees alone are around $0.007 USD. Propose: target $0.02, ceiling $0.025, and note that outbound volume is structurally small (one follow-up maximum per conversation, one booking link).
2. **Voice at $0.030 CAD has almost no headroom** at the recommended stack. It holds if Telnyx's Canadian inbound rate is near its published floor, or with Flash-Lite. Either confirm the rate or accept $0.032 as the target with the $0.040 ceiling unchanged.

### 6.4 Fixed cost (CAD per month)

| Item | 1 tenant | 10 tenants | 25 tenants |
|---|---|---|---|
| OVH VPS, Beauharnois (app, VAD, Caddy; Postgres in Compose at MVP) | 13.70 (VPS-2) | 37.90 (VPS-4) | 75.80 (2 × VPS-4) |
| OVH 7-day automatic backup | 1.80 | 1.80 | 3.60 |
| OVH VPS-1 staging and canary (optional) | 7.30 | 7.30 | 7.30 |
| DigitalOcean Managed Postgres, Toronto | 0 | 21.05 | 84.63 |
| Cloudflare R2 (or Backblaze B2 Toronto if "stored in Canada" must be nameable) | 0 | 0.83 | 4.17 |
| Amazon SES email | 0.50 | 2.00 | 5.00 |
| Domain (.com at cost) | 1.21 | 1.21 | 1.21 |
| Cloudflare Pro (optional, managed WAF rules) | 0 | 0 | 34.74 |
| **Total** | **24.5** | **72** | **216** |
| Brief ceiling | 60 | 150 | 400 |

Per-tenant recurring: one local number (about $1 USD), one toll-free number (about $1 to $2 USD), SMS add-on ($0.10), around CA$4.50 per tenant per month. This is variable cost in disguise and is modelled as such.

### 6.5 Margin

At 250 calls, 150 SMS conversations, 100 chat conversations and 300 outbound messages per tenant per month, variable plus per-tenant cost is about **CA$55 per tenant**. Gross margin at $999 is 92 percent at tenant one and 94 percent at tenant three, against the brief's 65 and 80. Doubling call volume moves per-tenant cost to about CA$105 and margin barely moves. The business works on these numbers with a wide buffer for the two unverified rates.

---

## 7. Compliance and the subprocessor register

**Jurisdiction, nameable:** data rests in Beauharnois, Quebec (compute and Postgres) and in R2 with a Canadian jurisdiction restriction, or Backblaze B2 CA East in Toronto. Voice audio and text are processed by US providers under no-training terms. The LLM can move to Vertex AI's Montreal region later if a tenant requires in-country processing, at a latency and price cost to be measured.

**Initial subprocessor register:**

| Provider | Role | No-training on customer data | Region |
|---|---|---|---|
| OVHcloud | compute, backups | n/a (infrastructure) | Beauharnois, QC |
| Cloudflare | DNS, proxy, R2, Workers | n/a | edge; R2 jurisdiction-restrictable |
| Telnyx | telephony, SMS | not stated on pricing pages; obtain DPA | Toronto / Montreal anchors |
| Soniox | STT | stated: never used to improve models; real-time audio not stored | US (data-residency doc exists) |
| Inworld | TTS | stated: never used for training; zero-data-retention workspace option | not stated |
| Google (Gemini API, paid tier) | LLM | stated: paid tier prompts not used to improve products | may transit any Google country; Vertex for regional |
| Amazon SES | email | n/a | ca-central-1 |
| Slack | delivery, if tenant opts in | tenant's own workspace | tenant's choice |
| Meta (Instagram, Facebook Pages) | inbound and outbound messages and comments on the tenant's own accounts | n/a: the conversation already lives on Meta's platform; Platform Terms apply, obtain the DPA | Meta's own regions |

Adding any provider is a register entry and a DPA, not just a config change. Telemetry: Pipecat has none by default; Dograh's PostHog default-on is one more reason not to adopt it.

**Retention:** per-tenant `retention_days` for transcripts (default 30), recordings (default off), usage detail (default 400 for invoicing). A nightly job deletes and writes a deletion receipt. **Audit:** every read of a conversation record, whether by a staff magic link or the ops CLI, writes an audit row. The access surface is small because there is no dashboard.

---

## 8. Skincentrix onboarding notes

What the bundle needs and what is still unknown:

- **Two Jane locations.** `services.yaml` carries a `booking_url` per service, so a service can deep-link to either Jane location. Service-level deep-linking is unverified; fall back to the location-level URL. Which services belong to "Skin & Scalp" must be asked.
- **Numbers.** One local Telnyx number for TELUS to forward to. One Canadian toll-free number, verified, for SMS and missed-call text-back. The text-back will come from the toll-free number, so the message must identify the clinic in its first words.
- **Forwarding.** TELUS Business Connect (RingCentral) forwards with original caller ID when "Incoming Caller ID" is selected rather than "Dialed Number". Verify with one test call at onboarding. The tenant identifies itself by which of our numbers was called, never by SIP Diversion headers.
- **Live transfer.** Requires a back-line on TELUS that does not forward to us. If none exists, business-hours transfer is replaced by a captured urgent callback, which the brief already allows after hours.
- **Hours.** The seven-day schedule is from a third-party listing. Confirm before the business-hours calendar is set, because every due time depends on it. If they really are open seven days, the product's job is overflow during treatments, and the sales pitch should say so.
- **Training courses** are a separate audience. A `training_enquiry` item type routes them to a different owner.
- **PHIPA.** With nurses, injectables and PRP they are likely a health information custodian. The clinical lexicon, recordings-off default and 30-day transcript retention should be presented to them as features, and the transcript limit in §5 stated plainly.
- **After-hours clinical contact** unknown. Until confirmed, the after-hours clinical script captures an urgent callback and tells the caller to contact emergency services if it is an emergency. That wording is fixed, not generated.

---

## 9. Sequence, if approved

Target: a working demo on our own numbers in days, then a pilot gated by three external clocks that do not compress. The detailed implementation plan is the next document.

**Day 0, paperwork that starts external clocks.** Telnyx account, one local and one toll-free number, toll-free SMS verification submitted (about five business days, double opt-in in Canada). Meta app created; Instagram Business Login configured; Skincentrix's Instagram admin added as a tester so Standard Access covers the pilot; Advanced Access review submitted for serving other clients (about 20 days reported). Telnyx Canadian rates read off the portal and `rates.json` corrected.

**Days 1 to 2, runtime core and voice.** Repo scaffold, Compose with Postgres and Caddy on the VPS. Capability interface and outcome types, Tier C fulfilment, renderer, guard, rules gate, prompt assembly, tenant config versions and bundle import, usage events. Pipecat voice adapter from the Telnyx example with Soniox, Smart Turn, Inworld, Gemini Flash; pre-synthesised disclosure. First real call answered on our local number. Flux and Aura-2 wired as alternatives so the bake-off is a config flip.

**Day 3, ledger and delivery.** Tracked items, business-hours SLA, escalation, Slack buttons, SES email with confirm-then-POST links, daily digest, human takeover state. promptfoo suite with the first 30 scenarios across the three bands, in CI.

**Day 4, text channels.** SMS adapter behind the Cloudflare Worker (works on the local number for testing until toll-free verifies), missed-call text-back, web widget on deep-chat, Instagram adapter from openreply's plumbing (comments and DMs) tested in Live mode with the tester account.

**Day 5, portal.** open-saas cloned and stripped, Organization and Membership added, runtime internal API, agency admin (tenants, usage, revenue), client pages (conversations, items, usage, config editor for hours, services, knowledge, scripts). Stripe in test mode.

**Days 6 to 7, operations and hardening.** Carrier failover bin, uptime monitor, WAL-G restore rehearsed, audit log, retention job, latency measured over 50 calls and the bake-off decided, cost model rerun with measured usage.

**Then, gated by the clinic.** TELUS forwarding test with caller ID, back-line confirmed, Skincentrix bundle authored with them, a shadow week, live.

---

## 10. Weaknesses, stated plainly

1. **The two largest cost lines rest on unpublished rates.** Telnyx's Canadian inbound per-minute and Canadian SMS carrier fees are not on any public page. The voice number swings between 0.025 and 0.031 CAD on this alone. It is a fifteen-minute portal check and it is item one in §0.
2. **Soniox and Inworld are smaller vendors, and Inworld's 25 ms first-byte figure is a vendor claim** not covered by any independent benchmark found. The bake-off in week one is not optional. If they lose, Deepgram Flux plus Aura-2 is the fallback and costs about 0.012 CAD per minute more, which still fits under the ceiling with Flash-Lite.
3. **Gemini 2.5 will be deprecated inside the 18-month horizon**, and the current newer generations are reasoning-first with worse first-token latency. A model swap is certain. The adapter makes it a config change; the regression suite is what makes it safe. Build the suite before the swap, not after.
4. **800 ms p95 is a budget, not a measurement.** Endpointing 200 to 300 ms plus Flash first token 430 ms plus TTS first byte 100 to 300 ms plus network is 750 to 1,100 ms. Flash-Lite (290 ms) or Cerebras gpt-oss-120b (470 ms, no retention) are the fallbacks if Flash misses. Filler audio ("one moment") is the last resort and costs call length.
5. **"Incapable of collecting medical history" is true for structured fields and not for transcripts.** The design minimises rather than prevents there. Say this to the client rather than let them discover it.
6. **Self-hosted Postgres on the app box at MVP** is a single point of failure operated by one person. Mitigated by WAL-G archiving every minute, OVH daily snapshots, and a rehearsed restore. Move to DigitalOcean Managed Postgres in Toronto at about ten tenants, or earlier if sleep matters more than CA$21 per month.
7. **Live transfer depends on a TELUS back-line that may not exist.** The design degrades to a captured urgent callback, which is honest but weaker than the brief's business-hours promise.
8. **Two apps in two languages.** The Python runtime and the TypeScript portal are a normal control-plane and data-plane split, but they are two codebases for one person. The mitigation is the rule that the portal owns no business logic and talks to the runtime only through its internal API, so the portal can be rebuilt on a plain Next.js starter in a week if Wasp ever becomes a problem.
9. **Wasp's multi-schema behaviour is unverified.** open-saas needs a single Prisma schema; whether Prisma's `multiSchema` flag survives Wasp's migrate is not documented. The design sidesteps it by giving the portal its own schema and no access to runtime tables, but if Prisma ever needs to read `runtime.*`, that is a database view or the internal API, not a shared table.
10. **"A few days" is the build, not the pilot.** Toll-free SMS verification, Meta Advanced Access and the clinic's forwarding test are external clocks. The demo on our own numbers is a days-scale target; the Skincentrix go-live is set by those clocks plus a shadow week.

---

## Appendix: evidence

- `docs/research/research-1a-voice-runtimes.md`: Dograh, Pipecat, LiveKit Agents, others
- `docs/research/research-1b-provider-pricing.md`: telephony, STT, TTS, LLM, speech-to-speech, latency benchmarks
- `docs/research/research-1c-sms-widget-delivery.md`: Canadian SMS, caller ID on forwarding, widget, email, Slack, takeover
- `docs/research/research-1d-repos-and-tooling.md`: suggested repos, observability, evals, ledger alternatives, config storage
- `docs/research/research-1e-hosting.md`: VPS, latency, Postgres, object storage, Cloudflare, carrier failover, queues
- `docs/research/research-2-adoption-check.md`: verified paths and contents of Pipecat examples, open-saas, openreply, portal fallbacks
- `docs/research/costmodel.py` and `docs/research/rates.json`: the cost model; run `python costmodel.py rates.json`
