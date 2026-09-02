# portal Task C8: Portal CI and contract drift check

Status: done with deviations
Commit: <filled in below>
Tests: `cd portal && npm run test:unit` -> 86/86 (15 new, all in `src/ci/workflow.server.test.ts`); full portal suite -> 222/222 (`npm run test:unit` 86, `wasp test client run` 70, `cd e2e-tests && npx playwright test` 66) plus `wasp build` and `npx tsc -p tsconfig.src.json --noEmit` clean; `cd runtime && uv run pytest tests/test_contract_snapshot.py -q` -> 5/5
Interfaces produced: `npm run check:client` (portal/package.json); job `portal` in `.github/workflows/ci.yml`; `docs/contracts/README.md`; `portal/src/ci/workflow.server.test.ts`

## What the job does

`.github/workflows/ci.yml` gains a third job, `portal`, beside `test` (runtime) and `edge`.
It is one Postgres, one runtime and one portal, in this order:

1. Node 24, `uv`, and `@wasp.sh/wasp-cli@0.25.0` (the version Task C1 built the app with).
2. **Contract drift** — `npm run check:client` in `portal/`, first, because it is the cheapest
   thing in the job and needs nothing built.
3. `uv venv --python 3.12 && uv pip install -e ".[dev]"`, then `uv run alembic upgrade head`
   against the service Postgres: the `runtime` schema.
4. The runtime itself: `uv run spatalk serve --host 127.0.0.1 --port 8000` in the background,
   with the step polling `/healthz` for up to sixty seconds and printing `runtime-serve.log`
   if it never answers.
5. `wasp db migrate-dev` for the portal's `public` schema, then `wasp build`.
6. The rest of the portal's suite: `npx tsc -p tsconfig.src.json --noEmit`, `npm run test:unit`,
   `wasp test client run`.
7. `npm ci` and `npx playwright install --with-deps chromium` in `portal/e2e-tests`, then
   `npx playwright test`. Playwright's `globalSetup` seeds the tenant and its fixtures and
   `playwright.config.ts` starts `wasp start` itself, so the job adds no seeding step of its own.
8. On failure, the Playwright report, the test results, `mail-sink.log` and the runtime's log
   are uploaded as an artifact.

One database, two schemas, as Task C1's spike settled: `POSTGRES_DB: spatalk`, Alembic owns
`runtime`, Prisma owns `public`, PgBoss owns `pgboss`, and no table is shared.

Three details are worth naming because they are the parts that would silently misbehave:

- **Two drivers, one database.** The job's `DATABASE_URL` is Prisma's
  (`postgresql://…/spatalk`). The runtime's steps override it at step level with
  `postgresql+asyncpg://…/spatalk`. The seeding script is a *runtime* script started by the
  *Playwright* process, so it would inherit Prisma's URL and fail on the driver; the job sets
  `RUNTIME_SEED_COMMAND` (a hook `tests/runtime.ts` already had) to
  `env DATABASE_URL=postgresql+asyncpg://… uv run python ../portal/e2e-tests/seed_runtime.py`
  instead. Verified by running exactly that form against the local database:
  `cd runtime && env DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk uv run python ../portal/e2e-tests/seed_runtime.py`
  -> `{"tenant": "skincentrix", "config_version": 1, …}`.
- **One key, two names.** `RUNTIME_INTERNAL_KEY` (what the portal presents) and
  `INTERNAL_API_KEY` (what the runtime accepts) are both `ci-internal-key`; a test asserts they
  are the same string, because the failure when they are not is a 401 inside a page.
- **`PORTAL_EMAIL_PROVIDER` is never set in the job.** Wasp bakes the email provider in at
  compile time and refuses the Dummy one for a production build (Task C1's note), while the
  end-to-end server needs Dummy to print the verification links. `playwright.config.ts` pins
  Dummy for the server *it* starts, so the job must not pin it globally. A test asserts the
  job never assigns that variable.

## The drift check, and the drift it found

`npm run check:client` regenerates the client from the committed contract into
`node_modules/.cache/runtime-client.ts` and `diff -u`s it against `src/runtime/client.ts`,
printing what to run when they differ. It never writes `src/runtime/client.ts`, so a failed
check leaves the working tree clean — the check reports drift, it does not silently fix it.

The other direction was already covered: `runtime/tests/test_contract_snapshot.py` fails when
the runtime's `/internal` routes and `docs/contracts/runtime-internal.openapi.json` disagree,
and the `test` job runs the whole runtime suite. `docs/contracts/README.md` is new and states
both directions, both regeneration commands (`make openapi` from `runtime/`, `npm run gen:client`
from `portal/`) and the rule that a contract change is a deliberate commit.

**The check found real drift on its first run.** The instagram plan's Task D3 added
`POST /internal/tenants/{tenant_id}/integrations/messenger/select` to the contract and
deliberately left the portal's client stale for D4 to regenerate (D3's report, "D4 must
regenerate the contract and the client anyway"). `npm run check:client` failed with that path,
its operation and the `MessengerPageSelectIn` / `MessengerPageSelected` schemas as the diff. The
client was regenerated in this commit — which is the deliberate commit the plan asks for — and
`npx tsc -p tsconfig.src.json --noEmit` stayed clean, so nothing the portal calls changed shape.

## What the tests assert

`portal/src/ci/workflow.server.test.ts`, 15 tests under `npm run test:unit`, named after the
task's behaviours. They read the workflow, `portal/package.json`, the contract, the generated
client and `docs/contracts/README.md` from disk; nothing is mocked.

- *the portal CI job*: starts a Postgres the runtime and the portal share; runs the runtime with
  `uv` on port 8000 (venv, `alembic upgrade head`, `spatalk serve --port 8000`, a `/healthz`
  wait); seeds a tenant into it with the async driver; builds the portal; runs Playwright with
  `RUNTIME_INTERNAL_URL` pointing at that runtime and `INTERNAL_API_KEY` equal to
  `RUNTIME_INTERNAL_KEY`; runs the rest of the portal's suite; never pins the Dummy email
  provider.
- *the contract drift check*: it is a step of its own; `check:client` regenerates from the
  committed contract, compares, and never overwrites `src/runtime/client.ts`; `gen:client` and
  `check:client` pin the same generator version and read the same contract file; the other
  direction is covered by the runtime job's pytest; `docs/contracts/README.md` names both
  commands.
- *the committed runtime client*: it declares exactly the paths, exactly the operations and
  exactly the schemas the committed contract declares. This is the drift check again, offline —
  it needs no generator and no network, so `npm run test:unit` catches a stale client before CI
  ever sees it. These three were the tests that failed on the D3 drift (17 contract paths against
  16 in the client, 20 operations against 19, 25 schemas against 23).

Seen failing first: with no `portal` job, no `check:client` script, no `docs/contracts/README.md`
and the stale client, `npm run test:unit` reported `14 failed | 72 passed`.

## Deviations

- **A test file the plan does not list** (`portal/src/ci/workflow.server.test.ts`), because the
  task's only stated "Done when" is "CI green on a clean push" and this repository has no git
  remote (`git remote -v` prints nothing), so no workflow run can be observed from here. The
  behaviours are asserted against the files instead, and every command the job runs was run
  locally. This is the honest limit of this task: **the workflow has not been executed by GitHub
  Actions.** What was executed: the drift check (both failing and passing), the seed command in
  its `env`-prefixed CI form, `wasp db migrate-dev`'s already-applied state, `wasp build`,
  `npx tsc --noEmit`, `npm run test:unit`, `wasp test client run` and the full Playwright suite
  against a live runtime.
- **`portal/src/runtime/client.ts` regenerated**, which is a Task C4 file. Unavoidable: it was
  drifted from the contract (above) and the check whose whole purpose is to fail on that would
  have failed on a clean checkout. Regenerated with the committed `npm run gen:client`, not by
  hand.
- **The job runs five commands, not two.** The behaviour says "builds the portal, runs Playwright
  against both"; the job also runs `tsc --noEmit`, `npm run test:unit` and `wasp test client run`,
  which are the rest of the portal's suite (C4's, C6's and C7's reports all call it five
  commands) and which CLAUDE.md's definition of done requires to pass.
- **`check:client` diffs into `node_modules/.cache/`** rather than regenerating in place and
  using `git diff --exit-code portal/src/runtime/client.ts`, which is what C4's note suggested.
  Same check, but a failing run leaves the working tree untouched and needs no git.
- **`.github/workflows/ci.yml` is shared with the operations plan.** Only a new job was appended;
  the `test` and `edge` jobs are byte-for-byte unchanged.
- **`portal/package-lock.json` was restored, not committed**, exactly as Task C6 recorded: running
  the end-to-end suite regenerates the Wasp SDK workspace with the Dummy email provider, which
  drops `nodemailer` from the lock, and `wasp build` with SMTP puts it back. The job's ordering
  (build before end-to-end, and no `npm ci` at `portal/` at all — Wasp installs the workspace
  itself) means CI never trips over that oscillation.

## Notes for neighbours

- **D4 (and anything else touching `/internal`)**: the contract and the client are now in step
  through the messenger selection endpoint. From here a contract change is two commands in one
  commit — `make openapi` from `runtime/`, `npm run gen:client` from `portal/` — or the `portal`
  job fails, and so does `npm run test:unit` locally before that.
- **C9**: the portal job builds with `wasp build`; C9's own done-criterion
  (`docker compose build portal-server portal-web`) is not in it. Add that as a step of the
  `portal` job after `wasp build`, where `.wasp/build/` already exists.
- **E-series / operations**: the workflow now has three jobs. The `portal` job leaves a runtime
  running in the background for the rest of the job; anything appended to it can use
  `http://localhost:8000` with `X-Internal-Key: ci-internal-key`. The job needs no secrets, so it
  runs on forks.
- **Anyone adding a limited endpoint**: the whole job runs from one address, so the portal's rate
  limit budget (ten a minute per address per endpoint, refunded on success) is shared by every
  spec in the same minute. C7's report has the detail.
- The seeding hook `RUNTIME_SEED_COMMAND` is split on spaces by `tests/runtime.ts`, which is why
  the CI value is an `env …` prefix and not a shell string with quotes.
