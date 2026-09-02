# portal Task C9: Containerise the portal and route it through Caddy

Status: done with deviations
Commit: cf826fbcf9bc0d0ee37d752b059fd40d8589cbe8
Tests: `cd portal && npx vitest run -c vitest.server.config.ts src/ops/containers.server.test.ts` -> 22/22 (new); full portal suite -> 244/244 (`npm run test:unit` 108, `wasp test client run` 70, `cd e2e-tests && npx playwright test` 66) plus `wasp build` and `npx tsc -p tsconfig.src.json --noEmit` clean; runtime suite -> 464 passed, 1 skipped, `uv run ruff check spatalk tests scenarios` clean
Interfaces produced: `portal/Dockerfile.server`, `portal/Dockerfile.web`, `portal/.dockerignore`; Compose services `portal-server` and `portal-web` in `runtime/docker-compose.yml`; Caddy sites `{$APP_HOST}` -> `portal-web:80` and `{$APP_API_HOST}` -> `portal-server:3001`; env `APP_HOST`, `APP_API_HOST` (runtime `.env`), build arg `REACT_APP_API_URL=https://${APP_API_HOST}`; CI step `docker compose build portal-server portal-web`

## What the two images are

Both build the portal **from the committed source**: each runs `wasp install`
then `wasp build` in a builder stage, so a deploy stays `git pull && docker
compose up -d --build` and the VPS needs Docker and nothing else.

- `Dockerfile.server` — builder installs `@wasp.sh/wasp-cli@0.25.0`, runs
  `wasp install`, `wasp build`, then `npm run bundle` in `.wasp/out/server`. The
  production stage copies the workspace `node_modules`, the bundle, the server's
  `package.json` and `.wasp/out/db` (schema plus the committed migrations), sets
  `PORT=3001`, and starts with
  `npx prisma migrate deploy --schema=../db/schema.prisma && npm run start`.
- `Dockerfile.web` — same builder, then `npx vite build` with
  `REACT_APP_API_URL` as a build argument; the production stage is
  `caddy:2-alpine` with `/srv` = the built client and a five-line Caddyfile:
  `try_files {path} {path}/index.html /200.html` in front of `file_server`.

Neither publishes a port. The project's existing Caddy gained the two sites and
now depends on `app`, `portal-web` and `portal-server`.

## The failable check: it was built and it was run

```
cd runtime && APP_API_HOST=app-api.localhost docker compose build portal-server   # EXIT=0
cd runtime && APP_API_HOST=app-api.localhost docker compose build portal-web      # EXIT=0
docker compose up -d db portal-server portal-web caddy   (+ an override giving Caddy
    APP_HOST=app.localhost / APP_API_HOST=app-api.localhost and the server SMTP values)
```

`docker compose logs portal-server`:

```
Prisma schema loaded from ../db/schema.prisma
Datasource "db": PostgreSQL database "spatalk", schema "public" at "db:5432"
3 migrations found in prisma/migrations
No pending migrations to apply.
🚀 "Email and password" auth initialized
pg-boss started!
Server listening on port 3001
```

Through Caddy, with `--resolve` pointing both names at the host:

| request | result |
|---|---|
| `https://app.localhost/login` | 200 `text/html`, `<title>SpaTalk</title>` (the 1.3 KB SPA shell) |
| `https://app.localhost/privacy` | 200, the 14.5 KB **prerendered** page containing "Privacy policy" |
| `https://app.localhost/app/skincentrix/overview` | 200, byte-identical to the shell — the SPA fallback works for deep links |
| `https://app.localhost/robots.txt` | 200 — static assets are served, not swallowed by the fallback |
| `https://app-api.localhost/auth/me` | 200 `{"json":null}` — the Wasp server, signed out |

The build argument really reaches the bundle: rebuilt with
`APP_API_HOST=app-api.example.com` (the value CI uses),
`grep -rl app-api.example.com /srv/assets` finds `assets/operations-*.js`. It
could not be otherwise — Wasp's client env schema fails the build when
`REACT_APP_API_URL` is absent or not a URL.

The containers were stopped and removed afterwards; only the `db` service was
left running, as it was before.

## The tests

`portal/src/ops/containers.server.test.ts`, 22 tests under `npm run test:unit`,
named after the task's behaviours. They read the two Dockerfiles, the
`.dockerignore`, `docker-compose.yml`, the `Caddyfile`, `runtime/.env.example`,
the CI workflow and the deploy runbook from disk; comment lines are stripped
from the Dockerfiles first, so a comment cannot satisfy a test. Seen failing
first, with none of the files written: **21 failed, 1 passed** (the one that
passed asserts the runtime's two existing Caddy sites are left alone).

They cover: `wasp build` in a builder stage at the pinned CLI version; the
bundle and `npm run start` from the generated server directory; `prisma migrate
deploy` and the absence of `migrate-dev`, `migrate reset` and `db push`; port
3001; no dotenv file copied into either image and none in the build context; the
API host as a build argument compiled into the client; the Caddy static site
with its SPA fallback and port 80; both Compose services' context, dockerfile,
`env_file`, `db:5432` override, health-gated `depends_on`, restart policy and
absence of published ports; the four Caddy sites; the two new environment
variables in `.env.example`; the CI step; and the runbook's hosts, migration
sentence and Stripe/Google URLs.

`runtime/tests/test_deploy_assets.py` (Task 16's) had to grow with the file it
guards: it asserted `set(services) == {"db", "app", "caddy"}` and
`caddy["depends_on"] == ["app"]`. Both now name the portal's containers, and the
Caddyfile test asserts the two new sites and the two new `.env.example` keys.

## Deviations

- **Wasp 0.25 has no `.wasp/build`.** The plan says `portal/Dockerfile.server`
  comes "from Wasp's generated `.wasp/build/Dockerfile`". `wasp build` in 0.25
  prints "Check it out in the .wasp/out/ directory" and `ls .wasp/build` ->
  "No such file or directory"; the generated Dockerfile is
  `portal/.wasp/out/Dockerfile` and its build context is `.wasp/out`. The
  production stage here follows that file step for step (same COPY list, same
  `mkdir -p .wasp/out/server/node_modules` before it), but the builder differs,
  below.
- **The images build the app themselves instead of taking `.wasp/out` as the
  build context.** Wasp's generated Dockerfile assumes someone has already run
  `wasp build` on the machine, which would put the Wasp CLI, Node and a
  successful build on the VPS before Docker ever starts — and `.wasp/` is
  gitignored, so a fresh clone has nothing to give Docker. Building inside the
  image keeps the deploy runbook's `git pull && docker compose up -d --build`
  honest. The cost is that `wasp build` runs in both images (they are separate
  Dockerfiles, as the plan's Files list has them), so a cold build of the pair
  takes about ten minutes; Docker's layer cache makes the second one seconds.
- **`wasp install` is required before `wasp build` on a clean checkout.** The
  first image build failed at `RUN wasp build` with "Missing or stale
  dependencies in project: Your project dependencies are out of date. Run `wasp
  install` to fix this." It never appears on a developer machine because `wasp
  start` has already done it. Both Dockerfiles now run it.
- **`wasp build` does not build the client in 0.25.** `.wasp/out/web-app` is
  empty after it; the client is a Vite build of the project itself
  (`npx vite build`), which Wasp's plugin forces into `.wasp/out/web-app/build`.
  Evidence: `find .wasp/out/web-app/build` after the build lists `200.html`,
  `assets/`, `privacy/index.html`, `pricing/index.html` and the `public/` files —
  and **no `index.html`**. The SPA shell is `200.html`
  (`spaFallbackFile: "200.html"` in `sdk/wasp/dist/client/vite/plugins/wasp.js`),
  which is why the web image's `try_files` ends in `/200.html` rather than
  `/index.html`; `/privacy` and `/pricing` are prerendered
  (`ssrPaths: ['/privacy', '/pricing']`) and are served by the `{path}` and
  `{path}/index.html` arms.
- **The start command spells out the migration instead of calling Wasp's
  `npm run start-production`.** They are the same two commands
  (`db-migrate-prod` = `prisma migrate deploy --schema=../db/schema.prisma`,
  then `start`); writing them out keeps the plan's behaviour visible in the file
  and assertable from a test.
- **Debian, not Wasp's Alpine.** `@wasp.sh/wasp-cli@0.25.0`'s optional
  dependencies are `linux-x64-musl`, `linux-x64-glibc` and `linux-arm64-glibc`:
  there is no arm64 musl build, so an Alpine builder would be x64-only. Both
  stages are `node:24.14.1-bookworm-slim` (the patch is pinned because Wasp's
  generated server declares `engines: { node: ">=24.14.1" }` with
  `engineStrict`), plus `openssl` for Prisma's engines.
- **Four files beyond the task's Files list.** `portal/.dockerignore` (without
  it the build context is the host's `node_modules` and `.wasp`, and `.env.server`
  would land in a layer); `portal/src/ops/containers.server.test.ts` (the task
  lists no test file, and CLAUDE.md's definition of done requires tests that were
  seen failing); `runtime/.env.example` (`APP_HOST` and `APP_API_HOST`, which
  Caddy reads through `env_file` — the accounts runbook already told the founder
  to set them); `.github/workflows/ci.yml` (the task's own test is "`docker
  compose build portal-server portal-web` succeeds in CI", and Task C8's report
  asked for it as a step of the `portal` job).
- **`runtime/tests/test_deploy_assets.py` is a runtime-plan file** (Task 16) and
  had to change: its exhaustive `set(services)` assertion fails the moment this
  task adds a service. Extended, not loosened.
- **The `docker compose up` check needed an override for SMTP.** The image is
  built with the SMTP email provider (Wasp bakes the provider in and refuses
  Dummy for a production build, Task C1's finding), so it validates
  `SMTP_HOST/PORT/USERNAME/PASSWORD` at start — and this machine's
  `portal/.env.server` runs the Dummy provider and has none of them. The server
  exited naming the four variables. That is correct behaviour, not a defect, so
  the fix went into the runbook: step 1 of "The portal" now says the SMTP block
  must be filled even though a development `.env.server` can leave it out.

## Notes for neighbours

- **A trap in `runtime/.env`, found while running the suites, unrelated to this
  task but worth someone's morning.** A key whose value is empty followed by an
  inline comment ends up *holding the comment*: with the machine's `.env` copied
  from `.env.example`, `Settings().edge_shared_key` is
  `'# shared with the Cloudflare SMS worker'` and `turnstile_secret_key` is
  `'# set to make /chat/ws challenge; empty = no challenge'`. Non-empty values
  make the widget demand an edge key or a Turnstile token, so
  `uv run pytest -q` reported **13 failures, all in `tests/test_widget.py`**, on
  this machine before and after this task. With those two cleared the suite is
  `464 passed, 1 skipped`. In production this would silently set a shared secret
  to a sentence. Keys with a real value are unaffected (`llm_model` reads
  `gemini-2.5-flash`), and Compose strips the comment when there is a value, so
  `APP_HOST` and `APP_API_HOST` reach Caddy clean — verified by running a probe
  container with `env_file` pointed at `.env.example`:
  `app.example.com`, `app-api.example.com`, `api.example.com`.
- **Changing `APP_API_HOST` means rebuilding `portal-web`.** The URL is compiled
  into the bundle. `docker compose build --no-cache portal-web` is in the
  runbook's troubleshooting list.
- **CI**: the `portal` job now builds both images after `wasp build`, with
  `APP_API_HOST: app-api.example.com`. It adds a cold Docker build (order of
  minutes) to that job; nothing else in the job depends on it, so it can be
  moved to a job of its own if the wall clock becomes the problem.
- **Operations plan, Task E2** rebuilds the `db` service from
  `runtime/scripts/db`. That is a different service; nothing here touches it.
  The Compose file now has five services, and `test_deploy_assets.py` asserts
  the exact set — E2 will not need to change that, but anything adding a sixth
  service will.
- The portal reaches the runtime inside the Compose network as
  `RUNTIME_INTERNAL_URL=http://app:8000` (already in `accounts-and-env.md`).
  `portal-server` deliberately does **not** `depends_on: app`: it would force a
  three-gigabyte runtime image build on anyone who only wants the portal up, and
  a runtime that is not answering is a friendly error in the portal already
  (Task C7).
