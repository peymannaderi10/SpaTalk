# operations plan Task E4: Nightly audit — lexicon scan, band audit with a judge model, health-context stats

Status: done with deviations
Commit: 1db8abf
Tests: `TEST_DATABASE_URL=…/spatalk_test_e4 uv run pytest -q tests/test_ops_nightly_audit.py` -> 27/27;
full suite `TEST_DATABASE_URL=…/spatalk_test_e4 uv run pytest -q` -> **672 passed, 1 failed, 1 skipped**
(674 total). The one failure is `tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table`,
which is **not this task's** and was red before this task wrote a line — see "Pre-existing
failure" below for the proof. The skip is `test_driver.py::test_gemini_client_calls_a_tool`,
`skipif` on `GOOGLE_API_KEY`. `uv run ruff check spatalk tests scenarios` -> All checks passed.

Interfaces produced: `spatalk.ops.nightly_audit.lexicon_scan(ctx, day, tenant_id=None) -> dict`,
`spatalk.ops.nightly_audit.band_audit(ctx, day, judge, tenant_id=None) -> dict`,
`spatalk.ops.nightly_audit.health_context_stats(ctx, day, tenant_id=None) -> dict`,
`spatalk.ops.nightly_audit.run_nightly_audit(ctx, day=None, judge=None) -> AuditReport`,
`spatalk.ops.nightly_audit.AuditReport`, `…TenantAudit`, `…blocking_findings(bands)`,
`…make_judge(settings)`, `…report_email(report)`, `…render_transcript`, `…parse_verdict`,
`…day_window(timezone_name, day)`, `…BAND_DEFINITIONS`, `…JUDGE_SYSTEM`,
`…JUDGE_THINKING_BUDGET = -1`, `…RUN_KIND = "ops.nightly_audit"`,
`spatalk.ops.alerts.notify(ctx, key, subject, body) -> bool`, `spatalk.ops.alerts.already_alerted(ctx, key)`,
`spatalk.ops.alerts.DEDUP_HOURS = 6`, `spatalk.models.AuditReport` (table `runtime.audit_reports`),
`spatalk.settings.Settings.judge_model`, `spatalk.settings.Settings.ops_email`,
`spatalk.ledger.scheduler.ensure_nightly_audit_scheduled(ctx) -> bool`,
`spatalk.ledger.scheduler.NIGHTLY_AUDIT_UTC_HOUR = 4`,
`GET /internal/tenants/{tenant_id}/audit/latest` (`AuditLatest`),
`alembic/versions/0007_ops_nightly_audit_audit_reports.py`

## What is in place

- **The lexicon scan is the gate auditing itself.** `lexicon_scan` re-runs the tenant's own
  clinical lexicon — built-ins plus the tenant's `guard.yaml` additions — over every
  customer turn of the day and returns the conversations that hold a clinical term but were
  not band 3. It reuses `spatalk.brain.rules._pattern`, so the audit and the gate cannot
  drift apart: a term added to the lexicon after the fact, a conversation a person took over
  before the gate saw the message, and a plain gate miss all surface here, and nowhere else.
- **The band audit is a second opinion, not a second gate.** Every transcript of the day is
  re-judged by an `LLMClient` against the three band definitions worded exactly as
  `docs/reference/data-model.md` defines `conversations.band` ("handled end to end",
  "captured for a human", "straight to a human"), plus the §7.1 list of what sends a
  conversation to band 3. The judge answers JSON `{band, reason}`; disagreements are
  recorded with both bands and the judge's sentence. Conversations with `controller ==
  'human'` are excluded, as are ones with no transcript and ones with no recorded band —
  there is nothing to judge in the first and nothing to disagree with in the last.
- **A judged band 3 handled as band 1 or 2 is blocking**, and blocking means an alert, not a
  line in a report: `blocking_findings` filters exactly that case and `alerts.notify` raises
  it under `audit_blocking:<tenant>:<day>`. A disagreement in the other direction (the
  assistant escalated something the judge would have handled) is recorded and does not page
  anybody: over-escalation costs one human callback, under-escalation is the S5 failure.
- **The report is a row before it is an email.** One `audit_reports` row per (day, tenant),
  written before the email is composed, so a mail failure cannot lose a finding; a re-run of
  the same night replaces its verdict through an `ON CONFLICT (day, tenant_id) DO UPDATE`
  rather than accumulating a second opinion. The email to `OPS_EMAIL` carries every tenant's
  counts and every blocking finding in plain text.
- **A quiet night still reports and still records.** Zero conversations produce a zero
  report, a stored row, an email and an `ops_runs` row with `ok=true`. That is the whole
  point of the operations plan's global constraint: a nightly job that silently stopped
  running must not look like one that found nothing to do.
- **The judge is `gemini-2.5-flash` with thinking on** (`thinking_budget=-1`), configured by
  `JUDGE_MODEL`. gemini-2.5-pro is not available on the founder's Google AI Studio key (404
  "no longer available to new users", promptfoo run A, 2026-09-02), and a band judgement is
  an offline call where reasoning time is free but a per-token price is not. `make_judge`
  returns `None` when no `GOOGLE_API_KEY` exists, and the run then does the lexicon scan and
  the counts anyway and says `bands.skipped` in the report — no test in this repository
  reaches a model, and every one drives the judge with `FakeLLM`.
- **Scheduled at 04:00 UTC, once per UTC day**, the same way and for the same reason as E3's
  retention at 03:00: one sweep over every tenant, keyed on the queued job's own `run_at`
  from the application clock.
- **The portal can read it**: `GET /internal/tenants/{id}/audit/latest` returns the newest
  report for a tenant, or `{day: null, created_at: null, report: null}` before the first
  night has run, so the admin health page (portal plan C5) renders "no audit yet" rather
  than an error.

## Deviations

1. **`spatalk/ops/alerts.py` landed here, not in E7.** E4's interface says a blocking
   finding "also raises an alert through `alerts.notify`", and the plan's File Structure
   gives that module to E7, which has not run. Following E1's precedent (it created
   `alert_log` for the same reason), this task adds the subset E4 uses and nothing more: the
   six-hour dedup on `alert_log.key`, the row, and the email to `ops_email`. **E7 must
   extend this file, not recreate it** — the SMS leg (`ops_sms_number`), the scheduler's
   conditions (dead jobs, stale queue, stale tick), the Sentry wiring and the PII scrubber
   are still E7's, and `notify`'s signature is exactly what the plan specifies for it. The
   `alert_log` row is written even when the email fails, and the email failure is logged
   rather than raised, so an alert cannot become the failure that stops the job that raised
   it. Evidence: `grep -n "alerts" docs/superpowers/plans/2026-09-01-operations-plan.md` ->
   E4's Interfaces name `alerts.notify`; E7's Files name `spatalk/ops/alerts.py`.
2. **`ops_sms_number` was deliberately *not* added to settings.** It is in E7's file list and
   nothing in E4 needs it; adding it would have meant guessing which number an ops SMS is
   sent *from*, which `docs/reference/api-surface.md` does not define. E4 adds only
   `judge_model` and `ops_email`, which the plan assigns to it.
3. **The three interface functions take an extra optional `tenant_id`.** The plan writes
   `lexicon_scan(ctx, day)`, `band_audit(ctx, day, judge)` and `health_context_stats(ctx,
   day)` but also says "the report is per tenant". The positional signatures are unchanged
   and calling them as the plan writes them scans every tenant; passing a tenant id scopes
   one, which is what `run_nightly_audit` does to build a per-tenant row. Pinned by
   `test_the_scan_is_scoped_to_one_tenant_when_asked`.
4. **`run_nightly_audit` takes `judge=None` and `day=None`.** The plan writes
   `run_nightly_audit(ctx, day) -> AuditReport`; the function needs a judge, and a test must
   be able to inject `FakeLLM`. Omitted, the judge comes from `make_judge(ctx.settings)` and
   the day defaults to yesterday, which is what the 04:00 job wants.
5. **`AuditReport` is the run; `TenantAudit` is the tenant.** The plan's return type is one
   `AuditReport` while the storage is one row per tenant, so `AuditReport` carries the day
   and a `TenantAudit` per tenant, and each of those is what lands in `audit_reports.report`.
   The ORM model is also called `AuditReport` (`spatalk.models.AuditReport`, table
   `runtime.audit_reports`, as `data-model.md` names it); `nightly_audit.py` imports it as
   `AuditReportRow` to keep both public names the ones the plan and the reference use.
6. **`spatalk/brain/driver.py` gained a `thinking_budget` argument on `GeminiClient`.**
   driver.py is E6's file. The plan requires the judge to run with
   `ThinkingConfig(thinking_budget=-1)` "unlike the conversational client which sets 0", and
   the client hard-coded 0. The change is additive and defaults to the old value, so no
   existing caller changes behaviour; the same edit also passes `tools=None` instead of an
   empty `types.Tool(function_declarations=[])` when a caller supplies no tools, which is
   the judge's case (it must classify, not act). Evidence: `uv run pytest -q
   tests/test_driver.py` -> 7 passed, 1 skipped (unchanged).
7. **`spatalk/http/internal.py`, the OpenAPI contract and the portal's generated client were
   regenerated.** E4's behaviour requires `GET /internal/tenants/{id}/audit/latest`, but the
   task's Files list does not mention the router. Adding the route changes
   `docs/contracts/runtime-internal.openapi.json` (checked by
   `tests/test_contract_snapshot.py`) and therefore `portal/src/runtime/client.ts` (checked
   by `tests/test_qa_gate_b.py::test_the_committed_contract_and_the_portal_client_declare_the_same_paths`
   and by the portal's own `npm run check:client`). Both were regenerated with the committed
   tooling — `spatalk openapi --internal` and `npm run gen:client` — and both diffs are
   purely additive (96 and 68 inserted lines, nothing removed). No portal page was changed:
   wiring the endpoint into the admin health page is portal work.
8. **`docs/reference/data-model.md` gained a `### audit_reports [operations plan, Task E4]`
   heading**, split out of the combined `audit_reports, provider_invoices` row exactly as E1
   did for `alert_log` and E3 for `ops_runs`/`deletion_receipts`, because
   `tests/test_qa_gate_a.py::_documented_tables` parses `^### (\w+) \[…\]` and would
   otherwise fail the gate's "no table the reference does not name" assertion. The columns
   are the ones the combined row already gave it; `provider_invoices` now has its own
   heading too, tagged Task E9, with its columns unchanged. Evidence: the full run includes
   `test_alembic_head_creates_every_documented_table_and_index` passing against a real
   `alembic upgrade head`.
9. **`runtime/.env.example` gained `OPS_EMAIL` and `JUDGE_MODEL`.** Not in the Files list,
   but `docs/reference/api-surface.md` lists both as runtime environment variables and the
   example file is where a founder discovers them.
10. **The migration is `0007_ops_nightly_audit_audit_reports.py`.** E3 took `0006` and said
    E4 should chain after it. Evidence: `alembic upgrade head` then `alembic check` on a
    throwaway `spatalk_e4_mig` -> `Running upgrade 0006 -> 0007`; `No new upgrade operations
    detected.`

## Pre-existing failure this task did not cause and did not touch

`tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table` fails at
HEAD. It compares two committed data files, `runtime/spatalk/rates.json` and
`docs/research/rates.json`, neither of which this task modified (nor does any code here read
rates). The difference was introduced by commit `12fc7b8` *"docs(research): add Soniox TTS
rate and a single-vendor Soniox stack to the cost model"*, which landed from a concurrent
agent at 17:46 today, after this task started, and added `tts.soniox_tts` and a `B4 Soniox
only` voice stack to the researched table without syncing the copy the runtime packages.

Proof, run at HEAD:

```
b339344 packaged == researched: True      # the commit this task branched from
HEAD    packaged == researched: False     # after 12fc7b8 and b5e7d8b
```

The fix is a one-file sync of `runtime/spatalk/rates.json`, but that file belongs to the
rates work that is still in flight (`b5e7d8b` changes the recommended stack again), so
syncing it here would only race that agent. **Orchestrator: route it to whoever owns the
rates change.** Arithmetic check that nothing else regressed: E3's report ended at 646
passed + 1 skipped = 647; this run is 672 passed + 1 failed + 1 skipped = 674, and
674 − 647 = 27, exactly the tests this task added.

## Notes for neighbours

- **E7 (`ops/alerts.py`, monitoring)**: the module exists with `notify(ctx, key, subject,
  body) -> bool` and a six-hour dedup on `alert_log.key`; extend it rather than replacing it,
  and the two things it deliberately does not do yet are the SMS leg and Sentry. Existing
  keys: `loop_guard:<tenant>:<E.164>` (E1) and `audit_blocking:<tenant>:<YYYY-MM-DD>` (here).
  For the "a nightly job stopped running" condition, `ops_runs` now carries both
  `ops.retention` and `ops.nightly_audit` rows, so "no row with this kind in the last 26
  hours" covers both.
- **E5 (latency)**: `alerts.notify` is ready for the SLO breach alert; use a key that names
  the stage (`slo:<tenant>:<stage>:<day>`) so a bad day dedups to one alert per stage.
- **E9 (cost report)**: `provider_invoices` now has its own `###` heading in
  `data-model.md` tagged Task E9; its column list is unchanged, so nothing to re-document —
  just create the table and chain your migration after `0007`.
- **Portal (C5 admin health page)**: `GET /internal/tenants/{id}/audit/latest` is in the
  contract and in `portal/src/runtime/client.ts` as
  `tenant_latest_audit_internal_tenants__tenant_id__audit_latest_get`. It returns
  `{day, created_at, report}` with all three null before the first night. The report shape is
  `{tenant_id, lexicon: {conversations_with_clinical_terms_not_band3, count}, bands:
  {reviewed, disagreements, errors, skipped?}, health_context: {conversations, flagged,
  items_flagged}, blocking: [{conversation_id, actual_band, judged_band, reason}]}`.
- **Retention ordering, as E3 flagged**: retention runs at 03:00 UTC and this runs at 04:00,
  so the audit reads a day whose transcripts have already been swept. At the default
  `retention_days` of 30 that is irrelevant; a tenant configured with `retention_days=1`
  would have yesterday's transcripts deleted an hour before they were audited, and the audit
  would honestly report a day with nothing in it. Moving the audit before retention would
  invert the problem (the deletes would wait on a model call), so the ordering is left as the
  plan specifies and recorded here instead.
- **The judge costs money in production.** One call per conversation per night with thinking
  unbounded. At Skincentrix's volume that is cents; if a tenant's volume grows, the first
  lever is to judge only conversations the lexicon scan or the band distribution makes
  interesting, not to turn thinking off.
- **Test database**: this task ran against a private `spatalk_test_e4` for the reason E1 and
  E3 give — `tests/conftest.py` drops and recreates the schema for every test, so two agents
  sharing `spatalk_test` corrupt each other's runs.
  `docker compose exec -T db psql -U spatalk -c "CREATE DATABASE spatalk_test_e4 OWNER spatalk"`,
  then `TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_e4`.

## Verification run

| Check | Result |
|---|---|
| `uv run pytest -q tests/test_ops_nightly_audit.py` (before any product code existed) | **27 failed** — `ModuleNotFoundError: No module named 'spatalk.ops.nightly_audit'`, `ImportError: cannot import name 'AuditReport' from 'spatalk.models'`, `ImportError: cannot import name 'ensure_nightly_audit_scheduled'`, and 404 on the unrouted `/internal/…/audit/latest` |
| `uv run pytest -q tests/test_ops_nightly_audit.py` (after) | **27 passed** in 12.6 s |
| `alembic upgrade head` + `alembic check` on a throwaway `spatalk_e4_mig` | `Running upgrade 0006 -> 0007`; `No new upgrade operations detected.` |
| `psql -c "\d runtime.audit_reports"` | bigserial id, date day, tenant_id, jsonb report, created_at; `UNIQUE (day, tenant_id)` |
| `spatalk openapi --internal` + `npm run gen:client` | contract +96 lines, client +68 lines, both additive, both LF |
| `uv run pytest -q tests/test_contract_snapshot.py tests/test_qa_gate_b.py tests/test_deploy_assets.py tests/test_driver.py tests/test_smoke_imports.py tests/test_scheduler.py` | 97 passed, 1 skipped |
| `uv run ruff check spatalk tests scenarios` | All checks passed |
| full suite | **672 passed, 1 failed, 1 skipped** — the failure is the pre-existing rates drift above |
