# operations plan Task E7: Monitoring, error reporting and alerts

Status: done with deviations
Commit: <filled in below>
Tests: `TEST_DATABASE_URL=…/spatalk_test_e7 uv run pytest -q tests/test_ops_alerts.py` -> **43/43**;
full suite `TEST_DATABASE_URL=…/spatalk_test_e7 uv run pytest -q` -> **731 passed, 2 failed,
1 skipped** (734). Neither failure is this task's and neither is in a file this task touched
— one belongs to a WhatsApp plan running concurrently in the same working tree, the other is
the rates drift E4 reported and handed to the rates owner. Proof for both under "Two failures
this task did not cause". The skip is `test_driver.py::test_gemini_client_calls_a_tool`,
`skipif` on `GOOGLE_API_KEY`. `uv run ruff check spatalk tests scenarios` -> All checks passed.

Interfaces produced: `spatalk.ops.alerts.notify(ctx, key, subject, body) -> bool` (unchanged
signature, now with the SMS leg), `…already_alerted(ctx, key)`, `…ops_sms_from(ctx) -> str | None`,
`…record_scheduler_tick(now)`, `…last_scheduler_tick() -> datetime | None`,
`…reset_monitoring_state()`, `…health_snapshot(ctx) -> dict`,
`…alert_conditions(ctx) -> list[AlertCondition]`, `…check_alert_conditions(ctx) -> list[str]`,
`…AlertCondition(key, subject, body)`, `…scrub_pii(value) -> str`,
`…scrub_breadcrumb(crumb, hint=None)`, `…scrub_event(event, hint=None)`,
`…init_sentry(settings) -> bool`, `…configure_logging(settings) -> bool`,
`…DEDUP_HOURS = 6`, `…STALE_QUEUE_SECONDS = 300`, `…STALE_TICK_SECONDS = 180`,
`…PHONE_RE`, `…EMAIL_RE`, `spatalk.ledger.scheduler.ensure_alert_conditions_checked(ctx) -> list[str] | None`,
`spatalk.ledger.scheduler.reset_alert_check_state()`, `spatalk.ledger.scheduler.ALERT_CHECK_SECONDS = 300`,
`spatalk.settings.Settings.ops_sms_number`, `.sentry_dsn`, `.log_format`,
`GET /healthz` + `queued_jobs`, `oldest_queued_age_s`, `dead_jobs`, `last_scheduler_tick`,
`docs/runbooks/monitoring.md`.

## What is in place

- **`/healthz` now says whether the runtime is *working*, not just answering.** A port check
  cannot tell a serving process from one that has quietly stopped draining its queue, so the
  endpoint carries `queued_jobs`, `oldest_queued_age_s`, `dead_jobs` and `last_scheduler_tick`
  beside the tenant list, config versions and commit it already had. `oldest_queued_age_s`
  deliberately measures only jobs that are already **due**: the retention job sits queued from
  03:00 for the rest of the night by design, and counting it as backlog would make the number
  meaningless. FastAPI serialises with no spaces, so the two keyword checks the runbook tells
  the founder to create — `"ok":true` and `"dead_jobs":0` — are literal bytes on the wire;
  `test_healthz_answers_the_two_keyword_checks_the_monitor_uses` pins them.
- **Four conditions, re-derived every five minutes by the scheduler.** `escalation_delivery_dead`
  (a `deliver.*` job with `escalation: true` that died — an item passed its due time, the
  runtime tried to tell the clinic, and the attempt failed, so a customer is waiting and
  nobody knows), `jobs_dead`, `queue_stale` (oldest due job over 5 minutes) and
  `scheduler_tick_stale` (last completed pass over 3 minutes old). Each is a key, and the key
  is the identity of the incident, so a condition that persists for a day sends one message,
  not 288.
- **The tick is a claim that a whole pass completed.** `alerts.record_scheduler_tick` is called
  at the *end* of the scheduler loop, after every piece of scheduled work, and inside the try:
  a pass that threw records nothing, which is exactly the state the stale-tick condition and
  the uptime monitor exist to notice. A process that has not finished a pass yet reports
  `null` and raises nothing — "nothing has run yet" is a start-up state, not an incident
  (`test_a_runtime_that_has_never_ticked_is_not_reported_as_stale`).
- **The SMS leg is one message per incident per six hours**, carrying the subject and nothing
  else, and it is wired through the same `SmsPort` as everything else, so no test reaches
  Telnyx. A failure to send is logged and swallowed for the same reason a failed email is: the
  `alert_log` row is written first, and an alert about a failure must not itself become the
  failure that stops the job that raised it (`test_a_delivery_failure_never_erases_the_incident`).
- **Sentry is optional, off, and never sees a caller.** No DSN, no client. With a DSN, it is
  initialised with `send_default_pii=False` plus `before_send`/`before_breadcrumb` scrubbers of
  our own that walk messages, exception values, breadcrumbs, `extra` and `request` and mask
  every phone number and email address. The phone pattern covers the five shapes this system
  actually sees (`+19055550100`, `905-703-7546`, `(905) 703-7546`, `905.703.7546`,
  `+1 905 555 0100`) and leaves job ids, item ids and ISO timestamps alone — the last is a
  test of its own, because a scrubber that eats the timestamp makes the report useless.
- **`LOG_FORMAT=json` sets `diagnose=False`**, which is not a style preference: loguru's
  diagnostic tracebacks print the value of every local variable, and on this service that means
  a caller's number in the log of the exception that mentioned it.
- **The runbook is the part a machine cannot do.** `docs/runbooks/monitoring.md` gives the two
  UptimeRobot keyword monitors on `/healthz`, the TCP monitor on `<MEDIA_HOST>:443` (a real
  WebSocket check is impossible: the media token is signed and single-use), the drill that
  proves all three fire, how to read `alert_log`, and what each environment variable does.

## Deviations

1. **`spatalk/models.py` was not touched.** The plan's Files list gives E7 `models.py
   (alert_log)`, but E1 created that table and its `(key, sent_at)` index for the loop guard
   and its report told E7 to extend rather than recreate it. Nothing in E7 needs a column
   that is not there. Evidence: `grep -n "class AlertLog" -A 15 spatalk/models.py` ->
   `__tablename__ = "alert_log"` with `Index("ix_alert_key_sent", "key", "sent_at")`. No
   migration was written for the same reason — E7 adds no table and no column.
2. **`Dockerfile` was not touched.** The plan asks for `ARG GIT_COMMIT` → env; it is already
   there from the portal plan (`ARG GIT_COMMIT=""` / `ENV GIT_COMMIT=$GIT_COMMIT`), as is
   `Settings.git_commit` and `/healthz`'s `commit`. Evidence: `grep -n GIT_COMMIT Dockerfile`.
3. **The scheduler-tick freshness is process state, not a row.** The plan lists
   `last_scheduler_tick` as a `/healthz` field and says the uptime monitor is what judges it.
   The fact being reported is "this process is still looping", so it is a module-level value in
   `ops/alerts.py`, not an `ops_runs` row: a row per minute would be 1,440 writes a day to say
   nothing happened, and the operations plan's global constraint asks for a row per *scheduled
   run*, which retention and the nightly audit already write. The consequence is honest and
   documented: a restarted process reports `null` until its first completed pass, and if the
   API and the scheduler are ever split into two processes, `/healthz` in the API process will
   report `null` forever and this must move to a row. `reset_alert_check_state()` exists so the
   tests can clear both pieces of process state; it is a seam, not a placeholder.
4. **The tick state and the health snapshot live in `ops/alerts.py`, not in `scheduler.py`.**
   `scheduler.py` imports `alerts` (for the conditions), so a tick stored in `scheduler.py` and
   read by `alerts.health_snapshot` would be a circular import. The dependency runs one way:
   scheduler → alerts. Evidence: `uv run pytest -q tests/test_smoke_imports.py` -> passed.
5. **An ops SMS is sent from the first tenant `sms_from_number` the registry knows.** E4's
   report flagged that `ops_sms_number` needed a decision about which number an alert is sent
   *from*, and `docs/reference/api-surface.md` defines no `OPS_SMS_FROM`. Inventing one would
   have meant an environment variable the reference does not list; there is one Telnyx account
   and the runtime owns no operations number, so `ops_sms_from(ctx)` scans tenants exactly as
   `cli.collect_tenant_texts` already does. **This has a live consequence recorded in the
   runbook:** Skincentrix has `sms_from_number: null` until the toll-free number is verified,
   so setting `OPS_SMS_NUMBER` today records and emails the alert, logs "no tenant has an
   `sms_from_number`", and texts nobody — it does not pretend to have texted. Pinned by
   `test_with_no_tenant_number_to_send_from_the_alert_is_still_recorded`. If the founder wants
   an ops SMS before that number lands, the smallest honest change is an `OPS_SMS_FROM`
   variable plus a line in `api-surface.md`.
6. **`spatalk/settings.py` gained `log_format` as well as the three variables the plan names.**
   The plan's Files list for settings is `sentry_dsn, ops_email, ops_sms_number, git_commit`,
   but its Behaviour requires `LOG_FORMAT=json`, and `api-surface.md` lists `LOG_FORMAT` under
   E7. `ops_email` and `git_commit` already existed (E4 and the portal plan).
7. **`runtime/.env.example`: the E7 variables were added and QA gate B's inline-comment bug was
   fixed for all twelve keys it affected, not just `GIT_COMMIT`.** Gate B found that
   `GIT_COMMIT=   # set by the image build` parses in python-dotenv as the *comment string*,
   because an inline comment is only stripped when the value is non-empty — so `/healthz`
   reported `"commit":"# set by the image build; reported by /healthz"` on this machine. That
   is an E7 field on an E7 endpoint, so it is this task's to close, and the identical bug on
   the other eleven empty-valued keys (including `TURNSTILE_SECRET_KEY`, which would have made
   the widget challenge with a bogus key, and `META_TOKEN_ENCRYPTION_KEY`) was fixed the same
   way: the comment moved to its own line above the assignment. No value changed. Pinned for
   good by `test_no_env_example_value_is_actually_an_inline_comment`, which parses the file
   with python-dotenv rather than reading it. Evidence, before and after:
   `uv run python -c "from dotenv import dotenv_values; …"` -> `42 keys; 12 poisoned` then
   `42 keys; 0 poisoned`.
8. **`sentry-sdk` was not added to `pyproject.toml`.** The plan's Tech Stack calls it optional
   and `pyproject.toml` is Task E6's file. `_sentry_init` imports it lazily inside the call, so
   a missing package is a `logger.warning` and a service that still boots rather than an
   ImportError at start-up (`test_a_missing_sentry_package_is_a_warning_not_a_crash`). It is in
   fact resolvable in this environment already, as a transitive dependency of
   `fastapi-cloud-cli`; evidence: `uv run python -c "import sentry_sdk; print(sentry_sdk.VERSION)"`
   -> `2.68.1`, and `grep -n sentry uv.lock` -> pinned at that version. If E6 or a later task
   wants it guaranteed, one line in `[project.optional-dependencies]` does it.
9. **`voice/texml.py`'s loop guard was left writing `alert_log` directly.** E1's report suggests
   routing it through `notify` "when notify exists". It was not done here: `notify` deduplicates
   on the key for six hours, and E1's tests assert one row per refused self-call, so the change
   would have altered a neighbouring task's tested behaviour. It is a two-line change plus a
   decision about whether a forwarding loop should page the founder once per six hours; it
   belongs to whoever owns `texml.py` next (E10). `texml.py` is not in E7's Files list.
10. **The condition list is exactly the plan's, and E3's suggestion was not added.** E3 proposed
    alerting on "no `ops_runs` row with `kind='ops.retention'` in the last 26 hours", which is a
    good check and the only way a nightly job that stopped running becomes visible. It is not in
    E7's Behaviour and it needs a decision about a fresh install (no runs yet is not an
    incident), so it is recorded here rather than invented. E4's `audit_blocking:<tenant>:<day>`
    and E5's SLO alert already route through the same `notify`, as the plan intends.

11. **`docs/runbooks/monitoring.md` is not in this task's commit — another agent's commit
    swept it up first.** It was written here, left untracked while the suite ran, and a
    concurrent runbooks commit added it verbatim: `git show --stat d728668` ->
    `docs/runbooks/monitoring.md | 129 ++++…`, and `git show HEAD:docs/runbooks/monitoring.md
    | diff - docs/runbooks/monitoring.md` -> identical. Nothing was lost and nothing needs
    redoing; it is recorded so the orchestrator is not surprised that E7's commit does not
    name the file its Files list does. Same working-tree-sharing cause as the failure below.

## Two failures this task did not cause

Both were reproduced in isolation and neither is in a file this task modified.

1. `tests/test_delivery.py::test_item_delivery_enqueues_per_destination_and_sends` — asserts
   `run_once` processes 2 jobs and gets 3. The captured log names the cause:
   `spatalk.ledger.delivery:_deliver_whatsapp:655 - whatsapp number env
   SKINCENTRIX_WHATSAPP_STAFF not set; skipping`. A WhatsApp plan is being written in this same
   working tree right now: `git diff --stat -- runtime/spatalk/ledger/delivery.py
   runtime/spatalk/models.py runtime/spatalk/tenants/schema.py` -> **387 insertions**, none of
   them this task's, alongside an untracked `docs/superpowers/plans/2026-09-02-whatsapp-delivery-plan.md`
   and `runtime/tests/test_whatsapp_delivery.py`. This task touched none of those files and its
   commit names its own paths explicitly.
2. `tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table` — the drift
   between `runtime/spatalk/rates.json` and `docs/research/rates.json` that E4's report
   documented and routed to the rates owner. Neither file is modified in this working tree
   (`git diff --stat` on both -> empty) and their last commits are different pieces of work:
   `7267613 feat(runtime): internal api for the portal…` versus `4fbee36 docs(research): telnyx
   voice ai add-on rates…`.

An earlier full run in the middle of the WhatsApp agent's edits produced 83 collection errors
across unrelated files; re-run twice afterwards it settled at the numbers above, and every file
that errored passes in isolation (`tests/test_widget.py` -> 22 passed). Concurrent agents in one
working tree remain the flakiest thing about these runs, as E1's report already warned.

## Notes for neighbours

- **E5 (latency)**: `alerts.notify` is ready; use a key that names the stage, e.g.
  `slo:<tenant>:<stage>:<day>`, so a bad day dedups to one alert per stage. If the SLO check
  runs from the scheduler, put it beside `ensure_alert_conditions_checked` — that call site is
  the five-minute cadence, and the tick recording must stay last in the loop.
- **E10 (live transfer)**: if the spike turns `texml.py` into a Call Control handler, that is the
  moment to route the loop guard through `alerts.notify` (deviation 9) and to decide whether a
  forwarding loop is worth an email.
- **E8 (rate limits)**: `/healthz` remains unlimited and unauthenticated, as your bins assume.
  Nothing here writes to `alert_log` on a rate-limit event, which matches your note.
- **Whoever next runs the suite**: `spatalk_test_e7` is this task's private database, for the
  reason E1, E3 and E4 all give — `tests/conftest.py` drops and recreates the schema for every
  test, so two agents sharing `spatalk_test` corrupt each other's runs.
- **A split of the API and scheduler into two processes breaks `last_scheduler_tick`** (deviation
  3). If that ever happens, the tick has to become a row; nothing else in this task cares.
- **The ops SMS is inert until a tenant has a verified `sms_from_number`** (deviation 5), and the
  runbook says so where the founder will read it.

## Verification run

| Check | Result |
|---|---|
| `uv run pytest -q tests/test_ops_alerts.py` (before any product code existed) | **43 errors/failures** — `ImportError: cannot import name 'reset_alert_check_state' from 'spatalk.ledger.scheduler'`, then `AttributeError: module 'spatalk.ops.alerts' has no attribute 'record_scheduler_tick'` |
| `uv run pytest -q tests/test_ops_alerts.py` (after) | **43 passed** in 13.2 s |
| Mutation check: `STALE_QUEUE_SECONDS`/`STALE_TICK_SECONDS` × 1000, `PHONE_RE` made to never match, `record_scheduler_tick` removed from the loop, `health_snapshot` removed from `/healthz` | **13 failed, 30 passed** — every threshold, the scrubber, the tick and the four `/healthz` fields are each pinned by a test that fails without them. Files restored and re-run: 43 passed. |
| `uv run ruff check spatalk tests scenarios` | All checks passed |
| `curl`-equivalent of the monitor's keyword check (`test_healthz_answers_the_two_keyword_checks_the_monitor_uses`) | `"ok":true` and `"dead_jobs":0` present in the raw body |
| `.env.example` parsed with python-dotenv | `42 keys; 12 poisoned` before -> `42 keys; 0 poisoned` after |
| full suite | **731 passed, 2 failed, 1 skipped** — both failures accounted for above |
