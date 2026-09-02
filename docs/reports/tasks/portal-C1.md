# portal Task C1: Clone open-saas, strip it, and settle the database question

Status: done with deviations
Commit: 6c4738c61214026561826ca2d8de5495dec6b74f
Tests: `cd portal/e2e-tests && npx playwright test` -> 9/9; `cd portal && wasp build` -> success; full portal suite (build + e2e) -> 10/10 checks
Interfaces produced: routes `/`, `/login`, `/signup`, `/request-password-reset`, `/password-reset`, `/email-verification`, `/app`, `/account`, `/pricing`, `/checkout`, `/privacy`, `/admin`, `/admin/users`, api `POST /payments-webhook`; env contract in `portal/.env.server.example` (`DATABASE_URL`, `JWT_SECRET`, `WASP_WEB_CLIENT_URL`, `WASP_SERVER_URL`, `ADMIN_EMAILS`, `PORTAL_EMAIL_PROVIDER`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM`, `MAIL_FROM_NAME`, `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_FRONTDESK`, `STRIPE_CUSTOMER_PORTAL_URL`, `RUNTIME_INTERNAL_URL`, `RUNTIME_INTERNAL_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)

## Template provenance

`wasp new portal -t saas` with `@wasp.sh/wasp-cli@0.25.0` (`wasp version` -> `0.25.0`) on Node v24.20.0, run 2026-09-02 inside WSL.

The CLI downloads `template.tar.gz` from `github.com/wasp-lang/open-saas` at the ref `wasp-v0.25-template` (strings in `wasp-bin`: `wasp-v`, `-template`, `open-saas`, `wasp-lang`, `template.tar.gz`). Resolved with `gh api`:

- repo `wasp-lang/open-saas`, annotated tag `wasp-v0.25-template` (tag object `8131901c637d45160b16521e2da3533c861f308c`)
- **commit `9ee052af84950433c76bffe999b317d24bc0205d`**, committed 2026-07-24, released 2026-07-27

This template is the newer TypeScript-spec Open SaaS: `main.wasp.ts` plus per-feature `*.wasp.ts` modules, React 19, Tailwind 4, shadcn, Prisma 5.19.1.

## The database question (behaviour 4)

Spiked on the local Postgres from `runtime/docker-compose.yml` (host port 5434), against two scratch databases so the real `spatalk` database was never the experiment. A `pg_dump -n runtime` backup was taken first.

- Order (a), portal first: `DATABASE_URL=…/spatalk_spike_a wasp db migrate-dev --name init` then `DATABASE_URL=postgresql+asyncpg://…/spatalk_spike_a uv run alembic upgrade head`. Both succeeded. `\dt runtime.*` -> 13 tables, `\dt public.*` -> 7 tables (Wasp auth + DailyStats + Logs + `_prisma_migrations`).
- Order (b), runtime first: alembic to head, then `wasp db migrate-dev`. Both succeeded; Prisma applied `20260902073235_init` without offering a reset, and `\dt runtime.*` was unchanged with `select count(*) from runtime.tenants` still readable.

**Result: one database, two schemas is the standard.** `portal/.env.server.example` points `DATABASE_URL` at `postgresql://spatalk:spatalk@localhost:5434/spatalk`, the same database the runtime uses (different URL scheme). The portal migration has since been applied there; `runtime.*` is intact at alembic head `0002`.

Two facts the spike surfaced that are now in `docs/runbooks/accounts-and-env.md` (new section "One database, two schemas"):

- `prisma migrate reset` / `wasp db reset` drops every schema Prisma can see, `runtime` included. Never run it against this database; point `DATABASE_URL` at a scratch database first. This is the one sharp edge of the shared layout.
- Wasp's job queue creates a third schema, `pgboss`, in the same database. It is portal-owned; no table is shared, so non-negotiable 7 holds.

The fallback (a second database `spatalk_portal`) is documented in the same runbook section with the exact `CREATE DATABASE` line, in case a future Prisma or Alembic release breaks the arrangement.

## What was removed

`src/demo-ai-app`, `src/landing-page`, `src/file-upload`, the `blog/` Astro site, the Plausible and Google Analytics providers and their env schemas plus the cookie-consent banner that existed for them, the Lemon Squeezy and Polar payment processors, the admin "Messages" dashboard, and the mock-user seed script. Prisma models `GptResponse`, `Task`, `File`, `ContactFormMessage`, `PageViewSource` are gone, as are `User.credits`, `User.lemonSqueezyCustomerPortalUrl` and the page-view columns of `DailyStats`. The three-directory template layout (`portal/app`, `portal/blog`, `portal/e2e-tests`) was flattened to the plan's `portal/` + `portal/e2e-tests/`.

## Deviations

- **The plan's `SMTP_USER` / `SMTP_PASS` are not Wasp's variable names.** Wasp 0.25 reads `SMTP_USERNAME` and `SMTP_PASSWORD`. Evidence: `.wasp/out/sdk/wasp/dist/server/email/index.js` -> `{ type: "smtp", host: env.SMTP_HOST, port: env.SMTP_PORT, username: env.SMTP_USERNAME, password: env.SMTP_PASSWORD }`. `portal/.env.server.example` uses Wasp's names and the runbook's variable table now lists the portal row separately from the runtime row. `docs/reference/api-surface.md` still says `SMTP_USER`/`SMTP_PASS` for the portal: that line is wrong and the orchestrator should correct it.
- **The email provider is a compile-time switch, `PORTAL_EMAIL_PROVIDER`.** Wasp bakes the provider into the generated app, and it refuses `Dummy` in `wasp build` ("app.emailSender must not be set to Dummy when building for production"). The default is SMTP, so production and CI builds are unaffected; `PORTAL_EMAIL_PROVIDER=Dummy wasp start` selects the Dummy provider for development and the e2e run. Wasp does not load `.env.server` when it evaluates `main.wasp.ts`, so the variable must be on the command line, which is what `playwright.config.ts` does.
- **The single Stripe plan was re-keyed in this task rather than in C6.** C1's env contract names `STRIPE_PRICE_ID_FRONTDESK`, which is incompatible with the template's `PAYMENTS_HOBBY/PRO/CREDITS_10_PLAN_ID`. `PaymentPlanId` is now a single `frontdesk` subscription. Billing is still keyed to `User`; C6 re-keys it to `Organization`. `STRIPE_CUSTOMER_PORTAL_URL` is honoured by `fetchCustomerPortalUrl` when set, otherwise a billing portal session is created through the API.
- **Three template demo pages were removed beyond the plan's list**: `/admin/settings`, `/admin/calendar`, `/admin/ui/buttons`. `/admin/settings` shipped a literal `// TODO implement` and an `alert("Not yet implemented")`, which the definition of done forbids, and the other two are pure component demos reachable only from the same sidebar group. The admin sidebar now shows Dashboard and Users.
- **`DefaultLayout` now actually redirects a non-admin.** The template returned `<Link to={...} replace />`, which renders an anchor and navigates nowhere; a non-admin stayed on `/admin` with an empty page. It is `<Navigate>` now, so `/admin` sends a non-admin to `/` and on to `/app`. The server-side refusal was already correct (`getDailyStats` throws 403).
- **Tests were written after the clone-and-strip, not before it.** The strip is mechanical deletion with no behaviour to specify; the behaviours that are specifiable (`/` redirects, `/app`, `/admin` denial, `/privacy`, signup-verify-login) were written as Playwright specs and run before they passed. Recorded red runs: run 1 failed to load the suite at all (`ReferenceError: exports is not defined in ES module scope` at `utils.ts:3`, the e2e package is CommonJS so `import.meta.url` is unusable); runs 2-5 failed with `Process from config.webServer exited early` / `Timed out waiting 300000ms from config.webServer`; run 6 was 8 passed, 1 failed (`the admin stats query refuses a user who is not an agency admin`: `Expected: 403, Received: 401`). Runs 7 and 8: 9 passed.
- **Playwright's web server is `wasp start`, not `run-wasp-app`.** `run-wasp-app dev` starts its own Postgres container and ignores `DATABASE_URL`, which defeats the point of the spike; it also left a container behind (`Conflict. The container name "/spatalkportal-…-db" is already in use`). `wasp start` uses `.env.server`. It also needs `</dev/null`: without stdin, Wasp's `prisma db execute --stdin` step blocks forever and the web server never comes up.
- **Chromium needed two system libraries in WSL**: `libnspr4` and `libnss3`, installed with apt as root (no password prompt). Noted in `portal/e2e-tests/README.md`.

## Notes for neighbours

- The app lives at `portal/` directly (`portal/main.wasp.ts`, `portal/src/`, `portal/schema.prisma`, `portal/e2e-tests/`), matching the plan's File Structure, not the template's `portal/app/`.
- C2: `schema.prisma` currently holds `User`, `DailyStats`, `Logs` only. `User` still carries `paymentProcessorUserId`, `subscriptionStatus`, `subscriptionPlan`, `datePaid`; C6 moves those to `Organization`.
- C2/C4: `/app` is a placeholder page at `src/client/AppPage.tsx` with the heading "Your front desk" (the e2e suite asserts that heading). The org-scoped routes `/app/:orgSlug/...` replace it.
- C4: `src/runtime/env.ts` already declares `RUNTIME_INTERNAL_URL` and `RUNTIME_INTERNAL_KEY` in the server env schema, so `api.ts` can read them from `wasp/server`'s `env`.
- C7: security headers and rate limits are not present yet; nothing in this task added middleware.
- C8: the CI job needs `libnspr4`/`libnss3` for Chromium, `PORTAL_EMAIL_PROVIDER=Dummy` for the e2e job, and must not run `wasp build` with that variable set (Wasp refuses Dummy for production builds).
- C9: `wasp build` is green at this commit, so the generated `.wasp/build/Dockerfile` is available as the base for `Dockerfile.server`.
