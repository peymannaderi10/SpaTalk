# Adoption check (verified 2026-09-01)

## 1. Pipecat: Telnyx example, Flows, Soniox, Inworld

**Telnyx example** — `pipecat-ai/pipecat-examples/telnyx-chatbot/{inbound,outbound}/` (repo last commit 2026-09-01).
- `inbound/` contains `bot.py, README.md, env.example, Dockerfile, pcc-deploy.toml, pyproject.toml` — **no server.py** (raw URL 404). Inbound flow: a Telnyx-hosted **TeXML Bin** returns `<Connect><Stream url="wss://.../ws" bidirectionalMode="rtp">`, assigned to the number via a TeXML Application; you run `uv run bot.py --transport telnyx --proxy <ngrok>`. The example itself serves no webhook; the generic runner (`pipecat/runner/run.py`) does: `@app.post("/")` returns a Telnyx TeXML template and `@app.websocket("/ws")` / `/ws/{token}` accept the stream; `--transport` choices include `twilio, telnyx, plivo, exotel`.
- `bot.py` uses `pipecat.runner.utils.create_transport`, `pipecat.runner.types.RunnerArguments`, `pipecat.transports.websocket.fastapi.FastAPIWebsocketParams`, `pipecat.runner.run.main`. Telnyx specifics are in `pipecat/runner/utils.py`: `from pipecat.serializers.telnyx import TelnyxFrameSerializer`, `from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport`; `parse_telephony_websocket` detects Telnyx by `stream_id`/`start`/`call_control_id` and builds `TelnyxFrameSerializer(stream_id=..., call_control_id=call_data["call_id"], outbound_encoding=..., inbound_encoding="PCMU", api_key=os.getenv("TELNYX_API_KEY"))`. Serializer defaults `auto_hang_up=True` and POSTs `api.telnyx.com/v2/calls/{id}/actions/hangup`.
- `outbound/` adds `server.py` with `POST /start` (dials via Telnyx REST) plus the WS endpoint.
- Take: write your own FastAPI TeXML webhook that puts a tenant token in the stream URL (`/ws/{token}`), then reuse `parse_telephony_websocket` + the serializer construction above.

**Flows** — **`pipecat-ai/pipecat-flows` was archived 2026-07-05**; Flows is in core `pipecat-ai` (v1.5.0+; latest v1.8.1, 2026-08-27) under `src/pipecat/flows/{manager,types,actions,adapters}.py`. Import: `from pipecat.flows import FlowManager, NodeConfig`. Examples now at `pipecat/examples/flows/`: `hello_world.py, food_ordering.py, food_ordering_advanced_functionschema.py, insurance_quote.py, llm_switching.py, multi_worker_handoff.py, patient_intake.py, podcast_interview.py, restaurant_reservation.py, warm_transfer.py`. Per-node tools confirmed in `food_ordering.py`: `NodeConfig(name="initial", ..., pre_actions=[...], functions=[choose_pizza, choose_sushi])`, later `functions=[select_pizza_order]`, `functions=[complete_order, revise_order]`. Do not clone the old repo.

**Soniox** — `class SonioxSTTService(WebsocketSTTService)` in `src/pipecat/services/soniox/stt.py`; import `from pipecat.services.soniox.stt import SonioxSTTService`; ctor `api_key`, `url` (default `wss://stt-rt.soniox.com/transcribe-websocket`), `sample_rate`, `audio_format="pcm_s16le"`, `vad_force_turn_endpoint=True`.

**Inworld** — `src/pipecat/services/inworld/tts.py` defines `class InworldTTSService(WebsocketTTSService)` and `class InworldHttpTTSService(TTSService)`; ctor `api_key`, `voice_id`, `model`. Import `from pipecat.services.inworld.tts import InworldTTSService`.

## 2. open-saas (wasp-lang/open-saas)

15.7k stars, MIT, last commit 2026-08-06. Layout: `template/{app,blog,e2e-tests}`, `opensaas-sh/`, `template-test/`, `tools/`.

- **(a) Wasp version**: `template/app/main.wasp.ts` declares `version: "^0.25.0"`; latest Wasp release is **v0.25.0 (2026-07-27)** — **no lag** (commits "Bump Wasp to 0.24.0" 2026-05-19, "Update to Wasp 0.25" 2026-06-19). Config is now TypeScript (`main.wasp.ts`), not `main.wasp`.
- **(b) Per-user only.** `schema.prisma` models: `User` (isAdmin, subscriptionStatus/Plan, credits), `GptResponse`, `Task`, `File`, `DailyStats`, `PageViewSource`, `Logs`, `ContactFormMessage`. No Organization/Team/Tenant/Workspace model; docs never mention teams.
- **(c) Admin dashboard** (`/admin`, `src/admin/`): Analytics page (total + last-7-day revenue from the payment processor; page views, deltas, top referrers from Plausible or Google Analytics; user/paying-user counts from DB via hourly PgBoss `calculateDailyStatsJob`) and a Users list. Charts: **ApexCharts 5.10.1 / react-apexcharts 2.1.0**. Gating: `User.isAdmin` seeded by `ADMIN_EMAILS`. UI: shadcn/Radix, Tailwind 4, React 19.
- **(d) Auth**: `src/auth/auth.wasp.ts` enables **email only**; Google/GitHub/Discord present but commented out. README advertises Slack/MS — not enabled in code (UNVERIFIED beyond README).
- **(e) Payments**: Stripe, Lemon Squeezy, Polar; pick one by exporting `paymentProcessor` in `src/payment/paymentProcessor.ts` (deps `stripe 18.1.0`, `@polar-sh/sdk`, `@lemonsqueezy/lemonsqueezy.js`).
- **(f) Strip**: `src/demo-ai-app/` (OpenAI task demo + `GptResponse`/`Task` models + `openai` dep), `src/landing-page/`, `template/blog/` (separate Astro Starlight site), `src/file-upload/` + S3 deps + `File` model, `ContactFormMessage`, unused payment dirs, `src/analytics/` if unwanted.
- **(g) DB**: Prisma (package.json pins `prisma 5.19.1`), `datasource url = env("DATABASE_URL")`. Wasp docs: `DATABASE_URL` may point at any external Postgres; constraints: single `schema.prisma`, provider postgresql/sqlite, `prisma-client-js` generator required, **`previewFeatures` allowed**. **No Wasp docs cover "existing database" foreign tables or multi-schema**; search results say Wasp does not support multiple Prisma schema files. Reasoning (UNVERIFIED in docs): keep Wasp tables in `public` via `wasp db migrate-dev`, put runtime tables in a separate Postgres schema owned by the Python service; whether Prisma 5.19's `multiSchema` flag behaves under Wasp's migrate is UNVERIFIED (community thread returned 403).

## 3. openreply (diwenne/openreply)

1.9k stars, MIT, last commit 2026-08-30. Stack: **Next.js 16, React 19, Prisma 7 + Postgres, BullMQ on Redis (`worker/`), Auth.js/NextAuth + Resend, Tailwind**. Already has a `workspace` concept (`app/api/workspace`, `lib/workspace*.ts`, invitations).

- **Login**: **Instagram Login (Business Login)**, not Facebook Login for Business (setup.md: "do not pick Authenticate with Facebook Login"). `lib/meta/oauth.ts`: authorize at `https://www.instagram.com/oauth/authorize` (comment: `api.instagram.com/oauth/authorize` now 404s), scopes `instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments,instagram_business_manage_insights`; code exchange `https://api.instagram.com/oauth/access_token`. Long-lived tokens: `lib/meta/client.ts` calls `/access_token` and `/refresh_access_token` on `graph.instagram.com`; a daily cron refreshes; tokens encrypted at rest (`ENCRYPTION_KEY`).
- **Webhooks**: Instagram fields `comments` + `messages` (setup.md: both required or nothing fires); also `POST /{ig-user-id}/subscribed_apps`. `app/api/webhook/route.ts` GET: `hub.mode=="subscribe" && hub.verify_token==WEBHOOK_VERIFY_TOKEN` → echo challenge; POST: HMAC-SHA256 `X-Hub-Signature-256` via `verifyWebhookSignature(rawBody, signature)` checked against both `FACEBOOK_APP_SECRET` and `INSTAGRAM_APP_SECRET`; parses comment/message/postback/read events into BullMQ jobs. No Messenger/Page webhooks.
- **Sending DMs**: `POST graph.instagram.com/{v}/{instagramAccountId}/messages` with `{"recipient":{"comment_id":...},"message":{"text":...}}` (private reply); public reply `POST /{commentId}/replies`; follow-gate `GET /{recipientId}?fields=is_user_follow_business`. No `private_replies`, no Page `/me/messages`.
- **Permissions** (setup.md): Standard Access to `instagram_business_basic`, `instagram_business_manage_comments`, `instagram_business_manage_messages`; Advanced Access (App Review) only to serve strangers' accounts. Meta's Instagram app-review page agrees: single-business = no review; Tech Provider = review.
- **Testing before review**: Meta: Development-mode apps can request permissions only from role users; unapproved permissions work only for role users. Instagram messaging doc: testers need a role on the app and on the IG professional account. But the Instagram webhooks doc says "Apps must be set to Live … to receive webhook notifications", and setup.md confirms real webhooks only arrive in Live mode (Dev mode only delivers the console Test button). Net: **Live mode + Standard Access + Instagram testers = full end-to-end testing without App Review**; onboarding client accounts needs Advanced Access (third parties add Business Verification).
- **Review duration**: no number in Meta docs fetched. bundle.social (2026-08-04) reports the App Review dashboard now says expect ~20 days (was 10); singhamandeep.com says messaging permissions usually 3–5 business days. Both secondhand — treat "1–4 weeks, budget 20 days" as UNVERIFIED-official.

## 4. Next.js fallbacks

**boxyhq/saas-starter-kit** — 4.9k stars, Apache-2.0, ~2,270 commits; last commits 2026-05-08 are all dependabot bumps (feature work looks stalled). next 15.5.14, react 18.3.1, next-auth 4.24.13, prisma 6.10.0, stripe 17.7.0, tailwind 3.4 + daisyui 4, saml-jackson 26.2. Full **teams** (create/delete, members, roles, invitations), Stripe billing, SAML SSO, Svix webhooks, Retraced audit logs, Playwright. Heaviest, but closest to "agency + client tenants" out of the box.

**nextjs/saas-starter (Vercel)** — 16.1k stars, MIT; last commit 2025-12-11 (CVE bump to next 15.6.0-canary.59; last feature commit 2025-06). Drizzle + Postgres, shadcn/ui, Tailwind 4, React 19, **custom JWT-cookie auth via `jose` + bcryptjs** (no NextAuth), teams with Owner/Member RBAC + invitations, Stripe Checkout + Customer Portal, activity log. Small and readable; low maintenance cadence.

## 5. Python-side alternative

**fastapi/full-stack-fastapi-template** — 45.3k stars, MIT, active (commits 2026-09-01). FastAPI + SQLModel + Postgres; React/TS/Vite + Tailwind + shadcn/ui; JWT auth, user management with admin UI, email password recovery (React Email, Mailpit), pytest + Playwright, GitHub Actions, Docker Compose + Traefik. **No Stripe, no teams/orgs** — you'd add tenants and billing yourself.

## Sources actually fetched

- https://github.com/pipecat-ai/pipecat-examples ; /tree/main/telnyx-chatbot ; /tree/main/telnyx-chatbot/inbound ; /tree/main/telnyx-chatbot/outbound ; https://api.github.com/repos/pipecat-ai/pipecat-examples/commits?per_page=1
- https://raw.githubusercontent.com/pipecat-ai/pipecat-examples/main/telnyx-chatbot/inbound/bot.py (server.py → 404)
- https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/runner/utils.py ; .../runner/run.py ; .../serializers/telnyx.py ; .../services/soniox/stt.py ; .../services/inworld/tts.py ; .../examples/flows/food_ordering.py
- https://github.com/pipecat-ai/pipecat/tree/main/src/pipecat/flows ; /tree/main/examples ; /tree/main/examples/flows ; https://api.github.com/repos/pipecat-ai/pipecat/releases/latest
- https://github.com/pipecat-ai/pipecat-flows ; /tree/main/examples ; /blob/main/examples/README.md ; raw examples/food_ordering.py
- https://github.com/wasp-lang/open-saas ; /commits/main ; /tree/main/template ; /tree/main/template/app ; /tree/main/template/app/src ; raw template/app/main.wasp.ts, package.json, schema.prisma, src/auth/auth.wasp.ts
- https://github.com/wasp-lang/wasp/releases ; /releases/tag/v0.25.0 ; https://api.github.com/repos/wasp-lang/wasp/releases/latest
- https://wasp.sh/docs/data-model/databases ; https://wasp.sh/docs/data-model/prisma-file ; https://www.prisma.io/docs/orm/prisma-schema/data-model/multi-schema (answeroverflow thread → 403)
- https://docs.opensaas.sh/ ; /general/admin-dashboard/ ; /guides/authentication/ ; /guides/payment-integrations/
- https://github.com/diwenne/openreply ; /commits/main ; /blob/main/docs/setup.md ; /tree/main/app/api ; /tree/main/app/api/webhook ; /tree/main/lib ; /tree/main/lib/meta ; raw app/api/webhook/route.ts, lib/meta/client.ts, lib/meta/oauth.ts
- https://developers.facebook.com/docs/development/build-and-test/app-modes/ ; /docs/instagram-platform/app-review/ ; /docs/instagram-platform/webhooks ; /docs/instagram-platform/instagram-api-with-instagram-login/messaging-api ; /docs/resp-plat-initiatives/individual-processes/app-review
- https://bundle.social/blog/meta-app-review-20-days ; https://singhamandeep.com/instagram-messaging-api-approval-getting-instagram_business_manage_messages-2026/
- https://github.com/boxyhq/saas-starter-kit ; /commits/main ; raw package.json
- https://github.com/nextjs/saas-starter ; /commits/main ; raw package.json
- https://github.com/fastapi/full-stack-fastapi-template ; /commits/master
