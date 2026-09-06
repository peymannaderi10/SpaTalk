# API surface, provider payload shapes, environment variables

## HTTP and WebSocket endpoints

All on the runtime unless marked portal or edge. Auth column says what proves the caller.

| Method and path | Plan | Auth | Purpose |
|---|---|---|---|
| GET /healthz | A14, E7, F2 | none | ok, tenants, config versions, commit, queue and scheduler health, and `llm: {primary, secondary, active, breaker_open_until}` — the vendor names `LLM_MODEL` and `LLM_MODEL_FALLBACK` resolve to, which one the next turn goes to, and, while a vendor is in its cooling-off period, the ISO time it will be tried again (`secondary` is null with no fallback configured) |
| POST /telnyx/texml | A13, E1 | Telnyx-only URL; loop guard | answers a call with TeXML `<Connect><Stream>` |
| WS /ws/{token} | A13 | signed stream token, 5 min | Telnyx bidirectional audio |
| GET /a/{token} | A9 | signed action link, 7 days | confirm page (never acts) or transcript view |
| POST /a/{token} | A9 | same | acknowledge or resolve |
| POST /slack/interactions | A9 | Slack signing secret | button callbacks: ack, resolve, handback |
| POST /slack/events | B5 | Slack signing secret | url_verification, thread replies from staff |
| POST /telnyx/sms | B2, S2 | `X-Edge-Key` or Telnyx Ed25519 signature | inbound SMS. In order: STOP/START/HELP from fixed wording; then, when the sender is one of `staff_numbers(cfg)`, the staff keywords below; otherwise the customer conversation |
| GET /widget.js | B4 | none | the chat widget |
| GET /widget/{tenant_id}/config | B4 | none | name, greeting, Turnstile site key |
| WS /chat/ws?tenant&session&turnstile | B4 | Turnstile token | web chat |
| POST /chat/fallback | B4 | `X-Edge-Key` or Turnstile | contact form when the socket fails |
| GET /instagram/connect, /callback | D1 | signed state | Instagram Business Login |
| GET, POST /instagram/webhook | D2 | verify token; HMAC-SHA256 | Meta events |
| POST /instagram/deauthorize, /delete | D1 | signed_request | Meta platform requirements |
| GET /messenger/connect, /callback; GET, POST /messenger/webhook | D3 | as Instagram | Facebook Page |
| /internal/* | C3, D4, E4 | `X-Internal-Key`, `X-Actor` | portal's only way in; see the portal plan for the full list |
| GET, POST /internal/tenants/{id}/sms-blocks; DELETE /internal/tenants/{id}/sms-blocks/{phone}?actor= | F2 | `X-Internal-Key`, `X-Actor` | the SMS block list: list, block (409 for a staff number, 422 unless E.164), unblock (404 when absent); every change is an audit row `sms.block` / `sms.unblock`. `GET .../health` gains `sms_muted_numbers`, `sms_blocked_numbers`, `sms_replies_today` |
| edge: POST /telnyx/sms, POST /chat/fallback, PUT /admin/tenant-texts, PUT /admin/blocked-numbers | B1 | Telnyx signature; `X-Edge-Key` | fallback front door |
| portal: /login, /signup, /invite/:token, /app/:orgSlug/*, /admin/*, /privacy, /payments-webhook | C1 to C6 | Wasp session; Stripe signature | |

## Staff replies on POST /telnyx/sms (S2)

Authorised senders are `spatalk.text.staff.staff_numbers(cfg)`: `delivery.staff_phone_numbers`
plus the number every `sms` destination's `address_env` resolves to right now. Nothing an
authorised sender writes reaches the model, and no reply text ever becomes item content.

| Inbound text | Response body | Reply sent from `sms_from_number` |
|---|---|---|
| `ACK 4821`, `ok 4821`, `acknowledge #4821` | `{"ok": true, "handled": "staff_ack"}` | `#4821 acknowledged.` |
| `DONE 4821`, `resolve 4821`, `resolved #4821`, `closed 4821` | `{"handled": "staff_resolve"}` | `#4821 resolved.` |
| any of those naming an id that is not this tenant's open item | `{"handled": "staff_unknown_item"}` | `No open item #4821.` |
| `LIST` | `{"handled": "staff_list"}` | count line plus up to five open items with ids |
| `#4821 on my way` | `{"handled": "staff_relay"}` | the words after the id, verbatim, to that customer |
| anything else | `{"handled": "staff_help"}` | `scripts.help_text` |

`ack` and `resolve` call the ledger as actor `sms:<E.164>` and write one `audit_log` row
(`action` `ack` or `resolve`, `record_type` `item`). An id from another tenant, and an id
already resolved, are both answered `No open item` and change nothing.

## The item shape the portal reads (`ItemOut`, L1, N1)

Every `/internal/*` response that carries an item — `GET /internal/tenants/{id}/items`,
`GET /internal/conversations/{id}`, `POST /internal/items/{id}/acknowledge` and `/resolve` —
returns every `runtime.items` column plus four fields the runtime derives or joins, so the
portal, the owner's SMS and the email all say the same sentence and none of them compose
wording.

| field | type | meaning |
|---|---|---|
| `returning_client` | bool null | true returning, false new, null not asked or not said |
| `practitioner` | string null | a `team[].name`, or `any` for "no preference" |
| `concern` | string null | one of the tenant's `concerns` |
| `summary` | string | `summarize_item(item, cfg)`: the whole request as one sentence, e.g. `"New booking: Mirapeel facial for pigmentation. New client, no practitioner preference. Callback Thursday 24 September, afternoons."` |
| `service_name` | string null | the catalog name of `service_id`; null when the item has no service or the catalog dropped it |
| `preferred_text` | string | `preferred_window` in words: `"any day"`, `"Thursday 24 September"`, `"Thursday 24 September, afternoons"`, `"Thursday"`, `"Thursday afternoon"`, `"mornings"`. A real date keeps its day and month; a weekday the caller named is only a weekday. Never `"any any"` |
| `notes` | string null | the call notes drafted from the item's *conversation*, joined on read so the request card needs one call. Null until the `call_notes` job has run, and null again once retention takes the transcript. Read-only: there is no column behind it on `items` and the portal never writes it [N1] |

The three derived fields are computed on read, never stored, so they cannot drift from the
columns; `notes` is joined from `conversations.notes`, for the same reason — the item has no
free-text column and never will. `docs/contracts/runtime-internal.openapi.json` is
regenerated whenever they change.

## The conversation shape the portal reads (`ConversationFull`, N1)

`GET /internal/conversations/{id}` returns `{conversation, messages, items}`. The
`conversation` object is `ConversationRow` (`id`, `channel`, `started_at`, `ended_at`,
`duration_s`, `band`, `health_context`, `controller`, `item_count`, `caller_masked`) plus
`tenant_id`, `caller`, `external_ref` and two more:

| field | type | meaning |
|---|---|---|
| `notes` | string null | the call notes for this conversation, shown under `scripts.notes_label` above the messages [N1] |
| `notes_at` | date-time null | when the drafting ran; set even when `notes` is null, because that is the mark that says the drafting happened and will not happen again [N1] |

The list endpoint `GET /internal/tenants/{id}/conversations` returns `ConversationRow` and
carries neither field: a page of rows is a list, and the notes are read on the page that
shows the transcript beside them. Reading a conversation still writes a `read_transcript`
audit row; reading a page of items still does not.

## Provider payload shapes for fixtures

These are the shapes the tests replay. They match the providers' documented formats as of 2026-09; if a provider test fails on a field name, check the current doc and fix the fixture, not the parser's intent.

### Telnyx TeXML voice webhook (form-encoded POST to /telnyx/texml)

```
CallSid=v3:abc...&From=%2B19055550101&To=%2B19055550100&Direction=inbound&CallStatus=ringing&AccountSid=...
```

### Telnyx media stream start message (first JSON frame on the WebSocket, parsed by Pipecat)

```json
{"event": "start", "sequence_number": "1", "stream_id": "b7a1...", "start": {"user_id": "...", "call_control_id": "v3:abc...", "client_state": null, "media_format": {"encoding": "PCMU", "sample_rate": 8000, "channels": 1}, "from": "+19055550101", "to": "+19055550100"}}
```

### Telnyx messaging webhook (JSON POST; headers `telnyx-signature-ed25519`, `telnyx-timestamp`)

```json
{"data": {"event_type": "message.received", "id": "evt-uuid", "occurred_at": "2026-09-02T14:00:00.000Z",
  "payload": {"id": "msg-uuid", "direction": "inbound", "type": "SMS", "text": "How much is a facial?",
    "from": {"phone_number": "+19055550101", "carrier": "Rogers", "line_type": "Wireless"},
    "to": [{"phone_number": "+18885550100", "status": "webhook_delivered"}],
    "received_at": "2026-09-02T14:00:00.000Z", "messaging_profile_id": "..."}}}
```

Signature: Ed25519 over `"{timestamp}|{raw_body}"`, base64 in the header; verify with the account public key; reject if `|now - timestamp| > 300 s`.

### Slack block_actions (form field `payload`, JSON)

```json
{"type": "block_actions", "user": {"id": "U1", "username": "dana"}, "channel": {"id": "C1"}, "message": {"ts": "1712.000100"},
 "actions": [{"action_id": "resolve", "value": "4821", "type": "button"}], "response_url": "https://hooks.slack.com/actions/..."}
```

### Slack Events API (JSON)

```json
{"type": "url_verification", "challenge": "abc"}
{"type": "event_callback", "event_id": "Ev1", "event": {"type": "message", "channel": "C1", "user": "U1", "text": "On my way, calling her now", "ts": "1712.000200", "thread_ts": "1712.000100"}}
```

### Instagram webhook (JSON POST; header `X-Hub-Signature-256: sha256=<hmac>`)

Comment:
```json
{"object": "instagram", "entry": [{"id": "17841400000000000", "time": 1756800000,
  "changes": [{"field": "comments", "value": {"id": "17900000000000001", "text": "how much?",
    "from": {"id": "9000000000000001", "username": "dana.w"}, "media": {"id": "17800000000000001", "media_product_type": "FEED"}}}]}]}
```

Direct message (and echo):
```json
{"object": "instagram", "entry": [{"id": "17841400000000000", "time": 1756800000,
  "messaging": [{"sender": {"id": "9000000000000001"}, "recipient": {"id": "17841400000000000"}, "timestamp": 1756800000000,
    "message": {"mid": "aWdfZAG1...", "text": "Are you open Sunday?"}}]}]}
```
An echo has `"message": {"mid": "...", "text": "...", "is_echo": true}` with sender equal to the account id. Postback: `"postback": {"mid", "title", "payload"}`. Read: `"read": {"mid"}`.

### Messenger (Page) webhook

```json
{"object": "page", "entry": [{"id": "1234567890", "time": 1756800000,
  "messaging": [{"sender": {"id": "PSID"}, "recipient": {"id": "1234567890"}, "timestamp": 1756800000000, "message": {"mid": "m_...", "text": "hi"}}]}]}
{"object": "page", "entry": [{"id": "1234567890", "time": 1756800000,
  "changes": [{"field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "1234567890_111", "post_id": "1234567890_222", "from": {"id": "999", "name": "Dana W"}, "message": "how much?"}}]}]}
```

### Graph API sends

- Instagram DM or private reply: `POST https://graph.instagram.com/v21.0/{ig_user_id}/messages` with `{"recipient": {"id": "<sender>"}}` or `{"recipient": {"comment_id": "<comment>"}}`, `"message": {"text": "..."}`; bearer token.
- Instagram public reply: `POST https://graph.instagram.com/v21.0/{comment_id}/replies` `{"message": "..."}`.
- Page message: `POST https://graph.facebook.com/v21.0/{page_id}/messages` `{"recipient": {"id": "<PSID>"}, "messaging_type": "RESPONSE", "message": {"text": "..."}}`.
- Page private reply to a comment: `POST https://graph.facebook.com/v21.0/{comment_id}/private_replies` `{"message": "..."}`; public: `POST /{comment_id}/comments`.
- Token refresh: `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=...`.
- WhatsApp staff message [W1]: `POST https://graph.facebook.com/v21.0/{phone_number_id}/messages`, bearer token, body always carrying `"messaging_product": "whatsapp"`, `"recipient_type": "individual"` and `"to"` in E.164. Three shapes: `"type": "text"` with `{"text": {"preview_url": false, "body": "..."}}`; `"type": "interactive"` with `{"interactive": {"type": "button", "body": {"text": "..."}, "action": {"buttons": [{"type": "reply", "reply": {"id": "ack:<token>", "title": "Acknowledge"}}]}}}` (max 3 buttons, title max 20 chars, id max 256, body max 1,024); `"type": "template"` with `{"template": {"name": "front_desk_item", "language": {"code": "en"}, "components": [{"type": "body", "parameters": [{"type": "text", "text": "..."}]}, {"type": "button", "sub_type": "quick_reply", "index": "0", "parameters": [{"type": "payload", "payload": "ack:<token>"}]}]}}`. A template parameter may not contain a newline, a tab or a run of more than four spaces. The answer is `{"messages": [{"id": "wamid...."}]}`. Text and interactive are legal only inside the 24-hour customer-service window (`whatsapp_windows`); outside it, only the approved template.

### Stripe webhook events used
`checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`. Verify with `STRIPE_WEBHOOK_SECRET`.

## Environment variables, complete

Runtime `runtime/.env`:

| variable | plan | required for |
|---|---|---|
| DATABASE_URL, TEST_DATABASE_URL | A | always |
| POSTGRES_PASSWORD, DB_BIND | deploy prep 2026-09-06 | the `db` container: Compose reads them for `${...}`; the password is what the volume is initialised with and what both in-network DATABASE_URLs carry; DB_BIND is the host address Postgres is published on (loopback unless a developer VM needs 0.0.0.0) |
| PUBLIC_BASE_URL, MEDIA_WS_HOST, API_HOST, MEDIA_HOST, SECRET_KEY | A | always |
| TELNYX_API_KEY | A | voice, SMS |
| TELNYX_PUBLIC_KEY | B | SMS without the edge worker |
| EDGE_SHARED_KEY | B | edge worker and chat fallback |
| SONIOX_API_KEY, SONIOX_VOICE, STT_PROVIDER | A | voice |
| INWORLD_API_KEY, INWORLD_VOICE, INWORLD_MODEL, TTS_PROVIDER | A | voice |
| DEEPGRAM_API_KEY | A | bake-off only |
| GOOGLE_API_KEY, LLM_MODEL | A | always |
| OPENAI_API_KEY | E6 | second vendor only |
| LLM_MODEL_FALLBACK | F1 | the second model every turn falls back to, same `vendor:model` syntax as LLM_MODEL. **Empty by default and empty means no failover** — today's behaviour exactly. `LLM_MODEL_FALLBACK=openai:gpt-4.1-mini` plus `OPENAI_API_KEY` is what activates it, on the phone and on text at once. |
| LLM_BREAKER_FAILURES, LLM_BREAKER_WINDOW_SECS, LLM_BREAKER_COOLDOWN_SECS | F1 | when a vendor is treated as down (defaults 3 failures in 60 s, avoided for 300 s) |
| OPENROUTER_API_KEY, DEEPSEEK_API_KEY, XAI_API_KEY, GROQ_API_KEY, TOGETHER_API_KEY, FIREWORKS_API_KEY, DASHSCOPE_API_KEY, COMPAT_API_KEY | F1 | one per OpenAI-compatible vendor; needed only for a vendor LLM_MODEL or LLM_MODEL_FALLBACK actually names. Prefixes and default hosts: `openai:` api.openai.com/v1, `openrouter:` openrouter.ai/api/v1, `deepseek:` api.deepseek.com/v1, `xai:` api.x.ai/v1, `groq:` api.groq.com/openai/v1, `together:` api.together.xyz/v1, `fireworks:` api.fireworks.ai/inference/v1, `dashscope:` dashscope-us.aliyuncs.com/compatible-mode/v1 (Alibaba's Qwen, US endpoint), `compat:` whatever LLM_COMPAT_BASE_URL names. A bare name is still Google. |
| LLM_OPENAI_BASE_URL, LLM_OPENROUTER_BASE_URL, LLM_DEEPSEEK_BASE_URL, LLM_XAI_BASE_URL, LLM_GROQ_BASE_URL, LLM_TOGETHER_BASE_URL, LLM_FIREWORKS_BASE_URL, LLM_DASHSCOPE_BASE_URL, LLM_COMPAT_BASE_URL | F1 | each vendor's host, overriding the built-in default, so a region change is an environment value too (`LLM_DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1` moves Qwen to Singapore; measured from the founder's laptop 2026-09-03, the US endpoint connects as fast as Google's and the Singapore one took 1.2 s). LLM_COMPAT_BASE_URL is the only one with no default: `compat:` has nothing sensible to fall back to and raises without it. |
| JUDGE_MODEL | E4 | nightly audit (defaults to gemini-3.5-flash-lite, the voice model, since gemini-2.5-flash went 404 on the founder's key on 2026-09-05; thinking enabled: `thinking_budget=-1`). gemini-2.5-pro is not available on the founder's Google AI Studio key (404 "no longer available to new users", promptfoo run A 2026-09-02), and Flash with thinking on judges band boundaries as well at a fraction of the cost. |
| SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_FROM | A | email delivery |
| SLACK_SIGNING_SECRET | A | Slack buttons |
| SLACK_BOT_TOKEN | B5 | threads and takeover |
| `<TENANT>_SLACK_WEBHOOK` per tenant | A | Slack delivery without bot token |
| TURNSTILE_SITE_KEY, TURNSTILE_SECRET_KEY | B4 | widget |
| INTERNAL_API_KEY | C3 | portal |
| INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET, FACEBOOK_APP_ID, FACEBOOK_APP_SECRET, INSTAGRAM_WEBHOOK_VERIFY_TOKEN, META_TOKEN_ENCRYPTION_KEY, META_GRAPH_VERSION | D | social |
| WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN, WHATSAPP_TEMPLATE_ITEM, WHATSAPP_TEMPLATE_DIGEST, WHATSAPP_TEMPLATE_LANG | W1 | WhatsApp staff delivery |
| `<TENANT>_WHATSAPP_STAFF` per tenant | W1 | the staff E.164 a `whatsapp` destination names; never written into a bundle |
| `<TENANT>_STAFF_SMS` per tenant | S1, S2 | the owner E.164 an `sms` destination names; tracked items and the digest are texted to it from `sms_from_number`, and its replies may acknowledge and resolve; never written into a bundle |
| OPS_EMAIL, OPS_SMS_NUMBER, SENTRY_DSN, LOG_FORMAT | E7 | operations |
| GIT_COMMIT | E7 | reported by `/healthz`; baked in by the image build (`scripts/deploy.sh`), never a `.env` line, because an env_file line overrides the image's value even when empty |
| R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT, R2_BUCKET | E2 | backups (WAL-G reads them as AWS_* in `walg.env`) |

Portal `portal/.env.server`: DATABASE_URL, JWT_SECRET, WASP_WEB_CLIENT_URL, WASP_SERVER_URL, ADMIN_EMAILS, SMTP_*, MAIL_FROM, STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID_FRONTDESK, STRIPE_CUSTOMER_PORTAL_URL, RUNTIME_INTERNAL_URL, RUNTIME_INTERNAL_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET. `portal/.env.client`: REACT_APP_API_URL (Wasp sets), nothing secret.

Edge `wrangler secret put`: EDGE_SHARED_KEY, TELNYX_PUBLIC_KEY, TELNYX_API_KEY; var RUNTIME_URL in `wrangler.toml`. Deploy needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID on the machine running `wrangler`.

CI secrets: GOOGLE_API_KEY (promptfoo), optionally OPENAI_API_KEY, SONIOX_API_KEY, INWORLD_API_KEY, TELNYX_API_KEY for nightly voice evals.
