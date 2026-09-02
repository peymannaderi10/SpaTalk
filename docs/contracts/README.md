# Contracts

The seam between the two codebases. `runtime-internal.openapi.json` is the runtime's
`/internal/*` API as an OpenAPI 3.1 document, and it is the **only** description of that
API the portal is allowed to know. The portal's `portal/src/runtime/client.ts` is generated
from it and never edited; every call the portal makes goes through
`portal/src/runtime/api.ts`, which wraps that client with `X-Internal-Key` and `X-Actor`.

Nothing else crosses. The runtime owns the Postgres schema `runtime`, the portal owns
`public`, and no table is shared (CLAUDE.md non-negotiable 7).

## The file

| | |
|---|---|
| `runtime-internal.openapi.json` | every `/internal` path, its parameters, its request and response schemas |
| written by | `runtime/spatalk/http/internal.py`, through `spatalk openapi --internal` |
| read by | `openapi-typescript`, which writes `portal/src/runtime/client.ts` |

It is filtered to `/internal` on purpose: `/healthz`, the provider webhooks and the widget
are not part of the portal's contract and must not appear here.

## Changing it

A contract change is a deliberate commit, in both directions. Neither file is generated at
build time and neither is gitignored, so a change to the runtime's routes that nobody
regenerated, or a client regenerated from a contract nobody committed, fails CI.

Change the runtime's `/internal` routes, then, from `runtime/`:

```
make openapi          # rewrites ../docs/contracts/runtime-internal.openapi.json
uv run pytest tests/test_contract_snapshot.py
```

Then regenerate the portal's client, from `portal/`:

```
npm run gen:client    # rewrites src/runtime/client.ts from the contract
npm run check:client  # what CI runs: regenerates into a temp file and diffs
```

Commit the contract, the client and the code that changed together. If a route the portal
already calls changed shape, `npx tsc -p tsconfig.src.json --noEmit` in `portal/` is what
tells you which call sites the change broke.

## Where the drift is caught

Two checks, one per direction, in `.github/workflows/ci.yml`:

| direction | check | job |
|---|---|---|
| runtime routes → contract | `runtime/tests/test_contract_snapshot.py`, run by `uv run pytest` | `test` |
| contract → generated client | `npm run check:client` in `portal/` | `portal` |

`portal/src/ci/workflow.server.test.ts` also compares the paths, operations and schemas the
two files declare, so the second direction is caught by `npm run test:unit` offline, without
the generator, before CI sees it.

## Related generated copies

`runtime/spatalk/rates.json` is the same idea for prices: a copy of `docs/research/rates.json`
taken into the package so the deployed runtime carries its own rates. `make sync-rates` from
`runtime/` refreshes it and `runtime/tests/test_internal_api.py` fails when the two drift.
