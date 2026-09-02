# API surface, provider payload shapes, environment variables

## HTTP and WebSocket endpoints

All on the runtime unless marked portal or edge. Auth column says what proves the caller.

| Method and path | Plan | Auth | Purpose |
|---|---|---|---|
| GET /healthz | A14, E7 | none | ok, tenants, config versions, commit, queue and scheduler health |
| POST /telnyx/texml | A13, E1 | Telnyx-only URL; loop guard | answers a call with TeXML `<Connect><Stream>` |
| WS /ws/{token} | A13 | signed stream token, 5 min | Telnyx bidirectional audio |
| GET /a/{token} | A9 | signed action link, 7 days | confirm page (never acts) or transcript view |
| POST /a/{token} | A9 | same | acknowledge or resolve |
| POST /slack/interactions | A9 | Slack signing secret | button callbacks: ack, resolve, handback |
| POST /slack/events | B5 | Slack signing secret | url_verification, thread replies from staff |
| POST /telnyx/sms | B2 | `X-Edge-Key` or Telnyx Ed25519 signature | inbound SMS |
| GET /widget.js | B4 | none | the chat widget |
| GET /widget/{tenant_id}/config | B4 | none | name, greeting, Turnstile site key |
| WS /chat/ws?tenant&session&turnstile | B4 | Turnstile token | web chat |
| POST /chat/fallback | B4 | `X-Edge-Key` or Turnstile | contact form when the socket fails |
| GET /instagram/connect, /callback | D1 | signed state | Instagram Business Login |
| GET, POST /instagram/webhook | D2 | verify token; HMAC-SHA256 | Meta events |
| POST /instagram/deauthorize, /delete | D1 | signed_request | Meta platform requirements |
| GET /messenger/connect, /callback; GET, POST /messenger/webhook | D3 | as Instagram | Facebook Page |
| /internal/* | C3, D4, E4 | `X-Internal-Key`, `X-Actor` | portal's only way in; see the portal plan for the full list |
| edge: POST /telnyx/sms, POST /chat/fallback, PUT /admin/tenant-texts | B1 | Telnyx signature; `X-Edge-Key` | fallback front door |
| portal: /login, /signup, /invite/:token, /app/:orgSlug/*, /admin/*, /privacy, /payments-webhook | C1 to C6 | Wasp session; Stripe signature | |

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
| PUBLIC_BASE_URL, MEDIA_WS_HOST, API_HOST, MEDIA_HOST, SECRET_KEY | A | always |
| TELNYX_API_KEY | A | voice, SMS |
| TELNYX_PUBLIC_KEY | B | SMS without the edge worker |
| EDGE_SHARED_KEY | B | edge worker and chat fallback |
| SONIOX_API_KEY, STT_PROVIDER | A | voice |
| INWORLD_API_KEY, INWORLD_VOICE, INWORLD_MODEL, TTS_PROVIDER | A | voice |
| DEEPGRAM_API_KEY | A | bake-off only |
| GOOGLE_API_KEY, LLM_MODEL | A | always |
| OPENAI_API_KEY | E6 | second vendor only |
| JUDGE_MODEL | E4 | nightly audit (defaults to gemini-2.5-flash, thinking enabled: `thinking_budget=-1`). gemini-2.5-pro is not available on the founder's Google AI Studio key (404 "no longer available to new users", promptfoo run A 2026-09-02), and Flash with thinking on judges band boundaries as well at a fraction of the cost. |
| SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_FROM | A | email delivery |
| SLACK_SIGNING_SECRET | A | Slack buttons |
| SLACK_BOT_TOKEN | B5 | threads and takeover |
| `<TENANT>_SLACK_WEBHOOK` per tenant | A | Slack delivery without bot token |
| TURNSTILE_SITE_KEY, TURNSTILE_SECRET_KEY | B4 | widget |
| INTERNAL_API_KEY | C3 | portal |
| INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET, FACEBOOK_APP_ID, FACEBOOK_APP_SECRET, INSTAGRAM_WEBHOOK_VERIFY_TOKEN, META_TOKEN_ENCRYPTION_KEY, META_GRAPH_VERSION | D | social |
| WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN, WHATSAPP_TEMPLATE_ITEM, WHATSAPP_TEMPLATE_DIGEST, WHATSAPP_TEMPLATE_LANG | W1 | WhatsApp staff delivery |
| `<TENANT>_WHATSAPP_STAFF` per tenant | W1 | the staff E.164 a `whatsapp` destination names; never written into a bundle |
| `<TENANT>_STAFF_SMS` per tenant | S1 | the owner E.164 an `sms` destination names; tracked items and the digest are texted to it from `sms_from_number`; never written into a bundle |
| OPS_EMAIL, OPS_SMS_NUMBER, SENTRY_DSN, LOG_FORMAT, GIT_COMMIT | E7 | operations |
| R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT, R2_BUCKET | E2 | backups (WAL-G reads them as AWS_* in `walg.env`) |

Portal `portal/.env.server`: DATABASE_URL, JWT_SECRET, WASP_WEB_CLIENT_URL, WASP_SERVER_URL, ADMIN_EMAILS, SMTP_*, MAIL_FROM, STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID_FRONTDESK, STRIPE_CUSTOMER_PORTAL_URL, RUNTIME_INTERNAL_URL, RUNTIME_INTERNAL_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET. `portal/.env.client`: REACT_APP_API_URL (Wasp sets), nothing secret.

Edge `wrangler secret put`: EDGE_SHARED_KEY, TELNYX_PUBLIC_KEY, TELNYX_API_KEY; var RUNTIME_URL in `wrangler.toml`. Deploy needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID on the machine running `wrangler`.

CI secrets: GOOGLE_API_KEY (promptfoo), optionally OPENAI_API_KEY, SONIOX_API_KEY, INWORLD_API_KEY, TELNYX_API_KEY for nightly voice evals.
