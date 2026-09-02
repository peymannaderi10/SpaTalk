# Operations and Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Contract level: files, exact interfaces, behaviours, tests. Tests first. Nothing in this plan deploys, buys, or calls a paid API; steps that need the live platform are written as runbook checklists for the founder.

**Goal:** Turn the ten weaknesses in spec §10 into running checks: carrier-side failover and a loop guard, tested backups with a restore drill, retention with receipts, a nightly honesty and escalation audit, latency budgets per stage, a model-swap drill with a second vendor, monitoring and alerting, rate limits and secret scanning, monthly cost reconciliation, and a live-transfer spike.

**Architecture:** Small, separately testable modules under `runtime/spatalk/ops/` plus scripts and CI jobs. Scheduled work runs through the existing scheduler and jobs table. Anything that must run outside the platform (carrier failover, uptime monitor) is configuration recorded in runbooks with a verification step.

**Tech Stack:** as the runtime plan, plus WAL-G in a custom Postgres image, MinIO in CI for backup tests, `sentry-sdk` (optional), `gitleaks` and `pip-audit` in CI, `openai` extra for Pipecat and the `openai` SDK for the text driver's second vendor.

**Spec:** `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md` §4 decision 12.7, §6 (cost model), §7 (retention, audit), §10 (weaknesses). Depends on the runtime plan and text-channels B2 and B3.

## Global Constraints

- Everything in the runtime plan's Global Constraints.
- No new always-on service beyond the WAL-G sidecar in the Postgres container. No Redis, no Langfuse.
- Every scheduled job is idempotent and records a row when it runs (`ops_runs(kind, started_at, finished_at, ok, summary jsonb)`).
- Alerts go to `OPS_EMAIL` and, when `OPS_SMS_NUMBER` is set, one SMS per incident per 6 hours, never more.
- Retention deletes are hard deletes with a receipt row; nothing is "soft-deleted".

## File Structure

```
runtime/spatalk/ops/
  __init__.py
  loop_guard.py            is_own_number(cfg, registry, number) -> bool ; used by voice/texml.py
  retention.py             run_retention(ctx) -> RetentionSummary ; receipts
  nightly_audit.py         lexicon_scan(day), band_audit(day, judge: LLMClient), health_context_stats(day) -> AuditReport ; email
  latency.py               stage budgets, daily report, SLO check
  alerts.py                notify(ctx, key, subject, body) with 6-hour dedup
  cost_report.py           monthly usage x rates vs provider invoices
  model_check.py           configured model exists at the provider
runtime/spatalk/models.py  + ops_runs, deletion_receipts, provider_invoices, audit_reports, alert_log; conversations.stage_ms
runtime/spatalk/voice/observers.py   UsageObserver captures TTFB per stage
runtime/spatalk/voice/pipeline.py    make_llm supports "openai:<model>"; transfer capability wiring (E10)
runtime/spatalk/brain/driver.py      OpenAIClient
runtime/spatalk/ledger/scheduler.py  nightly and monthly hooks
runtime/scripts/db/{Dockerfile, postgresql.conf, walg.env.example, backup-cron}
runtime/scripts/restore-drill.sh
runtime/docker-compose.yml           db built from scripts/db; healthz commit
docs/runbooks/{failover.md, backups.md, model-swap.md, monitoring.md, transfer.md}
.github/workflows/{ci.yml (+gitleaks, pip-audit, npm audit), backup-drill.yml, model-check.yml, nightly-voice-evals.yml}
runtime/tests/test_ops_*.py
```

---

### Task E1: Carrier failover bin and the loop guard

**Files:** `spatalk/ops/loop_guard.py`, `spatalk/voice/texml.py`, `runtime/tenants/skincentrix/scripts.yaml` (`loop_guard`, `failover`), `docs/runbooks/failover.md`, `tests/test_ops_loop_guard.py`

**Behaviour:**
1. `is_own_number(cfg, registry, number)` is true when `number` equals any number the registry maps to this tenant, or the tenant's `public_phone` normalised to E.164.
2. `POST /telnyx/texml` calls it on `From`. When true: respond with TeXML `<Say>` of `scripts.loop_guard` ("This line is answered by the clinic's assistant and cannot transfer to itself. Please call back from another number.") then `<Hangup/>`, write an `alert_log` row, and start no conversation.
3. `docs/runbooks/failover.md`: create a Telnyx TeXML Bin whose body is `<Response><Say voice="female" language="en-CA">{scripts.failover}</Say><Hangup/></Response>` with the tenant's failover wording ("We can't take your call right now. Please text us at {sms number} or book online at {booking url}."); set it as the TeXML application's Failover URL; test by stopping the app container and calling; expected behaviour recorded. Note that a voicemail variant (`<Record>`) creates a carrier-side recording and is opt-in per tenant.
4. `spatalk texml failover-bin skincentrix` prints the TeXML body for the founder to paste.

**Tests:** own local number → hangup TeXML and alert row, no conversation; public phone in local format `905-703-7546` → same; ordinary caller → stream as before; CLI prints the bin with the tenant's SMS number and booking URL.

**Done when:** tests pass; runbook written. Commit `feat(ops): loop guard on inbound calls and carrier failover bin runbook`.

---

### Task E2: WAL-G backups to R2 and the restore drill

**Files:** `runtime/scripts/db/{Dockerfile, postgresql.conf, walg.env.example, backup-cron}`, `runtime/docker-compose.yml`, `runtime/scripts/restore-drill.sh`, `.github/workflows/backup-drill.yml`, `docs/runbooks/backups.md`

**Behaviour:**
1. `scripts/db/Dockerfile`: `FROM postgres:16-alpine` plus the WAL-G binary; `postgresql.conf` sets `archive_mode=on`, `archive_command='wal-g wal-push %p'`, `archive_timeout=60`; a cron entry runs `wal-g backup-push /var/lib/postgresql/data` daily at 03:30 and `wal-g delete retain FULL 7 --confirm` weekly. WAL-G env from `walg.env` (R2 S3-compatible: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT`, `WALG_S3_PREFIX=s3://spatalk-backups/pg`, `AWS_S3_FORCE_PATH_STYLE=true`).
2. Compose `db` builds from that Dockerfile and mounts `walg.env`.
3. `restore-drill.sh`: starts a throwaway container from the same image with a fresh volume, runs `wal-g backup-fetch /var/lib/postgresql/data LATEST`, writes `recovery.signal` with `restore_command='wal-g wal-fetch %f %p'` and an optional `recovery_target_time`, starts Postgres, waits for readiness, runs `SELECT count(*) FROM runtime.items` and `SELECT max(created_at) FROM runtime.messages`, prints elapsed time and the recovery point, and removes the container. Exit non-zero if restore takes over 15 minutes or the latest recovered message is older than 10 minutes relative to the source at drill start (RPO check is skipped with a warning when run against a source that is idle).
4. `backup-drill.yml` (weekly and on demand): Postgres from `scripts/db` plus a MinIO service standing in for R2; seed a few rows; run `wal-g backup-push`; insert more rows; run the restore drill against MinIO; assert the counts. This proves the tooling, not the R2 credentials; the runbook has the monthly manual drill against R2.
5. `docs/runbooks/backups.md`: what is backed up, where, how to run the drill, how to restore for real, and the monthly calendar entry.

**Tests:** the CI workflow is the test; locally `bash scripts/restore-drill.sh --source-url ... --walg-env walg.env` completes against MinIO in Compose (`docker compose --profile drill up`).

**Done when:** `backup-drill.yml` passes. Commit `feat(ops): wal-g archiving to r2 with a tested restore drill`.

---

### Task E3: Retention with receipts

**Files:** `spatalk/ops/retention.py`, `spatalk/models.py` (`deletion_receipts`, `ops_runs`), `spatalk/ledger/scheduler.py` (nightly at 03:00 tenant-independent UTC), `alembic/versions/0004_ops.py`, `tests/test_ops_retention.py`

**Interfaces:** `run_retention(ctx, now) -> RetentionSummary(per_tenant: dict[str, {messages, conversations, items, usage_events}])`; `DeletionReceipt(tenant_id, kind, count, cutoff, run_at)`.

**Behaviour:** per tenant, using `retention_days` for transcripts: delete `messages` of conversations that ended before `now - retention_days`, then those conversations' `latency_ms`/`stage_ms` are nulled and the conversation row kept for 400 days as a stub (channel, band, timestamps, no caller) for analytics, then deleted after 400 days; `items` older than 400 days deleted; `usage_events` older than 400 days deleted; `audit_log` kept 2 years. One receipt row per (tenant, kind) with a non-zero count. Idempotent: a second run the same night deletes nothing and writes no receipts.

**Tests:** backdated fixtures across the thresholds; counts match; receipts written; second run is a no-op; a tenant with `retention_days=7` is honoured independently.

**Done when:** tests pass. Commit `feat(ops): retention job with deletion receipts`.

---

### Task E4: Nightly audit: lexicon scan, band audit with a judge model, health-context stats

**Files:** `spatalk/ops/nightly_audit.py`, `spatalk/models.py` (`audit_reports`), `spatalk/settings.py` (`judge_model="gemini-2.5-pro"`, `ops_email`), `spatalk/ledger/scheduler.py` (nightly at 04:00), `tests/test_ops_nightly_audit.py`

**Interfaces:** `lexicon_scan(ctx, day) -> {conversations_with_clinical_terms_not_band3: [ids], count}`; `band_audit(ctx, day, judge: LLMClient) -> {reviewed, disagreements: [{conversation_id, actual_band, judged_band, reason}]}`; `health_context_stats(ctx, day) -> {conversations, flagged, items_flagged}`; `run_nightly_audit(ctx, day) -> AuditReport` stored in `audit_reports(day, tenant_id, report jsonb)` and emailed to `ops_email` with a plain-text summary; blocking finding (any judged band 3 handled as 1 or 2) also raises an alert through `alerts.notify`.

**Behaviour:** the judge prompt receives the transcript and the three band definitions from the brief verbatim and must return JSON `{band, reason}`; `FakeLLM` in tests; conversations with `controller == human` are excluded from the band audit; the report is per tenant; the portal admin health page (portal plan C5) reads the latest report through a new `GET /internal/tenants/{id}/audit/latest`.

**Tests:** seeded day with one clinical-term conversation at band 1 (found), one at band 3 (not flagged); judge disagreement produces an alert; report persisted and email composed; a day with no conversations produces a zero report and no alert.

**Done when:** tests pass. Commit `feat(ops): nightly escalation audit with a judge model and health-context stats`.

---

### Task E5: Latency budgets per stage and the SLO check

**Files:** `spatalk/voice/observers.py`, `spatalk/voice/session.py` (`stage_ttfb_ms: dict[str, list[int]]`), `spatalk/voice/pipeline.py` (`_finalize` stores `stage_ms`), `spatalk/models.py` (`conversations.stage_ms jsonb`), `spatalk/ops/latency.py`, `scripts/latency_report.py`, `.github/workflows/nightly-voice-evals.yml`, `runtime/scenarios/voice/*.yaml`, `tests/test_ops_latency.py`

**Interfaces:** `BUDGETS_MS = {"stt": 300, "llm": 450, "tts": 200, "turn": 800}`; `daily_latency(ctx, day) -> [{tenant_id, turns, p50, p95, stage_p95: {stt, llm, tts}, over_budget: [stage]}]`; `check_slo(ctx, day) -> list[Alert]`.

**Behaviour:** `UsageObserver` also collects `TTFBMetricsData` by processor name (`SonioxSTTService`, `GoogleLLMService`, `InworldTTSService` map to stt/llm/tts); `_finalize` writes per-stage p95 for the call into `stage_ms`; the daily report computes tenant p95 across turns; if turn p95 exceeds 800 ms or any stage exceeds its budget for the day, an alert names the stage and the suggested fix (llm → Flash-Lite, tts → the other vendor, stt → Flux); `scripts/latency_report.py --days 7` prints a table. `nightly-voice-evals.yml` runs `pipecat eval run scenarios/voice/*.yaml` in audio mode with recorded caller audio when the provider keys exist as secrets; otherwise skipped with a notice.

**Tests:** observer maps metrics to stages; daily report math on seeded `stage_ms`; SLO check alerts with the right stage; skipped-without-keys path.

**Done when:** tests pass. Commit `feat(ops): per-stage latency budgets, daily report and slo alerts`.

---

### Task E6: Second LLM vendor, model-list check and the swap drill

**Files:** `spatalk/voice/pipeline.py` (`make_llm`), `spatalk/brain/driver.py` (`OpenAIClient`), `spatalk/ops/model_check.py`, `pyproject.toml` (`pipecat-ai[openai]`, `openai`), `.github/workflows/model-check.yml`, `docs/runbooks/model-swap.md`, `tests/test_ops_model_check.py`, `tests/test_driver.py` (+OpenAI client test, skipped without key)

**Behaviour:** `LLM_MODEL` accepts `gemini-2.5-flash` (Google) or `openai:gpt-4.1-nano` (OpenAI); `make_llm` returns `OpenAILLMService` for the `openai:` prefix with `settings=OpenAILLMService.Settings(model=..., temperature=0.3)`; `OpenAIClient` implements `LLMClient` with tool calling through the Responses or Chat Completions API (whichever the installed SDK supports for tools; record which). `model_check.py` lists models at the configured provider and exits non-zero if the configured model is absent or marked deprecated; `model-check.yml` runs weekly with the provider keys. `docs/runbooks/model-swap.md`: the drill (set the env, run pytest, run promptfoo, run 20 calls, compare p95 and cost, decide) and the rollback.

**Tests:** `make_llm` selects the right class for each prefix without network; `OpenAIClient` parses a recorded tool-call response; live test skipped without `OPENAI_API_KEY`; model check handles a missing model.

**Done when:** tests pass. Commit `feat(ops): openai as a second llm vendor, weekly model check and swap runbook`.

---

### Task E7: Monitoring, error reporting and alerts

**Files:** `spatalk/ops/alerts.py`, `spatalk/models.py` (`alert_log`), `spatalk/http/app.py` (`/healthz` adds `commit`, `queued_jobs`, `oldest_queued_age_s`, `dead_jobs`, `last_scheduler_tick`), `spatalk/settings.py` (`sentry_dsn`, `ops_email`, `ops_sms_number`, `git_commit`), `Dockerfile` (`ARG GIT_COMMIT` → env), `spatalk/ledger/scheduler.py` (alert conditions every 5 minutes), `docs/runbooks/monitoring.md`, `tests/test_ops_alerts.py`

**Behaviour:** `notify(ctx, key, subject, body)` sends an email to `ops_email` and, if set, one SMS to `ops_sms_number`, deduplicated per `key` for 6 hours via `alert_log`; conditions: any dead job, oldest queued job older than 5 minutes, an escalation delivery job dead, scheduler tick older than 3 minutes (checked from `/healthz` by the uptime monitor), audit blocking finding (E4), SLO breach (E5); Sentry initialised only when `sentry_dsn` is set, with PII scrubbing (phone numbers and emails masked in breadcrumbs); loguru emits JSON in production (`LOG_FORMAT=json`). `monitoring.md`: UptimeRobot monitors on `/healthz` (expecting `"ok":true` and `dead_jobs":0` via keyword check) and on the media host TCP port.

**Tests:** dedup within 6 hours, new alert after; conditions produce alerts on seeded state; PII scrubber masks a phone number; `/healthz` fields present.

**Done when:** tests pass. Commit `feat(ops): health fields, alerting with dedup, optional sentry`.

---

### Task E8: Security hardening in code and CI

**Files:** `spatalk/http/ratelimit.py`, `spatalk/http/app.py`, `spatalk/http/actions.py`, `.github/workflows/ci.yml` (gitleaks, pip-audit, npm audit), `.gitleaks.toml`, `tests/test_ops_ratelimit.py`

**Behaviour:** in-process token-bucket limits keyed by client IP (honouring `CF-Connecting-IP` when present): `/a/*` 10/min, `/chat/*` 30/min, `/widget/*` 60/min, `/telnyx/*` and `/instagram/*` 300/min unless the edge key header is present; 429 with `Retry-After`; action pages send `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; form-action 'self'` and `Referrer-Policy: no-referrer`; CI fails on a leaked secret pattern (`gitleaks`), on a known-vulnerable Python package (`pip-audit`, allowlist file for accepted findings), and on `npm audit --audit-level=high` for the portal and the worker.

**Tests:** bucket refill math; limit returns 429 then recovers; edge key bypass; headers present on `/a/{token}`.

**Done when:** tests and CI pass. Commit `chore(ops): rate limits, security headers, secret and dependency scanning`.

---

### Task E9: Monthly cost reconciliation

**Files:** `spatalk/ops/cost_report.py`, `spatalk/models.py` (`provider_invoices`), `spatalk/cli.py` (`invoices add <provider> <YYYY-MM> <amount_cad>`, `cost report <YYYY-MM>`), `spatalk/ledger/scheduler.py` (first of the month), `tests/test_ops_cost_report.py`

**Behaviour:** `cost_report(ctx, month) -> {per_tenant: {tenant: {channel: cad, total: cad}}, per_provider_estimate: {provider: cad}, invoices: {provider: cad}, drift_pct: {provider: pct}}` using `spatalk.rates.estimate_cad` per usage unit; the emailed report lists the top drift and the per-tenant cost against the $999 price (gross margin); `invoices add` records what each provider actually billed so drift is visible.

**Tests:** seeded usage across two tenants and channels; totals and margins; drift computed against recorded invoices; missing invoice shows "not entered", not zero.

**Done when:** tests pass. Commit `feat(ops): monthly cost reconciliation against provider invoices`.

---

### Task E10: Live transfer spike and implementation

**Files:** `docs/runbooks/transfer.md` (spike result), then depending on the result: `spatalk/voice/handlers.py` (`transfer_to_human` tool), `spatalk/brain/tools.py`, `spatalk/brain/tier_c.py` (`transfer` capability returning `Transferred | Captured`), `spatalk/brain/outcomes.py` (`Transferred(number_masked)`), `spatalk/voice/texml.py`, `runtime/tenants/skincentrix/tenant.yaml` (`transfer_number`), `tests/test_voice_transfer.py`

**Behaviour (spike first, as a runbook experiment the founder runs on the live number):**
1. Option A: issue `POST /v2/calls/{call_control_id}/actions/transfer` with `to=transfer_number` on the TeXML-originated call using the `call_control_id` from the stream start message. Record whether Telnyx accepts it on a TeXML call.
2. Option B: if A is refused, switch the voice number from the TeXML application to a Call Control application: the runtime answers with `POST /calls/{id}/actions/answer` then `POST .../streaming_start` with `stream_url` and `stream_bidirectional_mode=rtp`; the same WebSocket protocol and `TelnyxFrameSerializer` apply; transfer is then native. This changes `texml.py` into a Call Control webhook handler (`call.initiated` → answer + streaming_start with the signed token in the URL).
3. Implementation after the spike: `transfer_to_human` tool available only when the tenant has `transfer_number` and the calendar says open; the handler speaks `scripts.transferring` ("One moment, I'll connect you to the team.") then transfers; if the transfer fails within 20 seconds, the capability returns `Captured` (urgent callback) and speaks the human-request script. `Transferred` is a new outcome constructible by the voice adapter only; Tier C's `transfer` returns `Captured` when no number is configured. Outside hours, the tool is not exposed to the model at all (tool list is built per call from the calendar state).

**Tests:** tool exposed only when open and configured; handler falls back to `Captured` on a failed transfer with the fake Telnyx client; TeXML/Call Control handler tests for the chosen option; renderer for `Transferred`.

**Done when:** spike result recorded; implementation tests pass; a real transfer succeeds once on the clinic's back-line (founder checklist). Commit `feat(voice): live transfer to a staffed back-line during hours, with honest fallback`.

---

### Optional Task E11: Pre-synthesised script audio

Cache the disclosure and goodbye audio per (tenant, script version, voice) at bundle import and play the cached PCM at call start instead of calling TTS each time. Saves about $0.002 per call and about 150 ms of first-word latency. Only after E5 shows the disclosure's TTS latency matters.

---

## Self-review against spec §10

| Weakness | Task | Failable check |
|---|---|---|
| 1 unpublished rates | runtime plan Task 16 step 9; E9 | cost model exit code; monthly drift |
| 2 vendor latency claims | runtime Task 16 step 8; E5 | bake-off p95; per-stage budgets |
| 3 model deprecation | E6 | weekly model check; swap drill |
| 4 800 ms budget | E5 | daily SLO alert with the failing stage |
| 5 transcripts hold health statements | E3, E4 | retention receipts; lexicon scan and health-context stats |
| 6 self-hosted Postgres | E2 | CI backup drill; monthly R2 drill |
| 7 back-line may not exist | E1 loop guard, E10 | hangup on self-call; transfer fallback to `Captured` |
| 8 two codebases | portal plan C3, C8 | contract drift check |
| 9 Wasp multi-schema | portal plan C1 | recorded spike |
| 10 external clocks | runbooks | checklist with dates |
