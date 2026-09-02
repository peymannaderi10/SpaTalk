# Portal end-to-end tests

Playwright against the portal running in development mode.

```
npm install                 # once, plus: npx playwright install chromium
npm run e2e                 # or, from portal/: npm run e2e
```

`playwright.config.ts` starts the app itself (`wasp start` in `../`), so the
things that must already be running are Postgres and the runtime, and the
portal's migrations must be applied (`wasp db migrate-dev` in `../`).

## The runtime

`client.spec.ts` covers the pages that show tenant, conversation, item and usage
data, and the portal stores none of that: it all comes from the runtime's
`/internal` API. So the suite needs a runtime, and `global-setup.ts` refuses to
start without one.

Before any test runs, `global-setup.ts`:

1. runs `runtime/../portal/e2e-tests/seed_runtime.py` with `uv` — one tenant
   (`skincentrix`, config version 1), four conversations, four tracked items and
   a day of usage — and writes the ids it created to `.seed.json`;
2. waits for `RUNTIME_INTERNAL_URL/healthz` to answer.

The seeding is destructive for the `skincentrix` tenant and only for it.

`admin.spec.ts` also writes to the runtime: the onboarding wizard imports the
Skincentrix bundle under the id `skincentrix-portal-e2e`, so that tenant appears
beside the seeded one and gains a configuration version on every run. It is
never `skincentrix`, whose version `client.spec.ts` asserts.

| variable | default | meaning |
|---|---|---|
| `RUNTIME_INTERNAL_URL` | `http://localhost:8000` | where the runtime is, for the tests and for the portal server the suite starts |
| `RUNTIME_INTERNAL_KEY` | `dummy-internal-key` | must equal the runtime's `INTERNAL_API_KEY` |
| `RUNTIME_DATABASE_URL` | `postgresql://spatalk:spatalk@localhost:5434/spatalk` | read directly, only to check what the runtime recorded (an audit row, an item's state); nothing in the portal itself connects to the `runtime` schema |
| `RUNTIME_SEED_COMMAND` | `uv run python ../portal/e2e-tests/seed_runtime.py` | override if `uv` is not how you run the runtime |

On Linux, one runtime is enough:

```
cd ../../runtime && INTERNAL_API_KEY=dummy-internal-key uv run spatalk serve --port 8000
```

### On Windows, with Wasp in WSL

Wasp and Playwright run inside WSL; the runtime's virtualenv is a Windows one,
because Wasp does not run on Windows and the runtime's dependencies are already
installed there. WSL cannot open a port on the Windows host (the firewall allows
Docker's published ports and nothing else), so the runtime is published back
through a container:

```
# Windows, from runtime\
INTERNAL_API_KEY=dummy-internal-key uv run spatalk serve --host 0.0.0.0 --port 8000

# Windows, once: publish it where WSL can see it
docker run -d --name spatalk-runtime-bridge -p 8010:8010 alpine/socat \
  TCP-LISTEN:8010,fork,reuseaddr TCP:host.docker.internal:8000

# WSL, from portal/e2e-tests
RUNTIME_INTERNAL_URL=http://localhost:8010 npx playwright test
```

`seedCommand()` in `tests/runtime.ts` falls back from `uv` to `uv.exe`, so the
seeding step reaches the Windows runtime from WSL without any of this.

## The mail sink

The suite exercises real email verification, so it needs the verification link.
The dev server runs with `PORTAL_EMAIL_PROVIDER=Dummy`, which makes Wasp print
every message it would have sent instead of sending it. The web-server command
pipes that output through `tee` into `mail-sink.log`, and `tests/utils.ts` reads
the link out of that file. No SMTP server and no third-party mail service is
involved.

`mail-sink.log` is deleted at the start of each run and is gitignored.

## System dependencies

Chromium needs `libnspr4` and `libnss3`. On Ubuntu, `npx playwright
install-deps chromium` installs them; the two packages can also be installed
directly with apt.
