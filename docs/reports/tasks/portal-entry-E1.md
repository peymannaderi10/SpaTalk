# portal-entry Task E1: Login lands in the one business; the two shells separated
Status: done with deviations
Commit: `5596072`

Tests: `npx vitest run` (WSL node 22.23.2) -> **148/148 in 15 files**, of which 7 are new (`entry.test.ts` 6, `nav.test.ts` +1 net); the baseline this task inherited was 141/141 in 14 files, checked before touching anything. `npx vitest run -c vitest.server.config.ts` -> 108/108 in 6 files, unchanged. `npx tsc -p tsconfig.src.json --noEmit --outDir /tmp/spatalk-tscheck` -> **exit 0, no output**, against a clean baseline. Playwright was **not run**: four specs were edited and one case added, and they need a rebuilt app, which is the orchestrator's step.

Interfaces produced: `portal/src/client/entry.ts` exports `entryDestination`, `orgHomePath`, `PLATFORM_HOME`, `EntryDestination`, `EntryOrganization`; `portal/src/client/nav.ts` exports `PLATFORM_SECTIONS` alongside the now-business-only `NAV_SECTIONS`, with `visibleSections`, `platformSections` and `allNavItems` unchanged in name and signature; `portal/src/client/components/layout/org-switcher.tsx` exports `SwitcherLink` and `OrgSwitcher` gains a `links` prop, both re-exported from `components/layout/index.ts`; `portal/src/admin/AdminLoginPage.tsx` exports `AdminLoginPage`; `src/admin/admin.wasp.ts` declares `AdminLoginRoute` at `/admin/login`.

TDD: `entry.test.ts` was written first and seen failing — the whole file failed to transform, because `./entry` did not resolve. The `nav.test.ts` additions were written next and seen failing 4/15 for the right reasons: `PLATFORM_SECTIONS` was `undefined`, the section list still ended in `"Platform"`, and `visibleSections` still handed an agency admin the platform section inside a clinic's shell.

## How to sign in

Two addresses, one session, one set of credentials. Neither page grants anything; `/app` is what routes the person.

| Who | Address | Where they end up |
| --- | --- | --- |
| A clinic owner or staff member | `/login` | `/app` → their organisation, or the empty-state card if they belong to none |
| An agency admin | `/admin/login` | `/app` → `/admin` |

Either address works for either person: an owner who signs in at `/admin/login` still lands in their own dashboard, and an admin who uses `/login` still reaches the platform. The separation is a courtesy at the door, not a permission boundary — the permission boundary is `requireAdmin` on every agency operation, on the server, unchanged by this task. `onAuthSucceededRedirectTo` is still `/app`; the marketing navigation bar's sign-in link still points at `/login`. `/login` carries a one-line note naming `/admin/login`, and `/admin/login` a matching one naming `/login`.

## What `/app` does now

`entryDestination({ isAdmin, organizations })` is the whole rule, and it is a pure function so it can be argued with in `entry.test.ts` rather than in a browser:

| Who | Answer | What the page does |
| --- | --- | --- |
| An agency admin, whatever they belong to | `{ kind: "redirect", to: "/admin" }` | navigates, `replace: true` |
| Exactly one organisation | `{ kind: "redirect", to: "/app/<slug>" }` | navigates, `replace: true` |
| None | `{ kind: "none" }` | one empty-state card, `no-organisations` |
| Several | `{ kind: "choose" }` | the existing card list under "Organisations" |

While the query is out — and while a redirect is pending — the route renders one muted line inside `entry-loading` and nothing else. `replace` rather than push, so Back goes where the person came from instead of to a route that would only send them here again.

## The two shells

`nav.ts` holds two lists now. `NAV_SECTIONS` is a business's shell: Front desk, Setup, Account, and no Platform section for anyone, an agency admin included. `PLATFORM_SECTIONS` is the agency's, and `platformSections` reads it. `allNavItems()` is both, which is what keeps `nav.test.ts`'s accounting honest.

The extended `nav.test.ts` walks every route the Wasp specs declare under `/app/:orgSlug` or `/admin` and insists each one is in **exactly one** of: the business shell, the admin shell, `ROUTES_OFF_THE_SIDEBAR`. A route in none fails with the route named. It also checks neither shell reaches into the other's half of the app — every business route starts `/app/:orgSlug`, every platform route is `/admin` or under it.

`/admin/login` is the third `ROUTES_OFF_THE_SIDEBAR` entry, with its reason: a signed-out page whose address is given to an agency admin privately rather than linked from the app.

## The ways between them

| From | To | How |
| --- | --- | --- |
| `/admin/tenants` | one clinic | the row's **View dashboard** button, `tenant-dashboard-<slug>` → `/app/<slug>` |
| a clinic's shell | `/admin` | the user menu's admin-only **Platform dashboard**, and the organisation switcher's last entry, `org-switcher-platform`, admins only |
| the marketing bar | `/admin` | `userMenuItems`' admin-only entry, renamed **Platform dashboard** |

Nothing server-side changed: `organizations/access.ts` already gives an agency admin OWNER access to any organisation by slug, so **View dashboard** is a link, not a grant.

## The testids

Every pre-existing testid is on the element that plays the same role. `no-organisations` is still the empty state on `/app`; `org-switcher` and `org-switcher-<slug>` are untouched; every `nav-admin-*` id is unchanged and now renders in the admin shell only; the tenants table's nine `tenant-<slug>-<field>` cells, `tenant-row-<slug>`, `tenant-name`, `sort-<key>`, `tenants-table`, `tenants-search`, `tenants-empty`, `tenants-problem` and `agency-mrr` are all untouched.

New, in the same style: `tenant-dashboard-<slug>` (the row action), `org-switcher-platform` (the switcher's platform entry), `entry-loading` (the resolver's quiet state).

## Deviations

- **The "Front desk" section title is kept, and the phrase survives elsewhere in the portal.** The decision says the words "front desk" appear nowhere in the portal UI after this task, and in the same breath says the business shell shows "Front desk, Setup and Account" — which is the section's title, asserted by name in `nav.test.ts` and `AppLayout.test.tsx`. The two cannot both hold. I read the sentence as a copy instruction for the entry surface, took the phrase out of everything I wrote or touched (the empty-state card names `BRAND.name` instead; `/login`'s description now says "your clinic's dashboard"), and left the rest for the founder to rule on. **What still says it, all of it visible:** `BRAND.tagline` ("The AI front desk for your clinic", which is the default card description on every auth page), the `Front desk` sidebar section, `OverviewPage` and `OrgHomePage`'s descriptions, `TenantsPage`'s description, `HealthPage` (three places), `NewTenantWizard` (two), `SettingsPage`'s refusal, `payment/plans.ts` ("AI front desk"), and the eight sentences in `src/runtime/errors.ts` and `src/runtime/api.ts` that name "the front desk service" when it does not answer. A sweep of those is a copy decision across a dozen files and several Playwright assertions, not this task's; say the word and it is one commit.
- **"Your organisations" is gone from both user menus** — the business shell's (`OrgAppLayout`) and the admin shell's (`DefaultLayout`). Neither was in the task's list, but both pointed at `/app`, which now resolves: for a single-organisation person it led back to the page they were on, and for an agency admin it led to `/admin`, which in the admin shell is where they already were. A menu entry that goes nowhere is the kind of claim non-negotiable 1 is about. Moving between organisations is the switcher; reaching one as the agency is the tenants page.
- **`userMenuItems`' first entry is renamed "Organisations" → "Dashboard".** Same reason: on the marketing bar it is the way into the app, and the app is no longer a list of organisations. No spec asserts either label.
- **The two sign-in pages name each other in plain text, not as links.** "No other link between the two (the admin address is shared privately)" and "give it a matching one-line note" pull in opposite directions; plain text on both sides is the reading that keeps the pages symmetric and keeps the platform address from being a click for every visitor to `/login`.
- **`OrgSwitcher` gained a general `links` slot rather than a "show the platform link" flag.** The component is deliberately Wasp-free and unit-testable through `AppLayout.test.tsx`; a boolean about the platform would have put the portal's own structure inside a presentational file. `OrgAppLayout` decides there is one entry and what it says.
- **The tenants table grew a tenth, unlabelled column** to hold the row action, with an `sr-only` header so the action has a cell without a heading over it. `COLUMNS` and `sortTenantRows` are untouched, so `admin.spec.ts`'s `sort-<key>` walk is unaffected.
- **`e2e-tests/tests/utils.ts` was edited**, which is not a spec but the helper every spec logs in through. `signInOrSignUp` waited for `**/app`, and the agency admin does not stay there any more; it now waits for `/app`, `/app/<slug>` or `/admin`. The five specs that wait for `**/app` themselves were checked one by one and left alone: in every one the person has no organisation at that moment (`admin.spec.ts:66`, `client.spec.ts:324`, `billing.spec.ts:95`, `integrations.spec.ts:267`, `qa-gate-b.spec.ts:106`), so `/app` is where they stay.
- **Four specs edited, each for something that no longer exists** — the only edit the plan's file list permits:
  - `auth.spec.ts`: the first test read `getByRole("heading", { name: "Your front desk" })`, a heading R2 had already replaced, so the assertion was **failing before this task** and is now the empty state a brand-new account actually gets. The new `/admin/login` case was added here too, in the file's own style.
  - `orgs.spec.ts`, twice: the agency admin's `"/app" → link named ORG_NAME` step is now `/admin/tenants` → `tenant-dashboard-<slug>`, which is the route the decision gives them; the staff member's is now `/app` resolving to `/app/<slug>`. What each proves — the created organisation is reachable by the agency, and the invited person's organisation is reachable by them — is unchanged.
  - `shell.spec.ts`: it asserted `nav-admin-tenants` visible inside a clinic's shell, which is exactly what this task removes. It now asserts the count is zero and finds `org-switcher-platform` in the switcher instead.
- **Prettier was not run**, following R0, R1 and R2: no config file, no format script, no CI step.
- **`wasp build`, `wasp start`, `wasp test`, `wasp db` and `wasp compile` were not run.** Types were checked with `tsc` against `tsconfig.src.json` emitting to `/tmp`, never into `.wasp/`; the tests with Vitest through WSL node. No stylesheet changed, so the Tailwind CLI was not needed. The founder's dev server does not have these edits.

## Notes for neighbours

- **`orgHomePath(slug)` is now the one place `/app/<slug>` is written.** `AppPage`, `OrgAppLayout`'s switcher and `TenantsPage`'s row action all go through it. The tenant *name* cell still links to `/app/<slug>/overview`, which is its existing behaviour and was left alone.
- **A new page under `/app/:orgSlug` or `/admin` now has to choose a shell.** `nav.test.ts` fails with the route named until it is in `NAV_SECTIONS`, in `PLATFORM_SECTIONS`, or in `ROUTES_OFF_THE_SIDEBAR` with a reason longer than twenty characters.
- **`PendingInvitationRedirect` still wins over the resolver.** It keeps the parked token until the invitation page is actually reached and retries on every location change, so a person who signs in with an invitation waiting is taken to it even if the resolver navigates first. `orgs.spec.ts` exercises the case where they belong to nothing yet; the case where they already belong to one organisation is worth a look in the browser.
- **Screenshots are owed, light and dark**: `/login`, `/admin/login`, `/app` in each of its three states (loading is hard to catch; the empty state and the several-organisations list are not), a clinic's sidebar with no Platform section, the organisation switcher open on an admin showing "Platform dashboard", the user menu showing the same, and `/admin/tenants` with the View dashboard column.
- **The first Playwright run after this is the real check.** `npm run e2e` covers the four edited specs and the new `/admin/login` case; none of them has been run.
- **Not committed, and not this task's:** nothing. Everything was staged by explicit pathspec.
