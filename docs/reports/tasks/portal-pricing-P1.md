# portal-pricing Task P1: The provider cost is the agency's; a quote builder for admins
Status: done with deviations
Commits: `159a412` (the overview card), `7c46d71` (the quote builder)

Tests: `npx vitest run` (WSL node 22.23.2) → **177/177 in 17 files**, of which 29 are new (`pricing.test.ts` 23, `overview.test.tsx` 5, `nav.test.ts` +1); the baseline this task inherited was 148/148 in 15 files, checked before touching anything. `npx vitest run -c vitest.server.config.ts` → 108/108 in 6 files, unchanged. `npx tsc -p tsconfig.src.json --noEmit --outDir /tmp/spatalk-tscheck` → **exit 2, six errors, every one of them the generated Wasp SDK being older than this commit** — see "The type-check" below, which includes the run that proves it. Playwright was **not run** and **no spec was edited**: nothing this task changed is asserted by one.

Interfaces produced: `portal/src/admin/pricing.ts` exports `RatesFile`, `Telephony`, `Stt`, `Tts`, `Llm`, `Sms`, `CallAssumptions`, `TextAssumptions`, `VolumeAssumptions`, `VoiceStack`, `TextStack`, `ConversationAssumptions`, `conversationAssumptions`, `llmPerTurn`, `voicePerMinute`, `textConversation`, `outboundMessage`, `fixedPlatformCad`, `DEFAULT_MARGIN`, `DEFAULT_CLIENTS`, `clampMargin`, `clampClients`, `priceAtMargin`, `marginOf`, `QuoteInputs`, `QuoteLine`, `Quote`, `quote`, `recommendedVoiceStack`, `recommendedTextStack`, `defaultInputs`, `MeasuredTenant`, `MeasuredCost`, `measured`, `ASSUMPTIONS_STORAGE_KEY`, `StoredAssumptions`, `StorageLike`, `DEFAULT_ASSUMPTIONS`, `loadAssumptions`, `saveAssumptions`; `portal/src/admin/AdminPricingPage.tsx` exports `AdminPricingPage`; `portal/src/admin/operations.ts` exports `getRates`; `portal/src/client/overview.tsx` exports `OverviewTile`, `OverviewCards`, `overviewTiles`, `OverviewTiles`; `portal/src/client/operations.ts`'s `Overview` gains `viewerIsAgencyAdmin`; `src/admin/admin.wasp.ts` declares `AdminPricingRoute` at `/admin/pricing` and `query(getRates, { entities: [] })`; `nav.ts`'s `PLATFORM_SECTIONS` gains **Pricing**.

TDD: `pricing.test.ts` was written first and seen failing — the whole file failed to transform, because `./pricing` did not resolve. The `nav.test.ts` addition was written next and seen failing 1/16, naming `nav-pricing`. `overview.test.tsx` was written before `overview.tsx` but the two were run together, so it was not observed red; instead the guard was mutated (`if (data.viewerIsAgencyAdmin)` → `if (true)`) and the test seen failing 2/5 on exactly the two cases that matter ("shows a clinic no provider cost at all", "counts the cards: seven for a clinic, eight for the agency"), then restored.

## 1. The provider cost is the agency's number

`totals.est_cost_cad` is what Telnyx, Soniox, Inworld and Google charged **us** to answer this clinic's phone — around one hundredth of what the clinic pays for the month. Every owner and every staff member could read it on `/app/:orgSlug/overview`. Now only an agency admin can.

- The decision is the server's. `getTenantOverview` returns `viewerIsAgencyAdmin: context.user?.isAdmin === true` beside the role it already returned, which is how `organizationIsEntitled` is already told who is asking (`payment/entitlement.ts`, `organizations/operations.ts`). No operation returned a field of that name before, so this is the first; the pattern it copies is the argument name.
- The card list left the markup for `portal/src/client/overview.tsx`: `overviewTiles(data)` is a pure function returning eight descriptors for an admin and seven for anyone else, and `OverviewTiles` draws them in the kit's dashboard row. `OverviewPage.tsx` now renders `<OverviewTiles tiles={overviewTiles(data)} />` and its local `Tile` is gone.
- Every existing testid is on the card that had it: `tile-calls`, `tile-call-minutes`, `tile-texts`, `tile-chats`, `tile-open-items`, `tile-overdue-items`, `tile-p95-latency`, `tile-est-cost`. **Reply time (p95) stays for everyone.**
- **No Playwright spec was touched.** `client.spec.ts:117` asserts `tile-est-cost` on `ownerPage`, and `ownerPage` is signed in as `agencyAdmin` (`client.spec.ts:60`), so the assertion still holds. No spec puts a staff member on the overview.

## 2. `/admin/pricing`, the quote builder

| Piece | Where | What it is |
| --- | --- | --- |
| The rates | `getRates` in `src/admin/operations.ts` | `requireAdmin`, then `GET /internal/rates` through the same typed client every other runtime read uses. The portal keeps no copy: this is the file behind every `est_cost_cad`, and `runtime/spatalk/rates.json` is pinned equal to `docs/research/rates.json` by a runtime test. |
| The model | `src/admin/pricing.ts` | A port of `docs/research/costmodel.py`, function for function: `llmPerTurn`, `voicePerMinute`, `textConversation`, `outboundMessage`, `fixedPlatformCad`, `quote`. |
| The page | `src/admin/AdminPricingPage.tsx` | The kit's settings idiom: header, form card, results card, then the measured card and the assumptions disclosure. |
| The route | `admin.wasp.ts` | `AdminPricingRoute` at `/admin/pricing`, `authRequired: true`, inside `DefaultLayout`, which refuses a non-admin — and `getRates` refuses one again on the server. |
| The sidebar | `nav.ts` | **Pricing**, `nav-pricing`, in the Platform section between Tenants and Health. `nav.test.ts` accounts for the route. |

**The figures the test pins**, obtained by running `cd runtime && .venv/Scripts/python.exe ../docs/research/costmodel.py ../docs/research/rates.json` once and asserted to four decimal places (the precision the Python prints, so the test rounds with `toFixed(4)` rather than a tolerance):

| What | Python | Pinned |
| --- | --- | --- |
| Voice, CAD per call-minute, stack A | 0.0480 | ✓ |
| …stack B (recommended) | 0.0314 | ✓ |
| …B2 / B3 / C / D / B4 | 0.0394 / 0.0300 / 0.0224 / 0.0631 / 0.0309 | ✓ |
| B's USD/min split | tel 0.0130, stt 0.0020, tts 0.0062, llm 0.0014 | ✓ |
| Telnyx text stack: SMS conv / chat conv / outbound msg, CAD | 0.1423 / 0.0033 / 0.0174 | ✓ |
| Twilio text stack | 0.2234 / 0.0033 / 0.0227 | ✓ |
| Fixed platform cost, CAD/month, 1 / 10 / 25 clients | 24.51 / 72.09 / 216.45 | ✓ |
| Cost of goods at the default volumes, one client | 79.48 | 79.4811 |
| Price at 65% margin | — | 227.0890 |
| Margin at the CA$999 list price | 92.0% | 0.9204393 |
| The six breakdown lines | — | voice 23.5824, sms 21.3443, chat 0.3335, outbound 5.2110, per-tenant fixed 4.5000, platform share 24.5100 |

Also pinned: 65% margin on a cost of 100 is 285.71 (`priceAtMargin`), the tier choice for 1, 5, 10, 25 and 40 clients, `marginOf` and its refusal to report a margin on a price of nothing, a web chat costing the model and nothing else, an unknown stack key throwing rather than silently substituting, and the measured division refusing to divide by no calls. **Nothing in the test reaches the network**; it reads `docs/research/rates.json` off disk.

**What the page shows.** Inputs `pricing-calls`, `pricing-avg-minutes`, `pricing-sms-convs`, `pricing-chat-convs`, `pricing-outbound`, `pricing-voice-stack`, `pricing-text-stack`, all starting at `assumptions_volume` / `assumptions.avg_call_minutes` and the two stacks the file marks `recommended`. Results: six `pricing-line-<id>` rows, `pricing-cogs`, `pricing-price` with `pricing-at` under it ("at 65% margin, 1 client on the platform"), four unit costs (`pricing-per-call`, `pricing-per-minute`, `pricing-per-text`, `pricing-per-chat`) printed to four decimal places because two would say "$0.03", and `pricing-list-price` / `pricing-list-margin` for the brief's CA$999. Measured: `pricing-tenant` selects one of the agency's clinics and the table puts `pricing-measured-calls`, `-minutes`, `-cost`, `-per-call`, `-per-minute` beside `pricing-model-variable`, `pricing-model-per-call`, `pricing-model-per-minute`. `pricing-fx` footnotes `usd_to_cad` and `_fx_source`. `pricing-problem` is the refused-rates alert; `pricing-measured-problem` is a tenant the runtime could not answer for; `pricing-no-tenants` is the empty state.

**The assumptions disclosure** (the coordinator's addendum): a `Collapsible`, closed by default, trigger `pricing-assumptions`, holding `pricing-margin` (in per cent) and `pricing-clients`, the sentence "Margin, not markup: 65% margin means the cost is 35% of the price, so a cost of CA$100 is quoted at CA$285.71", and `pricing-reset` back to 65% and one client — shown only when the pair is not already the default, because a reset that resets nothing is a button that does nothing.

## The type-check

`npx tsc -p tsconfig.src.json --noEmit` exits 2 with six errors. **All six are the generated SDK snapshot being older than this commit, and all six clear when the orchestrator restarts the portal** (a restart regenerates `.wasp/out`). They are:

```
src/admin/AdminPricingPage.tsx(4,28): Module '"wasp/client/operations"' has no exported member 'getRates'.
src/admin/AdminPricingPage.tsx(114,19): Type '{}' is missing ... from type 'RatesFile'.   (a consequence of the first)
src/admin/operations.ts(7,8):  Module '"wasp/server/operations"' has no exported member 'GetRates'.
src/admin/operations.ts(265,59): Parameter '_args' implicitly has an 'any' type.           (a consequence of the third)
src/admin/operations.ts(265,66): Parameter 'context' implicitly has an 'any' type.          (likewise)
src/client/OverviewPage.tsx(58,43): 'Overview' is missing 'viewerIsAgencyAdmin'.
```

The first five are a new operation: `GetRates` and `getRates` do not exist in `.wasp/out/sdk/wasp` until Wasp regenerates it from `admin.wasp.ts`, and agents may not run `wasp compile`/`start`/`build`. Writing the operation without the generated type would have made these five go away and left the file the only operation in the portal not typed like its neighbours; the idiomatic version was kept.

The sixth looked like a real error and is not. `wasp/src/*` resolves through the SDK's `package.json` to `./dist/src/*.js` — `.wasp/out/sdk/wasp/dist/src/client/operations.d.ts`, dated **2026-09-03 18:52**, a compiled snapshot of `src/client/operations.ts` from before this task. That stale `Overview` is what `useQuery(getTenantOverview)` hands the page. Proof, run and then deleted:

```
# tsconfig.pathcheck.json: extends ./tsconfig.src.json,
#   "paths": { "wasp/src/*": ["./src/*"] }
npx tsc -p tsconfig.pathcheck.json --noEmit
→ the five getRates errors only; OverviewPage.tsx is clean.
```

So with the SDK pointed at the live sources, the only thing tsc has to say about this task is that the operation it adds has not been generated yet.

## Deviations

- **`viewerIsAgencyAdmin` is a new field, not a copied one.** The task says to add it "the way another operation already does". No operation returned such a field; what exists is `organizationIsEntitled({ viewerIsAgencyAdmin })`, an argument, in three call sites. The field is named after that argument and set from the same expression, and its doc comment says why the answer is the server's.
- **`voicePerMinute` and `textConversation` return USD, not CAD.** The Python's `voice_per_minute` reads a module-global `FX` to add `total_cad`; the signatures the task fixes (`voicePerMinute(tel, stt, tts, llm, assumptions)`) have nowhere to put an exchange rate. The functions therefore return the USD parts and a `totalUsd`, and `quote` — which has the whole rates file — converts. The test multiplies by `rates.usd_to_cad` and gets the Python's CAD figures to four decimals.
- **`textConversation`'s fourth argument is `{ turn, text }`.** The Python reads two module globals, `A` (`assumptions`) and `T` (`assumptions_text`); one conversation needs both, and `conversationAssumptions(rates)` builds the pair.
- **`fixedPlatformCad` picks the tier numerically.** `costmodel.py` writes `max(k for k in R["fixed_cad"] if int(k) <= n)` — a `max` over *strings*. For the file's three keys ("1", "10", "25") string order and numeric order agree at every client count, so the two implementations cannot disagree today; a fourth key such as "5" would make them differ, and numeric is what the Python means. A count below the smallest tier gets the smallest tier rather than the `ValueError` the Python would raise.
- **The measured "Provider cost" row compares against the four variable lines, not the whole cost of goods.** `est_cost_cad` is what the runtime priced from usage — minutes, tokens, characters, messages. The per-tenant fixed line and the share of the servers are the agency's own bill and are not in it, so putting them on the modelled side of that row would have compared two different things. The two unit-cost rows are the task's own definition, `est_cost_cad / calls` and `/ minutes`, and the paragraph under the table says out loud that they carry the month's texts and chats as well and are therefore the outside edge of what a call cost.
- **The measured column reuses `getAgencyTenants`.** The task says no new runtime endpoints and names "the runtime's usage endpoint the overview already uses"; `getAgencyTenants` already reads that endpoint per tenant and returns `calls`, `callMinutes` and `estCostCad` for the tenant's own month. A second operation doing the same reads would have been a second answer to the same question. A tenant whose row carries a `problem` shows "—" and the sentence, never its zeroes.
- **Margin and client count are per browser, not per agency.** `localStorage`, key `spatalk.admin.pricing.assumptions`, every read and write in `try`/`catch`, defaults 65% and 1 when nothing is stored or storage throws. **This is not shared between admins or between an admin's own browsers.** Somewhere shared would be a column on `Organization` or a new settings table and a Prisma migration with it, which is the orchestrator's to run, not an agent's. The page prints both values under the quoted price so a remembered figure is never a hidden one.
- **`clampMargin` caps at 0.99.** A margin of exactly 1 prices any cost at infinity; the input is capped at 99 as well, and a non-number falls back to 65% rather than quietly to zero.
- **No e2e spec was edited**, and none needed to be: `client.spec.ts`'s overview test runs as the agency admin, and no spec asserts the platform sidebar's exact contents. The first Playwright run after this is still worth watching for `nav-pricing` appearing in the admin shell.
- **Prettier was not run**, following R0, R1, R2 and E1: no config file, no format script, no CI step.
- **`wasp build`, `wasp start`, `wasp test`, `wasp db` and `wasp compile` were not run**, and nothing was written under `.wasp/`. Types were checked with `tsc` emitting to `/tmp`, the tests with Vitest through WSL node. No stylesheet changed, so the Tailwind CLI was not needed. `src/runtime/client.ts` was **not** regenerated: `/internal/rates` is already in it (`rates_internal_rates_get`, returning `{ [key: string]: unknown }`), which is why `getRates` casts once to `RatesFile`.
- **Nothing under `runtime/` was touched.** `runtime/spatalk/voice/pipeline.py` and `runtime/tests/test_voice_turns.py` were already modified in the working tree when this task started; they are somebody else's and were left unstaged.

## Notes for neighbours

- **The orchestrator's restart is what makes the page compile.** Until `.wasp/out` is regenerated the portal will not build with `getRates` in it; after the restart, re-run `npx tsc -p tsconfig.src.json --noEmit` and it should be silent.
- **Screenshots are owed, light and dark**: `/admin/pricing` with the Assumptions disclosure shut and open, the admin sidebar showing **Pricing**, and `/app/:orgSlug/overview` as a clinic owner (seven cards) and as an agency admin (eight).
- **The quote is a model and the page says so.** The measured column exists because on 2026-09-03 the runtime was using about 190,000 input tokens a call, against the roughly 50,400 the rate file's assumptions imply for a three-minute call. If the founder wants the model to match the runtime, the fix is `input_tokens_cached_per_turn` in `docs/research/rates.json` and `runtime/spatalk/rates.json` together — a runtime change, and not this task's.
- **A new page under `/admin` still has to choose a shell**; `nav.test.ts` fails with the route named until it is in `PLATFORM_SECTIONS`, `NAV_SECTIONS` or `ROUTES_OFF_THE_SIDEBAR`.
- **Not committed, and not this task's:** the two runtime files above. Everything else was staged by explicit pathspec.

---

# Follow-up, 2026-09-05: the page prices the production stack and shows a customer only the price
Status: done
Commit: the one this section arrived in, `feat(portal): quote page prices the production stack and shows customers only the price`

Tests: `npx vitest run` → **184/184 in 18 files** (from 177/177 in 17); `pricing.test.ts` 23 → 26, `QuoteBuilder.test.tsx` 6 new. `npx vitest run -c vitest.server.config.ts` → 108/108, unchanged. `npx tsc -p tsconfig.src.json --noEmit` → **exit 2, one error, again the stale compiled SDK snapshot** (details below). Playwright not run; no spec touched.

Three founder decisions, one commit.

## 1. One stack: the one that is running

`docs/research/rates.json` and `runtime/spatalk/rates.json` now carry `live_stack` — Telnyx telephony, Soniox STT, Soniox TTS, Gemini Flash-Lite at the 2.5 Flash-Lite rate, Telnyx toll-free SMS. `quote()` prices that and nothing else:

- `pricing.ts` gains `LiveStackRef` (the five keys and a label), `LiveStack` (the same with the rates read out) and `liveStack(rates)`, which **throws naming the field** when the file points at a vendor it does not hold, rather than pricing a missing vendor at nothing.
- `QuoteInputs` loses `voiceStack` and `textStack`; `recommendedVoiceStack` and `recommendedTextStack` are gone, and so are the two selects.
- `voice_stacks` and `text_stacks` stay on the `RatesFile` type and stay pinned in the test. They are the **calibration**: `costmodel.py` prints those seven per-minute figures and those six text figures, and asserting them is what proves `voicePerMinute` and `textConversation` are a faithful port. The live stack is not one of them, so its figures were computed with the Python's own formulas over the same file and asserted to the same four places.
- `Quote` gains `unitPrices` (each unit cost divided by `1 - margin`) and `stackLabel`.

**The new pinned figures**, live stack, `usd_to_cad` 1.3896:

| | |
| --- | --- |
| USD per call-minute | tel 0.0130, stt 0.0020, tts 0.0058, llm 0.0004 |
| Voice, CAD per call-minute | **0.0295** |
| SMS conversation / web-chat conversation / outbound message, CAD | **0.1399 / 0.0009 / 0.0174** |
| Cost of goods at the default volumes, one client | **77.4114** |
| Price at 65% margin | **221.1755** |
| Margin the CA$999 plan would carry | **0.9225111** |
| Breakdown | voice 22.1137, sms 20.9837, chat 0.0931, outbound 5.2110, per-tenant fixed 4.5000, platform share 24.5100 |
| Unit costs | per call 0.0885, per minute 0.0295, per SMS conversation 0.1399, per chat conversation 0.0009 |
| Unit prices at 65% | per call **0.2527**, per minute **0.0842**, per SMS conversation **0.3997**, per chat conversation **0.0027** |

Cheaper than the September recommendation on every line but one: Soniox TTS and Flash-Lite take the call-minute from 0.0314 to 0.0295 and the chat conversation from 0.0033 to 0.0009, and the month from CA$79.48 to CA$77.41.

## 2. The measured section is gone

The "Measured, this month" card, the `getAgencyTenants` query on this page, and `measured` / `MeasuredTenant` / `MeasuredCost` with their two tests, all removed. Nothing on the page reads a tenant's row now, and the page asks the runtime for one thing: its rates.

## 3. A page an admin can turn around

`AdminPricingPage.tsx` is now the Wasp shell alone — fetch the rates, hand them to `QuoteBuilder`. **`src/admin/QuoteBuilder.tsx` is Wasp-free**, which is what lets `QuoteBuilder.test.tsx` render the whole page from a rates file on disk.

| Visible | Inside **Internal** (`pricing-assumptions`, shut by default) |
| --- | --- |
| The five needs inputs: `pricing-calls`, `pricing-avg-minutes`, `pricing-sms-convs`, `pricing-chat-convs`, `pricing-outbound` | The cost-of-goods breakdown: six `pricing-line-*` and `pricing-cogs` |
| The monthly price, large: `pricing-price` | The margin and client read-out: `pricing-at` |
| Four unit **prices**, labelled as prices: `pricing-price-per-call`, `-per-minute`, `-per-text`, `-per-chat` | Four unit **costs**: `pricing-per-call`, `-per-minute`, `-per-text`, `-per-chat` |
| The standard plan for comparison: `pricing-list-price` | The controls, the margin-not-markup sentence and `pricing-reset`: `pricing-margin`, `pricing-clients` |
| | What the CA$999 plan would carry: `pricing-list-margin` |
| | The rates footnote with the exchange rate, its source and the stack label: `pricing-fx` |

Radix leaves a closed `CollapsibleContent` **unmounted**, so none of the right-hand column is in the document at all — not hidden, absent. `QuoteBuilder.test.tsx` asserts exactly that: every cost testid is `null` while the disclosure is shut, and `container.textContent` does not match `/margin|cost of goods|CAD\/min/i`; then it clicks the trigger and asserts the same words and testids appear, so the guard cannot pass vacuously.

The page header's description changed with it, from "What a month of SpaTalk costs the agency…" to "What a clinic would pay a month, from what its front desk has to handle."

## The type-check, again

One error:

```
src/admin/AdminPricingPage.tsx(57,24): Property 'live_stack' is missing in type
  '.wasp/out/sdk/wasp/dist/src/admin/pricing'.RatesFile
  but required in type 'src/admin/pricing'.RatesFile
```

The five `getRates` errors reported in the first half of this report are **gone**: the orchestrator restarted the portal at about 10:45 and Wasp regenerated the SDK, which is exactly what that section predicted. What is left is the same stale-snapshot mechanism one level down — `.wasp/out/sdk/wasp/dist/src/admin/pricing.d.ts`, compiled at 10:45 from the previous commit, has no `live_stack` — and it clears on the next restart. Proof, run and then deleted:

```
# tsconfig.pathcheck.json: extends ./tsconfig.src.json,
#   "paths": { "wasp/src/*": ["./src/*"] }
npx tsc -p tsconfig.pathcheck.json --noEmit
→ exit 0, no output.
```

## Deviations

- **The per-stack figures stayed in the test.** "Remove the stack inputs and their tests" was read as the selectors and the tests *of* them (`recommendedVoiceStack`/`recommendedTextStack`, "refuses a stack the rates file does not have" — both gone). The seven voice stacks and two text stacks that `costmodel.py` actually prints are the only place the port is checked against the Python's own output, and the live stack is not among them; dropping those assertions would have left the port unverified.
- **`measured()` went with its section.** Decision 2 names the card and the query; the helper existed only for that card, so it and its tests were removed rather than left as an export nothing calls.
- **`pricing-at` moved rather than disappeared.** The 2026-09-04 addendum wanted the margin and client count visible beside the results so a quote is never ambiguous; decision 3 puts everything about our side behind the disclosure. It is now the first line inside Internal, keeping its testid.
- **Prettier was not run**, and no `wasp` command was run; nothing was written under `.wasp/`.
- **Nothing under `runtime/` was touched.** The `live_stack` key was already in both rates files when this follow-up started.
