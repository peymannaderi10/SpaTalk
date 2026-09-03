# Portal Reskin Implementation Plan

> **For agentic workers:** contract level: files, exact interfaces, behaviours, tests. Read `CLAUDE.md`, `docs/superpowers/plans/2026-09-01-portal-plan.md` (what the portal does and which features must survive), `docs/reports/tasks/lead-context-L2.md` and `docs/reports/tasks/call-notes-N2.md` (how portal work is verified on the founder's laptop and what broke before), and the reports in `docs/reports/` that mention the portal. Status: **drafted 2026-09-03 on the founder's decision to re-skin; the kit choice below is a recommendation awaiting the founder's confirmation before Task R0 starts.**

**Goal:** The founder likes what Open SaaS does and dislikes how it looks. The portal keeps every feature it has (auth, organisations and invitations, billing, the agency admin pages, tenant settings, conversations, requests with lead summaries and call notes, health) and gets a coherent, designer-made dashboard look that does not read as assembled by an agent: one app shell with a sidebar, one table style, one card style, one set of tokens, one icon set, light and dark. The product name becomes a single configuration value so the brand can change later without a code hunt.

**Architecture:** No new UI framework. The portal already runs Tailwind v4 and shadcn/ui on Radix, with the component source under `src/client/components/ui`. The reskin **vendors an existing open-source shadcn dashboard kit** rather than inventing a look: its app shell, page layouts, table and settings patterns and its tokens are copied in and adapted to the portal's routes and data. Charts move from ApexCharts to the shadcn chart components (Recharts), so the whole surface is one system. Icons move to Tabler Icons, which the kit already uses and which carry the visual language the founder likes in Tabler. Strings and marks go through one `brand` module.

**The kit (recommended, to be confirmed):** `satnaing/shadcn-admin` (MIT, about 14k stars, Vite + React + TypeScript, shadcn/ui on Radix, Tailwind v4, Lucide and Tabler icons, light and dark, RTL, ten-plus pages: dashboard, tasks table, users table, settings with side navigation, auth pages, error pages). It is the most-used shadcn dashboard and the closest to this codebase's substrate. Its router is TanStack Router, which the portal does not use; the kit is vendored as **components and layouts**, never as routes or data layers. Runner-up if the founder prefers it after seeing both: `shadcndashboard/shadcndashboard` (MIT, Vite + React Router + Tailwind v4 + TanStack Table + Recharts) matches the portal's router but builds on Base UI primitives rather than Radix and has a much smaller community. Tremor's open-source chart and KPI blocks (Recharts on Radix) may be borrowed for the overview cards where the shadcn chart blocks are thinner; Tremor's premium blocks are out.

**Tech Stack:** Wasp 0.25, React 19, react-router, Tailwind v4, shadcn/ui (Radix), TanStack Table (new), Recharts through the shadcn chart components (new), `@tabler/icons-react` (new), vitest, Playwright. Removed: `apexcharts`, `react-apexcharts`, `lucide-react` once no import remains.

**Spec:** `docs/superpowers/plans/2026-09-01-portal-plan.md` remains the functional contract; this plan changes presentation only. Where a reference page names a `data-testid`, it stays.

## Global Constraints

- Every feature the portal has today keeps working and keeps its route: sign-up, log in, password reset, organisation switcher, invitations and roles, billing and the Stripe portal, tenant settings (all tabs), conversations with transcript and takeover, requests with summary, facts, call notes and the acknowledge and resolve actions, SMS blocks, the agency admin pages (dashboard, users, tenants, new tenant, health), theme toggle. The Playwright suite and the vitest suite are the proof; both run before and after each task.
- Every existing `data-testid` is preserved verbatim. New interactive elements get testids in the same style.
- One design system: shadcn/ui on Radix with the kit's tokens. No Bootstrap, no MUI, no second icon set once the migration is done, no per-page colour choices; a page that needs a colour uses a token.
- Brand through one module: `src/client/brand.ts` exports `BRAND = { name, shortName, tagline, supportEmail, logo: { light, dark, mark }, colors: { primary } }`. Every "SpaTalk" string in `portal/src` reads from it. Where Wasp needs a literal (the app title in the Wasp spec, the email sender name in `.env.server`), the literal is set once and a test asserts it equals `BRAND.name`.
- Nothing under `runtime/` changes. Tenant-facing wording (disclosure, outcome scripts, the notes label) stays tenant config and is not touched.
- Work on this laptop: the founder's `wasp start` runs in WSL and does **not** recompile edits under `portal/src` on its own; every task ends with the orchestrator running `stop-portal.sh` then `start-portal.ps1` and reading `wasp-start.log`. Agents never run `wasp build`, `wasp start`, `wasp test`, `wasp db` or `wasp compile` (they regenerate `.wasp/out` and kill the running server). Vitest runs through WSL node as in the N2 report. `wasp build` is run only by the orchestrator with the founder's server stopped.
- Screenshots are part of done: each task's report links light and dark screenshots of every page it touched, taken by the orchestrator through the browser after the restart, so the founder judges the look, not the diff.

## File Structure

```
portal/src/client/brand.ts                         BRAND, used everywhere a name, logo or support address appears
portal/src/client/components/ui/*                  refreshed from the shadcn registry to the kit's versions; new: sidebar, table, command, tooltip, badge, tabs, skeleton, breadcrumb, chart, scroll-area, popover, collapsible
portal/src/client/components/layout/*              vendored from the kit: AppSidebar, SidebarNav (data-driven), Header, Breadcrumbs, ThemeSwitch, ProfileDropdown, Search (command palette), Main
portal/src/client/components/data-table/*          vendored: DataTable, DataTableToolbar, DataTableColumnHeader, DataTablePagination, DataTableViewOptions, faceted filter
portal/src/client/components/empty-state.tsx       one empty state for lists
portal/src/client/layout/AppLayout.tsx             the shell for /app/:orgSlug/* (sidebar + header + main), replaces the top tab strip
portal/src/admin/layout/DefaultLayout.tsx          the same shell with the admin navigation
portal/src/client/Main.css                         the kit's tokens (light and dark), fonts, radius; the portal's own extras kept only where a token is missing
portal/src/client/nav.ts                           the sidebar model: sections, items, icons, routes, who sees what (role, admin)
portal/src/client/*Page.tsx, settings/*Tab.tsx, src/admin/**/*.tsx, src/auth/*.tsx   restyled in place; same operations, same testids
portal/src/client/charts/*                         shadcn chart components (Recharts) replacing the ApexCharts files under src/admin/dashboards
portal/e2e-tests/tests/*.spec.ts                   unchanged unless a selector was on a removed element; then the same testid is put on the replacement
portal/package.json                                + @tanstack/react-table, recharts, @tabler/icons-react; − apexcharts, react-apexcharts, lucide-react (last)
docs/reports/tasks/portal-reskin-R*.md             one report per task with the screenshots
```

## Task R0: Kit vendored, tokens, brand module, component refresh

**Files:** `brand.ts`, `components/ui/*`, `components/layout/*`, `components/data-table/*`, `Main.css`, `nav.ts` (model only), `package.json`.

**Produces:**
- `BRAND` as above, plus `brand.test.ts` asserting the Wasp app title and the auth email sender name equal `BRAND.name`, and a test that greps `portal/src` for the literal product name outside `brand.ts` and finds none.
- The kit's tokens in `Main.css` for `:root` and `.dark`, mapped onto the existing token names the portal already uses (`--background`, `--card`, `--primary`, `--sidebar-*`, `--chart-*`, `--radius`), so every existing page picks up the new look before it is touched. Fonts loaded locally or through the existing mechanism, no runtime CDN dependency.
- `components/ui` refreshed to the registry versions the kit uses; a diff note in the report for any component the portal had customised (the `Toaster`, the `Form` helpers) so nothing regresses.
- The layout and data-table components vendored, typed, compiling, unused yet.
- Dependencies added; nothing removed yet.

**Tests:** `brand.test.ts`; the vitest suite green; compile clean after the orchestrator restarts the portal; the Playwright suite green (the shell has not changed yet, so it must be).

**Done when:** the founder can open the portal and see the new tokens on the old layout. Commit `feat(portal): vendor the dashboard kit, tokens and brand module`.

## Task R1: The app shell

**Files:** `layout/AppLayout.tsx`, `admin/layout/DefaultLayout.tsx`, `nav.ts`, `components/layout/*`, the pages only where they mount the old tab strip.

**Produces:**
- `nav.ts`: `sections: NavSection[]` with `{ title, items: { label, to, icon, testId, visible: (ctx) => boolean }[] }`. Sections: **Front desk** (Overview, Conversations, Requests), **Setup** (the settings tabs as sidebar items with the same routes and query params they use today), **Account** (Billing, People), **Platform** (Dashboard, Users, Tenants, Health; admins only). The organisation switcher sits at the top of the sidebar; the user menu, theme switch and a command palette (jump to a page, open a request by number, open a conversation by phone) sit in the header. Breadcrumbs from the route.
- Mobile: the sidebar collapses to an icon rail and a sheet; every page usable at 390 px wide.
- The old top tab strip is removed; its testids move onto the sidebar items.

**Tests:** a vitest test that every route the Wasp spec declares under `/app/:orgSlug` and `/admin` appears in `nav.ts` exactly once and vice versa; keyboard navigation of the sidebar (tab order, Enter) in a Playwright test; the full Playwright suite green.

**Done when:** every page renders inside the shell with no layout regressions in the screenshots. Commit `feat(portal): sidebar app shell from the kit`.

## Task R2: The pages

**Files:** every page and tab under `src/client`, `src/client/settings`, `src/admin`, `src/auth`, `src/organizations`, `src/billing`.

**Produces, page by page, all with the kit's patterns:**
- **Overview**: KPI cards (calls, texts, chats, open requests, overdue) in the kit's stat-card style, a seven-day chart, a "needs attention" list. Same operations.
- **Conversations**: a DataTable (channel, caller, band, started, last message, controller) with faceted filters (channel, band, needs a human) and search; a row opens the transcript sheet with the call notes block above the messages, as today; the takeover and block actions in the sheet.
- **Requests**: the cards stay (a request is read as a card, not a row) restyled to the kit's card, with the summary as the title, the facts in a two-column description list, the notes block, and the actions as the kit's buttons; the Open and Resolved switch becomes tabs; empty state when there are none.
- **Settings**: the kit's settings layout (side navigation, section header, form card, sticky save bar); every tab keeps its fields, validation and testids; the numbers tab's SMS block panel becomes a small DataTable.
- **Billing and People**: the kit's plan card and members table; invitations in a dialog.
- **Platform admin**: dashboard KPIs and charts on the new chart components; users and tenants as DataTables with the same columns; new-tenant form; health as status cards.
- **Auth**: the kit's auth pages (sign in, sign up, forgot, reset, verify) with `BRAND` and the existing Wasp auth forms inside them.

**Tests:** vitest for any new helper; the Playwright suite green with every existing testid; a screenshot set (light and dark) per page in the report.

**Done when:** no page is left on the old layout; the founder has looked at the screenshots. Commit per group: `feat(portal): front desk pages on the kit`, `feat(portal): settings, billing and people on the kit`, `feat(portal): admin and auth pages on the kit`.

## Task R3: Charts, icons, removals

**Files:** `charts/*`, `src/admin/dashboards/**`, every icon import, `package.json`.

**Produces:** ApexCharts replaced by shadcn chart components on the admin dashboard and the overview; `lucide-react` imports replaced by `@tabler/icons-react`; `apexcharts`, `react-apexcharts`, `lucide-react` removed from `package.json`; the "non-passive event listener" console warning that ApexCharts produced is gone.

**Tests:** vitest and Playwright green; a test that no file under `portal/src` imports `lucide-react` or `react-apexcharts`.

**Done when:** one chart library, one icon set. Commit `feat(portal): shadcn charts and Tabler icons; ApexCharts and Lucide removed`.

## Task R4: Acceptance

Run by the orchestrator, not an agent: the founder's server stopped, `wasp build` in WSL, `npm run e2e` against the built app, the full vitest suite, a light and dark screenshot walk of every route, an accessibility pass (keyboard-only through the sidebar and one form, visible focus rings, contrast of the tokens checked with the kit's defaults), and the state document updated. The Open SaaS feature list in the portal plan is walked once more against the running app.

## Self-review against the constraints

- Features: the plan touches presentation files and `nav.ts`; every operation, route and entity stays. The Playwright suite is the regression net and runs on every task.
- Consistency: one kit, one token file, one table component, one icon set; the "looks AI-made" risk the founder named is answered by vendoring a designer-made system and by screenshots as a done criterion, not by an agent's taste.
- Brand: one module and a test that hunts literals.
- Founder decisions still open: confirm the kit; whether the requests page stays cards (this plan says yes); whether the command palette is wanted in the first pass.
