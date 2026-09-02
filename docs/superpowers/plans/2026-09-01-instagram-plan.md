# Instagram and Messenger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Contract level: files, exact interfaces, behaviours, tests. Tests first, with recorded webhook fixtures; no live Meta calls in tests.

**Goal:** Instagram comments and DMs, and Facebook Page messages and comments, are answered by the same brain, with the same tracked-item outcomes and the same human takeover, using Meta plumbing copied from diwenne/openreply.

**Architecture:** A `social/` package in the runtime holds Meta OAuth, encrypted token storage with daily refresh, webhook verification, and two thin adapters (Instagram, Messenger) that turn Meta events into `TextConversationService.handle_inbound` calls and send replies through the Graph API. Comment handling is a fixed, tenant-configured policy: keyword or all, private reply through the brain, optional fixed public reply. The portal gets Connect buttons that start the OAuth flows.

**Tech Stack:** as the runtime plan, plus `cryptography` (Fernet) for tokens at rest, `httpx` for Graph calls with a fake client in tests. Reference implementation to copy from: `diwenne/openreply` `lib/meta/oauth.ts`, `lib/meta/client.ts`, `app/api/webhook/route.ts`, `docs/setup.md` (verified 2026-09-01 in `docs/research/research-2-adoption-check.md`).

**Spec:** `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md` §0 (Instagram row), §2.1 (openreply), §7 (subprocessors: add Meta). Depends on the text-channels plan B2 and B5 and the portal plan C3 and C4.

## Global Constraints

- Everything in the runtime and text-channels Global Constraints.
- Tokens are stored encrypted with `META_TOKEN_ENCRYPTION_KEY` (Fernet); never logged; refreshed by a job when under 30 days to expiry.
- Every Meta webhook POST is verified with HMAC-SHA256 over the raw body against both `INSTAGRAM_APP_SECRET` and `FACEBOOK_APP_SECRET`; an invalid signature is 401 and nothing is processed.
- Webhook handlers return 200 within 2 seconds; all work happens in jobs.
- Replies are sent only inside Meta's 24-hour messaging window from the last inbound message; outside it, the conversation is closed and an item is captured for the team if one is not already open.
- Echo events (`is_echo`) and events from the tenant's own account are ignored. Duplicate event ids are ignored.
- Public comment replies are fixed wording from `scripts.comment_public_reply`, never generated. Private replies go through the brain and the guard like any channel.
- Instagram and Messenger prompts add: "Reply in under 500 characters, plain text, no emoji unless the customer used one."

## File Structure

```
runtime/spatalk/social/
  __init__.py
  crypto.py               encrypt_token(str) -> str, decrypt_token(str) -> str  (Fernet, key from settings)
  models.py               TenantIntegration, MetaEvent (dedup), MetaWindow (last inbound per sender)
  graph.py                GraphClient protocol + HttpGraphClient + FakeGraphClient
  meta_oauth.py           Instagram Business Login: build_start_url, exchange_code, exchange_long_lived, refresh; Facebook Login for Pages: build_page_start_url, exchange, list_pages, subscribe_page
  instagram.py            router: GET /instagram/connect, GET /instagram/callback, GET+POST /instagram/webhook, POST /instagram/deauthorize, POST /instagram/delete
  messenger.py            router: GET /messenger/connect, GET /messenger/callback, GET+POST /messenger/webhook
  events.py               parse_instagram_payload(body) -> list[SocialEvent]; parse_messenger_payload(body) -> list[SocialEvent]
  handlers.py             job handlers: social.ig_event, social.fb_event, social.refresh_tokens
runtime/spatalk/tenants/schema.py      + SocialSettings(comment_mode, comment_keywords, public_reply_enabled); scripts comment_public_reply, dm_greeting
runtime/spatalk/http/internal.py       + GET /internal/tenants/{id}/integrations, DELETE .../integrations/{provider}
runtime/spatalk/text/takeover.py       relay_from_staff: instagram and messenger sends
runtime/tests/fixtures/meta/*.json     comment, dm, dm_echo, postback, read, page_message, page_feed_comment, dedup pairs
runtime/tests/test_social_*.py
portal/src/client/settings/Integrations.tsx    Connect buttons and status
docs/runbooks/meta-setup.md            app configuration, roles, review, per-tenant connect flow
```

---

### Task D1: Token storage, OAuth flows and refresh

**Files:** `social/{__init__.py, crypto.py, models.py, graph.py, meta_oauth.py}`, `spatalk/settings.py` (`instagram_app_id`, `instagram_app_secret`, `facebook_app_id`, `facebook_app_secret`, `meta_token_encryption_key`, `meta_graph_version="v21.0"`), `alembic/versions/0003_social.py`, `tests/test_social_oauth.py`, `tests/test_social_crypto.py`

**Interfaces:**
- `TenantIntegration(tenant_id, provider: "instagram"|"messenger", external_id, display_name, access_token_enc, token_expires_at, scopes, connected_by, created_at, updated_at; unique (tenant_id, provider))`.
- `GraphClient` protocol: `get(path, params) -> dict`, `post(path, json|data) -> dict`; `HttpGraphClient(base_url, token_getter)`; `FakeGraphClient(responses)` recording calls.
- `meta_oauth.build_instagram_start_url(settings, state) -> str` (authorize at `https://www.instagram.com/oauth/authorize`, scopes `instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments,instagram_business_manage_insights`, redirect `PUBLIC_BASE_URL/instagram/callback`); `exchange_instagram_code(code) -> ShortToken`; `exchange_long_lived(short) -> LongToken(access_token, expires_in)` via `graph.instagram.com/access_token?grant_type=ig_exchange_token`; `refresh_long_lived(token)` via `graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token`; `me(token) -> {id, username}`; `subscribe_instagram(ig_user_id, token)` → `POST /{id}/subscribed_apps?subscribed_fields=comments,messages`.
- `meta_oauth.build_page_start_url(settings, state)` (Facebook Login, scopes `pages_messaging,pages_manage_metadata,pages_read_engagement,pages_show_list`), `exchange_page_code`, `list_pages(user_token) -> [{id, name, access_token}]`, `subscribe_page(page_id, page_token)` → `POST /{page-id}/subscribed_apps?subscribed_fields=messages,feed`.
- `state` is an `itsdangerous` signed payload `{tenant_id, return_to}` valid 15 minutes.
- Job `social.refresh_tokens` (daily): refreshes any integration with under 30 days to expiry; on failure, marks `needs_reconnect` and enqueues an ops email.

**Tests:** encrypt/decrypt round trip and key rotation error; start URL contains scopes and signed state; callback exchange sequence with `FakeGraphClient` stores an encrypted token and the ig user id, and subscribes fields; tampered state 400; refresh job refreshes only near-expiry tokens; a refresh failure sets `needs_reconnect`.

**Done when:** tests pass, migration applies. Commit `feat(social): meta oauth, encrypted token storage and refresh job`.

---

### Task D2: Instagram webhook, comments and DMs

**Files:** `social/{instagram.py, events.py, handlers.py}`, `spatalk/tenants/schema.py`, `runtime/tenants/skincentrix/{tenant.yaml, scripts.yaml}`, `spatalk/brain/prompt.py` (channel rule), `tests/fixtures/meta/*.json`, `tests/test_social_instagram.py`

**Interfaces:**
- `SocialSettings(comment_mode: "off"|"keyword"|"all" = "keyword", comment_keywords: list[str] = [], public_reply_enabled: bool = False)` on `TenantConfig.social`.
- Scripts: `comment_public_reply` ("Thanks! Check your DMs."), `dm_greeting` (used when the first message is a comment-triggered private reply: the brain's reply is prefixed by nothing; the greeting is the AI disclosure for this channel, one sentence: "Hi, this is {name}'s assistant.").
- `parse_instagram_payload(body: dict) -> list[SocialEvent]` where `SocialEvent(kind: "comment"|"message"|"postback"|"read"|"echo", tenant_external_id, sender_id, event_id, text, comment_id, media_id, timestamp)`.
- `GET /instagram/webhook` (hub verification), `POST /instagram/webhook` (signature, dedup, enqueue `social.ig_event` per event), `POST /instagram/deauthorize`, `POST /instagram/delete` (parse `signed_request`, delete the integration, return `{url, confirmation_code}`).
- Handler `social.ig_event(payload, ctx)`.

**Behaviour:**
1. Verification: `hub.mode == subscribe` and `hub.verify_token == settings.instagram_webhook_verify_token` → respond with `hub.challenge` as text; otherwise 403.
2. POST: compute HMAC-SHA256 of the raw body with each app secret; accept if either matches the `X-Hub-Signature-256` header (constant time); else 401. Parse; for each event insert `MetaEvent(event_id unique)`; duplicates skipped; enqueue one job per new event; respond 200.
3. Tenant resolution: `TenantIntegration.external_id == entry.id` for provider instagram. Unknown → log and drop.
4. `message` events: drop if `is_echo` or sender is the integration's own id. Record `MetaWindow(tenant_id, provider, sender_id, last_inbound_at)`. Call `TextConversationService.handle_inbound(channel="instagram", external_id=sender_id, sender=None, text, provider_message_id=mid)`. For each reply, `POST /{ig_user_id}/messages` `{recipient: {id: sender_id}, message: {text}}`. Usage `ig_in`, `ig_out`. The first assistant reply in a new conversation is prefixed with `scripts.dm_greeting`.
5. `comment` events: ignore comments authored by the integration's own account. If `comment_mode == "off"` → nothing. If `"keyword"` and no keyword (case-insensitive, word-bounded) matches → nothing. Otherwise: create or reuse the conversation for `external_id=commenter_id`; call `handle_inbound` with the comment text; send the reply as a private reply `POST /{ig_user_id}/messages` `{recipient: {comment_id}, message: {text}}`; if `public_reply_enabled`, also `POST /{comment_id}/replies` `{message: scripts.comment_public_reply}` (fixed). Record the window as of the comment time.
6. 24-hour window: before any send, if `now - last_inbound_at > 24h`, do not send; close the conversation; if no open item exists for it, capture a `callback` item with the sender's IG username as `contact.name` (the only contact we have) so a human follows up from the Instagram inbox.
7. `postback` and `read` events are stored as `MetaEvent` and ignored. Graph 429 or 5xx → the job retries with backoff (existing jobs mechanism); 4xx other than 429 → dead-letter with the response body in `last_error`.
8. Takeover: `relay_from_staff` for `channel == "instagram"` sends through the same messages endpoint; while `controller == human` the brain is not called (inherited from B5).

**Tests (fixtures replayed through the router with valid and invalid signatures):** verify handshake; bad signature 401 and no job; duplicate event id enqueues once; DM → brain (`FakeLLM`) → one `messages` call with the reply prefixed by the greeting; echo ignored; own-account comment ignored; keyword comment → private reply, plus public reply when enabled; non-matching comment in keyword mode → nothing; `comment_mode=all` replies to any comment; window expired → no send, conversation closed, callback item captured once; 429 → job requeued; takeover relay sends via Graph.

**Done when:** tests pass. Commit `feat(social): instagram webhook, comment-to-dm and dm conversations`.

---

### Task D3: Messenger (Facebook Page) adapter

**Files:** `social/messenger.py`, `social/events.py` (`parse_messenger_payload`), `social/handlers.py` (`social.fb_event`), `tests/fixtures/meta/page_*.json`, `tests/test_social_messenger.py`

**Interfaces:** `GET /messenger/connect?tenant=&state=` (Facebook Login), `GET /messenger/callback` (exchange, list pages, if exactly one page: store and subscribe; if several: redirect to portal with the list to choose from, then `POST /internal/tenants/{id}/integrations/messenger/select` stores the chosen page), `GET+POST /messenger/webhook`.

**Behaviour:** mirrors D2 with Page semantics: `messaging` events with `sender.id` (PSID) and `message.text`; send via `POST /{page_id}/messages` `{recipient: {id}, message: {text}, messaging_type: "RESPONSE"}` with the page token; `feed` change events with `item == "comment"` and `verb == "add"` from users other than the page → policy as D2; private reply via `POST /{comment_id}/private_replies` `{message}`; public reply via `POST /{comment_id}/comments` `{message}` when enabled. Same 24-hour window rule, dedup, echo and self filters, takeover relay.

**Tests:** same matrix as D2 against the page fixtures; page selection flow with two pages.

**Done when:** tests pass. Commit `feat(social): facebook page messenger and comment adapter`.

---

### Task D4: Portal Connect buttons and integration status

**Files:** `portal/src/client/settings/Integrations.tsx`, `runtime/spatalk/http/internal.py` (`GET /internal/tenants/{id}/integrations`, `DELETE /internal/tenants/{id}/integrations/{provider}`, `GET /internal/tenants/{id}/integrations/{provider}/connect-url?return_to=`), `docs/contracts/runtime-internal.openapi.json`, `portal/e2e-tests/integrations.spec.ts`

**Behaviour:** the Settings page shows Instagram and Facebook Page cards with status (connected as @username / page name, token expiry, `needs_reconnect`), a Connect button that opens the runtime's connect URL (signed state carries `return_to` back to the portal), and a Disconnect button (OWNER only) that deletes the integration and unsubscribes. Comment policy (mode, keywords, public reply on/off) is edited in the Scripts and Delivery tabs' schema-driven forms since it lives in `TenantConfig.social`.

**Tests:** contract snapshot updated; Playwright: status renders from a seeded integration; Disconnect calls the API and the card returns to "Not connected".

**Done when:** tests pass; contract file updated deliberately. Commit `feat(portal): instagram and messenger connect status`.

---

### Task D5: Scenarios, runbook and CI

**Files:** `runtime/scenarios/promptfooconfig.yaml`, `runtime/scenarios/asserts.py`, `docs/runbooks/meta-setup.md`, `.github/workflows/ci.yml`

**Behaviour:**
1. Scenarios with `channel: instagram`: a price question by DM (under 500 chars, no emoji), a comment "how much?" on a promo post routed through the comment path (deterministic pytest, not promptfoo), a clinical DM (gate), a booking link request in DM (link shown inline, no SMS).
2. `docs/runbooks/meta-setup.md`: the app configuration steps (mirrors `accounts-and-env.md` step 9), how a tenant connects, what Standard vs Advanced Access means for onboarding, the tester-invite flow, and the App Review submission checklist (screencast of the DM flow, privacy URL, data deletion URL, use-case text).
3. CI runs the social tests as part of the runtime job (no extra secrets).

**Done when:** promptfoo passes with a key; runbook written. Commit `test(social): instagram scenarios and meta setup runbook`.

---

## Self-review against the spec

- Spec §0 Instagram row and §2.1: OAuth, webhook verification, comment-to-private-reply and token refresh copied from openreply's verified structure; Messenger added on the same shape (D3).
- One brain, many doors (brief §3.3): both adapters call `TextConversationService.handle_inbound`; outcomes, guard, rules gate and takeover are inherited unchanged.
- Data minimisation: the only contact captured from Instagram is the username, as `contact.name`; no free text on items; window-expired follow-ups become a callback item for a human.
- Compliance: Meta is added to the subprocessor register in the spec §7 table (do this in D5's runbook task by editing the spec); tokens encrypted at rest; deauthorize and data-deletion endpoints exist (Meta platform requirement).
- Fixed wording: `comment_public_reply`, `dm_greeting` in `scripts.yaml`.
