# portal Task C4: Client pages

Status: done with deviations
Commit: <filled below>
Tests: `cd portal/e2e-tests && RUNTIME_INTERNAL_URL=… npx playwright test tests/client.spec.ts` -> 16/16; full portal suite -> 77/77 (`npx playwright test` 32, `wasp test client run` 34, `npm run test:unit` 11) plus `wasp build` and `npx tsc -p tsconfig.src.json --noEmit` clean

Interfaces produced:
`npm run gen:client` (regenerates `portal/src/runtime/client.ts` from `docs/contracts/runtime-internal.openapi.json`); `portal/src/runtime/client.ts` (generated `paths`/`components`); `runtime(actorEmail) -> RuntimeClient`, `runtimeCall(call, what) -> T` and `type RuntimeClient` in `portal/src/runtime/api.ts`; `fieldErrorsFrom`, `summariseFieldErrors`, `friendlyRuntimeMessage`, `type FieldError` in `portal/src/runtime/errors.ts`; queries `getTenantOverview`, `getTenantConversations`, `getTenantRequests`, `getTenantSettings` and actions `readConversation`, `acknowledgeItem`, `resolveItem`, `saveTenantConfig`, `rollBackTenantConfig` in `portal/src/client/operations.ts`; routes `/app/:orgSlug/overview`, `/app/:orgSlug/conversations`, `/app/:orgSlug/requests`, `/app/:orgSlug/settings` (`clientPagesSpec` in `portal/src/client/pages.wasp.ts`); components `OrgShell`, `Problem`, `OverviewPage`, `ConversationsPage`, `RequestsPage`, `SettingsPage`, `HoursTab`, `ServicesTab`, `KnowledgeTab`, `ScriptsTab`, `DeliveryTab`, `NumbersTab`, `VersionsPanel`, `SchemaInput`; schema readers `fieldsOf`, `objectFields`, `rootFields`, `definition` in `portal/src/client/settings/schemaFields.ts`; display helpers `bandLabel`, `itemTypeLabel`, `channelLabel`, `isOverdue`, `formatDateTime`, `formatDuration`, `formatCad`, `formatMinutes` in `portal/src/client/formatting.ts`; e2e harness `portal/e2e-tests/{global-setup.ts, seed_runtime.py, tests/runtime.ts}`.

## What the tests assert

End to end (`portal/e2e-tests/tests/client.spec.ts`, 16), against a runtime seeded with one
tenant, four conversations, four tracked items and a day of usage:

- the overview shows this month's counts from the runtime (2 calls, 6.0 call minutes, 4
  texts, 1 chat, 3 open requests, 1 overdue, a p95 in ms and a cost in dollars), draws a
  thirty-day chart, and lists the overdue item by number, contact and the word "Overdue";
- the conversations list labels each band ("handled", "sent to team", "to a person"),
  badges the health-context conversation, shows the caller masked (`***0101`) and never the
  whole number, and narrows to one channel and back;
- opening a transcript shows what was said and leaves one new `audit_log` row with action
  `read_transcript` and actor `portal:<the signed-in email>`;
- the requests page splits open (open + acknowledged) from resolved, and acknowledging and
  then resolving one changes its state in the runtime's own table, naming the person;
- saving hours writes config version 2 and `/healthz` serves it; an invalid span is refused
  with the field named (`field-error-hours`) and no version is written; rolling back to
  version 1 writes version 3 with the original hours; the numbers tab shows the mapped
  numbers read-only;
- a staff member joins from an invitation, sees the requests page, has no Save button, and
  is refused `saveTenantConfig` and `rollBackTenantConfig` by the server with 403.

Unit, in the browser runner (`wasp test client run`): `formatting.test.ts` (11) — the three
band labels and the "in progress" a running conversation gets, item type wording, overdue
being about unresolved work past its promised time only, and the small formatters;
`settings/schemaFields.test.ts` (9) — the schema reader keeps the model's field order, reads
a `Literal` as a choice, reads pydantic's `anyOf`-with-null as an optional value of the real
type, tells booleans from integers, marks a shape it has no control for instead of guessing,
and is empty for a model the runtime does not define; `runtime/errors.test.ts` (7) — a 422
`loc` becomes a named field with `config`/`body` dropped, a nested path is kept so a form can
find the entry, non-pydantic bodies yield nothing, and no message mentions the shared key.

## Red before green

The whole implementation was stashed (`git stash push -u` over the fourteen new or edited
source files plus `main.wasp.ts`) and `npx playwright test tests/client.spec.ts` run against
the C2-level app: `1 failed, 15 did not run`, the failure being
`getByRole('heading', { name: 'Overview' })` → `<element(s) not found>` at
`client.spec.ts:92` — the routes did not exist. Stash popped, then two real defects came out
of the first green attempts:

1. `acknowledged_by` came back as `admin@spatalk.test` where the test expected
   `portal:admin@spatalk.test`. The runtime stores the `actor` from the request body
   verbatim and prefixes only the *audit* row (`portal_actor`). Settled deliberately: the
   item records the person, the audit row records the channel they came through. Test and
   seed fixture changed to match.
2. `field-error-hours` never appeared. Wasp's client hands `error.data` the *whole* response
   body, and the body is `{ message, data }` (`.wasp/out/server/src/app.js:22`), so an
   `HttpError`'s own payload is one level in. `SettingsPage` now reads
   `error.data.data.fieldErrors`.

## How the runtime gets into the end-to-end suite

The plan's tests are "Playwright against a running runtime seeded with one tenant and
fixtures", and the portal owns none of that data, so the suite grew a runtime side:

- `portal/e2e-tests/seed_runtime.py` — a *runtime-side* script using the runtime's own models
  and `TenantRegistry.import_bundle`, wiping and rebuilding everything belonging to
  `skincentrix` so the config version is 1 and the counts are fixed on every run. Nothing in
  the portal itself opens a connection to the `runtime` schema (non-negotiable 7).
- `portal/e2e-tests/global-setup.ts` — runs that script (`uv`, falling back to `uv.exe`),
  writes the ids it created to `.seed.json`, and then refuses to start the suite unless a
  runtime answers `RUNTIME_INTERNAL_URL/healthz`.
- `portal/e2e-tests/tests/runtime.ts` — where the runtime is, plus the two questions no
  portal table can answer: what `audit_log` recorded, and what state an item is really in.

`playwright.config.ts` passes `RUNTIME_INTERNAL_URL` and `RUNTIME_INTERNAL_KEY` into the
`wasp start` it launches, so the app under test and the assertions look at the same runtime.

## Deviations

1. **`openapi-typescript` is not a dependency; `gen:client` runs it through `npx` at a pinned
   version.** The plan asks for it in `package.json`, but it peer-requires `typescript@^5.x`
   and this project is on 6.0.3. Evidence: `npm install --save-dev openapi-typescript@7` →
   `npm error Could not resolve dependency: peer typescript@"^5.x" from
   openapi-typescript@7.13.0 … dev typescript@"6.0.3" from the root project`. The script is
   `npx --yes openapi-typescript@7.13.0 ../docs/contracts/runtime-internal.openapi.json -o
   src/runtime/client.ts`, so regeneration is deterministic and C8's drift check can run it.
   `openapi-fetch@0.14.0` *is* a dependency, as the plan says.
2. **`pg` and `@types/pg` were added to `portal/e2e-tests` devDependencies.** Two of the
   plan's own assertions — "opening a transcript creates an audit row (verify via
   `GET /internal/…` or the DB)" and "resolving an item changes its state" — have no
   endpoint behind them: nothing under `/internal` reads `audit_log`. The tests read those
   two tables directly, and only the tests.
3. **The tenancy guard on acknowledge and resolve is the portal's, because the contract has
   no place for it.** `POST /internal/items/{id}/acknowledge|resolve` takes an item number
   and no tenant, so on that contract any member of any organisation could act on any
   tenant's item by guessing a number. `actionableItem()` therefore refuses unless the item
   is currently open or acknowledged *for this organisation's tenant*, which costs one or two
   small list calls. **For the orchestrator:** the durable fix belongs in C3's router —
   either `GET /internal/items/{id}` or a tenant-scoped mutate path — and would let the
   portal drop the pre-flight.
4. **The Requests page asks for `state=all` and splits client side**, exactly as C3's report
   (note 8) predicted, because `state=open` is an exact match and the page wants open *and*
   acknowledged.
5. **`acknowledged_by` and `resolved_by` carry the plain email, not `portal:<email>`.**
   `docs/reference/data-model.md` fixes the `portal:` form for `audit_log.actor` only, and the
   two item columns are shown to staff as "acknowledged by …". The audit row keeps the
   prefix, so provenance is not lost.
6. **`readConversation` is an action, not a query.** Reading a transcript writes an audit row
   every time; a Wasp query is cached, so the second read would go unrecorded.
7. **"This month" is anchored on the runtime's clock, not the portal's.** The overview first
   asks for usage with no dates — the runtime answers with the last thirty days *in the
   tenant's timezone* — and takes the last of those days as the tenant's today before asking
   for the month. A clinic's month is never the portal server's month (non-negotiable 8).
8. **Files beyond the plan's list.** `portal/src/runtime/errors.ts` (pure 422-to-field
   mapping, importable by both the server wrapper and a browser test);
   `portal/src/client/{operations.ts, pages.wasp.ts, OrgShell.tsx, formatting.ts}` (the plan
   names the four pages and `settings/*`, but the operations, the Wasp spec module, the shared
   page frame and the display helpers have to live somewhere); `portal/src/client/settings/`
   holds `schemaFields.ts`, `SchemaInput.tsx` and the six tabs plus `VersionsPanel.tsx`;
   `portal/e2e-tests/{global-setup.ts, seed_runtime.py, tests/runtime.ts}` (above); three
   unit-test files.
9. **`portal/src/organizations/OrgHomePage.tsx` (a C2 file) gained a four-link nav** to the
   new pages. Without it `/app/:orgSlug` is a dead end and the pages are reachable only by
   typing a URL.
10. **The spec is `e2e-tests/tests/client.spec.ts`, not `e2e-tests/client.spec.ts`** as the
    plan writes it: C1 set `testDir: "./tests"` and the other four specs are there.
11. **Wasp's SuperJSON payload types reject `Record<string, unknown>`.** Wasp's own
    `SuperJSONValue` excludes `any`, so an index signature of `unknown` fails to compile
    (`Type '{ [key: string]: unknown; }' … is missing the following properties from type
    'Decimal'`). `operations.ts` declares `JsonValue`/`JsonObject` and uses them for a tenant
    configuration, the JSON schema and an item's `preferred_window`, casting at the runtime
    boundary.
12. **`playwright.config.ts` and `e2e-tests/package.json` (C1 files) were edited**: a
    `globalSetup`, the two runtime variables in the `wasp start` environment, and the `pg`
    dependency. `e2e-tests/.gitignore` gained `.seed.json`.
13. **Running the suite on this machine needs a bridge container.** WSL holds Wasp and
    Playwright; the runtime's virtualenv is a Windows one. WSL cannot reach a Windows-hosted
    port (only Docker's published ports are allowed through), so the runtime is republished
    with `docker run -d --name spatalk-runtime-bridge -p 8010:8010 alpine/socat
    TCP-LISTEN:8010,fork,reuseaddr TCP:host.docker.internal:8000` and the suite is run with
    `RUNTIME_INTERNAL_URL=http://localhost:8010`. Both the default (`http://localhost:8000`)
    and the override are documented in `portal/e2e-tests/README.md`; on Linux, and in CI,
    nothing but a plain `spatalk serve` is needed.

No conflict was found between the four reference documents and this task. Two things worth
repeating to the orchestrator, neither new here: `docs/reference/api-surface.md` still lists
`SMTP_USER`/`SMTP_PASS` for the portal where Wasp reads `SMTP_USERNAME`/`SMTP_PASSWORD`
(flagged in C1), and `docs/reference/tenant-config.md`'s promise that "the portal's settings
forms are generated from the JSON schema the runtime serves at
`GET /internal/schema/tenant-config`" is now literally true: `schemaFields.ts` reads that
document and the Scripts, Services, Delivery and Escalation forms are drawn from it, so a
field added to the pydantic models appears in the portal without a portal edit.

## Notes for neighbours

- **C5**: `runtime(actorEmail)` and `runtimeCall(call, what)` from `src/runtime/api.ts` are
  the only way to reach the runtime; the admin pages should use them too rather than a second
  client. `docs/contracts/runtime-internal.openapi.json` already contains
  `POST /internal/tenants/from-bundle`, so `npm run gen:client` needs no rerun for the wizard.
  The health page wants `GET /internal/health` and `/healthz`, neither of which the client
  pages call yet.
- **C6**: the client pages are not gated on `subscriptionStatus` yet. The gate belongs in the
  four operations in `src/client/operations.ts` (all of them go through `session()` /
  `ownerSession()`, which is the one place to add it) as well as in the UI.
- **C7**: `runtimeCall` already turns every runtime failure into a sentence with no stack, no
  status line and no mention of the key, and `X-Actor` is on every call. What is missing is
  the rate limiting, the headers and the log-scrub test. Also still open from C2: React Query
  retries a refused query three times, so a 403 takes several seconds to appear as text.
- **C8**: the portal suite is now five commands — `npm run test:unit`, `wasp test client run`,
  `npm run e2e`, `wasp build`, `npx tsc -p tsconfig.src.json --noEmit`. The e2e job needs a
  runtime on `RUNTIME_INTERNAL_URL` with `INTERNAL_API_KEY` equal to `RUNTIME_INTERNAL_KEY`,
  a database the seed script can reach (`RUNTIME_DATABASE_URL`), and `uv` on PATH; everything
  else it seeds itself. The client-side drift check is `npm run gen:client` followed by
  `git diff --exit-code portal/src/runtime/client.ts`.
- **E5** adds `conversations.stage_ms`; the overview's "Reply time (p95)" tile reads the last
  day of `GET /internal/tenants/{id}/latency`, so a per-stage breakdown would slot in there.
