# sms-flood-guard Task F1: settings, table, verdict, the guard in the route

Status: done with deviations
Engineer: the orchestrating assistant (inline, founder's instruction 2026-09-03; Opus agents unavailable, HTTP 529)
Plan: `docs/superpowers/plans/2026-09-02-sms-flood-guard-plan.md`

## What changed

- `runtime/spatalk/tenants/schema.py`: `SmsGuard` (burst 12 in 10 min, 40 a day, mute 24 h, tenant ceiling 400 replies a day; every value at least 1) on `TenantConfig.sms_guard`; `Scripts.sms_paused` with a default that names no reply time, validated like every script.
- `runtime/spatalk/models.py` + `alembic/versions/0010_sms_blocks.py`: `runtime.sms_blocks` (tenant_id, phone) with `until` (null = permanent), `reason`, `created_by`, `created_at`; index `(tenant_id, until)`. Applied, downgraded and reapplied on a scratch database; one head.
- `runtime/spatalk/text/flood.py` (new): `inbound_verdict`, `mute`, `block`, `unblock`, `list_blocks`, `replies_today`, `paused_notice_once`, `local_day_start`, `local_day`. Counts come from `messages` joined to `conversations` (channel `sms`, caller), in the tenant's local day.
- `runtime/spatalk/conversations.py`: `append_message(..., at=None)` stamps a message with the application clock when asked; `runtime/spatalk/text/service.py` passes `at=ctx.clock.now()` for user and assistant messages and gains `handle_inbound(..., suppressed_reason=None)`, which stores the text, mirrors it, meters the inbound and returns without a model call, reply or follow-up.
- `runtime/spatalk/text/sms.py`: after the carrier keywords and the staff check, `inbound_verdict`; `blocked` and `muted` store and return `{"ok": true, "suppressed": <verdict>}`; `capped` stores and sends `scripts.sms_paused` once per sender per local day (bookkeeping row in `alert_log`, no email).
- Alerts through E7 `notify`: `sms.flood:<tenant>:<phone>` on a mute, `sms.daily_cap:<tenant>:<local day>` on the ceiling.
- Skincentrix bundle: `sms_guard` defaults written out; `sms_paused` in `scripts.yaml`. `docs/reference/tenant-config.md` and `data-model.md` updated.

## Tests

`runtime/tests/test_sms_flood.py`, 8 tests, all seen failing before the implementation (8 failed) and passing after: the 13th text in ten minutes is stored, unanswered, mutes for 24 h with one alert and no model call; a muted number still gets HELP and STOP answers and nothing else; the daily limit rolls over at Toronto midnight, proven with a text at 03:00 UTC (still capped) and 04:05 UTC (answered); a permanent block never expires and every text is still on the record; the tenant ceiling pauses the assistant with one fixed text per sender per day, one alert, and resumes the next local day; staff numbers are never muted or capped; settings validation and the bundle round trip.

Full suite: 957 passed, 2 skipped. `ruff check spatalk tests scenarios`: clean.

## Deviations

- Carrier keywords do not count toward the sender's burst, contrary to the plan's Global Constraints. STOP, START and HELP are answered before any message is stored, so there is no row to count; making them count would mean storing keyword messages, which the text service deliberately does not. A STOP flood therefore still costs one confirmation per text, as the carrier requires.
- `notify` deduplicates for six hours, so the daily-cap alert can repeat up to three more times in a heavy day (the key carries the local date, so never across days). Accepted rather than adding a second dedup window.
- Message timestamps in the text service now come from the application clock instead of the database default. In production the two are the same wall clock; in tests it is what lets the fixed clock drive the limits. Voice transcripts are unchanged.

## Notes for neighbours

- F2 manages `sms_blocks` through `block`, `unblock`, `list_blocks` in `spatalk/text/flood.py`; do not write the table directly. A staff number must be refused by the API and the CLI before calling `block`.
- F3's edge worker rule (one offline reply per sender per hour) is independent of this table; only permanent blocks (`until is null`) should be synced to the worker.
- Response body for a suppressed text is `{"ok": true, "suppressed": "blocked" | "muted" | "capped"}`; tests assert it, so it is a contract.
