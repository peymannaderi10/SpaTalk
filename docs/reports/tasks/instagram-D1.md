# instagram Task D1: Token storage, OAuth flows and refresh

Status: done with deviations
Commit: `2c9659b` `feat(social): meta oauth, encrypted token storage and refresh job` (this line was filled in by the follow-up docs commit; a hash cannot be written into the commit that carries it)
Tests: `uv run pytest tests/test_social_crypto.py tests/test_social_oauth.py -q` -> 27/27 (7 crypto, 20 oauth); full runtime suite `uv run pytest -q` -> 395 passed, 1 skipped; `uv run ruff check spatalk tests scenarios` -> "All checks passed!"; `uv run alembic upgrade head` -> `Running upgrade 0003 -> 0004, social`
Interfaces produced: `spatalk.social.crypto.{encrypt_token, decrypt_token, TokenEncryptionError, TokenDecryptionError}`; `spatalk.social.models.{TenantIntegration, MetaEvent, MetaWindow}`; `spatalk.social.graph.{GraphClient, HttpGraphClient, FakeGraphClient, GraphCall, GraphError}`; `spatalk.social.meta_oauth.{OAuthState, sign_state, verify_state, instagram_redirect_uri, page_redirect_uri, build_instagram_start_url, build_page_start_url, ShortToken, LongToken, exchange_instagram_code, exchange_long_lived, refresh_long_lived, me, subscribe_instagram, exchange_page_code, list_pages, subscribe_page, ConnectResult, PageChoices, store_integration, integration_for, integration_by_external_id, access_token, delete_integration, complete_instagram_connect, complete_page_connect, refresh_tokens, ensure_daily_refresh_scheduled, REFRESH_JOB, REFRESH_WINDOW, INSTAGRAM_SCOPES, PAGE_SCOPES, INSTAGRAM_WEBHOOK_FIELDS, PAGE_WEBHOOK_FIELDS}`; job kind `social.refresh_tokens`; `Settings.{instagram_app_id, instagram_app_secret, facebook_app_id, facebook_app_secret, meta_token_encryption_key, meta_graph_version, instagram_webhook_verify_token}`; `JobContext.graph`

## What it does

`spatalk/social/crypto.py` is the only door a Meta token goes through. Fernet, key from
`META_TOKEN_ENCRYPTION_KEY`. With no key, or a malformed one, `encrypt_token` raises
`TokenEncryptionError` instead of falling back to plaintext; a ciphertext written under a
rotated key raises `TokenDecryptionError` instead of returning something wrong. No token is
returned by a public function, logged, or put in an email anywhere in the package.

`spatalk/social/models.py` adds the three tables `data-model.md` documents for this plan:
`tenant_integrations` (unique `(tenant_id, provider)`, index `(provider, external_id)` for
webhook resolution), `meta_events` (dedup by event id) and `meta_windows` (24-hour window
anchor). D2 and D3 need the last two, but the plan's file structure puts all three in this
module and D2/D3 own no migration, so all three ship here in `0004_social.py`.

`spatalk/social/graph.py` is the vendor seam: a `GraphClient` protocol, `HttpGraphClient`
(one base host, optional sync-or-async bearer `token_getter`, raises `GraphError(status,
body)` on a non-2xx) and `FakeGraphClient` (answers from a `{"METHOD /path": dict | list |
exception}` table, records every call as a `GraphCall`, and raises on a path nobody stubbed,
so no test can pass because a call went nowhere). `GraphError.retryable` is the rule D2's
event jobs follow: 429 and 5xx come back, every other 4xx dead-letters with the body.

`spatalk/social/meta_oauth.py` holds both flows and the refresh job:

* `sign_state` / `verify_state`: an `itsdangerous` payload `{tenant_id, return_to}`, salt
  `meta-oauth`, 15 minutes. `verify_state` raises `HTTPException(400)` directly, so the D2
  and D3 routers get the plan's "tampered state 400" without repeating the mapping.
* `build_instagram_start_url` (instagram.com/oauth/authorize, the four
  `instagram_business_*` scopes, redirect `PUBLIC_BASE_URL/instagram/callback`) and
  `build_page_start_url` (facebook.com/v21.0/dialog/oauth, the four `pages_*` scopes,
  redirect `PUBLIC_BASE_URL/messenger/callback`).
* `complete_instagram_connect`: verify state, `POST api.instagram.com/oauth/access_token`,
  `GET graph.instagram.com/access_token?grant_type=ig_exchange_token`, `GET /v21.0/me`,
  `POST /v21.0/{ig_user_id}/subscribed_apps?subscribed_fields=comments,messages`, then one
  upsert with the long-lived token encrypted and `token_expires_at = now + expires_in`.
* `complete_page_connect`: exchange, `GET /v21.0/me/accounts`; exactly one page (or an
  explicit `page_id`) is subscribed to `messages,feed` and stored; several pages return
  `PageChoices` and store nothing, which is the selection step D3 renders.
* `social.refresh_tokens` (registered handler): every integration inside 30 days of expiry
  and not already flagged. Instagram rows are refreshed through
  `refresh_access_token?grant_type=ig_refresh_token`; any failure, and any Page row that
  carries an expiry (a Page token cannot be renewed this way), sets `needs_reconnect` and
  emails the tenant's escalation owner in staff wording that never contains the token. A row
  already flagged is left alone: only a person can fix it.
* `ensure_daily_refresh_scheduled` queues that job at most once a day; the minute scheduler
  calls it, which is what makes the job daily in production.

## Deviations

- **The migration is `alembic/versions/0004_social.py`, not `0003_social.py`.** `0003` was
  taken by the text-channels plan's `0003_slack_threads.py` before this plan started.
  Generated with `uv run alembic revision --autogenerate -m "social" --rev-id 0004`, applied
  with `uv run alembic upgrade head` -> `Running upgrade 0003 -> 0004, social`; the three
  tables and `ix_integration_external` are in `\dt runtime.*`.
- **Conflict between `api-surface.md` and the plan, reported as instructed and resolved in
  favour of the plan's file structure.** `api-surface.md` puts `GET /instagram/connect`,
  `GET /instagram/callback`, `POST /instagram/deauthorize` and `POST /instagram/delete` in
  D1, but D1's Files list contains no router module and the plan's File Structure puts those
  routes in `social/instagram.py`, which is a **D2** file (D2's own Interfaces block lists
  deauthorize and delete). Creating `social/instagram.py` here would have made D2 open a file
  it is told to create. So D1 ships every piece those routes need as functions
  (`build_instagram_start_url`, `verify_state`, `complete_instagram_connect`,
  `delete_integration`) and no route; the endpoints appear when D2 and D3 add their routers.
  The reference's endpoint list is satisfied by the system, one task later than it says.
- **`social/handlers.py` was not created; the refresh job lives in `meta_oauth.py`.** The
  plan's File Structure lists `social.refresh_tokens` in `handlers.py`, but `handlers.py` is
  a D2 file and D1's Files list is `{__init__, crypto, models, graph, meta_oauth}`. The job
  is an OAuth concern (it calls `refresh_long_lived`), so it sits with the flow it renews.
  D2 and D3 create `handlers.py` fresh for `social.ig_event` and `social.fb_event`.
- **`Settings.instagram_webhook_verify_token` was added even though D1's field list omits
  it.** `api-surface.md` lists `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` under plan D, D2's behaviour
  reads `settings.instagram_webhook_verify_token`, and D2 does not own `settings.py`. Adding
  it here is the only place it can go without a later task touching a file it does not own.
- **`me`, `subscribe_instagram`, `exchange_page_code`, `list_pages` and `subscribe_page` take
  `settings` as their first argument**, which the plan's one-line signatures omit. They need
  `settings.meta_graph_version` for the versioned Graph path (`/v21.0/me`,
  `/v21.0/{id}/subscribed_apps`), and CLAUDE.md forbids hard-wiring a vendor's version in
  code. The token exchange and refresh endpoints stay unversioned, as Meta documents them.
- **`JobContext` gained one optional field, `graph`** (`spatalk/jobs.py`, delimited block).
  It is how a test injects `FakeGraphClient` into the refresh job and how D2/D3 will inject
  one into the event handlers; production leaves it None and each call builds the client for
  the host it needs.
- **Four shared files gained one line each, all additive and delimited:**
  `alembic/env.py` and `tests/conftest.py` import `spatalk.social.models` so autogenerate and
  the per-test `create_all` see the new tables; `spatalk/ledger/scheduler.py` calls
  `ensure_daily_refresh_scheduled` in its minute loop (and that import is also what registers
  the handler in production); `runtime/.env.example` gained the seven Meta variables, matching
  what B2, B4, B5 and C3 each did for their own settings.
- **Three tests for `HttpGraphClient` live in `tests/test_social_oauth.py`** rather than a new
  `tests/test_social_graph.py`, to keep to the file list D1 names. They use
  `httpx.MockTransport`, so the production client path (bearer header, URL assembly, 429/5xx
  retryable versus 4xx dead-letter) is covered without a network.
- The plan's `TenantIntegration` interface line omits `needs_reconnect`; `data-model.md` has
  it and the refresh job needs it, so the reference won.

## Notes for neighbours

- **D2 (`social/instagram.py`)**: the file does not exist yet, create it. `GET
  /instagram/connect` is `RedirectResponse(build_instagram_start_url(settings,
  sign_state(settings.secret_key, tenant_id, return_to)))`; `GET /instagram/callback` is
  `await complete_instagram_connect(ctx.sf, ctx.settings, ctx.clock, code=..., state=...,
  connected_by=..., client=ctx.graph)` and then a redirect to `result.return_to`. A tampered
  or stale state already raises `HTTPException(400)` inside `verify_state`. For
  `/instagram/deauthorize` and `/instagram/delete`, `delete_integration(sf, tenant_id,
  "instagram")` removes the row and its token. Attach the router with `attach_router` in
  `http/app.py` (FastAPI 0.141 made `include_router` lazy).
- **D2 webhook tenant resolution** is `integration_by_external_id(sf, "instagram",
  entry["id"])`; the token for a send is `access_token(integration, settings)` (decrypts;
  hold it in a local, never log it). `MetaEvent` and `MetaWindow` already exist as models and
  as tables, so D2 needs no migration.
- **D2/D3 sends**: build `HttpGraphClient("https://graph.instagram.com", token_getter)` (or
  `graph.facebook.com`) and honour `GraphError.retryable` — 429 and 5xx re-raise so the jobs
  mechanism retries with backoff, other 4xx should dead-letter with `err.body` in
  `last_error`. In tests inject `FakeGraphClient` through `ctx.graph`.
- **D3 (`social/messenger.py`)**: `complete_page_connect` returns either a `ConnectResult`
  (one page, already subscribed and stored) or `PageChoices(tenant_id, pages, return_to)`
  where each page dict is `{id, name, access_token}`. The OAuth code is single use, so if you
  redirect the owner to the portal to choose, you must carry the chosen page's `access_token`
  through the selection step (or re-run the flow with `page_id` set); `store_integration` and
  `subscribe_page` are exported for exactly that.
- **D4 (portal)**: `GET /internal/tenants/{id}/integrations` can read `integration_for(sf,
  tenant_id, provider)` for status (`display_name`, `token_expires_at`, `needs_reconnect`,
  `scopes`) and `delete_integration` for Disconnect; the connect URL is
  `build_instagram_start_url` / `build_page_start_url` with a `sign_state(...)` carrying
  `return_to`. No endpoint may return `access_token_enc`.
- **Everyone**: the suite is 395 passed, 1 skipped after this task (the brief's "184 passed"
  predates the B and C tasks). `META_TOKEN_ENCRYPTION_KEY` must be set in any environment
  that stores a Meta token; without it `store_integration` raises rather than writing
  plaintext, which is deliberate.
