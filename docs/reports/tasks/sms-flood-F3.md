# sms-flood-guard Task F3: the edge worker follows the same rules

Status: done with deviations
Engineer: the orchestrating assistant (inline)
Plan: `docs/superpowers/plans/2026-09-02-sms-flood-guard-plan.md`

## What changed

- `edge/sms-worker/src/index.ts`: the offline auto-reply now goes out at most once per sender per hour (`replied:sender:<E.164>` in `PENDING`, TTL 3600 s) on top of once per message id, and never to a number under a `blocked:<E.164>` key in `TENANT_TEXTS`. Every event is still queued for replay either way. New `PUT /admin/blocked-numbers` (edge key, body `{numbers: [E.164, ...]}`) replaces the block list: it writes the keys given and prunes the rest.
- `runtime/spatalk/cli.py`: `collect_blocked_numbers` (permanent blocks across tenants; mutes excluded) and `sync_blocked_numbers` (pushed even when empty, so the worker prunes). `spatalk edge sync-texts` pushes both the offline wording and the block list, and its `--dry-run` prints both.
- Docs: `accounts-and-env.md` edge step notes the block list and when to re-run the sync; `api-surface.md` names the new admin route.

## Tests

- `edge/sms-worker/test/index.test.ts`: six new tests. With the worker change stashed they failed (5 failed, 24 passed; the sixth, the 401, passes without it because the route falls to the 404 branch); with it, 29 passed. Three texts from one sender during an outage produce one reply and three queued events; a second sender gets its own; a blocked sender gets none and is still queued; the admin route rejects a wrong key, writes and prunes, and refuses non-E.164 bodies.
- `runtime/tests/test_edge_sync.py`: two new tests, only permanent blocks are collected; the push goes to `/admin/blocked-numbers` with the edge key even when the list is empty. 18 passed in the file with `test_sms_blocks_api.py`.

## Deviations

- The block list travels on its own admin route, `PUT /admin/blocked-numbers`, rather than as a `blocked` key inside the tenant-texts payload the plan described. That payload is a map keyed by phone number, so a `blocked` entry would have been parsed as a number; a second route keeps both shapes strict.
- The per-sender key is claimed together with the per-message key before sending, so a Telnyx retry of the same message within the hour is suppressed twice over; after the hour a redelivery could earn a second reply. Telnyx retries within minutes, so this was left simple.

## Notes for neighbours

- Blocking a number in the portal does not reach the worker until `spatalk edge sync-texts` runs; the runbook says so. A scheduled sync from the runtime is a small follow-up if it matters.
- The worker's own tests run with `npm test` in `edge/sms-worker`; `tsc --noEmit` is clean.
