# operations Task E8: Security hardening in code and CI

Status: done with deviations
Commit: <pending>
Tests: `uv run pytest -q tests/test_ops_ratelimit.py` -> 14/14; full suite `uv run pytest -q` -> 635 passed, 1 skipped, 0 failed (the skip is the live-key voice test)
Interfaces produced: `spatalk.http.ratelimit.Rule`, `RULES`, `TokenBucket`, `IpRateLimiter`, `client_ip`, `carries_edge_key`, `install_rate_limits`; `spatalk.http.actions.SECURITY_HEADERS`

## What is in place

- **Per-IP token buckets** in front of every HTTP route (`spatalk/http/ratelimit.py`, installed by
  `create_app`): `/a/*` 10/min, `/chat/*` 30/min, `/widget/*` 60/min, `/telnyx/*`, `/instagram/*`
  and `/messenger/*` 300/min. Over the limit is `429` with an integer `Retry-After`, never a
  silent drop. `/healthz`, `/internal/*`, `/slack/*` and `/ws/{token}` are in no bin: the uptime
  monitor polls the first, the second is a shared key, the third a signed Slack signature and the
  fourth a five-minute signed token.
- **The edge key lifts the webhook bin**, and only a *correct* key does
  (`hmac.compare_digest` against `EDGE_SHARED_KEY`): the worker's replay burst after an outage
  (text-channels B1) must not be turned away by us, and a header anyone can set would hand the
  larger bin to anyone who reads the source.
- **Security headers on the action pages** (`spatalk/http/actions.py`):
  `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; form-action 'self'`
  and `Referrer-Policy: no-referrer` on the confirm page, the transcript page and the done page.
  The policy permits exactly what the page uses — one inline style attribute and a form posting
  back to itself — and no script, image, frame or outbound request at all.
- **CI job `security`** (`.github/workflows/ci.yml`, appended; nothing reordered): gitleaks over
  the full history, `pip-audit` over the runtime environment, and `npm audit` for the portal and
  the worker. All three are allowlist-driven: an accepted finding is a line in a file with a
  reason beside it, never a flag that silences a class of finding.
- **`.gitleaks.toml`**: the default rule set plus one rule for this project's own shared keys
  (`INTERNAL_API_KEY`, `RUNTIME_INTERNAL_KEY`, `EDGE_SHARED_KEY`, `SECRET_KEY`,
  `META_TOKEN_ENCRYPTION_KEY`, `TELNYX_API_KEY` assigned a 20-character-or-longer value), and two
  documented allowlists: the test trees, whose fixtures are supposed to look like credentials,
  and the `change-me`/CI placeholder values.
- **`runtime/.pip-audit-ignore`** and **`.github/npm-audit-allow.json`**: the findings we carry
  today, each with the package, why the product is not exposed, and what removes it from the list.

## Evidence

- Scanners run here, not just written:
  - `docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.30.1 detect --source=/repo --config=/repo/.gitleaks.toml --redact --no-banner -v`
    → `92 commits scanned` … `no leaks found` (without the config it is `leaks found: 2`, both
    fixtures: the CI job's throwaway `JWT_SECRET` and a constant in
    `portal/src/runtime/api.server.test.ts`). The same scan with `--no-git` over copies of every
    file this task adds or changes: `no leaks found`.
  - The new rule is not dead: the same scan over a throwaway `runtime/deploy.env` holding
    `INTERNAL_API_KEY=<36 random characters>` reports `RuleID: spatalk-shared-key`,
    `leaks found: 1`.
  - `uv run pip-audit --progress-spinner off --skip-editable --ignore-vuln PYSEC-2026-3740`
    → `No known vulnerabilities found, 1 ignored`. Without the ignore: `Found 1 known
    vulnerability in 1 package — nltk 3.10.3 PYSEC-2026-3740`, no fix version published.
  - `node .github/scripts/npm-audit-gate.mjs portal` → four accepted high advisories, exit 0;
    `node .github/scripts/npm-audit-gate.mjs edge/sms-worker` → nothing to accept, exit 0; the
    same gate with an empty allowlist → `4 high or critical advisory not in …`, exit 1, so the
    gate is proved to fail as well as to pass.
- `uv run ruff check spatalk tests scenarios` → `All checks passed!`
- The full-suite number above was measured against a throwaway database
  (`TEST_DATABASE_URL=…/spatalk_test_e8`). Tasks E1, E2 and E8 were written in this working
  tree at the same time, and two `pytest` runs on one `spatalk_test` drop and recreate the
  schema under each other: an earlier run scored `10 failed` and a second `3 failed`, all of
  them fixture errors in `test_internal_api`, `test_jobs`, `test_conversations`,
  `test_textback`, `test_voice_texml` and `test_widget`, each traced to a `DROP TABLE
  runtime.jobs` blocked on another run's open transaction (`pg_stat_activity`:
  `idle in transaction` holding the jobs table). Alone on its own database the same tree is
  green. Concurrent agents on this machine should each use their own test database.

## Deviations

1. **`/messenger/*` shares the webhook bin** although the plan names only `/telnyx/*` and
   `/instagram/*`. The plan predates instagram plan Task D3, which split the Meta adapter in two;
   the Page webhook is the same traffic from the same platform, and leaving it in no bin at all
   would have been the weaker outcome. Evidence: `docs/reference/api-surface.md` lists
   `GET, POST /messenger/webhook` beside the Instagram one.
2. **The edge-key exemption requires the configured key, not merely the header.** The plan says
   "unless the edge key header is present". A header anyone can set would be a published bypass
   of the webhook limit, so `carries_edge_key` compares it with `EDGE_SHARED_KEY` in constant
   time and an unset key exempts nobody. `tests/test_ops_ratelimit.py::test_a_wrong_edge_key_is_still_rate_limited`
   pins it.
3. **`npm audit --audit-level=high` is wrapped rather than run bare**
   (`.github/scripts/npm-audit-gate.mjs`, new file, not in the plan's file list). Run bare it can
   never pass: `portal/package-lock.json` carries the Wasp-generated development server, whose
   `nodemon → simple-update-notifier → semver` chain has three high advisories whose only fix is
   nodemon 3.x — which Wasp 0.25 does not use — plus `nodemailer`. A gate that is permanently red
   is not read, so the wrapper fails on any high or critical advisory that is not in
   `.github/npm-audit-allow.json` with a reason, and prints (without failing) allowlist entries
   that no longer match. It audits `--package-lock-only`, so the answer does not depend on
   whether anyone ran `npm ci` or `wasp build` first. Evidence:
   `cd portal && npm audit --audit-level=high --package-lock-only` → `8 vulnerabilities (4
   moderate, 4 high)`, exit 1, and the same numbers from a directory holding only the committed
   `package.json` and `package-lock.json`.
4. **`pip-audit`'s allowlist is a file this task invented** (`runtime/.pip-audit-ignore`, one
   advisory id per line with a comment block above it). pip-audit has no allowlist-file option,
   only a repeatable `--ignore-vuln`; the CI step builds the flags from the file so the reasons
   live next to the ids. Evidence: `uv run pip-audit --help` lists `--ignore-vuln ID` and no file
   equivalent.
5. **`pip-audit` is not added to `pyproject.toml`.** `pyproject.toml` is E6's file in this plan;
   the CI job installs the tool with `uv pip install pip-audit` beside the project environment
   instead.

## Notes for neighbours

- `create_app` now installs the limiter before any router (`app.state.rate_limiter`). A test that
  makes more than ten requests to `/a/*`, thirty to `/chat/*` or sixty to `/widget/*` **from one
  app instance and one IP within a minute** will now see `429`. Replace `app.state.rate_limiter`
  with `IpRateLimiter([...])` (or a rule set of your own) if you need different numbers; passing a
  `CF-Connecting-IP` header gives a request its own bucket.
- The limiter reads `ctx.clock`, so a `FixedClock` test controls refill with `clock.advance(...)`
  rather than real time.
- E7 owns `alerts.py` and the `/healthz` fields; nothing here writes to `alert_log`. A rate-limit
  event is a `logger.warning`, not an alert: a limited scraper is not an incident.
- The portal's `nodemailer` advisory (GHSA-p6gq-j5cr-w38f) has a non-breaking fix, but
  `portal/package-lock.json` is regenerated by the Wasp toolchain and belongs to a portal task.
  It is accepted in `.github/npm-audit-allow.json` with that note; whoever next touches the portal
  lockfile should bump it and delete the entry.
- Task E2 was being written in the same working tree while this task ran. Nothing here touches
  `docker-compose.yml`, `.env.example`, `.gitignore`, `runtime/scripts/` or `test_deploy_assets.py`,
  and the commit names its files explicitly.
