# sms-flood-guard Task F2: block list management: CLI, internal API, portal

Status: done with deviations
Engineer: the orchestrating assistant (inline)
Plan: `docs/superpowers/plans/2026-09-02-sms-flood-guard-plan.md`

## What changed

- `runtime/spatalk/http/internal.py`: `GET /internal/tenants/{id}/sms-blocks`, `POST` (body `{phone, actor}`; 409 for a staff number, 422 unless E.164), `DELETE /internal/tenants/{id}/sms-blocks/{phone}?actor=` (404 when absent). Audit rows `sms.block` / `sms.unblock` with the portal actor. `TenantHealth` gains `sms_muted_numbers`, `sms_blocked_numbers`, `sms_replies_today`.
- `runtime/spatalk/cli.py`: `spatalk sms block|unblock|blocks <tenant> [<number>]`. The work lives in `sms_block_work`, `sms_unblock_work`, `sms_blocks_work` (async, return exit code and text) so tests drive them on the test loop; the typer commands validate E.164 and print.
- `docs/contracts/runtime-internal.openapi.json` regenerated; `portal/src/runtime/client.ts` regenerated from it.
- Portal: `getTenantSettings` returns `blocks`; actions `blockSmsNumber` and `unblockSmsNumber` (member access through `session()`, actor carried to the runtime); `NumbersTab` gains the "Blocked and muted numbers" panel with the carrier-fee copy, an add form that normalises "905 555 0188" to E.164, and Unblock; the transcript drawer on an SMS conversation gains "Block this number". `formatting.blockStateLabel` with three unit tests. Playwright spec `e2e-tests/tests/sms-blocks.spec.ts`.
- Docs: `api-surface.md` route row; `accounts-and-env.md` Telnyx blocklist check (the plan filed it under F3; it belongs with the founder's Telnyx steps).

## Tests

- `runtime/tests/test_sms_blocks_api.py`, 6 tests, seen failing before the implementation (5 failed, then the CLI test rewritten and re-seen): list, add, staff 409, 422, audit rows; remove a mute, 404 on the second delete, audit; health counts (one live mute, one expired, one permanent block, two replies today and one yesterday); 401 without the key; the CLI work functions; the typer wiring and the E.164 check.
- `tests/test_contract_snapshot.py` and `tests/test_internal_api.py`: 41 passed after regeneration.
- Portal: `wasp build` succeeds in WSL; `npm run test:unit` 108 passed; `wasp test client run` 73 passed (70 before, the three `blockStateLabel` tests are new).
- **Not run:** the Playwright spec. It needs the full stack (runtime seeded by `global-setup.py`, portal server, Stripe webhook helper) that QA gate C ran with `RUNTIME_SEED_COMMAND` set; the spec follows `client.spec.ts` line for line and should be run at the next gate.

## Deviations

- `DELETE` takes the actor as a query parameter, not a body. The plan said body; a body on DELETE is awkward in openapi-fetch and some proxies, and the `X-Actor` header still wins through `portal_actor`.
- The CLI test drives the async work functions rather than `CliRunner` against the database: typer's `asyncio.run` opens its own loop and asyncpg connections from the test loop cannot be reused there. The commands themselves are exercised by `CliRunner` for `--help` and the E.164 refusal.
- Blocking is open to any organisation member, not owners only. A staff member answering texts is exactly who meets a spammer first; the runtime audits who did it and the owner can undo it.

## Notes for neighbours

- F3 syncs only permanent blocks (`until` null) to the edge worker: `list_blocks` and filter in the CLI's `edge sync-texts`.
- The portal reads `sms_muted_numbers` and friends from health but does not yet show them; the agency health page can pick them up.
