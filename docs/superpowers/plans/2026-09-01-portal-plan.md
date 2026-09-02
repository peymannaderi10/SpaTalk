# Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Contract level: files, exact interfaces, behaviours, tests. Tests first.

**Goal:** A portal where the agency sees every tenant's usage, cost and health, and each client sees their AI's conversations, tracked items, usage and settings, with login, organisations, invitations and Stripe billing, without the portal owning any business logic.

**Architecture:** `portal/` is a clone of wasp-lang/open-saas (Wasp 0.25, React 19, Prisma, PgBoss, shadcn) stripped to auth, payments, admin and email, plus an Organization model. It owns the Postgres `public` schema. Everything about tenants, conversations, items and usage is read and written through the runtime's new `/internal/*` HTTP API (Task C3, on the Python side), authenticated with a shared key and carrying the acting user's email for audit. A generated TypeScript client from the runtime's OpenAPI document is the only way the portal talks to the runtime.

**Tech Stack:** Wasp 0.25 (`wasp new -t saas`), TypeScript, Prisma (portal tables only), Stripe, Playwright; runtime side FastAPI + pydantic, `openapi-typescript` + `openapi-fetch` for the client.

**Spec:** `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md` §0 (brief change), §3 (control plane and data plane), §4 decision 12.4, §10 weaknesses 8 and 9. Depends on the runtime plan Task 14 and on text-channels B2 for the SMS usage fields.

## Global Constraints

- The portal holds no tenant configuration, conversation, item or usage data of its own. Its tables: `User`, `Organization`, `Membership`, `Invitation`, open-saas's `DailyStats`/`Logs`, and Stripe fields. A Prisma model that mirrors a runtime table is a defect.
- All runtime access goes through `portal/src/runtime/client.ts`, generated from `docs/contracts/runtime-internal.openapi.json`. No raw fetches to the runtime anywhere else.
- Every server operation that takes an organisation id calls `requireOrgAccess(context, orgId)` first. Agency admins (`User.isAdmin`) bypass; everyone else needs a Membership.
- The `X-Actor` header on every runtime call is the acting user's email; the runtime writes audit rows from it.
- No secrets in client code. Stripe, SMTP and the internal key live in `.env.server`.
- Landing page, blog, demo AI app, file upload and contact form from open-saas are removed, not hidden.

## File Structure

```
portal/                                   (wasp new -t saas, then stripped)
  main.wasp.ts                            app, db, auth (email + optional google), emailSender SMTP, routes, jobs
  schema.prisma                           User (+isAdmin), Organization, Membership, Invitation, Stripe fields
  src/auth/                               kept from template; add invitation acceptance
  src/organizations/{operations.ts, access.ts, OrgSwitcher.tsx, InvitePage.tsx}
  src/runtime/{client.ts (generated), api.ts (wrapper: key, actor, errors)}
  src/client/{OverviewPage.tsx, ConversationsPage.tsx, RequestsPage.tsx, SettingsPage.tsx, settings/*.tsx}
  src/admin/{TenantsPage.tsx, NewTenantWizard.tsx, HealthPage.tsx} (+ template analytics)
  src/payment/                            template Stripe plumbing re-keyed to Organization
  src/legal/PrivacyPage.tsx               public /privacy (Meta requirement)
  e2e-tests/                              Playwright: auth, orgs, client pages, admin pages
runtime/spatalk/http/internal.py          /internal/* router (Task C3)
runtime/spatalk/rates.py                  rates loader for cost estimates (copies docs/research/rates.json into the package)
runtime/spatalk/cli.py                    + `spatalk openapi`
docs/contracts/runtime-internal.openapi.json
runtime/tests/test_internal_api.py, test_contract_snapshot.py
```

---

### Task C1: Clone open-saas, strip it, and settle the database question

**Files:** `portal/**` (new), `docs/reports/tasks/portal-C1.md`

**Interfaces produced:** a Wasp app that builds, with routes `/login`, `/signup`, `/app` (placeholder), `/admin`, `/privacy`; env contract in `portal/.env.server.example`: `DATABASE_URL`, `JWT_SECRET`, `WASP_WEB_CLIENT_URL`, `WASP_SERVER_URL`, `ADMIN_EMAILS`, `SMTP_HOST/PORT/USER/PASS`, `MAIL_FROM`, `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_FRONTDESK`, `STRIPE_CUSTOMER_PORTAL_URL`, `RUNTIME_INTERNAL_URL`, `RUNTIME_INTERNAL_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (optional).

**Behaviour:**
1. `wasp new portal -t saas` at Wasp 0.25 (or clone `wasp-lang/open-saas` `template/app` at the commit tagged for 0.25). Record the exact commit in the report.
2. Remove `src/demo-ai-app`, `src/landing-page`, `src/file-upload`, the blog directory, `ContactFormMessage` and `File`/`GptResponse`/`Task` models and their routes, Plausible/GA analytics hooks, Lemon Squeezy and Polar payment providers. `/` redirects to `/login` when signed out and `/app` when signed in.
3. Keep email auth with verification; leave Google auth wired but disabled unless both `GOOGLE_CLIENT_*` are set. Email sender: SMTP provider using the SES variables.
4. Database spike, both orders, against one local Postgres containing the runtime schema: (a) `wasp db migrate-dev` then runtime `alembic upgrade head`; (b) the reverse. Pass: both succeed and `\dt runtime.*` and `\dt public.*` are untouched by the other tool. Record the result. If either order fails, set `DATABASE_URL` to a second database `spatalk_portal` on the same server and record that the two-database layout is the standard. Update `docs/runbooks/accounts-and-env.md` accordingly.
5. `/privacy` page with the privacy policy text for the platform (data collected: name, contact, service interest, transcripts with 30-day retention; subprocessor list from spec §7; contact email).

**Tests:** `wasp build` succeeds; Playwright: sign up, verify (email captured by a test mail sink), log in, land on `/app`; `/admin` denied for a non-admin; `/privacy` renders.

**Done when:** build and e2e pass; report written with the commit hash and the spike result. Commit `feat(portal): open-saas clone stripped to auth, billing, admin and email`.

---

### Task C2: Organizations, memberships, invitations

**Files:** `portal/schema.prisma`, `portal/src/organizations/*`, `portal/main.wasp.ts` (operations, routes), `portal/e2e-tests/orgs.spec.ts`

**Interfaces:**
- Prisma: `Organization { id, name, slug @unique, runtimeTenantId @unique, stripeCustomerId?, subscriptionStatus?, subscriptionPlan?, createdAt }`, `Membership { id, userId, organizationId, role: "OWNER" | "STAFF", @@unique([userId, organizationId]) }`, `Invitation { id, email, organizationId, role, token @unique, expiresAt, acceptedAt? }`.
- Server: `requireOrgAccess(context, organizationId): Promise<{ org, role }>` (throws 403 `HttpError`); `requireAdmin(context)`; operations `createOrganization` (admin only), `listMyOrganizations`, `inviteMember(orgId, email, role)` (OWNER or admin), `acceptInvitation(token)`, `removeMember`.
- Client: `OrgSwitcher` in the app shell; `/invite/:token` page; current org in URL `/app/:orgSlug/...`.

**Behaviour:** invitations expire in 7 days and are single use; accepting while signed out goes through signup then accept; an OWNER can invite STAFF and OWNER; STAFF can view everything in their org and act on items but cannot change settings or billing.

**Tests:** unit tests for `requireOrgAccess` (member ok, non-member 403, admin bypass); Playwright: admin creates org, invites an email, second browser accepts and sees the org; STAFF cannot open settings.

**Done when:** tests pass. Commit `feat(portal): organizations, memberships and invitations`.

---

### Task C3: Runtime internal API and its contract (Python side)

**Files:** `runtime/spatalk/http/internal.py`, `runtime/spatalk/rates.py`, `runtime/spatalk/http/app.py` (include router, `/healthz` gains `config_versions`), `runtime/spatalk/cli.py` (`openapi`), `runtime/spatalk/settings.py` (`internal_api_key`), `docs/contracts/runtime-internal.openapi.json`, `runtime/tests/test_internal_api.py`, `runtime/tests/test_contract_snapshot.py`

**Interfaces (all under `/internal`, require header `X-Internal-Key`, compared in constant time; optional `X-Actor` for audit):**
- `GET /tenants` → `[{id, name, version, numbers: [{number, kind}], sms_from_number, integration_tier}]`
- `POST /tenants` body `{config: TenantConfig JSON, created_by}` → `{id, version}` (creates or new version)
- `GET /tenants/{id}/config` → `{version, config}`
- `PUT /tenants/{id}/config` body `{config, created_by}` → `{version}`; 422 with pydantic errors on invalid config
- `GET /tenants/{id}/config/versions` → `[{version, created_by, created_at}]`
- `POST /tenants/{id}/config/rollback` body `{version, created_by}` → `{version}` (new version equal to the old one)
- `GET /tenants/{id}/usage?from=YYYY-MM-DD&to=YYYY-MM-DD` → `{days: [{date, calls, call_minutes, sms_in, sms_out, chats, ig_messages, llm_input_tokens, llm_cached_tokens, llm_output_tokens, tts_chars, est_cost_cad}], totals: {...}}`
- `GET /tenants/{id}/conversations?from&to&channel&band&page&page_size` → `{items: [{id, channel, started_at, ended_at, duration_s, band, health_context, controller, item_count, caller_masked}], total}` (caller masked to last 4 digits in lists)
- `GET /conversations/{id}` → `{conversation, messages: [{role, text, created_at}], items: [...]}`; writes an audit row `read_transcript` with actor from `X-Actor`
- `GET /tenants/{id}/items?state=open|acknowledged|resolved|all` → `[Item]`
- `POST /items/{id}/acknowledge` and `/resolve` body `{actor}` → `Item`
- `GET /tenants/{id}/latency?from&to` → `[{date, turns, p50_ms, p95_ms}]`
- `GET /tenants/{id}/health` → `{open_items, overdue_items, last_call_at, last_sms_at, config_version}`
- `GET /health` → `{ok, queued_jobs, oldest_queued_age_s, dead_jobs}`
- `GET /rates` → the rates JSON; `spatalk.rates.estimate_cad(usage_totals) -> float` used for `est_cost_cad`
- `POST /audit` body `{actor, action, record_type, record_id}` → 204
- `spatalk openapi` prints the app's OpenAPI JSON; `docs/contracts/runtime-internal.openapi.json` is that output filtered to `/internal` paths.

**Behaviour:** all list endpoints paginate (default 50, max 200); dates are interpreted in the tenant's timezone; usage aggregates come from `usage_events` grouped by day and unit; cost estimate multiplies by the rates table copied into the package at build time (`spatalk/rates.json`, refreshed by a `make sync-rates` target from `docs/research/rates.json`).

**Tests:** missing or wrong key 401; each endpoint against the test DB with seeded conversations, items and usage; invalid config PUT returns 422 with a field path; rollback produces version N+1 equal to version K; transcript read writes audit with the actor; contract snapshot test regenerates the OpenAPI JSON and fails if it differs from the committed file (so contract changes are deliberate).

**Done when:** tests pass, contract file committed. Commit `feat(runtime): internal api for the portal with openapi contract`.

---

### Task C4: Client pages

**Files:** `portal/src/runtime/{client.ts, api.ts}`, `portal/src/client/**`, `portal/main.wasp.ts`, `portal/package.json` (`openapi-typescript`, `openapi-fetch`, `apexcharts`, `react-apexcharts`), `portal/e2e-tests/client.spec.ts`

**Interfaces:** `npm run gen:client` regenerates `client.ts` from `docs/contracts/runtime-internal.openapi.json`; `api.ts` exports `runtime(actorEmail)` returning a typed client that adds `X-Internal-Key` from `RUNTIME_INTERNAL_KEY` and `X-Actor`.

**Behaviour:**
1. `/app/:orgSlug/overview`: this month's calls, minutes, texts, chats, items open and overdue, p95 latency, estimated cost; a 30-day usage chart; a "needs attention" list of overdue items.
2. `/app/:orgSlug/conversations`: filterable list; clicking opens a transcript drawer (the read writes the audit row through the API); health-context flag shown as a badge; band shown as a label ("handled", "sent to team", "to a person").
3. `/app/:orgSlug/requests`: open and acknowledged items with Acknowledge and Resolve buttons calling the API with the user's email as actor; resolved tab.
4. `/app/:orgSlug/settings`: tabs Hours, Services, Knowledge, Scripts, Delivery, Numbers (read-only). Forms are generated from the runtime's pydantic schema (served at `GET /internal/schema/tenant-config` added in C3 if not already: add it). Save calls `PUT config`; validation errors map to fields; a Versions panel lists versions with a Roll back button. OWNER only; STAFF sees read-only.
5. All pages gated by `requireOrgAccess`; STAFF role restrictions enforced server side, not just in the UI.

**Tests:** Playwright against a running runtime seeded with one tenant and fixtures: overview shows the seeded counts; opening a transcript creates an audit row (verify via `GET /internal/…` or the DB); resolving an item changes its state; saving hours produces a new config version and `/healthz` shows the new version within 30 s; rollback restores; STAFF cannot save settings (server 403).

**Done when:** e2e passes. Commit `feat(portal): client overview, conversations, requests and settings backed by the runtime api`.

---

### Task C5: Agency admin pages and onboarding wizard

**Files:** `portal/src/admin/{TenantsPage.tsx, NewTenantWizard.tsx, HealthPage.tsx}`, `portal/main.wasp.ts`, `portal/e2e-tests/admin.spec.ts`

**Behaviour:**
1. `/admin/tenants`: every organisation with runtime usage this month, estimated cost, Stripe subscription status and MRR, open and overdue items, last activity, config version. Sortable.
2. `/admin/tenants/new`: wizard: organisation name and slug; upload the five bundle files (or paste YAML); the portal converts them with the same rules as `load_bundle` by posting the raw files to a new runtime endpoint `POST /internal/tenants/from-bundle` (multipart, added to C3's router in this task with a test); invite the owner email; show the numbers to buy and the Slack channel to create as a checklist linking to the runbook.
3. `/admin/health`: runtime `/internal/health` and `/healthz`, queue age, dead jobs, last deploy commit (from `GET /healthz` `commit` field, added: the runtime reads `GIT_COMMIT` env set by the Dockerfile).
4. Keep open-saas's revenue and users analytics page; add MRR per tenant from `Organization.subscriptionStatus`.

**Tests:** Playwright: admin creates a tenant from the Skincentrix bundle files, the runtime lists it, the owner invitation is created; health page renders queue numbers.

**Done when:** e2e passes. Commit `feat(portal): agency admin tenants table, onboarding wizard and health page`.

---

### Task C6: Billing per organisation

**Files:** `portal/src/payment/**` (re-keyed), `portal/main.wasp.ts`, `portal/e2e-tests/billing.spec.ts`

**Behaviour:** Stripe Checkout for the `STRIPE_PRICE_ID_FRONTDESK` price with `client_reference_id = organizationId` and `customer_email = owner`; the webhook (open-saas's handler) updates `Organization.stripeCustomerId`, `subscriptionStatus`, `subscriptionPlan`; the customer portal link opens Stripe's portal; client pages other than Overview require `subscriptionStatus in (active, trialing)` unless the user is an admin; a banner explains when it is not.

**Tests:** webhook fixture events (`checkout.session.completed`, `customer.subscription.deleted`) update the organisation; gating renders the banner for a past-due org; admin bypass.

**Done when:** tests pass in Stripe test mode with the CLI's fixture events. Commit `feat(portal): stripe subscription per organisation`.

---

### Task C7: Security and audit hardening

**Files:** `portal/src/server/security.ts`, `portal/main.wasp.ts`, `portal/src/runtime/api.ts`

**Behaviour:** rate limit login, signup and invitation endpoints (10 per minute per IP); security headers (CSP allowing only self and Stripe, frame-ancestors none, HSTS); session cookie `Secure`, `SameSite=Lax`; every transcript view and every settings save carries `X-Actor`; failed runtime calls surface as a friendly error, never a raw stack; the internal key is read once at server start and never logged.

**Tests:** header assertions in Playwright; rate limit unit test; a log-scrub test that the key never appears in server logs during a failing call.

**Done when:** tests pass. Commit `chore(portal): rate limits, security headers, audit actor on every runtime call`.

---

### Task C8: Portal CI and contract drift check

**Files:** `.github/workflows/ci.yml` (portal job), `portal/package.json` scripts, `docs/contracts/README.md`

**Behaviour:** CI job starts Postgres, runs the runtime with `uv` on port 8000 with a seeded tenant, builds the portal, runs Playwright against both; a separate step regenerates `client.ts` and fails if it differs from the committed file (contract drift in either direction is a deliberate commit).

**Done when:** CI green on a clean push. Commit `ci(portal): build, e2e against the runtime, contract drift check`.

---

### Task C9: Containerise the portal and route it through Caddy

**Files:** `portal/Dockerfile.server` (from Wasp's generated `.wasp/build/Dockerfile`), `portal/Dockerfile.web` (build the client, serve static with Caddy's file server), `runtime/docker-compose.yml` (services `portal-server`, `portal-web`), `runtime/Caddyfile` (two new sites), `docs/runbooks/deploy.md`

**Interfaces:** hosts `APP_HOST=app.<domain>` (client static) and `APP_API_HOST=app-api.<domain>` (Wasp server). Env contract: `WASP_WEB_CLIENT_URL=https://app.<domain>`, `WASP_SERVER_URL=https://app-api.<domain>`, client build arg `REACT_APP_API_URL=https://app-api.<domain>`. Stripe webhook and Google OAuth redirect therefore point at `app-api.<domain>` (already reflected in the runbook).

**Behaviour:** `wasp build` in a builder stage; the server image runs `npm run start` from `.wasp/build/server` on port 3001 with `.env.server` via Compose `env_file`; the web image contains the built client and a minimal Caddyfile serving it with SPA fallback; the main Caddy adds `{$APP_HOST}` → `portal-web:80` and `{$APP_API_HOST}` → `portal-server:3001`; `wasp db migrate-dev` is not used in production: the server image runs `npx prisma migrate deploy` on start.

**Tests:** `docker compose build portal-server portal-web` succeeds in CI; `docker compose up` locally serves the login page on the app host and `/auth/me` on the API host; the deploy runbook gains the portal steps.

**Done when:** CI builds both images. Commit `ops(portal): containers and caddy routes for app and app-api hosts`.

---

## Self-review against the spec

- Spec §0 brief change (portal for agency and clients): C4, C5. Staff still get Slack and email; the portal is for owners and us.
- Spec §3 control plane and data plane, zero shared tables: Global Constraints, C1 spike, C3 contract, C8 drift check.
- Decision 12.4 (config in Postgres, versioned, portal-edited, YAML import): C3 config endpoints, C4 settings, C5 bundle import.
- Weakness 8 (two codebases): the portal owns no business logic; C3's contract is the seam; a rebuild on another starter reuses `client.ts`.
- Weakness 9 (Wasp multi-schema): C1 step 4 settles it on day one with a recorded result and a fallback.
- Compliance: every transcript read from the portal is audited (C3, C4, C7); privacy page exists for the Meta app (C1).
