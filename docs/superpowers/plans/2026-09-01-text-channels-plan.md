# Text Channels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is written at contract level: each task states files, exact interfaces, behaviours and the tests that prove them. Write the tests first from the behaviour list, see them fail, then implement.

**Goal:** SMS and web chat answer from the same brain as voice, survive the platform being down, follow up once when a conversation goes quiet, text back a missed caller, and step aside when a human joins.

**Architecture:** A Cloudflare Worker fronts the Telnyx SMS webhook and auto-replies with tenant wording if the runtime is unreachable, replaying later. The runtime gains a `TextConversationService` that all text channels share (SMS now, chat now, Instagram in the next plan): it finds or creates the conversation, loads history, calls `Brain.turn`, persists, sends, schedules the single follow-up, and defers to a human when the conversation is under staff control. Slack delivery moves from webhooks to the bot API so each conversation has a thread staff can reply in.

**Tech Stack:** as the runtime plan, plus Cloudflare Workers (TypeScript, wrangler, vitest with `@cloudflare/vitest-pool-workers`), `tweetnacl` or WebCrypto Ed25519 for Telnyx signatures, Slack Web API via `slack_sdk`, Cloudflare Turnstile, a vanilla-JS widget.

**Spec:** `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md` §3 (adapters, fallback), §4 decision 12.7, brief §4.1, §4.2 (follow-up, steps aside), §4.4. Depends on the runtime plan Tasks 1 to 14 being complete.

## Global Constraints

- Everything in the runtime plan's Global Constraints.
- SMS replies are at most 300 characters and contain no markdown; if the brain returns more, split at a sentence boundary into at most two messages, never truncate mid-sentence.
- One follow-up per conversation, ever. Enforced by a column, not by a scheduler's memory.
- STOP, UNSUBSCRIBE, CANCEL, END, QUIT opt a number out for that tenant permanently until START or UNSTOP; nothing is ever sent to an opted-out number, including missed-call text-backs.
- The Worker never replies twice to the same Telnyx message id, and never replies at all when the runtime accepted the message.
- Staff-relayed text is sent verbatim and stored with role `staff`; the model never sees it as its own words.
- New fixed wording lives in `scripts.yaml`: `followup`, `missed_call_text`, `chat_greeting`, `link_shown`, `optout_confirm`, `help_text`, `takeover_notice`.

## File Structure

```
edge/sms-worker/
  wrangler.toml                  KV: TENANT_TEXTS, PENDING; cron */5; vars RUNTIME_URL
  src/index.ts                   fetch: /telnyx/sms, /chat/fallback, /admin/tenant-texts; scheduled: replay
  src/telnyx-signature.ts        verifyTelnyxSignature(rawBody, signatureB64, timestamp, publicKeyB64, toleranceSec)
  test/*.test.ts
runtime/spatalk/
  settings.py                    + edge_shared_key, telnyx_public_key, turnstile_secret_key, slack_bot_token
  tenants/schema.py              + Scripts fields above; Destination.channel_id; Delivery.staff_phone_numbers (exists)
  models.py                      + inbound_messages, sms_optouts, textbacks; conversations: last_message_at, followup_sent_at, closed_at, slack_channel, slack_ts, external_session
  text/__init__.py
  text/service.py                TextConversationService
  text/sms.py                    router: POST /telnyx/sms, staff-SMS relay
  text/chat.py                   router: GET /widget.js, GET /widget/{tenant_id}/config, WS /chat/ws, POST /chat/fallback
  text/textback.py               schedule_missed_call_textback(), job handler sms.textback
  text/takeover.py               relay_from_staff(), set_controller(), mirror_to_thread()
  text/segments.py               split_sms(text, limit=300) -> list[str]
  http/slack_events.py           POST /slack/events (url_verification, message events)
  ledger/delivery.py             + SlackBotDelivery (chat.postMessage, thread_ts), handback button
  static/widget.js               the widget
  voice/pipeline.py              _finalize: call schedule_missed_call_textback
  brain/prompt.py                channel rules for sms and chat
  brain/tier_c.py                send_booking_link on chat returns LinkSent without SMS
  brain/renderer.py              LinkSent on chat -> scripts.link_shown
runtime/tests/test_text_*.py, test_slack_events.py, test_widget.py
docs/runbooks/widget-install.md
```

---

### Task B1: Cloudflare Worker in front of the SMS webhook

**Files:** `edge/sms-worker/{wrangler.toml, package.json, tsconfig.json, src/index.ts, src/telnyx-signature.ts, test/index.test.ts, test/signature.test.ts}`

**Interfaces:**
- Env bindings: `RUNTIME_URL`, `EDGE_SHARED_KEY` (secret), `TELNYX_PUBLIC_KEY` (secret), `TELNYX_API_KEY` (secret), KV `TENANT_TEXTS`, KV `PENDING`.
- `TENANT_TEXTS` value shape per key `<to E.164>`: `{"tenant_id": str, "from": str, "text": str}`.
- Produces HTTP: `POST /telnyx/sms`, `POST /chat/fallback`, `PUT /admin/tenant-texts` (body `{ "<number>": {...} }`, requires `X-Edge-Key`).

**Behaviour:**
1. `POST /telnyx/sms`: read raw body; verify Telnyx Ed25519 signature from headers `telnyx-signature-ed25519` and `telnyx-timestamp` against `TELNYX_PUBLIC_KEY` with 300 s tolerance; on failure respond 401 and do nothing else.
2. Forward the raw body to `${RUNTIME_URL}/telnyx/sms` with headers `Content-Type: application/json`, `X-Edge-Key`, and the original two Telnyx headers, timeout 8 s. On 2xx respond 200.
3. On timeout or non-2xx: if `data.event_type == "message.received"`, look up `TENANT_TEXTS[to]`; if present and `PENDING` has no `replied:<message_id>`, send the auto-reply through `POST https://api.telnyx.com/v2/messages` `{from, to: sender, text}` and store `replied:<message_id>` with 7-day TTL. Always store the event under `pending:<message_id>` with a 24 h TTL. Respond 200 (Telnyx must not retry into a second reply).
4. `scheduled` (every 5 minutes): list `pending:*`, re-forward each; delete on 2xx; leave otherwise.
5. `POST /chat/fallback`: forward to `${RUNTIME_URL}/chat/fallback` with `X-Edge-Key`; on failure store under `pending:chat:<uuid>` and respond 202 with `{"queued": true}`.
6. `PUT /admin/tenant-texts`: requires `X-Edge-Key`; replaces the KV entries given.

**Tests (vitest):** valid signature forwards and returns 200 with no auto-reply; invalid signature 401 and no fetch to runtime; runtime 503 triggers exactly one auto-reply and one pending entry; the same message id a second time triggers no second reply; scheduled replay deletes pending on 2xx and keeps it on 5xx; `/chat/fallback` queues on failure; admin endpoint rejects without key.

**Done when:** `npm test` passes and `npx wrangler deploy --dry-run` succeeds. Commit `feat(edge): sms webhook worker with offline auto-reply and replay`.

---

### Task B2: Text conversation service and the SMS adapter

**Files:** `runtime/spatalk/text/{__init__.py, service.py, sms.py, segments.py}`, `runtime/spatalk/models.py`, `runtime/spatalk/settings.py`, `runtime/spatalk/tenants/schema.py`, `runtime/tenants/skincentrix/scripts.yaml`, `runtime/spatalk/brain/prompt.py`, `runtime/alembic/versions/0002_text_channels.py`, `runtime/tests/test_text_service.py`, `runtime/tests/test_text_sms.py`, `runtime/tests/test_segments.py`

**Interfaces:**
- `split_sms(text: str, limit: int = 300) -> list[str]` (at most 2 parts, sentence-boundary split, never mid-word).
- `class TextConversationService:`
  - `__init__(self, ctx: JobContext, llm: LLMClient)`
  - `async def handle_inbound(self, tenant_id: str, channel: Literal["sms","chat","instagram","messenger"], external_id: str, sender: str | None, text: str, provider_message_id: str | None) -> InboundResult` where `InboundResult(conversation_id: UUID, replies: list[str], turn: TurnResult | None, suppressed: bool, reason: str | None)`.
  - `async def find_or_create_conversation(self, tenant_id, channel, external_id, sender) -> Conversation` (reuse if `last_message_at` within 24 h and not closed).
  - `async def history(self, conversation_id, limit=20) -> list[dict]` (roles user/assistant only; staff messages appear as `{"role": "assistant", "content": "<staff said> ..."}`? No: staff messages are excluded from model history and the model is told the conversation was handled by a person).
  - `async def schedule_followup(self, conversation)` and job handler `text.followup`.
- `models`: `InboundMessage(provider_message_id unique, tenant_id, channel, received_at)`, `SmsOptout(tenant_id, phone, created_at, pk (tenant_id, phone))`, `Textback(tenant_id, phone, sent_at)`; `Conversation` gains `last_message_at`, `followup_sent_at`, `closed_at`, `external_session`.
- Settings: `edge_shared_key: str = ""`, `telnyx_public_key: str = ""`.
- Router `POST /telnyx/sms`.

**Behaviour:**
1. `POST /telnyx/sms` accepts when `X-Edge-Key` equals `settings.edge_shared_key` (constant-time), or, if no edge key configured and `settings.telnyx_public_key` is set, when the Telnyx signature verifies. Otherwise 401.
2. Only `message.received` events are handled; others return 200 with no action. Duplicate `payload.id` returns 200 with no action.
3. Tenant is resolved by `payload.to[0].phone_number`; unknown numbers return 200 and log.
4. Keyword handling before the brain (case-insensitive, trimmed): STOP family → insert optout, reply `scripts.optout_confirm`, close conversation. START/UNSTOP → delete optout, reply `scripts.help_text`. HELP → reply `scripts.help_text`.
5. Opted-out senders receive nothing, ever; the inbound message is still stored.
6. Otherwise `handle_inbound` runs the brain with the last 20 messages as history and the channel `sms`; the reply is split with `split_sms` and each part is sent through `TelnyxSms` from the tenant's `sms_from_number`; usage events `sms_in` (1) and `sms_out` (parts) recorded; messages persisted with roles user/assistant; `health_context` propagated to the conversation.
7. If `turn.ended`, `closed_at` is set. If the reply ends with a question mark and no item was created in this conversation and `followup_sent_at` is null, a `text.followup` job is enqueued for 2 h later (if that lands after 21:00 or before 09:00 tenant time, move to 09:00 next business day via `BusinessCalendar.next_open`). The handler sends `scripts.followup` only if no user message arrived after the assistant's last message, then sets `followup_sent_at`.
8. If `conversation.controller == "human"`, the brain is not called; the message is stored and mirrored to staff (Task B5); `suppressed=True, reason="human"`.
9. Prompt rule for `channel == "sms"`: "Reply in under 300 characters, plain text, no lists." For `chat`: "Reply in under 500 characters, plain text."

**Tests:** segment splitting (short passes through; 450 chars splits into two at a sentence end; a 700-char reply yields two parts and logs the rest dropped); edge key accepted, wrong key 401; duplicate id ignored; STOP writes optout and confirms; opted-out sender gets no reply; a `FakeLLM` reply is sent and stored; second message within 24 h joins the same conversation, after 25 h starts a new one; follow-up job enqueued exactly once and not sent when the user replied; controller=human suppresses the brain.

**Done when:** tests pass, migration applies on a fresh DB, `ruff` clean. Commit `feat(text): shared text conversation service and telnyx sms adapter with opt-out and single follow-up`.

---

### Task B3: Missed-call text-back

**Files:** `runtime/spatalk/text/textback.py`, `runtime/spatalk/voice/pipeline.py` (`_finalize`), `runtime/tenants/skincentrix/scripts.yaml` (`missed_call_text`), `runtime/tests/test_textback.py`

**Interfaces:**
- `async def schedule_missed_call_textback(ctx, session: VoiceSession, had_user_speech: bool, duration_s: float) -> bool` (returns whether a job was enqueued); job handler `sms.textback` with payload `{tenant_id, to, conversation_id}`.

**Behaviour:**
1. Enqueue only when all hold: caller phone present; caller is not the tenant's `public_phone` and not one of the tenant's own numbers (caller-id-lost case); tenant has `sms_from_number`; caller not opted out; no `Textback` row for (tenant, phone) in the last 24 h; and either `duration_s < 20` or no user transcription was received.
2. The handler sends `scripts.missed_call_text` rendered with `{name}` and `{booking_url}` (`booking_url_default`), records a `Textback` row and usage `sms_out`, and links the SMS conversation to the voice conversation by storing the voice `conversation_id` in the new SMS conversation's `external_session`.
3. If the caller later replies, the SMS adapter continues the conversation normally.

**Tests:** sent once for a 5-second hang-up; not sent after a full conversation; not sent twice within 24 h; not sent to an opted-out number; not sent when the caller id equals the clinic's public phone; not sent when the tenant has no SMS number.

**Done when:** tests pass. Commit `feat(text): missed-call text-back, once per caller per day`.

---

### Task B4: Web chat widget and fallback form

**Files:** `runtime/spatalk/text/chat.py`, `runtime/spatalk/static/widget.js`, `runtime/spatalk/settings.py` (`turnstile_secret_key`), `runtime/tenants/skincentrix/scripts.yaml` (`chat_greeting`, `link_shown`), `runtime/spatalk/brain/tier_c.py`, `runtime/spatalk/brain/renderer.py`, `runtime/tests/test_widget.py`, `docs/runbooks/widget-install.md`

**Interfaces:**
- `GET /widget.js` (cache 1 h), `GET /widget/{tenant_id}/config` → `{name, greeting, accent, turnstile_site_key}`.
- `WS /chat/ws?tenant=<id>&session=<uuid>&turnstile=<token>`; client sends `{"type":"message","text":...}`; server sends `{"type":"reply","text":...}`, `{"type":"typing"}`, `{"type":"ended"}`, `{"type":"staff","text":...}` (Task B5).
- `POST /chat/fallback` JSON `{tenant_id, name, contact, message, session}` → creates conversation (channel chat), stores the message as a user message, creates an item of type `callback` with the contact (the message body is never copied into the item), returns `{"ok": true}`.
- Tier C: `send_booking_link` when `ref.channel in ("chat", "instagram", "messenger")` returns `LinkSent(service_id, url)` without sending SMS; renderer uses `scripts.link_shown` (`"Here is the booking link for {service}: {url}"`) for those channels and `scripts.link_sent` for voice and SMS.

**Behaviour:**
1. On WS connect, verify the Turnstile token against `https://challenges.cloudflare.com/turnstile/v0/siteverify` when `turnstile_secret_key` is set; reject with close code 4401 otherwise. In tests the verifier is injected.
2. Each message goes through `TextConversationService.handle_inbound(channel="chat", external_id=session, sender=None, ...)`. Replies are sent as `reply` frames. `ended` closes the socket after the goodbye.
3. Per-IP limits: 5 new sessions per minute, 30 messages per minute; excess gets close code 4429.
4. The widget: floating button, panel, greeting from config, message list, input, reconnect up to 3 times, then shows the fallback form (name, phone or email, message) posting to `/chat/fallback` through the Worker URL if configured else directly. No third-party assets; inline CSS; respects `prefers-color-scheme`.
5. `docs/runbooks/widget-install.md`: the Squarespace code-injection snippet `<script src="https://api.<domain>/widget.js" data-tenant="skincentrix" defer></script>` and how to change the accent colour.

**Tests:** config endpoint; WS round trip with `FakeLLM`; Turnstile rejection; rate limit close code; fallback creates conversation, message and a `callback` item with no message text on the item; chat booking link renders inline without SMS.

**Done when:** tests pass; opening `widget.js` in a browser against a local runtime shows the greeting and a reply. Commit `feat(text): web chat widget over websocket with turnstile and fallback form`.

---

### Task B5: Human takeover through Slack threads and staff SMS

**Files:** `runtime/spatalk/ledger/delivery.py` (`SlackBotDelivery`), `runtime/spatalk/http/slack_events.py`, `runtime/spatalk/http/slack.py` (`handback` action), `runtime/spatalk/text/takeover.py`, `runtime/spatalk/text/sms.py` (staff relay), `runtime/spatalk/models.py` (conversation `slack_channel`, `slack_ts`), `runtime/tenants/skincentrix/tenant.yaml` (destination `channel_id`), `runtime/tests/test_takeover.py`, `runtime/tests/test_slack_events.py`

**Interfaces:**
- `Destination` gains `channel_id: str | None` (Slack channel id, used with the bot token).
- `SlackBotDelivery(settings)` implements `DeliveryPort.send_slack` plus `post_thread_root(channel_id, blocks, text) -> ts` and `post_in_thread(channel_id, thread_ts, text)`; selected when `settings.slack_bot_token` is set, else `HttpSlackEmailDelivery` webhook behaviour.
- `takeover.set_controller(sf, conversation_id, controller: Literal["ai","human","closed"], by: str)`, `takeover.relay_from_staff(ctx, conversation_id, text, staff_id) -> None`, `takeover.mirror_to_thread(ctx, conversation_id, text, who: Literal["customer","assistant"])`.
- `POST /slack/events`: handles `url_verification` and `event_callback` with `event.type == "message"`.

**Behaviour:**
1. When the first item of a conversation is delivered to Slack with a bot token, the root message is posted with `chat.postMessage` in `destination.channel_id`; its `ts` and channel are stored on the conversation; later items and every customer and assistant message of that conversation are posted in the thread (`mirror_to_thread`). Without a bot token, behaviour is unchanged (webhook, no thread).
2. A human message in that thread (not from the bot, `thread_ts` matches a conversation) sets `controller=human`, stores it with role `staff`, and relays it to the customer on the original channel: SMS via `TelnyxSms`, chat via the open socket (or stored for the next connect), Instagram in the next plan. The first relay also posts `scripts.takeover_notice` to the customer? No: the staff message itself is the notice; nothing generated is sent.
3. While `controller=human`, customer messages are stored and mirrored, and the brain is not called. A "Hand back to assistant" button (`action_id=handback`) on the thread root sets `controller=ai`. After 12 h without a staff message, a scheduled job sets `controller=ai` and posts a note in the thread.
4. Staff SMS relay: an inbound SMS whose sender is in `delivery.staff_phone_numbers` and whose text starts with `#<item_id>` relays the remainder to that item's conversation and sets `controller=human`; any other staff SMS gets `scripts.help_text`.
5. Signature verification on `/slack/events` uses the same `SignatureVerifier`; retries (header `X-Slack-Retry-Num`) are acknowledged without reprocessing (dedup on `event_id`).

**Tests:** url_verification echoes challenge; bot's own messages ignored; staff thread reply relays via `MemorySms` and pauses the brain; customer message while paused is mirrored and gets no bot reply; handback resumes; 12 h auto hand-back; staff `#123 on my way` relays; unknown staff format gets help text; without bot token, delivery still works via webhook.

**Done when:** tests pass. Commit `feat(text): human takeover via slack threads and staff sms, with hand-back`.

---

### Task B6: Text scenarios, edge tests in CI, tenant-text sync

**Files:** `runtime/scenarios/promptfooconfig.yaml`, `runtime/scenarios/asserts.py`, `runtime/spatalk/cli.py` (`edge sync-texts`), `.github/workflows/ci.yml`

**Behaviour:**
1. Scenarios with `channel: sms`: price question (reply under 300 chars, no markdown, python assert `sms_brevity`), cancellation (captured wording under 300), clinical (gate), STOP is handled before the brain (deterministic pytest, not promptfoo).
2. Scenarios with `channel: chat`: booking link shown inline; contact capture flow across two turns using `history`.
3. `spatalk edge sync-texts` pushes `{number: {tenant_id, from, text}}` for every tenant with an SMS number to the Worker's admin endpoint using `EDGE_SHARED_KEY`; the text is `scripts.missed_call_text`'s sibling `scripts.offline_reply` (add it: "Thanks for texting {name}. We'll reply shortly. To book now: {booking_url}").
4. CI: add a job that runs `npm ci && npm test` in `edge/sms-worker`.

**Done when:** promptfoo passes with a key; CI green. Commit `test(text): sms and chat scenarios; ci for the edge worker; tenant text sync`.

---

## Self-review against the spec

- Brief §4.1 SMS two-way and web chat: B2, B4. §4.2 single follow-up: B2 step 7 with the `followup_sent_at` column. §4.2 steps aside when a human joins: B5. §4.2 honours request for a human on every channel: the rules gate runs inside `Brain.turn` for every channel.
- Spec decision 12.7 (down-time fallback outside the system): B1 Worker with auto-reply and replay; chat fallback form through the same Worker (B4).
- Spec §8 missed-call text-back and caller-id-lost handling: B3.
- Data minimisation: the fallback form's free text goes to the transcript, not the item (B4). Staff text is stored as `staff`, never fed back as the model's own words (B2, B5).
- Compliance: opt-out handling is permanent per tenant and enforced before any send (B2, B3).
