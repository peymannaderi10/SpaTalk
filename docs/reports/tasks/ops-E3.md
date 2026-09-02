# operations plan Task E3: Retention with receipts

Status: done with deviations
Commit: <pending>
Tests: `TEST_DATABASE_URL=…/spatalk_test_e3 uv run pytest -q tests/test_ops_retention.py` -> 11/11;
full suite `TEST_DATABASE_URL=…/spatalk_test_e3 uv run pytest -q` -> **646 passed, 1 skipped**
in 175 s (647/647; the skip is `test_driver.py::test_gemini_client_calls_a_tool`, `skipif` on
`GOOGLE_API_KEY`). `uv run ruff check spatalk tests scenarios` -> All checks passed.
Interfaces produced: `spatalk.ops.retention.run_retention(ctx, now=None) -> RetentionSummary`,
`spatalk.ops.retention.RetentionSummary(per_tenant: dict[str, dict[str, int]], audit_log: int)`
with `.total()` and `.as_json()`, `spatalk.ops.retention.RUN_KIND = "ops.retention"`,
`spatalk.ops.retention.STUB_DAYS = 400`, `spatalk.ops.retention.AUDIT_LOG_DAYS = 730`,
`spatalk.models.DeletionReceipt` (table `runtime.deletion_receipts`),
`spatalk.models.OpsRun` (table `runtime.ops_runs`), `spatalk.models.Conversation.stage_ms`,
`spatalk.ledger.scheduler.ensure_nightly_retention_scheduled(ctx) -> bool`,
`spatalk.ledger.scheduler.NIGHTLY_RETENTION_UTC_HOUR = 3`,
`alembic/versions/0006_ops_retention.py`

## What is in place

- `run_retention(ctx, now)` sweeps every tenant in the `tenants` table in one pass and
  returns the counts it deleted. Per tenant, in one transaction: transcripts of finished
  conversations past that tenant's own `retention_days`; the surviving conversation rows
  reduced to stubs (`caller`, `latency_ms`, `stage_ms` nulled, channel, band and timestamps
  kept); `items` and `usage_events` past 400 days; then the 400-day-old conversation rows
  themselves, with anything still pointing at them. `audit_log` is swept once per run at two
  years, outside `per_tenant`, because the table carries no tenant column.
- Every non-zero (tenant, kind) count writes one `deletion_receipts` row carrying the cutoff
  it used and the run's clock. A zero writes nothing: a receipt for nothing would dilute the
  ones that mean something.
- Every run — successful or not — writes one `ops_runs` row (`kind='ops.retention'`,
  `started_at`, `finished_at`, `ok`, `summary` jsonb), in its own transaction so a failed
  sweep still leaves the record. That is the operations plan's global constraint, and it is
  what makes "the nightly job stopped running" distinguishable from "the nightly job found
  nothing to do".
- Idempotent by construction, not by a flag: a second run the same night finds nothing past
  a cutoff, so it deletes nothing and writes no receipts. Proven by
  `test_a_second_run_the_same_night_deletes_nothing_and_writes_no_receipts`, which asserts
  the receipt table is byte-for-byte what it was.
- The scheduler queues `ops.retention` at most once per UTC day from 03:00 UTC
  (`ensure_nightly_retention_scheduled`), and `spatalk.ops.retention` registers the handler
  for that job kind, so the work runs on the job worker like every other scheduled job.
  Retention at 03:00 and E2's base backup at 03:30 are deliberately an hour apart, per E2's
  note: the nightly backup is taken after the deletes.

## Deviations

1. **`conversations.stage_ms` and its migration landed here, not in E5.** E3's behaviour
   says the expired conversations' `latency_ms`/`stage_ms` are nulled, and
   `docs/reference/data-model.md` documents `stage_ms` on `conversations`, but the plan's
   File Structure assigns that column to Task E5. An `UPDATE … SET stage_ms = NULL` against
   a column that does not exist is a `ProgrammingError`, so the column is added here, in its
   own delimited block at the end of the `Conversation` class, with a comment naming E5 as
   its filler. **E5 must not add it again**; it only needs to write to it in `_finalize`.
   Evidence: `alembic check` against a database at head -> `No new upgrade operations detected.`
2. **The migration is `0006_ops_retention.py`, not `0004_ops.py`.** E1 already took `0005`
   for `alert_log` and said so; `0004` is the social migration. Evidence:
   `grep -n "revision" alembic/versions/*.py` -> `0004` social, `0005` ops alert log.
   E4 (`audit_reports`) and E9 (`provider_invoices`) should chain after `0006`.
3. **Transcript expiry falls back past `ended_at`.** The reference measures transcript
   retention "30 days after `ended_at`". A text conversation the customer simply abandoned
   never gets an `ended_at`: `spatalk/text/service.py:277-279` sets `closed_at`/`ended_at`
   only when the assistant ends the turn, and find-or-create just starts a new conversation
   after 24 hours (`text/service.py:121-131`). Under a literal reading those transcripts —
   the ones most likely to hold a volunteered health statement — would be kept for 400 days,
   which is the opposite of what §10 weakness 5 asks this task to close. The rule
   implemented is `coalesce(ended_at, closed_at, last_message_at, started_at) < cutoff`, so
   every conversation that *has* an `ended_at` is treated exactly as the reference says and
   the ones that never got one are no longer immortal. Pinned by
   `test_a_transcript_of_a_conversation_that_never_ended_still_expires`.
4. **`audit_log`'s two-year purge has no receipt and sits outside `per_tenant`.** The plan
   lists "audit_log kept 2 years" in E3's behaviour, but `audit_log` has no `tenant_id` and
   `deletion_receipts.kind` is documented as exactly the four tenant-scoped kinds. The count
   is returned as `RetentionSummary.audit_log` and recorded in the `ops_runs` summary
   instead. Adding a fifth receipt kind would have contradicted `data-model.md`, which wins.
5. **`docs/reference/data-model.md` gained `### ops_runs` and `### deletion_receipts`
   headings.** The five operations tables shared one combined `###` heading that
   `tests/test_qa_gate_a.py::_documented_tables` cannot parse (its regex is
   `^### (\w+) \[…\]`), so a schema containing either table failed the gate's "no table the
   reference does not name" assertion — the same presentational fix E1 made for `alert_log`,
   and its report told E3, E7 and E9 to expect it. Column lists are unchanged; `audit_reports`
   and `provider_invoices` are left in the combined row for E4 and E9 to split out.
   Evidence: `uv run pytest -q tests/test_qa_gate_a.py -k alembic` -> passed (a real
   `alembic upgrade head` on a throwaway database).
6. **`ensure_nightly_retention_scheduled` keys on the queued job's `run_at`, not its
   `created_at`.** `Job.created_at` is a `server_default=now()`, i.e. the database's wall
   clock, while the scheduler decides on `ctx.clock`; the existing
   `ensure_daily_refresh_scheduled` mixes the two and only works because the drift is under
   a day. Enqueuing with an explicit `run_at` from the application clock makes the
   "already done today" test exact and testable with `FixedClock`. No existing code changed.

## Notes for neighbours

- **E4 (nightly audit)**: `OpsRun` already exists and is the shape your 04:00 job should
  write too — copy `_start_run`/`_finish_run` from `ops/retention.py` rather than inventing
  a second convention, and use `kind="ops.nightly_audit"`. Schedule the same way
  (`ensure_nightly_retention_scheduled` is four lines you can mirror with hour 4).
  Note the ordering: retention at 03:00 deletes transcripts before the 04:00 audit reads
  them, so the audit's `day` will always be inside every tenant's `retention_days` window —
  fine at 30 days, but a tenant on `retention_days=1` would have its previous day audited
  after the transcripts were removed. Worth a line in your report if you keep 04:00.
- **E5 (latency)**: `conversations.stage_ms` exists (jsonb, nullable) with migration `0006`.
  Do not add the column or a second migration for it. Retention nulls it with `latency_ms`,
  so a stage_ms-based report must not read conversations older than `retention_days`.
- **E7 (alerts)**: `run_retention` raises on failure after writing `ok=false`; when
  `alerts.notify` exists, the job handler `_retention_job` is the place to call it, and the
  natural dedup key is `retention:failed`. Also consider alerting on "no `ops_runs` row with
  `kind='ops.retention'` in the last 26 hours", which is the only way a silently dead
  scheduler becomes visible.
- **E9 (cost report)**: usage events are hard-deleted at 400 days, so a monthly report can
  never be recomputed for a month more than 13 months old. If that matters, the monthly
  totals need to be persisted when they are first computed.
- **Portal**: nothing in `/internal/*` exposes receipts yet. If the founder wants "prove the
  transcript is gone" in the portal, `deletion_receipts` is the table to read.
- **Known residue, deliberately not touched**: the stub keeps `external_ref`, which for SMS,
  Instagram and Messenger is the sender's identifier. `data-model.md` defines the stub as
  "no caller, no latency" and the reference wins over my judgement, so `external_ref`
  survives the transcript purge and goes only with the 400-day delete. If the founder wants
  it gone at `retention_days`, it is one more column in the `values(...)` call in
  `_sweep_tenant` and one line in the reference.
- **Test database**: this task ran against a private `spatalk_test_e3` for the reason E1's
  report gives — `tests/conftest.py` drops and recreates the schema for every test, so two
  agents sharing `spatalk_test` corrupt each other's runs. `docker compose exec -T db psql
  -U spatalk -c "CREATE DATABASE spatalk_test_e3 OWNER spatalk"`, then
  `TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_e3`.

## Verification run

| Check | Result |
|---|---|
| `uv run pytest -q tests/test_ops_retention.py` (before any product code existed) | **11 failed** — `ModuleNotFoundError: spatalk.ops.retention` / `ImportError: cannot import name 'ensure_nightly_retention_scheduled'` |
| `uv run pytest -q tests/test_ops_retention.py` (after) | **11 passed** in 5.7 s |
| `uv run pytest -q tests/test_qa_gate_a.py -k alembic` | 1 passed (real `alembic upgrade head` on a throwaway database) |
| `alembic upgrade head` + `alembic check` on a throwaway `spatalk_e3_mig` | `Running upgrade 0005 -> 0006`; `No new upgrade operations detected.` |
| `uv run ruff check spatalk tests scenarios` | All checks passed |
| full suite | **646 passed, 1 skipped** in 175 s |
