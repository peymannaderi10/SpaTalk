# portal-reskin Task R3: Charts, icons, removals
Status: done with deviations
Commit: `e698d18`

Tests: `npx vitest run` (WSL node 22.23.2) -> **141/141 in 14 files**, of which 16 are new (`no-legacy-ui.test.ts` 5, `usage-chart.test.tsx` 5, `revenue-chart.test.tsx` 6); the baseline this task inherited from R2 was 125/125 in 11 files, re-run and confirmed before anything was touched. `npx vitest run -c vitest.server.config.ts` -> 108/108 in 6 files, unchanged. `npx tsc -p tsconfig.src.json --noEmit --outDir /tmp/spatalk-tscheck` -> **exit 0, no output**, against a baseline checked first and also clean. `npx @tailwindcss/cli@4 -i src/client/Main.css -o /tmp/tw-out.css` -> "Done in 1s". Playwright was **not run**, as the task requires.

Interfaces produced: `portal/src/client/charts/usage-chart.tsx` exports `UsageChart` and `type UsagePoint { day, calls, texts, chats }`; `portal/src/client/charts/revenue-chart.tsx` exports `RevenueChart` and `type RevenuePoint { day, revenue, profit }`. Both take `{ data, className? }` and import nothing from Wasp. `UsageOverview` (private to `OverviewPage.tsx`) and `RevenueAndProfitChart` keep their names and signatures.

TDD: `no-legacy-ui.test.ts` was written first and run against the untouched tree — **2 failed / 3 passed**, listing all sixteen `lucide-react` importers and the three surviving dependencies (`AssertionError: these are still in package.json, so removing the imports proved nothing: expected [ 'lucide-react', …(2) ] to deeply equal []`). The two chart render tests were written before the components drew anything and were seen failing four times over, each time for a different real reason — no `ResizeObserver`, then a zero-height plot, then the wrong tick selector, then a bar count that counted zero-valued bars.

## What changed

| Thing | Before | After |
| --- | --- | --- |
| Overview chart | `UsageOverview`, three proportional `div` bars and a "busiest day" line | `UsageChart`: a stacked `BarChart` in `ChartContainer`, calls/texts/chats on `--chart-1..3`, `ChartTooltip` + `ChartLegend`, `CartesianGrid`, both axes |
| Platform dashboard chart | `RevenueAndProfitChart`, one proportional bar a day | `RevenueChart`: two gradient `Area`s in `ChartContainer`, revenue and profit on `--chart-1..2`, money on the axis and in the tooltip through `formatCad` |
| Icons | `lucide-react` in 16 files | `@tabler/icons-react` in all 16; no call site's classes or props changed |
| `package.json` | `apexcharts`, `react-apexcharts`, `lucide-react` | all three uninstalled, `package.json` and `package-lock.json` committed together |
| `Main.css` | eleven dead `.apexcharts-*` rule blocks | gone |

The icon mapping, where the Tabler name is not the Lucide one:

```
LogIn          -> IconLogin2        (IconLogin's arrow enters from the right)
Menu           -> IconMenu2         (IconMenu is two bars, not three)
MoreHorizontal -> IconDots
PanelLeftIcon  -> IconLayoutSidebar (rect with a rule at x=9: the same glyph)
CheckCircle    -> IconCircleCheck
LogOut         -> IconLogout
X / XIcon      -> IconX
```

Name-for-name: `Moon`, `Sun`, `Check`, `Search`, `Circle`, `ChevronDown`, `ChevronUp`, `ChevronRight`, `User`, `Settings`, `Shield`, `LayoutDashboard`. Tabler's `createReactComponent` keeps a passed `className` (it appends it after `tabler-icon tabler-icon-<name>`) and accepts the same `size` prop the two user-menu files pass as `"1.1rem"`, so nothing needed a class change: `git diff` on the sixteen files is import lines and JSX tag names only.

## Deviations

- **The overview chart draws thirty days, not the seven the plan asks for.** `getTenantOverview` asks the runtime for `/usage` with no dates and is answered with the last thirty days in the tenant's timezone; the card's header reads "Last `{data.days.length}` days" and `e2e-tests/tests/client.spec.ts:124` asserts `usage-chart-days` has text `"30"`. Slicing to seven would make both the header and that assertion lie, and the spec is only editable where a selector sat on a removed element, which this one does not. The axis thins its own labels through `minTickGap` instead.
- **Eleven `.apexcharts-*` rule blocks came out, not the five R2's notes counted.** `Main.css:444-477` held eleven, every one dead. Evidence: `grep -c apexcharts src/client/Main.css` -> `0`.
- **The two page components keep their names and become the mapping layer**; the drawing moved into `src/client/charts/`. The task says "replace the body of", and the bodies are replaced — but the drawing had to be a separate module to be renderable in a unit test at all, because `RevenueAndProfitChart` imports `DailyStatsProps` from `analytics/stats.ts`, which imports `wasp/server/jobs`. `UsageOverview` now maps a runtime `UsageDay` to a `UsagePoint` (the two SMS directions summed into one "texts" bar) and `RevenueAndProfitChart` orders and labels the weekly stats; each then renders its chart.
- **The "no days recorded yet" and "no day has been recorded yet" lines moved into the chart components**, so the empty case is one place and is covered by their tests rather than being a branch in a page nothing renders in vitest. The wording is unchanged.
- **A date is parsed at local midnight**, not through `new Date("2026-09-03")`. That constructor reads an ISO date as UTC midnight, which is the previous day in Mississauga; the runtime's `UsageDay.date` is a bare `YYYY-MM-DD`, so `dayLabel` splits it and builds a local `Date`.
- **The chart tests stub `ResizeObserver` and the box of one element.** Recharts only measures when a `ResizeObserver` exists, and jsdom lays every element out at zero by zero, so with neither stub nothing is drawn. Stubbing *every* element's `getBoundingClientRect` is worse: the legend is measured the same way, comes back as tall as the chart, and leaves the plot a clip rect of `height="0"`. Only `.recharts-responsive-container` gets a box.
- **`RevenueChart`'s two gradients take their ids from `useId`.** An SVG id is global to the document, and a second instance of the chart would otherwise paint from the first one's gradient.
- **`recharts@3.8` puts axis tick *labels* in a separate z-index layer from the axis**, so the tests read `.recharts-<axis>-tick-labels .recharts-cartesian-axis-tick-value`, not the axis group. Recorded because it is the sort of thing that looks like a typo later.
- **No ApexCharts type shim existed to delete.** `grep -rni "apexchart" src e2e-tests main.wasp.ts tsconfig*.json vite.config.ts` found only the placeholder's own comment; the only `.d.ts` files under `src` are `vite-env.d.ts` and the data-table's `tanstack-table.d.ts`.
- **`npm uninstall` reported "added 6 packages, and removed 6 packages".** The lockfile diff is removals only — `apexcharts`, `react-apexcharts`, `lucide-react`, `@yr/monotone-cubic-spline`, `loose-envify` — plus one `"peer": true` marker on `js-tokens`. The "added" count is npm re-linking the four workspace entries.
- **Prettier was not run**, following R0, R1 and R2: no config file, no format script, no CI step.
- **`wasp build`, `wasp start`, `wasp test`, `wasp db` and `wasp compile` were not run.** Types were checked with `tsc` emitting to `/tmp`, the stylesheet with the standalone Tailwind v4 CLI, the tests with Vitest through WSL node 22.23.2. Nothing under `.wasp/` was written.
- **`nvm` is not on the path of a WSL non-login-interactive shell.** `wsl -e bash -lc "npx vitest run"` falls through to Windows `npx` and fails with a `cmd.exe` error. Every command in this report ran through a two-line script that sources `$HOME/.nvm/nvm.sh` and `nvm use 22.23.2` first; the WSL default is now v24.20.0, and 22.23.2 was chosen to match the baseline R0 to R2 measured.

## Notes for R4

- **Screenshots are owed** for the two pages whose chart changed, light and dark: `/app/:orgSlug/overview` and `/admin`. Both charts follow the theme through `--chart-*`, which is the first thing to look at in dark mode.
- **The console warning ApexCharts produced** ("Added non-passive event listener to a scroll-blocking event") should be gone; it is worth confirming in the browser console on the overview, since its absence is a done criterion of this task.
- **The e2e suite has not run since R2 edited three specs.** `client.spec.ts:121-124` is the assertion that pins the overview chart panel and its thirty days; nothing in this task moved a testid.
- **`.tableCheckbox` is still in `Main.css`** under "third-party libraries CSS" with no call site (`grep -rn tableCheckbox src` finds nothing outside the stylesheet). It was not this task's to remove.
- **One icon set, verified by a test.** `src/client/no-legacy-ui.test.ts` fails on an import specifier naming `lucide-react`, `react-apexcharts` or `apexcharts`, and separately on any of the three still being a dependency. Adding a fourth retired package is one line in its `RETIRED` map.
- **Not committed, and not this task's:** nothing. Everything was staged by explicit pathspec.
