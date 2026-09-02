# portal Task C7: Security and audit hardening

Status: done with deviations
Commit: <filled in below>
Tests: `cd portal && npm run test:unit` -> 71/71 (45 of them new here); `cd portal/e2e-tests && RUNTIME_INTERNAL_URL=… npx playwright test tests/security.spec.ts` -> 9/9; full portal suite -> 207/207 (`npx playwright test` 66, `wasp test client run` 70, `npm run test:unit` 71), green twice in a row, plus `wasp build` and `npx tsc -p tsconfig.src.json --noEmit` clean

Interfaces produced:
`portal/src/server/security.ts` — `contentSecurityPolicy({connectOrigins})`, `SECURITY_HEADERS`,
`securityHeaders(headers?)`, `STRIPE_SCRIPT_ORIGIN`, `STRIPE_API_ORIGIN`, `STRIPE_FRAME_ORIGINS`,
`STRIPE_IMAGE_ORIGIN`, `RATE_LIMIT_MAX_REQUESTS`, `RATE_LIMIT_WINDOW_MS`, `RATE_LIMITED_PATHS`,
`ALWAYS_COUNTED_PATHS`, `isRateLimitedPath`, `countsWhenItSucceeds`, `requestPath`, `clientIpOf`,
`createRateLimiter(options?)`, types `RateLimiter`/`RateLimiterOptions`/`ContentSecurityPolicyOptions`/
`LogScrubbingOptions`, `REDACTED`, `SECRET_MIN_LENGTH`, `registerSecret`, `registeredSecrets`,
`__resetRegisteredSecrets`, `scrubSecrets`, `scrubLogArgument`, `installLogScrubbing`,
`ACCESS_LOG_MIDDLEWARE`, `portalMiddleware`;
`portal/src/server/setup.ts` — `serverSetup` (Wasp `ServerSetupFn`);
`portal/src/runtime/api.ts` — `runtime(actorEmail: string)` (the actor is now required),
`__resetRuntimeCredentials()`; `main.wasp.ts` `server.setupFn` and `server.middlewareConfigFn`.

## What the tests assert

Server-side unit (`npm run test:unit`, 45 new across two files):

`src/server/security.server.test.ts` (35) —
- the headers: the policy names this origin and Stripe and holds no wildcard and no
  `'unsafe-eval'`; the app may not be framed by anyone (`frame-ancestors 'none'` and
  `X-Frame-Options: DENY`); HSTS is a year with subdomains; `nosniff`, `no-referrer` and
  no `X-Powered-By`; the request is passed on; and a caller can add the API origin a
  browser may reach without widening the table the server itself ships;
- the limit: the eight endpoints that are limited and the five that are not (Stripe's
  webhook among them); ten a minute through and the eleventh refused with a sentence, no
  stack and a `Retry-After`; one address running out does not lock out another, nor does
  running out of logins close the invitation page; the window is forgiven after a minute;
  an unlimited path is never counted; the path is read from `originalUrl`, because express
  strips the mount point; a password typed *correctly* is not held against the person
  while a refused one is, a good login does not buy back a refused guess, and sending a
  password-reset email or an invitation counts either way; a burst of guesses whose
  answers are still pending cannot slip through;
- the middleware Wasp is handed: helmet replaced, headers first, the limiter immediately
  after the access log, and every one of Wasp's own entries kept;
- the scrubbing: a secret in a line, inside a serialised object, or carried by an error is
  replaced; a line with no secret is untouched; a value shorter than eight characters is
  never treated as a secret; a circular object does not break logging; uninstalling puts
  the console back.

`src/runtime/api.server.test.ts` (10) — the key is read from the environment once however
many calls are made and is presented only to the runtime; every call carries `X-Actor`; a
call that cannot name anybody is refused before any request is made, and the refusal does
not mention the key; a failing call reaches the page as a sentence with no stack, no status
line and none of the runtime's error text, carries the key nowhere on the error, and is
logged without it; a connection that was never made is still a sentence; and a refused
configuration still names the field that was wrong.

End to end (`e2e-tests/tests/security.spec.ts`, 9) — `/` and `/auth/me` refuse to be framed;
the policy allows this origin and Stripe and nothing else; HSTS and `nosniff` and
`no-referrer` are there; the server does not name itself; a signed-out operation call (401)
still carries the headers; an eleventh guess at a password-reset token in a minute is
refused 429 with a `Retry-After` and a sentence, while logging in is unaffected; and the
shared key appears nowhere in the server's whole log for the run, including the line written
when a real runtime call fails (an organisation is pointed at a tenant the runtime has never
heard of, and the agency tenants table is asked for).

## Red before green

`npm run test:unit` before implementing: `Error: Cannot find module './security'` for the
whole `security.server.test.ts` file, and `10 failed | 26 passed` overall, the ten being
every test in `api.server.test.ts` (`TypeError: __resetRuntimeCredentials is not a function`).

Two real things came out of running it green afterwards, both recorded as deviations below:
the refusals were invisible in the access log (the limiter had been placed before morgan),
and the suite's own successful logins exceeded ten a minute from one address, which is what
turned the "count every attempt" reading of the limit into "count the refused ones".

## Deviations

1. **There is no session cookie to make `Secure` or `SameSite=Lax`.** Wasp 0.25 does not use
   cookies for sessions at all: the session token travels in an `Authorization` header and
   is kept in `localStorage`. Evidence: `.wasp/out/sdk/wasp/auth/lucia.ts` — *"We are not
   using cookies for session management. Instead, we are using the Authorization header to
   send the session token"*, with the `sessionCookie` block commented out; and
   `.wasp/out/sdk/wasp/core/storage.ts`, which is `localStorage` behind a `wasp:` prefix
   (`tests/utils.ts` already reads `wasp:sessionId` from it). So that behaviour of the task
   cannot be implemented and nothing was faked in its place. What the same threat asks for
   instead is here: `frame-ancestors 'none'` (the clickjacking half of `SameSite`) and HSTS
   (the plaintext half of `Secure`). **For the orchestrator:** if cookie sessions matter,
   that is a Wasp-level change, not a portal one.
2. **`portal/src/server/setup.ts` is a file beyond the task's list.** The task names
   `security.ts`, `main.wasp.ts` and `runtime/api.ts`. Registering the secrets and setting
   express's `trust proxy` needs `wasp/server`'s `env` and the `app`, and putting that
   inside `security.ts` would have made the whole security module unimportable without
   mocking Wasp. `security.ts` is therefore pure — its only Wasp import is an erased
   `import type` — and `setup.ts` is the twelve lines that read the environment.
3. **The limit counts *refused* attempts on the endpoints where a success proves the caller
   is not guessing**, and every attempt on the two that send an email
   (`request-password-reset`, `invite-member`). The plan says "10 per minute per IP" without
   qualification. Counting successes on login would lock a clinic's front desk out of its own
   portal — five staff behind one office address share one bucket — while slowing an attacker
   by not a single guess, which is why OWASP's guidance is to throttle *failed* authentication.
   It is also not theoretical: with every attempt counted, the existing suite locked itself
   out. Evidence, from that run's server log:
   `POST /auth/email/login 200` ×16 then `POST /auth/email/login 429 0.111 ms - 101`, and the
   test that followed failed with `No verification email for admin@spatalk.test appeared …`
   because `signInOrSignUp` fell through to signing up an account that already existed.
   The counting is `ALWAYS_COUNTED_PATHS` in `src/server/security.ts` with the reasoning in a
   comment; the attempt is counted first and refunded only once a `< 400` answer has been
   written, so a burst whose answers are still pending cannot slip through (there is a test
   for exactly that).
4. **The headers are the Wasp *server's*; the client host still owes the same table.** In
   production the documents come from Caddy (`app.<domain>`), not from the Wasp server
   (`app-api.<domain>`), and in development they come from Vite. A CSP written for the API
   origin cannot know the client's, so `contentSecurityPolicy({ connectOrigins })` takes it
   and `SECURITY_HEADERS` is exported as data. **C9 must send that table from Caddy for the
   client host, with `connect-src` extended to `WASP_SERVER_URL`**, or the browser gets the
   protection on the JSON API and not on the pages.
5. **helmet is removed rather than configured.** Wasp's default entry is `helmet()`, whose
   defaults allow same-origin framing and describe a policy that knows nothing about Stripe.
   `portalMiddleware` deletes it and sets the explicit table instead — no new dependency, and
   the exact headers are readable in one place and asserted by name.
6. **The limiter sits immediately after Wasp's `logger`, not at the very front.** Placed
   first, a refusal short-circuits before morgan and a brute-force attempt leaves no trace:
   the first green run answered 429 twice with nothing in the access log. It is now
   `securityHeaders` → cors → logger → `rateLimit` → the body parsers, so the headers are on
   every answer including the refusal, and the refusal is logged
   (`POST /auth/email/reset-password 429 0.076 ms - 101`).
7. **`runtime(actor)` now requires the actor.** It was `runtime(actorEmail?: string | null)`
   and would happily build a client with no `X-Actor`. An audit row that cannot name anybody
   is not an audit row, so a blank actor is refused with an `HttpError(500, …)` before any
   request is made. Every existing call site already passes a non-empty string
   (`context.user?.email ?? context.user?.id ?? "unknown"`), so no other file changed.
8. **The shared key and the runtime's address are cached on first use, not literally "at
   server start".** Wasp validates the environment when `wasp/server` is first imported, and
   `env.RUNTIME_INTERNAL_KEY` is read exactly once thereafter (there is a test that counts the
   reads). The key is registered as a secret at the same moment, which is what makes it
   impossible to print.
9. **`runtimeCall` now logs the failures it swallows.** A promise of "the key is never
   logged" over code that logs nothing is worth nothing, and an operator needs to know a
   runtime call failed. One scrubbed line names what was being read and what came back; the
   422 path stays silent, because a refused configuration is the person's own input and is
   already shown to them.
10. **The console is wrapped for the whole process, not only for our own logging.** A secret
    reaches a log through whatever prints it — Wasp, Prisma, or Stripe's SDK dumping an error
    object (C6's report flagged its `console.error` path). `installLogScrubbing` redacts
    registered secrets from every console call; a value that holds no secret is passed
    through byte for byte, so ordinary logging keeps its formatting.
11. **Five secrets are registered, not one.** The task names the internal key;
    `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `JWT_SECRET` and `DATABASE_URL` (which carries
    the database password) are held by the same process and are redacted the same way.
    `SMTP_PASSWORD` is read from `process.env` because Wasp's email sender reads it itself and
    it is not part of the validated `env` object.
12. **`app.set("trust proxy", ["loopback", "linklocal", "uniquelocal"])`.** Behind Caddy every
    request would otherwise be counted against the proxy's address, which turns a per-address
    limit into a global one; trusting the forwarded-for header unconditionally would let a
    stranger choose their own bucket. Trusting it only from a private peer is right in both
    places and needed no new environment variable.
13. **The spec is `e2e-tests/tests/security.spec.ts`** (C1 set `testDir: "./tests"`), and it
    leaves one organisation behind, `runtime-unknown-security-e2e`, deliberately pointed at a
    tenant the runtime does not have. It is a fixed slug, so re-runs reuse it; it shows up on
    `/admin/tenants` as "Not configured", beside the one `admin.spec.ts` already leaves.
14. **`e2e-tests/README.md` (a C1 file) gained a "The rate limit" section**, because a future
    spec author needs to know the whole suite shares one address and one budget.
15. **Tests were derived from the task's Behaviour and Tests lists, not given verbatim** (this
    is a contract-level plan).

No conflict was found between the four reference documents and this task. One line already
flagged by C1 and C4 is worth repeating, because this task reads that variable:
`docs/reference/api-surface.md` lists `SMTP_USER`/`SMTP_PASS` for the portal where Wasp reads
`SMTP_USERNAME`/`SMTP_PASSWORD`; `setup.ts` uses Wasp's name.

## Notes for neighbours

- **C8**: the portal suite is still five commands and needs nothing new. Two things about CI:
  the whole job runs from one address, so the rate limit's budget is shared by every spec in
  the same minute (successful logins and signups are refunded, so this only bites a spec that
  sends more than ten emails a minute); and `security.spec.ts` reads `mail-sink.log`, so the
  e2e job must keep piping `wasp start` into it as `playwright.config.ts` does.
- **C9**: this task hardened the Wasp *server*. The client host is still owed the same
  headers — import `SECURITY_HEADERS` and `contentSecurityPolicy({ connectOrigins: [WASP_SERVER_URL] })`
  from `src/server/security.ts` and write them into the web image's Caddyfile, or generate them
  from it. `frame-ancestors 'none'` and HSTS on the API alone do not protect the pages. The
  main Caddy must also forward the client address (`X-Forwarded-For`), which it does by
  default; the server already trusts a private peer's version of it.
- **C9/E7**: HSTS is sent unconditionally. That is right behind Caddy's TLS and harmless on
  `localhost` (browsers ignore HSTS for it), but a deploy that ever serves the API over plain
  HTTP on a real hostname would pin browsers to https for a year.
- Still open from C2, C4 and C6, and deliberately not fixed here because it is outside this
  task's behaviours: React Query retries a refused query three times, so a 402 or 403 banner
  takes a few seconds to appear on a cold page. The fix is a query-client policy that does not
  retry 4xx.
- Nothing in `src/client/**`, `src/admin/**`, `src/organizations/**` or `src/payment/**` was
  touched; `main.wasp.ts` gained only the two `server:` keys.
