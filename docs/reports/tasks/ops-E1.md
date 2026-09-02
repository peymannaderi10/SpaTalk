# operations Task E1: Carrier failover bin and the loop guard

Status: done with deviations
Commit: <pending>
Tests: `uv run pytest -q tests/test_ops_loop_guard.py` -> 10/10; full suite
`TEST_DATABASE_URL=…/spatalk_test_e1 uv run pytest -q` -> 635 passed, 1 skipped, 0 failed
(636/636; the skip is `test_driver.py::test_gemini_client_calls_a_tool`, `skipif` on
`GOOGLE_API_KEY`). `uv run ruff check spatalk tests scenarios` -> All checks passed.
Interfaces produced: `spatalk.ops.loop_guard.is_own_number(cfg, registry, number) -> bool` (async), `spatalk.ops.loop_guard.normalise_e164(value, country_code="1") -> str | None`, `spatalk.ops.loop_guard.own_numbers(cfg) -> set[str]`, `spatalk.ops.loop_guard.log_loop_guard_alert(sf, tenant_id, number) -> None`, `spatalk.voice.texml.failover_bin(cfg, now) -> str`, `spatalk.voice.texml.say_and_hangup(sentence) -> str`, `spatalk.models.AlertLog` (table `runtime.alert_log`), CLI `spatalk texml failover-bin <tenant_id>`

## What is in place

- `POST /telnyx/texml` resolves the tenant, then asks the loop guard about `From` before
  anything else happens. On a match the caller hears `scripts.loop_guard`, the call is hung
  up, one `runtime.alert_log` row is written, and `start_conversation` is never reached, so
  no conversation, no stream token and no media socket exist for that call.
- `is_own_number` matches two sources: every number the registry maps to this tenant
  (`tenant_numbers`, authoritative for numbers we bought) and the numbers the bundle itself
  claims (`public_phone`, `sms_from_number`, `voice_numbers`). Comparison is in E.164, so
  the bundle's `905-703-7546` and the carrier's `+19057037546` are one number.
- `spatalk texml failover-bin skincentrix` prints
  `<Response><Say voice="female" language="en-CA">…</Say><Hangup/></Response>` carrying the
  tenant's live `scripts.failover`, rendered through `render_script` like every other fixed
  sentence, so the carrier-hosted wording is config and not a literal in code.
- `docs/runbooks/failover.md` covers the bin (get it, paste it, point the TeXML
  application's Failover URL at it), the verification call with the app container stopped
  and a table to record the result in, the loop guard and the SQL to read its alerts, and
  why the `<Record>` voicemail variant is opt-in per tenant.

## Deviations

- **`is_own_number` is `async`.** The plan writes `is_own_number(cfg, registry, number) -> bool`,
  but the only registry lookup for a number is `TenantRegistry.resolve_number`, which is a
  coroutine (`spatalk/tenants/registry.py`). The name, the argument order and the return
  type are exactly as the plan specifies; only the coroutine marker is added, and the sole
  caller (`voice/texml.py`) already awaits inside an async route.
  Evidence: `grep -n "async def resolve_number" runtime/spatalk/tenants/registry.py` ->
  `async def resolve_number(self, number: str) -> str | None:`.
- **`alert_log` and its migration landed here, not in E7.** E1's behaviour 2 requires an
  `alert_log` row, but the plan's File Structure assigns `models.py (+ … alert_log)` to
  Task E7 and the ops migration to E3. Nothing can write a row to a table that does not
  exist, so this task adds `spatalk.models.AlertLog` (appended in its own delimited block,
  no existing model touched) and `alembic/versions/0005_ops_alert_log.py`, chained after
  `0004` (the current head; `0004_ops.py` in E3's file list is now taken, so E3 should
  number its migration `0006` or later). Columns and index are exactly what
  `docs/reference/data-model.md` specifies, so E7's `alerts.notify` can dedup on `key`
  without changing the table.
  Evidence: `uv run pytest -q tests/test_qa_gate_a.py::test_alembic_head_creates_every_documented_table_and_index`
  -> passed (real `alembic upgrade head` on a throwaway database).
- **`docs/reference/data-model.md` gained a `### alert_log` heading.** The reference listed
  the five operations tables under one combined `###` heading, and
  `tests/test_qa_gate_a.py::_documented_tables` parses `^### (\w+) \[…\]`, so a schema
  containing `alert_log` failed the gate's "no table the reference does not name" assertion.
  The fix is presentational: `alert_log` now has its own section with the same columns and
  index the combined table gave it, and it is removed from that table's list. No documented
  column changed. E3, E7 and E9 will want to do the same for the tables they create.
  Evidence: before the doc change the full suite reported
  `FAILED tests/test_qa_gate_a.py::test_alembic_head_creates_every_documented_table_and_index`;
  after it, that test passes.
- **`spatalk/cli.py` is not in E1's Files list** but behaviour 4 requires the command, so a
  `texml` sub-app was appended in its own delimited block (no existing command reordered).
  `failover_bin` itself lives in `spatalk/voice/texml.py` rather than in
  `spatalk/ops/loop_guard.py`: it builds a TeXML document, which is what that module owns,
  and it keeps every TeXML string in one file. The CLI command is a four-line wrapper.
- **`runtime/tenants/skincentrix/scripts.yaml` needed no edit.** The plan lists it for the
  `loop_guard` and `failover` keys; both were already present with exactly the authored
  wording (`docs/reference/tenant-config.md`), as are the defaults in
  `spatalk/tenants/schema.py`. Nothing was changed.

## Notes for neighbours

- **E7 (`ops/alerts.py`)**: the table you need already exists, with
  `Index("ix_alert_key_sent", "key", "sent_at")`. The key convention this task set is
  `"<condition>:<scope>"` — the loop guard writes `loop_guard:<tenant_id>:<E.164>`, one key
  per (tenant, calling number), so a number stuck in a forwarding loop dedups to a single
  alert rather than one per ring. E1 writes the row directly and sends nothing; when
  `notify` exists, the loop guard should route through it instead of
  `log_loop_guard_alert`, which is a two-line change in `voice/texml.py`.
- **E3**: `0005` is taken. Chain your ops migration after it and rename `0004_ops.py` in the
  plan's file list accordingly.
- **E10 (live transfer)**: `is_own_number` is also the check that stops a transfer target
  pointing back at us. If option B turns `texml.py` into a Call Control handler, the guard
  call must move with it — it has to run before `answer`, not after.
- **Founder-visible honesty gap the runbook flags**: with `sms_from_number: null` in
  `tenants/skincentrix/tenant.yaml`, `render_script("failover", …)` falls back through
  `{sms_number}` to `public_phone`, so today the bin would tell callers to text the clinic's
  landline. The runbook says to generate and paste the bin only after the toll-free number
  is verified, and to re-paste it whenever the number, the booking URL or the script
  changes. Nothing keeps a carrier-hosted bin in sync automatically.
- **Concurrent agents cannot share `spatalk_test`; this is worth fixing before the next
  parallel batch.** E2 and E8 were working in the same tree while this task ran. Three
  full-suite runs against the default `spatalk_test` produced three different failure sets
  (2, then 5, then 10 failures) spread across `test_text_sms.py`, `test_takeover.py`,
  `test_http_actions.py` and `test_deploy_assets.py` — tests this task does not touch, with
  symptoms like `inbound sms to unconfigured number +18885550100`, i.e. rows that should
  exist having vanished mid-test. `tests/conftest.py` runs `drop_all` + `create_all` on the
  shared database for **every** test, so one agent's pytest drops the schema out from under
  another's. Re-run on a private database, the whole tree is green:
  `docker compose exec -T db psql -U spatalk -d spatalk -c "CREATE DATABASE spatalk_test_e1 OWNER spatalk"`
  then `TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_e1 uv run pytest -q`
  -> **635 passed, 1 skipped**, including E2's and E8's tests. Suggested fix for the
  orchestrator: give each concurrent agent its own `TEST_DATABASE_URL`, or make the schema
  fixture use a per-worker database name. Do not read a red suite from a parallel batch as a
  regression without re-running it in isolation first.
