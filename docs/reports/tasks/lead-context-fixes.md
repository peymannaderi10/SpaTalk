# Lead context Task V1-fix: close the verification findings

Status: done with deviations
Commit: 3ff71a5 (the fixes), plus this report's own commit
Tests: `cd runtime && SPATALK_NO_ENV_FILE=1 TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_fix .venv/Scripts/python.exe -m pytest -q tests/test_lead_context_verification.py tests/test_lead_context.py tests/test_ops_latency.py::test_the_eval_bot_runs_the_production_pipeline_in_the_production_order` -> 66 passed (66/66); full runtime suite -> 1054 passed, 2 skipped, 0 failed, 0 xfailed (1054/1054 excluding skips)
Interfaces produced: `PreferredWindow._closed_date`, `WEEKDAY_NAMES`, `MONTH_NAMES`, `TenantConfig._concerns_are_cosmetic`, `Concern` (annotated `str`, max 40)

Closes the eight findings in `docs/reports/tasks/lead-context-V1.md`, each with the smallest
change that satisfies its test. All eight were pinned by `xfail(strict=True)` tests in
`runtime/tests/test_lead_context_verification.py`; every marker was deleted with its fix, which
is what `strict=True` was there to force. The suite now has no xfails at all.

## The eight

1. **[blocking] The eval bot ran a different pipeline from production.**
   `runtime/scenarios/voice/eval_bot.py` now builds `FillerProcessor(session)` after the user
   aggregator and before the LLM, exactly as `runtime/spatalk/voice/pipeline.py:242` does, so an
   eval measures the pipeline production runs. `test_ops_latency.py::test_the_eval_bot_runs_the_production_pipeline_in_the_production_order`
   was the one test failing on a clean checkout; it passes.

2. **[blocking] `preferred_window.date` was free text.**
   `PreferredWindow.date` (`runtime/spatalk/brain/requests.py`) gains a `mode="before"` field
   validator: an ISO date normalises to `YYYY-MM-DD`, a weekday name normalises to its
   capitalised form, and everything else — a sentence in the caller's words, a mangled date,
   an empty string, `None` — becomes `"any"`. It never raises, so a rejected value costs the
   preference and never the request. `WINDOW["properties"]["date"]`'s description in
   `runtime/spatalk/brain/tools.py` now says what the field takes and that anything else is
   discarded. The ledger writes `model_dump()` unchanged, so the JSONB column can no longer
   hold anything but those three shapes.

3. **[major] The SMS drop order put the summary last.**
   `build_sms_text` in `runtime/spatalk/ledger/delivery.py` now drops the summary first, then
   the health line, then the who line: `((flagged, True, True), (flagged, True, False),
   (False, True, False), (False, False, False))`. Every word of the sentence is on the portal
   card and in the transcript; the health line tells the owner how to read the call before they
   make it, and the who line is the number they call. The docstring, which stated the old order
   as if it were the intended one, is corrected.

4. **[major] The day the caller named survived on no channel.**
   `preferred_text` in `runtime/spatalk/ledger/summary.py` renders a real date as
   `"Thursday 24 September"`, and with a part of day as `"Thursday 24 September, afternoons"`.
   A weekday the caller named without a date is only a weekday and still renders
   `"Thursday"` / `"Thursday afternoon"`, which is the plan's own table; `"any"` still renders
   `"any day"`. One place changes, so the SMS, the email, the Slack card, the digest and the
   portal card all move together.

5. **[major] A rejected value was echoed into the service log.**
   `practitioner_for` and `concern_for` in `runtime/spatalk/ledger/items.py` log the tenant, the
   field and the value's length, never the value. The caller's words live only in the
   transcript, which retention reaches.

6. **[major] The `concern` description invited free text.**
   `runtime/spatalk/brain/tools.py`: "The closest of the listed concerns to what the caller says
   they want help with." The parameter no longer tells the model to do the one thing the ledger
   will silently null.

7. **[major] The offer instruction was unconditional.**
   `runtime/spatalk/brain/prompt.py`: "mention the clinic's new-client offers listed in the facts
   once, warmly, as options, but only if the facts list any, and never invent one". A tenant whose
   knowledge file lists no offer is no longer told to name one. The wording itself still lives in
   the knowledge file, not in code (CLAUDE.md 3).

8. **[major] A legal tenant config could break every item write, and could smuggle in medicine.**
   `runtime/spatalk/tenants/schema.py`: `TeamMember.name` is `Field(max_length=80)` and each
   entry of `concerns` is `Annotated[str, Field(max_length=40)]`, matching `items.practitioner`
   varchar(80) and `items.concern` varchar(40), so a config that could not be written to an item
   is refused at import rather than at 2 a.m. A new `TenantConfig` model validator rejects a
   concern whose text, or any single word of it, is a clinical or health-context lexicon term;
   `spatalk.brain.rules` is imported inside the validator because it imports this module.
   New tests: `test_a_name_or_a_concern_wider_than_its_column_is_refused_at_import`,
   `test_a_medical_word_cannot_be_configured_as_a_cosmetic_concern` and
   `test_the_preferred_window_date_is_a_closed_value_and_never_a_sentence` in
   `runtime/tests/test_lead_context.py`.

## Deviations

- **Three existing tests pinned behaviour the fixes deliberately change, and were updated.**
  - `tests/test_lead_context.py::test_preferred_text_reads_like_a_person_wrote_it_and_never_says_any_any`
    and `::test_a_returning_caller_who_asked_for_someone_says_so`, and
    `tests/test_lead_context_verification.py::test_preferred_text_over_the_whole_grid_of_windows`,
    asserted the old date rendering (`"Thursday"`, `"Thursday afternoon"`). They now assert the new
    one and additionally cover a weekday-name window, which the validator in finding 2 made
    reachable. Each says in its own docstring or comment why the expectation moved.
  - `tests/test_sms_staff_delivery.py::test_the_message_drops_the_health_line_then_the_who_line_but_never_the_link`
    named the old drop order. Renamed to
    `test_the_message_drops_the_summary_then_the_health_line_then_the_who_line`, with a docstring
    giving the reason for the order. No assertion was weakened; the two cases it exercises pass
    unchanged under the new order.
  - Nothing was skipped, deleted or loosened. The one subset assertion in
    `test_the_only_unenumerated_strings_on_a_tool_are_contact_details` kept its `<=` shape, but its
    comment no longer calls the window date a gap: an ISO date cannot be a JSON-schema enum, so
    the string stays open at the tool edge and `PreferredWindow` closes it before the ledger.
- **Reference docs updated with the behaviour changes**, since `docs/reference/` wins over a plan:
  `data-model.md` (the `preferred_window` shape), `api-surface.md` (`preferred_text`'s table and the
  `summary` example), `tenant-config.md` (the `team[].name` and `concerns` bounds, the medical-concern
  refusal, and the conditional offer clause). `docs/contracts/runtime-internal.openapi.json` is
  unchanged and still equals the live `ItemOut`, verified by
  `test_the_contract_matches_the_running_models`: the three derived fields are computed on read, so
  changing their wording changes no type.
- **The two minor findings in V1 were left alone, deliberately**, as the task directed:
  `http/internal.py:781` (acknowledge and resolve now need a tenant config row, a new coupling worth
  knowing about but not a defect) and `ledger/summary.py` `type_label`'s fallback to the raw type
  (every constructible type is labelled, and `test_every_item_type_the_runtime_can_create_has_a_label`
  locks that door).
- **`portal/` was not touched and not built.** No portal source changed; the founder's `wasp start`
  was left running, as the hard rules require.
- Ran on a scratch database `spatalk_test_fix`, dropped at the end. The runtime on port 8000,
  `runtime/.env` and the dev database `spatalk` were never touched. `ruff check spatalk tests
  scenarios` -> "All checks passed!".

## Notes for neighbours

- `preferred_text` output changed shape for a dated window. Anything that string-matches it —
  a portal snapshot, a digest fixture, an eval assertion — should expect
  `"Thursday 24 September, afternoons"`, not `"Thursday afternoon"`. Nothing in the repository did.
- `PreferredWindow.date` is now normalising, not validating: a caller's phrase silently becomes
  `"any"`. That is deliberate (a rejected value must not cost the request), so a future test that
  wants to detect a mangled date must look at the model's raw tool arguments, not at the item.
- `TenantConfig` now rejects a config at import for a medical concern. A tenant-settings screen in
  the portal must surface that `ValidationError` rather than swallowing it, or an owner will not
  know why their edit did not take.
