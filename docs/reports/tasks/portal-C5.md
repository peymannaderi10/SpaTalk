# portal Task C5: Agency admin pages and onboarding wizard

Status: done with deviations
Commit: <filled below>
Tests: `cd portal/e2e-tests && RUNTIME_INTERNAL_URL=… npx playwright test tests/admin.spec.ts` -> 12/12; full portal suite -> 108/108 (`npx playwright test` 42, `wasp test client run` 55, `npm run test:unit` 11), green twice in a row, plus `wasp build` and `npx tsc -p tsconfig.src.json --noEmit` clean

Interfaces produced:
routes `/admin/tenants`, `/admin/tenants/new`, `/admin/health` (`adminSpec` in `portal/src/admin/admin.wasp.ts`); queries `getAgencyTenants`, `getAgencyRevenue`, `getRuntimeStatus` and action `createTenantFromBundle` in `portal/src/admin/operations.ts`, with types `AgencyTenantRow`, `RevenueRow`, `AgencyRevenue`, `RuntimePlatformHealth`, `RuntimeStatusView`, `NewTenant`; components `TenantsPage`, `NewTenantWizard`, `HealthPage`, `RecurringRevenueCard`; browser-safe rules `PLAN_MONTHLY_CAD`, `isPayingStatus`, `mrrCadFor`, `totalMrrCad`, `lastActivityOf`, `sortTenantRows`, types `AgencyTenantRow`/`SortKey`/`SortDirection` in `portal/src/admin/agency.ts`, and `BUNDLE_SLOTS`, `emptyBundle`, `slotForFilename`, `missingSlots`, `isCompleteBundle`, `filenameFor`, types `BundleSlot`/`BundleDraft`/`BundleSlotSpec` in `portal/src/admin/bundle.ts`; `runtimeHealthz(): Promise<RuntimeStatus>` and `bundleFormData(parts, filenames)` in `portal/src/runtime/api.ts`; `createAndSendInvitation({entities, org, email, role})` in `portal/src/organizations/operations.ts`.

No runtime (Python) code was touched: `POST /internal/tenants/from-bundle`, `GET /internal/health` and `/healthz`'s `commit` were all delivered by C3, as the task note said.

## What the tests assert

End to end (`portal/e2e-tests/tests/admin.spec.ts`, 12), against the runtime the
suite already seeds:

- `/admin` sends a user who is not an agency admin back to `/app`, and
  `get-daily-stats`, `get-agency-tenants`, `get-runtime-status` and
  `create-tenant-from-bundle` each refuse them with 403 on the server, not only
  in the page;
- the wizard, driven through its four steps, imports the real Skincentrix
  bundle (re-identified as `skincentrix-portal-e2e`) and the runtime then lists
  that tenant by name with a configuration version;
- the owner invitation exists for the address typed into the wizard, and the
  organisation it belongs to carries the runtime tenant id the runtime returned;
- the closing checklist names the `spatalk numbers add` lines for this tenant,
  the Slack channel, and the runbook the steps come from;
- the tenants table shows that organisation's runtime numbers — calls, estimated
  cost, open items, configuration version — and says "No subscription" where the
  agency is not being paid;
- an organisation whose runtime tenant does not exist is listed as
  "Not configured" with the runtime's own refusal underneath, instead of showing
  zeroes or emptying the table;
- clicking a column header sorts by it, and clicking again reverses it;
- the health page shows the queue depth and dead-job count `GET /internal/health`
  reports at that moment, the age of the oldest queued job, the deployed commit,
  and every tenant the runtime is serving with its configuration version;
- the analytics page shows recurring revenue per tenant beside the template's
  own numbers.

Unit, in the browser runner (`wasp test client run`): `src/admin/agency.test.ts`
(13) — which Stripe statuses count as paying (`active`, `trialing`,
`cancel_at_period_end`, and nothing else, including no subscription at all),
what a paying and a non-paying organisation contribute to MRR, that the price is
a parameter so a changed plan needs no new arithmetic, that last activity is the
later of the last call and the last text and is nothing when there has been
neither, and that sorting orders numbers numerically, does not mutate its input,
and puts a row with nothing in the column last in *either* direction;
`src/admin/bundle.test.ts` (8) — the five filenames the bundle reference names,
recognising each one whatever directory or casing it arrives in, accepting
`.yml` for `.yaml`, refusing a file that is not part of a bundle rather than
guessing, and naming what is still missing (whitespace counts as missing).

## Red before green

- Unit: `wasp test client run` with the two test files written and neither module
  existing -> `src/admin/agency.test.ts(10,8): error TS2307: Cannot find module
  './agency'`, `src/admin/bundle.test.ts(9,8): error TS2307: Cannot find module
  './bundle'`, and the SDK build failed with exit code 2. After implementing:
  55 passed.
- End to end: `npx playwright test tests/admin.spec.ts` against the C4-level app
  -> `1 failed, 9 did not run, 2 passed`; the failure was
  `POST /operations/get-agency-tenants 404` → `Expected: 403, Received: 404`,
  the operations not existing yet. After implementing: 12 passed.

Two real defects came out of the first green attempts:

1. **The whole `/admin` dashboard was an error page whenever the daily-stats job
   had not run.** `getDailyStats` answers 200 with `undefined`, which React Query
   reports as the error `["operations/get-daily-stats"] data is undefined`, and
   the template's page early-returned on any error — so the "No daily stats
   generated yet" overlay it also carries was unreachable, and so was the new
   revenue card. Evidence: a throwaway spec printed the body text of `/admin` for
   the agency admin: `MENU Dashboard Users Tenants Health admin@spatalk.test
   Error ["operations/get-daily-stats"] data is undefined`. The error card is
   still shown, but the agency's own recurring revenue is now rendered beside it
   rather than instead of it.
2. **The wizard refused its own second run.** The first version checked the
   organisation slug for a clash *before* uploading, so re-uploading a corrected
   bundle for a tenant that already had an organisation was a 409. The check now
   happens only when no organisation exists for the tenant the runtime returned,
   which is what "re-uploading a corrected bundle" has to mean; C3's endpoint
   already treats a re-upload as a new version rather than a refusal.

## Deviations

1. **`GET /healthz` is reached with `fetch`, not through the generated client.**
   The Global Constraint says every runtime call goes through
   `src/runtime/client.ts`, but that file is generated from
   `docs/contracts/runtime-internal.openapi.json`, which is filtered to
   `/internal` paths — and `/healthz` is deliberately unauthenticated and outside
   it. `runtimeHealthz()` lives in `src/runtime/api.ts`, the one module that is
   allowed to reach the runtime, next to `runtime()`; no page or operation
   fetches the runtime anywhere else. The alternative — putting `/healthz` in the
   internal contract — would change C3's committed artefact and the drift check
   for a liveness endpoint that has no key and no `/internal` prefix. **For the
   orchestrator:** if the contract should cover it, that is a C3/C8 change.
2. **`POST /internal/tenants/from-bundle` needs a body serialiser.** The
   generated client types the five parts as strings, but FastAPI only treats a
   part as `UploadFile` when it carries a filename, so `bundleFormData` builds
   the multipart body and `openapi-fetch` passes a `FormData` through untouched
   (its `index.js`: "if serialized body is FormData; browser will correctly set
   Content-Type & boundary expression"). The call is still made through the typed
   client and the path is still checked against the contract.
3. **MRR is computed in the portal from the plan's list price, not read from
   Stripe.** The plan says "add MRR per tenant from `Organization.subscriptionStatus`",
   and a status carries no money. `PLAN_MONTHLY_CAD = 999` comes from
   `docs/runbooks/accounts-and-env.md` § 10 ("recurring price CA$999 per month");
   both places that show a total say "at the list price of CA$999.00" and the
   analytics card adds "Stripe holds the price of record", so the page never
   implies the figure came back from Stripe. No new environment variable was
   added. **For C6:** if the subscription's real amount should be shown, read it
   from the Stripe price in the webhook and store it on `Organization`; then
   `mrrCadFor(status, storedAmount)` takes it without any other change.
4. **The invitation code was lifted out of `inviteMember` into
   `createAndSendInvitation`** (a C2 file, `src/organizations/operations.ts`).
   The wizard has to invite the owner, and a second copy of the token, expiry and
   email rules is how the two would drift. `inviteMember` is now
   `requireOrgOwner` plus that call; its behaviour and the C2 e2e are unchanged.
5. **The organisation the wizard creates is resolved by runtime tenant id, and
   the typed name and slug are then ignored.** If an organisation already exists
   for the tenant the bundle imported as, it is kept (the result page says so);
   the slug clash is only refused when there is no such organisation, and the
   refusal names the tenant that already holds the address and says the bundle
   does not have to change. See defect 2 above.
6. **The checklist names the runbook rather than linking to it.**
   `docs/runbooks/accounts-and-env.md` is a file in the repository, not a hosted
   page, so a hyperlink would 404 for the founder. Each item carries the section
   and step numbers it comes from (§ 3 steps 4-9, § 8 step 4, § 10).
7. **Files beyond the plan's list.** The plan names three components;
   `src/admin/agency.ts` and `src/admin/bundle.ts` hold the browser-safe rules so
   the server operation and the page share them and the unit tests can reach
   them, `src/admin/operations.ts` holds the four server operations (there is no
   other place for them), and
   `src/admin/dashboards/analytics/RecurringRevenueCard.tsx` is behaviour 4's
   addition to the template's analytics page. `src/admin/layout/Sidebar.tsx` (a
   C1 template file) gained the Tenants and Health links; without them the two
   pages are reachable only by typing a URL. `portal/e2e-tests/README.md` gained
   a note that the admin suite writes a second tenant into the runtime.
8. **The spec is `e2e-tests/tests/admin.spec.ts`, not `e2e-tests/admin.spec.ts`**
   as the plan writes it: C1 set `testDir: "./tests"` and the other four specs
   are there. The file already existed (C1's two `/admin` denial tests); its
   tests are kept and three describe blocks were added around them.
9. **The e2e onboards `skincentrix-portal-e2e`, not `skincentrix`.** The bundle
   is the real Skincentrix one with `id:` and `name:` rewritten. Importing it
   over `skincentrix` would write a new configuration version under
   `client.spec.ts`, which asserts that tenant is on version 1 after seeding.
10. **`getRuntimeStatus` declares no entities.** It reads nothing of the
    portal's; `requireAdmin` only needs `context.user`.
11. **Tests were derived from the task's Behaviour and Tests lists, not given
    verbatim** (this is a contract-level plan), and are named after the
    behaviours.
12. **Prettier was run only on the files this task wrote or edited.** The
    template's own `src/admin/layout/*.tsx` and two analytics cards already fail
    `prettier --check` at C1's commit, so formatting them would be unrelated
    churn; `src/admin/layout/Sidebar.tsx` is therefore left as unformatted as it
    was found. Evidence: with this task's changes stashed,
    `npx prettier --check src/admin/layout/Sidebar.tsx` -> `[warn]`, while
    `src/runtime/api.ts`, `src/organizations/operations.ts` and
    `AnalyticsDashboardPage.tsx` were clean and are clean again.

No conflict was found between the four reference documents and this task.
`docs/reference/api-surface.md`'s portal row (`/admin/*`, Wasp session) and its
`/internal/*` row are both satisfied as written. Two known reference errors,
already flagged by C1 and C4, are unchanged here: the portal's SMTP variables are
`SMTP_USERNAME`/`SMTP_PASSWORD`, not `SMTP_USER`/`SMTP_PASS`.

## Notes for neighbours

- **C6**: the tenants table and the analytics card both read
  `Organization.subscriptionStatus` and `subscriptionPlan`, which are still
  always null until billing is re-keyed to the organisation. `mrrCadFor(status,
  monthlyCad?)` takes an amount, so storing the real Stripe amount on
  `Organization` is the whole change on this side. The wizard's checklist already
  tells the agency to subscribe the new organisation (§ 10).
- **C7**: the admin pages add three queries and one action, all behind
  `requireAdmin`; `createTenantFromBundle` is the one operation that accepts a
  large body (five files), so if a rate limit or a body-size limit is added, it
  needs a limit that admits a bundle. `runtimeHealthz()` is a second place a
  runtime failure has to stay a sentence: it already throws the same friendly
  `HttpError` as `runtimeCall`.
- **C8**: the e2e job needs nothing new — the admin spec reads the bundle from
  `runtime/tenants/skincentrix/` in the repository and posts it through the
  portal. It does leave `skincentrix-portal-e2e` and `tenant-that-does-not-exist`
  behind in the runtime and the portal database, which is harmless and
  idempotent across runs.
- **C9/E7**: `/admin/health` shows `commit` from `/healthz`, and it is empty
  unless the image was built with `--build-arg GIT_COMMIT=$(git rev-parse HEAD)`.
  The page says "not recorded in this build" rather than showing a blank, but the
  deploy step that sets it is still owed.
- The agency's own `/admin` dashboard no longer disappears when the daily-stats
  job has not run; anyone touching `AnalyticsDashboardPage` should keep the
  revenue card outside the stats block for that reason.
