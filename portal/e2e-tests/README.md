# Portal end-to-end tests

Playwright against the portal running in development mode.

```
npm install                 # once, plus: npx playwright install chromium
npm run e2e                 # or, from portal/: npm run e2e
```

`playwright.config.ts` starts the app itself (`wasp start` in `../`), so the
only thing that must already be running is Postgres, and the portal's
migrations must be applied (`wasp db migrate-dev` in `../`).

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
