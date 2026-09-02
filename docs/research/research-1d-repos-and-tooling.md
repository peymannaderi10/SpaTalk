# Research 1d — Suggested repos and tooling (evaluated 2026-09-01)

Product context: multi-tenant AI front desk (voice + SMS + web chat), one KB per tenant, handoff ledger delivered to staff via email/Slack, **no dashboard in MVP**, onboarding = config bundle. All GitHub numbers come from `api.github.com` on 2026-09-01.

## Summary verdicts

| # | Item | Licence | Stars / last push / open issues | Verdict |
|---|------|---------|----------------------------------|---------|
| 1 | wasp-lang/open-saas | MIT | 15.7k / 2026-08-06 / 103 | **SKIP** — bundles a customer dashboard, Stripe UI and landing page we do not ship; the Wasp compiler layer buys nothing for a voice/SMS backend. |
| 2 | knadh/listmonk | AGPL-3.0 | 23.2k / 2026-08-25 / 117 | **ADOPT LATER (Phase 3)** — transactional + campaign email via API, list-level roles; SMS only through a self-written "messenger" webhook. |
| 3 | xbirimensah/opensetter | MIT | 0 / 2026-08-02 / 0 | **SKIP** — a three-day, zero-star personal fork of openreply (Instagram DM bot); nothing on our channels. |
| 4 | calcom/cal.diy | MIT | 48.1k / 2026-09-01 / 1,424 | **ADOPT LATER (Phase 2, optional)** — it *is* the old Cal.com repo, relicensed MIT with teams/orgs/workflows removed; fine for demos, weak as a per-tenant booking engine. |
| 5 | langfuse/langfuse | MIT + `ee/` | 34.1k / 2026-09-01 / 875 | **ADOPT LATER (Phase 2)** — six containers, 16 GiB recommended; at MVP emit OTel spans to Postgres or one Phoenix container. |
| 6 | Conversation regression | — | — | **ADOPT promptfoo** (MIT) for the CI scenario suite; pair with Pipecat Evals or LiveKit's test framework for audio-mode checks. |
| 7 | Incident tools as ledger | — | — | **SKIP (trap)** — Grafana OnCall OSS is archived; Keep is a UI-first alert console; hand-roll the ledger table + Slack buttons. |
| 8 | Config/KB storage | — | — | **ADOPT (a)** git YAML/Markdown bundles synced into Postgres JSONB; add Payload only when a non-technical operator must edit. |

## 1. Open SaaS (wasp-lang/open-saas)

A Wasp-based SaaS boilerplate: React + Node + Prisma + Postgres with email-verified and social auth (email, Google, GitHub, Slack, Microsoft), Stripe/Polar/Lemon Squeezy payments, SendGrid/Mailgun/SMTP email, S3 uploads, cron/queues, an admin dashboard, Plausible/GA analytics, an Astro blog and an OpenAI demo (https://github.com/wasp-lang/open-saas; https://docs.opensaas.sh/). GitHub lists MDX as the language because of the docs; the app is TypeScript. Docs target "Wasp ≤0.23" while Wasp is at 0.24–0.25 (https://wasp.sh/docs; https://github.com/wasp-lang/wasp).

**Lock-in:** Wasp is a compiler generating client/server from `main.wasp.ts`. Its README claims "no lock-in… you have complete control over the code (…in `.wasp/` directory)", yet the maintainers' issue #2255 stresses Wasp is "a proper framework and not a one-shot code generator" (https://github.com/wasp-lang/wasp/issues/2255). Ejecting means adopting generated code: possible, not a supported workflow.

**For us:** with no customer dashboard in MVP, the auth UI, checkout, admin panel and landing page are dead weight; multi-tenant routing, telephony webhooks and workers are ours to write regardless. **Self-host:** Node + Postgres, small. **Verdict: SKIP** — revisit only if a customer portal ships in Phase 3, and even then a plain Next.js/Hono app is less risky than a 0.x compiler.

## 2. listmonk (knadh/listmonk)

Go single binary + Postgres newsletter/campaign manager. Transactional email: `POST /api/tx` with a `template_id`, `subscriber_emails` in `external` mode (no subscriber lookup), attachments via multipart, custom headers/data (https://listmonk.app/docs/apis/transactional/). "Messengers" are HTTP postback endpoints that receive campaign JSON and can "broadcast as SMS, FCM etc."; community adapters exist for AWS Pinpoint SMS, Verimor and Novu (https://listmonk.app/docs/messengers/). SMS is possible only via a webhook we host in front of Twilio. Multi-user with **list-level** permissions since v4.0.0; no workspaces or orgs (https://listmonk.app/docs/roles-and-permissions/). Multi-tenancy = one instance, one list and one list-role per tenant — workable, not isolated (templates and settings are shared).

**Self-host cost:** one binary + Postgres; RAM not stated (UNVERIFIED; a Go binary, expect well under 512 MB). AGPL is a non-issue if used unmodified over its API. **Verdict: ADOPT LATER (Phase 3)** for "outbound campaigns from tenant-supplied lists"; not needed before.

## 3. opensetter (xbirimensah/opensetter)

Created 2026-07-30, last push 2026-08-02, 0 stars, 0 forks, 121 commits, TypeScript, MIT. It is a fork of **diwenne/openreply** ("the open-source Manychat alternative", MIT, 1.9k stars, created 2026-07-17, pushed 2026-08-30; https://api.github.com/repos/diwenne/openreply), which watches Instagram post comments and sends keyword-triggered DMs through the official Meta API. opensetter adds an "AI DM setter" (Claude by default) that drafts replies in the owner's voice, qualifies prospects and drops a booking link, in draft-for-approval or autopilot mode; stack Next.js 16 + Prisma + Postgres + Redis (https://github.com/xbirimensah/opensetter). Instagram only. (Unrelated: myind-ai/openreply, a social-listening tool.)

**Honest read:** three days of activity, then a month of silence; nobody but the author uses it. Nothing covers voice, SMS or web chat. The only reusable idea is the draft-vs-autopilot switch. **Verdict: SKIP.** If Instagram DMs become a channel later, look at upstream openreply, not this fork.

## 4. cal.diy (calcom/cal.diy)

Not a fork or a distro: it is the original `calcom/cal.com` repository (created 2021-03-22, 16.5k commits) **renamed** to cal.diy and relicensed AGPL-3.0 → MIT when Cal.com took its production codebase private in April 2026 (https://cal.com/blog/cal-diy-open-source-to-closed-source). Removed: organizations, teams and multi-tenant management, Routing Forms, Workflows, Instant Booking, AI Phone, SAML/SSO, Insights, API v1, admin impersonation. It keeps the scheduling engine, app-store framework, booking pages and multiple user accounts on one instance; "self-hosted project. There is no hosted/managed version" (https://github.com/calcom/cal.diy). Stack Next.js/tRPC/Prisma/Postgres ≥13, Node ≥18. Pushed 2026-09-01; 1,424 open issues; community-maintained from here.

**For us:** spas mostly already run Mindbody/Vagaro/Square; the agent should book into those. cal.diy could be the fallback engine for tenants with nothing, one cal.diy user per tenant — no isolation, no Workflows, no Routing Forms. **Self-host cost:** a large Next.js monorepo + Postgres; multi-GB build memory (UNVERIFIED). **Verdict: ADOPT LATER (Phase 2, optional)**; for the founder's own demo scheduling it is fine today.

## 5. Langfuse and alternatives

Langfuse: tracing, evals, prompt management, datasets, playground; TypeScript. LICENSE is MIT with `ee/`, `web/src/ee/`, `worker/src/ee/` under a separate licence (https://github.com/langfuse/langfuse/blob/main/LICENSE). "All core Langfuse features and APIs are available in Langfuse OSS (MIT licensed) without any limits"; EE-only: project-level RBAC, protected prompt labels, data-retention policies, audit logs, server-side data masking, UI customization, org creators, org-management API/SCIM, instance-management API (https://langfuse.com/self-hosting/license-key). **Confirmed footprint:** web + worker + Postgres + ClickHouse + Redis/Valkey + S3/MinIO (https://langfuse.com/self-hosting); the compose guide recommends "at least 4 cores and 16 GiB of memory" and ~100 GiB storage, and says compose is not for production (https://langfuse.com/self-hosting/deployment/docker-compose).

| Tool | Licence | Stars / push | Self-host footprint |
|------|---------|--------------|---------------------|
| Langfuse | MIT + ee | 34.1k / 09-01 | six containers, 16 GiB recommended |
| Phoenix (Arize) | Elastic 2.0 — cannot be offered as a managed service; internal use fine (https://github.com/Arize-ai/phoenix/blob/main/LICENSE) | 11.3k / 09-01 | **single container**, SQLite default, Postgres optional (https://arize.com/docs/phoenix/self-hosting/deployment-options/docker) |
| Helicone | Apache-2.0 | 6.1k / 08-31 | all-in-one image bundling web, Jawn, MinIO, Postgres, ClickHouse; the image has no LLM proxy, no email, unauthenticated port 8585 (https://docs.helicone.ai/getting-started/self-host/docker) |
| OpenLLMetry | Apache-2.0 | 7.4k / 08-10 | SDK only (OTel instrumentation); needs any OTLP backend |
| Opik | Apache-2.0 | 21.7k / 09-01 | MySQL + Redis + ClickHouse + ZooKeeper + MinIO + backend + frontend; compose "not meant for production" (https://www.comet.com/docs/opik/self-host/local_deployment) |
| Laminar | Apache-2.0 | 3.2k / 09-01 | "lightweight" and "full" compose variants (https://github.com/lmnr-ai/lmnr); component list UNVERIFIED (docs URL 404) |

**Verdict: ADOPT LATER (Phase 2).** Transcripts must live in our Postgres anyway (the ledger needs them), so at MVP log OTel spans there and, if a trace UI is wanted, run Phoenix as one container on SQLite. Move to Langfuse when per-tenant prompt versioning and dataset-backed evals justify ClickHouse.

## 6. Conversation regression testing

- **promptfoo** — MIT, TypeScript, 24.7k stars, pushed 2026-09-02. Multi-turn via the `promptfoo:simulated-user` provider (`maxTurns`, per-test `instructions`), `llm-rubric` judge assertions, and custom providers so the "model under test" is our agent's HTTP endpoint (https://www.promptfoo.dev/docs/providers/simulated-user/). Python asserts: `type: python, value: file://assert.py`; the function receives `output` and a context with `vars`, `prompt`, `test`, and returns bool/score/GradingResult (https://www.promptfoo.dev/docs/configuration/expected-outputs/python/). CI: GitHub Action, `--fail-on-error`, cache via `PROMPTFOO_CACHE_PATH`, JSON/HTML/JUnit output (https://www.promptfoo.dev/docs/integrations/ci-cd/).
- **DeepEval** — Apache-2.0, Python, 18.0k stars. `ConversationalTestCase` of `Turn`s with scenario/expected_outcome, conversational metrics, a conversation simulator, pytest-native; Confident AI cloud "entirely optional" (https://deepeval.com/docs/evaluation-multiturn-test-cases). Python-only and metric-centric rather than scenario-centric.
- **Inspect (UK AISI)** — MIT, 2.7k stars. 200+ benchmarks, agents, sandboxing, model-graded scorers; built for research benchmarks, not product regression (https://inspect.aisi.org.uk/).
- **Braintrust** — hosted. Free: 1 GB processed data/month, 14-day retention; Pro $249/month, 5 GB, 30-day retention; self-host is Enterprise only (https://www.braintrust.dev/pricing).
- **Pipecat Evals** — built into `pipecat-ai[cli]`, `pipecat eval run`; YAML scenarios; text mode (bypasses STT/TTS) and audio mode (local Kokoro/Moonshine/Whisper); substring or LLM-judge (Ollama default), tool-call-with-arguments, context retention, interruption recovery and per-event latency assertions (https://docs.pipecat.ai/pipecat/fundamentals/evaluations/overview).
- **LiveKit Agents** — testing framework with pytest/Vitest, `.judge(llm, intent=…)`, tool-call/argument/handoff assertions, and multi-turn "agent simulations" (https://docs.livekit.io/agents/build/testing/).

**Recommendation:** promptfoo as the channel-agnostic CI gate — one YAML suite per tenant config, simulated-user scenarios ("caller wants a couples massage Saturday, then cancels"), Python asserts that check ledger side-effects, run on every prompt/config PR. Use the chosen voice framework's native evals (Pipecat or LiveKit) for audio-mode and latency checks. Skip Braintrust and Inspect.

## 7. Incident tools as a follow-up ledger

- **Grafana OnCall OSS** — AGPL-3.0, **archived 2026-03-24** after maintenance mode from 2025-03-11; Cloud-connected SMS/phone notifications were switched off (https://api.github.com/repos/grafana/oncall; https://grafana.com/blog/grafana-oncall-maintenance-mode/). Dead.
- **LinkedIn Oncall** — BSD-2, 1.3k stars, last push 2025-08-20; a shift-scheduling calendar, with paging in a separate project (Iris). Not a ledger.
- **Keep** — MIT + `ee/` (https://github.com/keephq/keep/blob/main/LICENSE), 12.3k stars, pushed 2026-08-24. FastAPI backend + Next.js UI + Soketi websocket + Postgres/MySQL, optional Keycloak (https://docs.keephq.dev/deployment/docker). The Slack provider supports Block Kit buttons/inputs and editable messages (https://docs.keephq.dev/providers/documentation/slack-provider). Workflows are YAML with alert/incident/interval/manual triggers; an `is_business_hours` helper exists, but SLA timers, escalation and named-owner routing are composed by hand (https://docs.keephq.dev/workflows/overview).

**Assessment: a trap.** (1) These model *alerts* (severity, dedup, noise), not *promises to a customer* (who, what was said, owner, due, resolution note); the mismatch leaks into every Slack message. (2) The parts we need — business-hours SLA, escalation to a named owner, per-tenant routing — are exactly what Keep leaves to YAML, so we write them anyway while running three or four extra containers. (3) "Staff never log into anything new" breaks the moment anyone needs Keep's UI, where most of its value lives. The hand-rolled version is a `handoff_items` table (tenant, channel, transcript ref, owner, due_at, state, evidence), a Slack Block Kit message with ack/resolve buttons behind one signed interactive endpoint, an email fallback with signed one-click links, and a cron for reminders and escalation. Steal Keep's "server-side state + editable Slack message" pattern, nothing else. **SKIP all three.**

## 8. Tenant config and KB storage with zero-deploy onboarding

**(a) YAML/Markdown bundles in a private git repo synced into Postgres.** Onboarding = a directory plus a PR; every change is diffable, reviewable and, via item 6, CI-tested before it ships. A `sync` job validates against a JSON Schema/zod, writes `tenants.config` JSONB, chunks and embeds the Markdown KB. No new service, no auth surface, no admin UI to secure. Cost: only technical operators can edit; tenants cannot self-serve (acceptable with no MVP dashboard).

**(b) Postgres JSONB edited through a lightweight admin.** NocoDB moved from AGPL to a non-OSI "Sustainable Use License" at 0.301.0 in January 2026 (https://api.github.com/repos/nocodb/nocodb/license; https://github.com/nocodb/nocodb/discussions/12891); quickstart is four containers (https://nocodb.com/docs/self-hosting/installation/docker). Directus is MSCL (free for internal use, GPL-3.0 after four years; https://github.com/directus/directus/blob/main/license), one Docker image, minimum 0.25 vCPU/512 MB (https://directus.com/docs/self-hosting/requirements). Payload is MIT, lives inside your Next.js app on your Postgres, with an official free multi-tenant plugin (https://payloadcms.com/docs/plugins/multi-tenant). pgweb is an MIT single binary for browse/query/export only, no row editing (https://github.com/sosedoff/pgweb). Editing raw JSONB in a grid is error-prone; schema validation on write is still needed.

**(c) Headless CMS.** Payload or Directus as the content model gives typed collections, an admin UI, versioning and an API. Downside: tenant config becomes "content" in someone else's schema, KB embeddings live outside the CMS anyway, and you inherit an admin surface to secure — the dashboard the MVP avoids.

**Recommendation for a solo founder: (a).** Git bundles are the source of truth, Postgres JSONB the runtime copy, promptfoo runs on the PR. Add Payload (MIT, same Postgres, multi-tenant plugin) in Phase 2 if an operator or tenant must edit without git; keep pgweb for read-only peeks.

## Sources actually fetched

- GitHub API (`api.github.com/repos/<owner>/<repo>`, 2026-09-01) for every repo in the tables above, plus `.../nocodb/nocodb/license`.
- Repo pages: github.com/{wasp-lang/open-saas, wasp-lang/wasp, wasp-lang/wasp/issues/2255, xbirimensah/opensetter, calcom/cal.diy, langfuse/langfuse/blob/main/LICENSE, Arize-ai/phoenix/blob/main/LICENSE, lmnr-ai/lmnr, keephq/keep, keephq/keep/blob/main/LICENSE, directus/directus/blob/main/license, sosedoff/pgweb}.
- Docs: docs.opensaas.sh; wasp.sh/docs; listmonk.app/docs/{apis/transactional, messengers, roles-and-permissions}; cal.com/blog/cal-diy-open-source-to-closed-source; langfuse.com/self-hosting{, /license-key, /deployment/docker-compose}; arize.com/docs/phoenix/self-hosting{, /deployment-options/docker}; docs.helicone.ai/getting-started/self-host/docker; comet.com/docs/opik/self-host/local_deployment; promptfoo.dev/docs/{providers/simulated-user, configuration/expected-outputs/python, integrations/ci-cd}; deepeval.com/docs/evaluation-multiturn-test-cases; inspect.aisi.org.uk; braintrust.dev/pricing; docs.pipecat.ai/pipecat/fundamentals/evaluations/overview; docs.livekit.io/agents/build/testing; docs.keephq.dev/{providers/documentation/slack-provider, workflows/overview, deployment/docker}; nocodb.com/docs/self-hosting/installation/docker; directus.com/docs/self-hosting/requirements; payloadcms.com/docs/plugins/multi-tenant.
- Web searches: openreply/opensetter provenance; Pipecat evals; Grafana OnCall archival (grafana.com/blog/grafana-oncall-maintenance-mode); cal.diy; Wasp lock-in; NocoDB licence change (github.com/nocodb/nocodb/discussions/12891).
- Failed (404): github.com/pipecat-ai/pipecat/tree/main/evals; laminar.sh/docs/self-hosting/setup; github.com/nocodb/nocodb/blob/develop/LICENSE.
