# instagram Task D4: Portal Connect buttons and integration status

Status: done with deviations
Commit: `b3f51df` `feat(portal): instagram and messenger connect status` (recorded by the
follow-up docs commit; a hash cannot be written into the commit that carries it)
Tests: `uv run pytest tests/test_social_integrations_api.py -q` -> 21/21; `uv run pytest
tests/test_contract_snapshot.py -q` -> 5/5; full runtime suite `uv run pytest -q` -> 472
passed, 13 failed (all pre-existing, evidence below), 1 skipped; `uv run ruff check spatalk
tests scenarios` -> "All checks passed!"; `npx playwright test tests/integrations.spec.ts`
-> 7/7; full portal suite -> `npm run test:unit` 108/108, `wasp test client run` 70/70,
`npx playwright test` 73/73, plus `wasp build`, `npx tsc -p tsconfig.src.json --noEmit` and
`npm run check:client` clean

Interfaces produced: `GET /internal/tenants/{tenant_id}/integrations`,
`GET /internal/tenants/{tenant_id}/integrations/{provider}/connect-url?return_to=`,
`DELETE /internal/tenants/{tenant_id}/integrations/{provider}`;
`spatalk.http.internal.{IntegrationOut, ConnectUrlOut, IntegrationRemoved, SOCIAL_PROVIDERS}`;
`spatalk.social.meta_oauth.unsubscribe_integration`; `GraphClient.delete` on the Graph seam;
portal `IntegrationsTab` (`src/client/settings/Integrations.tsx`) and the operations
`getTenantIntegrations`, `startIntegrationConnect`, `disconnectIntegration`,
`selectMessengerPage`

## What it does

**Runtime.** Three endpoints, appended to `spatalk/http/internal.py` in the delimited block
`# --- social integrations, portal side (instagram plan, Task D4) ---`:

- `GET .../integrations` answers one row per provider, connected or not, so the page can
  draw both cards from one call: `provider, connected, configured, external_id,
  display_name, token_expires_at, scopes, needs_reconnect, connected_by, connected_at`.
  **No token in any form** — not the plaintext, not the ciphertext — and a test asserts the
  whole response body contains neither.
- `GET .../integrations/{provider}/connect-url?return_to=` mints the Meta authorisation URL
  with a fresh 15-minute signed state carrying the tenant and where to come back to, and
  answers `{url, expires_in}`. A provider this runtime has no app id and secret for is a
  409, not a button that could only fail; a `return_to` that is not an `http(s)` URL is a
  400; an unknown provider or tenant is a 404.
- `DELETE .../integrations/{provider}` unsubscribes the app from that account's webhook
  fields and then deletes the row and its token, answering `{provider, disconnected,
  unsubscribed}`.

Both mutating calls write the runtime's own audit row against the acting portal user
(`portal:<email>`, actions `integration_connect_started` and `integration_disconnect`).

**Portal.** A new "Integrations" tab on the Settings page (`src/client/settings/
Integrations.tsx`) with an Instagram card and a Facebook Page card: status ("Connected as
@name" / "Not connected"), the expiry with the note that the connection is renewed
automatically, a loud line when `needs_reconnect` is set, and — for an owner only —
Connect/Reconnect and Disconnect. Connect asks the runtime for the URL **on the click**,
because the signed state is good for fifteen minutes and a settings page can sit open for
longer, then leaves for Meta. Disconnect calls the runtime and redraws the card from what
the runtime answers, never from what the button assumed. The tab also renders the Page
choice D3's connect flow hands back in the query string, and posts the choice to
`/internal/tenants/{id}/integrations/messenger/select`.

`docs/contracts/runtime-internal.openapi.json` was regenerated (`uv run spatalk openapi
--internal`, normalised to LF) and `portal/src/runtime/client.ts` with it (`npm run
gen:client`); `npm run check:client` is clean in both directions.

## Deviations

- **`social/graph.py` and `social/meta_oauth.py` are D1 files and both gained an addition.**
  Disconnect has to unsubscribe (the task's Behaviour line), and Meta spells that
  `DELETE /{id}/subscribed_apps`, which the Graph seam had no verb for. `GraphClient`,
  `HttpGraphClient` and `FakeGraphClient` each gained a `delete(path, params)` in a marked
  block, and `meta_oauth.unsubscribe_integration(settings, integration, client)` sits beside
  `subscribe_instagram`/`subscribe_page` because it is the same call in reverse. Nothing was
  reordered or reformatted. Evidence: `uv run pytest tests/test_social_oauth.py
  tests/test_social_instagram.py tests/test_social_messenger.py -q` -> 89 passed after the
  change.
- **The unsubscribe is best effort and never blocks the disconnect.** A revoked token, a
  rotated `META_TOKEN_ENCRYPTION_KEY` or an unreachable Meta would otherwise trap a tenant
  inside a connection they have asked to end, and the row is the thing that makes the
  runtime answer that account's events. `unsubscribed: false` in the response says which of
  the two happened rather than pretending. Evidence:
  `test_disconnect_still_removes_the_row_when_meta_refuses_the_unsubscribe`.
- **`connect-url` returns Meta's authorisation URL, not the runtime's own
  `/instagram/connect?tenant=…`.** D2's report suggested the latter; D1's report suggested
  this. `/instagram/connect` takes the tenant id straight from the query string with no
  authentication, so anyone who guesses a tenant id can start a connect flow against it;
  this endpoint is behind `X-Internal-Key` and mints the signed state itself, so the only
  tenant an account can land on is the one a key-holder named. The plan's wording ("a
  Connect button that opens the runtime's connect URL (signed state carries `return_to`
  back to the portal)") is satisfied either way. The unauthenticated `/instagram/connect`
  and `/messenger/connect` routes are untouched and still work.
- **`IntegrationOut` carries a field the plan does not name, `configured`.** Without an app
  id and secret the runtime cannot build a connect URL at all, and a Connect button that
  can only 409 is worse than a card that says the provider is not set up on this service
  yet.
- **`tests/test_contract_snapshot.py` (a C3 file) gained three lines** — the new paths in
  the "every endpoint the portal needs" set. The plan's done criterion is "contract file
  updated deliberately", and that list is where "deliberately" is written down.
- **`.github/workflows/ci.yml` (a D5 file) gained four environment values** on the step that
  starts the runtime the portal reads from: `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`,
  `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, all dummy strings. Without them
  `integrations.spec.ts`'s connect-URL test would fail in CI on a 409, because the runtime
  correctly refuses to build a URL for an app it does not have. Nothing reaches Meta; the
  values only end up inside a URL the test parses. `e2e-tests/README.md` says the same for
  a developer's local runtime.
- **`src/client/operations.ts`, `src/client/pages.wasp.ts` and `src/client/SettingsPage.tsx`
  are C4 files and each gained an append.** Wasp resolves an operation only if it is
  declared in the spec, and the tab has to hang off the page that owns the tab strip; there
  is no way to add a client operation or a settings tab without them. All three additions
  are at the end of their lists, in the existing style.
- **`selectMessengerPage` was implemented even though D4's Behaviour list does not mention
  it.** D3's "notes for neighbours" hands the multi-Page choice to this task explicitly, and
  without it an owner who administers more than one Facebook Page cannot finish connecting
  one — the Connect button would be a dead end for exactly the tenants most likely to press
  it. The runtime endpoint already existed (D3); this is the portal half.
- **Test order: the runtime tests were written first and seen failing (17 of the 21 failed
  for the expected reason — no such route; the other 4 asserted 404s that a missing route
  also gives). The Playwright spec was written after the page it drives**, because a
  Playwright test cannot be run at all until the page renders. Its assertions are not
  cosmetic: the disconnect test reads `runtime.tenant_integrations` and `runtime.audit_log`
  directly to check the row and the audit line the runtime wrote.
- **The 13 failures in the full runtime suite are pre-existing and unrelated**, the same 13
  D3 recorded: `tests/test_widget.py` (11), `test_takeover.py::test_a_staff_message_left_
  waiting_is_delivered_when_the_widget_reconnects` and `test_text_sms.py::test_a_telnyx_
  signature_is_accepted_when_no_edge_key_is_configured`. Evidence, run today on a tree with
  this task's changes stashed (`git stash push -u -- runtime/spatalk runtime/tests
  docs/contracts`): `uv run pytest tests/test_widget.py tests/test_takeover.py
  tests/test_text_sms.py -q` -> `13 failed, 43 passed`, the same names. The widget ones hang
  reaching `challenges.cloudflare.com` for Turnstile; the Telnyx one signs against the
  `FixedClock` (2026-09-01) and verifies against the wall clock, which is now 2026-09-02.
  No test was skipped, weakened or touched here.

## Notes for neighbours

- **D5 (runbook)**: the tenant-facing connect path is Settings → Integrations → Connect,
  which is what `docs/runbooks/meta-setup.md` should tell an owner. The runtime needs
  `INSTAGRAM_APP_ID`/`INSTAGRAM_APP_SECRET` and `FACEBOOK_APP_ID`/`FACEBOOK_APP_SECRET` set
  or the card reads "not set up on this service yet" — that is the honest symptom of a
  half-configured deployment, and worth a line in the runbook.
- **The `return_to` the portal signs is `${frontendUrl}/app/<slug>/settings?connected=<provider>`**,
  built on the server from `config.frontendUrl`, never taken from the browser. Anything
  reading that query parameter later (a "connected!" toast) can rely on it.
- **`GraphClient` now has a third verb, `delete`.** Any fake or alternative client written
  from here on must implement it.
- **Audit vocabulary grew by two actions**, `integration_connect_started` and
  `integration_disconnect`, both on `record_type = "tenant"`. `data-model.md`'s action list
  is a list of examples and `record_type` stayed inside its three.
- **The e2e suite now needs the runtime to have Meta app credentials** (any value). CI sets
  them; `e2e-tests/README.md` documents them for a local run.
- The full portal suite is 73 Playwright tests (66 + 7 new), 108 unit tests and 70 client
  tests after this task; the runtime suite is 493 tests (472 passing, 13 pre-existing
  failures, 1 skipped).

Blocked on: nothing.
