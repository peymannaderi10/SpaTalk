# Lead context Task V1: adversarial verification of L1 and L2

Status: done with deviations
Commit: 7eaf2e8 (tests), plus this report's own commit
Tests: `cd runtime && SPATALK_NO_ENV_FILE=1 TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_v1 .venv/Scripts/python.exe -m pytest -q tests/test_lead_context_verification.py` -> 29 passed, 8 xfailed (37/37); full runtime suite -> 1042 passed, 1 failed, 2 skipped, 8 xfailed (1042/1043 excluding skips)
Verdict: **pass with majors** for tasks L1 (69dd0bf) and L2 (13977db). Two blocking items belong to the gate and not to this plan: the suite is not green on a clean checkout, and `items.preferred_window` still accepts free text. Neither was introduced by L1 or L2.

## What was verified, and how

Read the diffs, not the reports: `git show 69dd0bf` and `git show 13977db` in full, plus the plan, `docs/reference/{data-model,tenant-config,api-surface}.md`, `docs/agents/QA.md` and `docs/agents/REVIEWER.md`. Then wrote `runtime/tests/test_lead_context_verification.py` (37 tests) to try to break each promise the plan makes, in the plan's own words. No product code was changed; no existing test was weakened, skipped or deleted.

Evidence run outside pytest:

- Migration cycle on a scratch database `spatalk_test_v1mig`: `alembic upgrade head` (0010 -> 0011), `information_schema` shows `returning_client boolean null`, `practitioner varchar(80) null`, `concern varchar(40) null` exactly as `data-model.md` states; `alembic downgrade -1` leaves zero of the three columns; `alembic upgrade head` re-applies; `alembic check` reports "No new upgrade operations detected".
- Portal: `npx vitest run --environment node src/client/formatting.test.ts` in WSL -> 19 passed, including the six new `clientLabel` / `practitionerLabel` cases. Run with vitest directly rather than `wasp test client run`, deliberately: `wasp` regenerates `.wasp/out`, which the founder's running `wasp start` watches, and the hard rules forbid disturbing it. `npm run --silent test:unit` -> 108 passed (server suite, unchanged by this plan).
- `ruff check spatalk tests scenarios` -> "All checks passed!".
- Scratch databases `spatalk_test_v1` and `spatalk_test_v1mig` were dropped at the end. The runtime on port 8000, `runtime/.env`, the dev database `spatalk` and the founder's running portal were never touched.

## Findings (most severe first)

**[blocking, inherited] `runtime/tests/test_ops_latency.py:599` — the suite is not green on a clean checkout.**
`test_the_eval_bot_runs_the_production_pipeline_in_the_production_order` fails at HEAD. It parses the `Pipeline([...])` lists of `runtime/spatalk/voice/pipeline.py` and `runtime/scenarios/voice/eval_bot.py`; commit `1fc602b` added `FillerProcessor(session)` to production without adding it to the eval bot. Neither file was touched by L1 or L2 (`git log -1 --` on both returns `0216195` and `63d86a6`), so this predates the plan. QA.md makes "a suite that does not pass on a clean checkout" blocking, so it blocks the gate, not the two tasks. Fix: add `FillerProcessor(session)` to `scenarios/voice/eval_bot.py` in the same position, or state the divergence in the test.

**[blocking, inherited] `runtime/spatalk/brain/tools.py:27` — free text still reaches an item through `preferred_window.date`.**
`WINDOW["properties"]["date"]` is `{"type": "string"}` with no enum, `PreferredWindow.date` is an unvalidated `str`, and `PgLedger.create_item` writes `draft.preferred_window.model_dump()` straight into the JSONB column. A draft with `date="whenever the burn on my arm from the laser settles down"` is stored verbatim (proved by `test_free_text_in_the_preferred_window_never_reaches_the_items_table`, currently `xfail(strict=True)`). QA.md makes "a free-text field on an item" blocking. It predates the lead-context plan but the plan re-affirms "Still no free text", so it is in scope for this gate. Fix: a field validator on `PreferredWindow` that keeps `"any"` or an ISO `YYYY-MM-DD` and rewrites anything else to `"any"` — one line, and `preferred_text` already treats an unparseable date as no date.

**[major] `runtime/spatalk/ledger/delivery.py:870-875` — the summary outranks the health warning and the caller's number in the owner's text.**
The drop order is health line, then who line, then summary, so the 154-character sentence is the last thing to go. A breached, health-flagged `new_booking` whose caller gave an email address (`ESCALATED, past due:` prefix, name "Priya Balasubramanian", `priya.balasubramanian@gmail.com`) now arrives without `Caller mentioned a health condition; read the transcript first.`; the same item's text was 313 characters and kept that line before this task. With a longer name the who line goes too, and the owner gets a lead with no number to call. Fix: reorder the loop so the summary is dropped first — `((flagged, True, True), (flagged, True, False), (False, True, False), (False, False, False))` — and correct the docstring at `:833-840`, which states the wrong priority as if it were the intended one.

**[major] `runtime/spatalk/ledger/summary.py:88-110` and `delivery.py:66` — the day the caller actually named survives on no channel.**
`preferred_text` maps an ISO date to a bare weekday, so "call me back on the 24th of September" reaches the owner as "Thursday" in the SMS, the email, the Slack card, the digest and the portal card alike. Before L1 the staff line read `Preferred: 2026-09-24, afternoon`. Three weeks out, "Thursday" reads as this Thursday. Fix: when the window holds a real date, render it as `"Thursday 24 September"` in the staff fact line (`preferred_text` may keep the short form inside the sentence if the plan's table must stand).

**[major] `runtime/spatalk/ledger/items.py:31` and `:41` — the rejected value is echoed into the service log.**
`practitioner_for` and `concern_for` log `{!r}` of whatever the model returned. The model returns what the caller said, so `WARNING ... has no concern 'my rash keeps coming back and I am 20 weeks pregnant'` lands in the runtime log, which no retention job reaches and which is not the transcript. CLAUDE.md 2 says the detail lives only in the transcript. Fix: log the tenant, the field and the length, never the value.

**[major] `runtime/spatalk/brain/tools.py:60` — the `concern` description invites a value outside its own enum.**
"What the caller says they want help with, in their own terms." A model that obeys that returns free text, the ledger nulls it, and the lead context is silently lost (and logged, see above). Fix: "The closest of the listed concerns to what the caller says they want help with."

**[major] `runtime/spatalk/brain/prompt.py:112` — the offer instruction is unconditional.**
"If they have not: mention the clinic's new-client offers listed in the facts once" is given to every tenant, including one whose knowledge file lists no offer. The plan's own constraint is "it never invents a discount", and nothing downstream would catch an invented one: `guard()` checks completion wording, not prices. Fix: make the clause conditional — "If they have not, and the facts list a new-client offer: mention it once, warmly, as an option".

**[major] `runtime/spatalk/tenants/schema.py:34` and `:275-276` — a legal tenant config can break every item write.**
`TeamMember.name` and `concerns[]` are unbounded strings, but the columns are `varchar(80)` and `varchar(40)`. A team name of 200 characters is accepted at import and then every item naming that person fails with `asyncpg.exceptions.StringDataRightTruncationError`, losing the request mid-call. Fix: `Field(max_length=80)` on `TeamMember.name` and `max_length=40` on the concern items, so a bad config is refused at import instead of at 2 a.m.

**[major] `runtime/spatalk/tenants/schema.py:46-62` — nothing keeps medicine out of `concerns`.**
The shipped default list is clean (verified against both lexicons), but `TenantConfig.model_validate` accepts `["rosacea", "pregnancy"]`, after which the ledger treats those as valid closed values and writes them to `items.concern`. That is the plan's "Health stays out of the fields" enforced by convention only. Fix: validate `concerns` against `DEFAULT_LEXICONS["clinical"]` and `HEALTH_CONTEXT_DEFAULT` in the schema.

**[minor] `runtime/spatalk/http/internal.py:781` — acknowledge and resolve now depend on a tenant config.**
`_transition` calls `item_out(item, await _tenant_config(...))`; before L1 it validated the row alone. A tenant whose config row is missing turns two previously working portal actions into a 404. Acceptable, but it is a new coupling worth knowing about.

**[minor] `runtime/spatalk/ledger/summary.py:83-85` — `type_label` falls back to the raw type.**
An item type with no entry in `TYPE_LABELS` would print `escalation_whatever` to the owner. Every type the code can construct is labelled today; `test_every_item_type_the_runtime_can_create_has_a_label` locks that door so a new type cannot leak a raw id.

## What held up under attack

- **The closed vocabulary.** Six values a model plausibly returns instead of the enum — an invented name, the right name in the wrong case, a first name, the caller's own words, `"ANY"`, and the empty string — all store `NULL`. Every clinical and health-context lexicon term offered as a `practitioner` and a `concern` (63 items) stores `NULL` while `health_context` stays true. `Item(...)` is constructed in exactly one file, so there is no second writer that skips the check.
- **The sentence.** 20,160 combinations of type × service × practitioner × concern × returning × window (including a null window, empty strings and an unparseable date) contain no `"None"`, no `"any any"`, no double space, no `" ."`, and no underscore — so no raw service id and no raw type. Every service in the bundle renders by name and never by id. `summary`, `service_name` and `preferred_text` are not columns, so the sentence cannot drift from the fields.
- **Honesty.** Nothing under `spatalk/brain` imports `ledger.summary`, so the composed sentence cannot reach a caller; the spoken outcome of a fully-qualified capture names neither the practitioner, the concern, nor "new client". The summary of a health-flagged item says nothing about health.
- **The three-segment rule.** Four items including the longest service, the longest practitioner, the longest concern, a 44-character name, a 66-character email, an urgent escalation and a name outside GSM-7 (which forces UCS-2 and 201 characters) all stay within three segments and all end in the intact transcript link.
- **The tool surface.** `returning_client` is a boolean with no enum; `practitioner` equals `cfg.practitioner_names()`; `concern` equals `cfg.concerns`; none is required; `request_appointment_change`, `escalate` and `end_conversation` gained nothing; no parameter anywhere contains "note".
- **The contract and the card.** The committed OpenAPI equals the live `ItemOut` schema, all six new fields are required, the generated `client.ts` declares them with the right types, `RequestsPage.tsx` contains no `service_id`, and every optional fact on the card is guarded so an unasked question renders nothing.
- **The migration.** Adds three columns and drops exactly those three, both against `schema="runtime"`, `0010 -> 0011`, widths matching the models, and a clean up/down/up cycle with no drift.

## Deviations

- The eight gaps above are recorded as `xfail(strict=True)` tests rather than failures, as the task asked: each marker's reason names the plan line it breaks, so an XPASS after a fix forces the marker to be deleted with it. The suite therefore stays green and the gaps stay visible.
- `test_the_only_unenumerated_strings_on_a_tool_are_contact_details` asserts a subset (`<=`) rather than equality, so that fixing `preferred_window.date` does not fail it; the gap itself is pinned by the strict xfail.
- The portal's client tests were run with `npx vitest run` on `src/client/formatting.test.ts` rather than `wasp test client run`, to avoid regenerating `.wasp/out` under the founder's running `wasp start`. `wasp build` was not run for the same reason; L2's report records 78/78 and a successful build, and this task changed no portal file.
- Three portal source files are read from the runtime suite (`formatting.ts`, `formatting.test.ts`, `RequestsPage.tsx`, `client.ts`). That follows the precedent in `tests/test_qa_gate_b.py:686`, which already reads `portal/src/runtime/client.ts` from Python.

## Notes for neighbours

- The two smallest, highest-value fixes are the SMS drop order (one tuple in `delivery.py`) and the `concern` description (one sentence in `tools.py`). Both are inside files L1 owns.
- Do not delete an `xfail` marker without the fix: `strict=True` means the test fails if the behaviour changes, which is the point.
- `runtime/tests/test_lead_context_verification.py` needs a database (four of its tests use the `sf` / `registry` fixtures) and reads `portal/`, so it runs from `runtime/` with `TEST_DATABASE_URL` set, like the rest of the suite.
