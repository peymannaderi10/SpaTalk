# portal Task C3: Runtime internal API and its contract (Python side)

Status: done with deviations
Commit: 72676139f21a70571d11922bad7daed6fce42348
Tests: `uv run pytest tests/test_internal_api.py tests/test_contract_snapshot.py -q` -> 41/41; full suite `uv run pytest -q` -> 368 passed, 1 skipped (369); `uv run ruff check spatalk tests scenarios` -> clean

Interfaces produced:
`spatalk.http.internal.router` (APIRouter, prefix `/internal`, `Depends(require_internal_key)` on every route), `require_internal_key`, `mask_caller`, `portal_actor`, `write_audit`, `config_versions(sf) -> dict[str, int]`, `openapi_document(internal_only=True) -> dict`; models `NumberOut, TenantSummary, TenantCreated, VersionOut, ConfigOut, ConfigVersionOut, ConfigIn, RollbackIn, ActorIn, AuditIn, UsageTotals, UsageDay, UsageOut, ConversationRow, ConversationPage, ConversationFull, MessageOut, ItemOut, ConversationDetail, LatencyDay, TenantHealth, RuntimeHealth`; `spatalk.rates.{RATES_PATH, PRICED_UNITS, load_rates, recommended_stack, estimate_cad(usage, rates=None) -> float}`; `spatalk.tenants.bundle.config_from_texts(texts, source="bundle") -> TenantConfig`; `Settings.internal_api_key`, `Settings.git_commit`; CLI `spatalk openapi [--internal/--no-internal] [--out PATH]`; `docs/contracts/runtime-internal.openapi.json`; `make sync-rates`, `make openapi`.

Endpoints, all under `/internal`, all requiring `X-Internal-Key` (constant-time compare, fails closed when `INTERNAL_API_KEY` is unset) and honouring optional `X-Actor`:

```
GET  /internal/tenants
POST /internal/tenants                              {config, created_by} -> {id, version}
POST /internal/tenants/from-bundle                  multipart: tenant, services, knowledge, scripts, guard, created_by
GET  /internal/tenants/{id}/config                  -> {version, config}
PUT  /internal/tenants/{id}/config                  -> {version}; 422 with field paths
GET  /internal/tenants/{id}/config/versions
POST /internal/tenants/{id}/config/rollback         {version, created_by} -> {version}
GET  /internal/tenants/{id}/usage?from&to           -> {days[], totals}
GET  /internal/tenants/{id}/conversations?from&to&channel&band&page&page_size
GET  /internal/tenants/{id}/items?state&page&page_size
GET  /internal/tenants/{id}/latency?from&to
GET  /internal/tenants/{id}/health
GET  /internal/conversations/{id}                   -> {conversation, messages, items}; audits read_transcript
POST /internal/items/{id}/acknowledge | /resolve    {actor} -> Item
GET  /internal/schema/tenant-config                 -> TenantConfig JSON schema
GET  /internal/health                               -> {ok, queued_jobs, oldest_queued_age_s, dead_jobs}
GET  /internal/rates                                -> the packaged rates table
POST /internal/audit                                -> 204
```

`GET /healthz` (unauthenticated, unchanged otherwise) now also returns `config_versions` (every tenant's current config version) and `commit` (`GIT_COMMIT`).

## What was built and why it is shaped this way

- **Two planes stay separated.** Nothing here lets the portal reach the database; every read is a projection the runtime chose to expose, and every write goes through the same `TenantRegistry` and `PgLedger` the voice and text channels use, so a portal-side acknowledgement is indistinguishable from a Slack-button one.
- **Days are tenant days.** `usage`, `conversations`, `latency` interpret `from`/`to` as `YYYY-MM-DD` in the tenant's timezone and group by `CAST(timezone(<tz>, created_at) AS DATE)`, so a clinic in Toronto sees Toronto Mondays. The range is capped at 400 days (422 beyond that) and defaults to the last 30 tenant days.
- **The cost estimate names no vendor.** `estimate_cad` prices whichever entry in `rates.json` carries `recommended: true` (today Telnyx + Soniox + Inworld + Gemini 2.5 Flash for voice, Telnyx toll-free for SMS) and converts at the table's recorded FX rate. Swapping providers is an edit to the table, not to the code (non-negotiable 4). `GET /internal/rates` serves the same table so the portal can show its working.
- **The contract is a committed artefact.** `spatalk openapi --internal` filters the app's OpenAPI document to `/internal` paths and prunes the component schemas nothing kept references; `tests/test_contract_snapshot.py` regenerates it on every run and fails if the committed file differs, in either direction. `X-Internal-Key` is declared as an OpenAPI *security scheme*, not as a header parameter, so the portal's generated client does not have to pass it on every call site (C4's `api.ts` injects it once).
- **Audit rows are written by the runtime, from the header.** Reading a transcript, saving a config, rolling back and acknowledging or resolving an item each write an `audit_log` row with actor `portal:<X-Actor>`, exactly as `docs/reference/data-model.md` spells it. `POST /internal/audit` is the one place the caller's own `actor` string is stored verbatim, because there the portal is recording an act of its own.

## Deviations

1. **`spatalk/tenants/bundle.py` (a runtime-plan Task 7 file) gained `config_from_texts` and `load_bundle` now delegates to it.** C5's wizard has to apply "the same rules as `load_bundle`" to uploaded files, and duplicating the assembly is how the CLI path and the portal path drift apart. `load_bundle` reads the five files into a dict and calls the new function; behaviour is unchanged except that a malformed `services.yaml` now raises `ValueError` instead of `KeyError`. Evidence: `uv run pytest tests/test_tenant_bundle.py -q` -> `5 passed`.
2. **`runtime/Dockerfile` gained `ARG GIT_COMMIT` / `ENV GIT_COMMIT`.** The task's additional scope asks for `/healthz` to report the deployed commit from `GIT_COMMIT`; without the build arg it is always empty inside the image. The operations plan E7 lists the identical change on the same file, so E7 will find it already done. Evidence: `uv run pytest tests/test_deploy_assets.py -q` -> `6 passed`.
3. **`runtime/Makefile` is new** (not in the task's Files list). The task's Behaviour names a `make sync-rates` target and no Makefile existed; it holds `sync-rates` (copy `docs/research/rates.json` into the package) and `openapi` (regenerate the contract). `tests/test_internal_api.py::test_the_packaged_rates_match_the_researched_table` fails if the copy drifts.
4. **`runtime/.env.example` gained `INTERNAL_API_KEY` and `GIT_COMMIT`.** `docs/reference/api-surface.md` already lists both as runtime variables; the example file is the env contract an operator copies. `docs/runbooks/accounts-and-env.md` already told the founder to generate `INTERNAL_API_KEY`, so no runbook change was needed there.
5. **Two runbook lines that quoted the old `/healthz` body were rewritten** (`docs/runbooks/deploy.md`, `docs/runbooks/accounts-and-env.md`) to `curl -s … | jq -c '{ok,tenants}'` with a sentence naming the new fields. They now describe the real response, and the exact string `{"ok":true,"tenants":["skincentrix"]}` survives, which Task A16's `tests/test_deploy_assets.py::test_deploy_runbook_carries_the_first_call_checklist` asserts.
6. **`calls` and `chats` in the usage rows are counted from `conversations`, not from `usage_events`.** The plan says usage aggregates come from `usage_events` grouped by day and unit, which is true of every other field; a call and a chat are conversations, not units, and counting them from usage rows would silently drop a call that recorded no usage. `ig_messages` is `ig_in + ig_out` from the units.
7. **`est_cost_cad` is computed from the raw unit totals, which include `stt_seconds`, a unit the day row does not expose.** The plan fixes the day's field list and `stt_seconds` is not in it, but leaving speech-to-text out of the cost would understate it. The day object keeps exactly the listed fields.
8. **`GET /internal/tenants/{id}/items?state=` is an exact match on one state, plus `all`.** The plan's enumeration is `open|acknowledged|resolved|all`, so "open" means `state = 'open'`. C4's Requests page wants open *and* acknowledged: ask for `state=all` and split client side, or make two calls. `GET /internal/tenants/{id}/health`'s `open_items` does count open + acknowledged, matching `PgLedger.list_open`.
9. **The conversations list applies a date filter only when `from` or `to` is given.** A silent 30-day cutoff on a list the owner is paging through would look like data loss. `usage` and `latency` do default to the last 30 tenant days, because both are charts of a period.
10. **`GET /internal/health`'s `queued_jobs` is the whole queued backlog, not only jobs already due, and `oldest_queued_age_s` is clamped at zero.** A queue depth that hides scheduled work is not a queue depth, and a negative age (jobs scheduled for the future) is not an age.
11. **Tests were derived from the task's Behaviour and Tests lists, not given verbatim** (this is a contract-level plan). Recorded red run before implementing: `uv run pytest tests/test_internal_api.py tests/test_contract_snapshot.py -q` -> `36 failed, 5 passed`, the five passing being the four "unknown id is 404" cases and one more that pass vacuously while the routes do not exist yet (a missing route is also a 404); every other test failed with `ModuleNotFoundError: spatalk.rates` or `assert 404 == 200`.

No conflict was found between the four reference documents and the task text. Two reference lines are worth flagging to the orchestrator, neither contradicting this task:

- `docs/reference/api-surface.md` says `GET /healthz` returns "ok, tenants, config versions, commit, queue and scheduler health" and marks the row `A14, E7`. Config versions and commit exist now; queue and scheduler health remain E7's half of the row.
- `docs/reference/tenant-config.md` says the portal's settings forms are generated from `GET /internal/schema/tenant-config`. The plan only mentions that endpoint in C4 ("added in C3 if not already"); it is implemented here, so C4 has nothing to add on the runtime side.

## Notes for neighbours

- **C4** generates `client.ts` from `docs/contracts/runtime-internal.openapi.json`. The wrapper must send `X-Internal-Key: RUNTIME_INTERNAL_KEY` and `X-Actor: <user email>`. A rejected config comes back as `422 {"detail": [{"loc": ["config", "hours"], "msg": …, "type": …}]}`, so a settings form maps an error to its field by dropping the leading `"config"` from `loc`. Query dates are `from` and `to` (`from` is a reserved word in Python; the runtime declares it by alias, so the wire name really is `from`).
- **C4** should call `PUT /internal/tenants/{id}/config` with the *whole* config object, not a patch: the version stored is exactly what was sent, and `GET …/config` returns what the form should be populated from.
- **C5**: `POST /internal/tenants/from-bundle` takes five file parts named `tenant`, `services`, `knowledge`, `scripts`, `guard` (their filenames are ignored) plus a `created_by` form field. An invalid bundle answers `422` with the loader's message at `loc = ["body", "bundle"]`. It creates a new version for an existing tenant rather than refusing, which is what re-uploading a corrected bundle should do.
- **C5**: `/admin/health` reads `GET /internal/health` and `GET /healthz`. `commit` is empty unless the image was built with `--build-arg GIT_COMMIT=$(git rev-parse HEAD)`; the deploy runbook step for that belongs to C9/E7.
- **C7**: the internal key is read from `Settings` on every request through `request.app.state.ctx.settings` and never logged; a wrong key produces `401 {"detail": "invalid internal key"}` with no echo of what was presented.
- **C8**: the drift check is `uv run pytest tests/test_contract_snapshot.py` on the runtime side; regenerate with `make openapi` (from `runtime/`). The rates copy has the same shape of check: `make sync-rates` after editing `docs/research/rates.json`.
- **E7**: extend the existing `/healthz` handler in `spatalk/http/app.py`; `settings.git_commit` and the Dockerfile's `ARG GIT_COMMIT` already exist, and `internal.config_versions(sf)` is reusable. `GET /internal/health` already reports `queued_jobs`, `oldest_queued_age_s` and `dead_jobs`, so the alert conditions can read one place.
- **E5** adds `conversations.stage_ms`; `GET /internal/tenants/{id}/latency` currently reads `latency_ms` only. Adding the per-stage p95 to that response is a contract change: regenerate the snapshot in the same commit.
