# SMS Flood Guard Implementation Plan

> **For agentic workers:** contract level: files, exact interfaces, behaviours, tests. Tests first (write the test, see it fail, make it pass, commit). Use superpowers:subagent-driven-development or superpowers:executing-plans task by task. Read `CLAUDE.md`, spec §3 and §5, `docs/reference/tenant-config.md` and `docs/superpowers/plans/2026-09-02-sms-staff-delivery-plan.md` first. Founder decision 2026-09-02: queued to build immediately after the operations plan's final review.

**Goal:** One number texting the assistant hundreds of times, or a whole tenant's SMS traffic running past a daily ceiling, stops costing money after a small, known amount: the texts are still stored, nothing is generated, nothing is sent, the owner is told once, and a person can block or unblock a number from the portal or the command line.

**Architecture:** A `sms_blocks` table holds permanent blocks and timed mutes per tenant and number. A pure-ish `inbound_verdict` reads counts from the existing `messages` and `conversations` rows (no counters to keep in sync) and returns one of `ok`, `blocked`, `muted`, `capped`; the SMS route consults it after the carrier keywords and the staff check and before the model. A suppressed text is stored on the conversation with no reply and no follow-up. The Cloudflare edge worker gets the same two rules for its offline auto-reply: one reply per sender per hour, none to a blocked number.

**Tech Stack:** existing runtime (FastAPI route in `spatalk/text/sms.py`, `TextConversationService`, SQLAlchemy models, Alembic, E7 alerting in `spatalk/ops/alerts.py`, Typer CLI), portal (Wasp 0.25, internal API), edge worker (Cloudflare Workers, KV, vitest with miniflare).

**Spec:** `docs/superpowers/specs/2026-09-01-ai-front-desk-architecture-design.md` §3 (every message is in the record), §5 (fixed wording is config; the system never claims what it did not do), §8 (cost ceilings: the text conversation ceiling assumes bounded traffic). Reference pages win over this plan where they disagree.

## Global Constraints

- Everything in `CLAUDE.md` "Non-negotiables". No new service, no Redis: counts come from the tables that already exist, and the one-process token buckets in `spatalk/http/ratelimit.py` stay per-IP and untouched.
- **Nothing is dropped silently.** A suppressed inbound text is stored as a user message on the sender's conversation exactly as an answered one is, so the transcript in the portal shows everything the number sent. Only the reply and the model call are withheld.
- **Carrier keywords keep working.** STOP, START and HELP are answered from fixed wording even from a muted or blocked number, because the carrier requires it. They still count toward the sender's burst.
- **Fixed wording.** The one text a sender may receive while the tenant is capped is a script, `sms_paused`, and it must not promise a reply time. Default: `"Thanks for texting {name}. The assistant is paused right now. A member of the team will read your message, or you can call {phone}."` It goes through the banned-word validator like every script.
- **Business time.** "Today" for daily counts is the tenant's local day from `BusinessCalendar`; never a UTC midnight.
- **Inbound fees are outside our control.** The guard stops model calls and outbound texts. The founder step in `docs/runbooks/accounts-and-env.md` is to check whether the Telnyx messaging profile offers a sender blocklist and, if it does, to use it for permanent blocks.
- Defaults, all per tenant and editable in the bundle and the portal: burst 12 texts in 10 minutes, 40 texts in a local day, mute for 24 hours, tenant ceiling 400 assistant replies in a local day.

## File Structure

```
runtime/spatalk/tenants/schema.py            SmsGuard settings on TenantConfig; Scripts.sms_paused
runtime/spatalk/models.py                    SmsBlock table
runtime/alembic/versions/00NN_sms_blocks.py  next free number at build time
runtime/spatalk/text/flood.py (new)          inbound_verdict, mute, block, unblock, list_blocks, replies_today
runtime/spatalk/text/service.py              handle_inbound gains suppressed_reason
runtime/spatalk/text/sms.py                  the guard step in POST /telnyx/sms (delimited block)
runtime/spatalk/ops/alerts.py                two alert keys (no new mechanism)
runtime/spatalk/cli.py                       `spatalk sms block|unblock|blocks`
runtime/spatalk/http/internal.py             sms-blocks endpoints; health fields (delimited block)
runtime/tenants/skincentrix/tenant.yaml      sms_guard defaults written out; scripts.yaml gains sms_paused
edge/sms-worker/src/index.ts                 per-sender hourly reply key; blocked list from KV
runtime/spatalk/cli.py (edge sync-texts)     payload gains the permanent block list
portal/src/client/settings/NumbersTab.tsx    "Blocked and muted numbers" panel
portal/src/client/ConversationsPage.tsx      "Block this number" on an SMS conversation
portal/src/client/operations.ts              three operations (delimited block)
docs/reference/{data-model,tenant-config,api-surface}.md, docs/runbooks/accounts-and-env.md
runtime/tests/test_sms_flood.py, test_sms_blocks_api.py; edge/sms-worker/test/flood.test.ts; portal unit tests
```

## Task F1: Settings, table, verdict, the guard in the route

**Files:** `runtime/spatalk/tenants/schema.py`, `runtime/spatalk/models.py`, migration, `runtime/spatalk/text/flood.py`, `runtime/spatalk/text/service.py`, `runtime/spatalk/text/sms.py`, `runtime/spatalk/ops/alerts.py`, Skincentrix bundle, `docs/reference/{data-model,tenant-config}.md`, tests `runtime/tests/test_sms_flood.py`.

**Interfaces (consumes):** `Message`, `Conversation` from `spatalk/models.py`; `BusinessCalendar` from `spatalk/tenants/calendar.py` (or wherever the runtime plan put it: check `grep -rn "class BusinessCalendar"`); `notify(ctx, key, subject, body)` and `already_alerted(ctx, key)` from `spatalk/ops/alerts.py`; `render_script(name, cfg, now, urgent)` from `spatalk/brain/renderer.py`; `TextConversationService.handle_inbound` and `InboundResult` from `spatalk/text/service.py`; `staff_numbers(cfg)` from `spatalk/text/staff.py`.

**Interfaces (produces):**
- `SmsGuard(BaseModel, frozen=True)`: `burst_limit: int = 12`, `burst_window_minutes: int = 10`, `daily_limit: int = 40`, `mute_hours: int = 24`, `tenant_daily_replies: int = 400`. Every value at least 1. Field `sms_guard: SmsGuard = SmsGuard()` on `TenantConfig`. `Scripts.sms_paused` with the default above.
- Table `runtime.sms_blocks`: `tenant_id` fk, `phone` text, primary key `(tenant_id, phone)`; `until` timestamptz null (null means permanent); `reason` text (`flood` | `manual`); `created_by` text (`system:flood`, `cli:<user>`, `user:<id>`); `created_at` timestamptz default now; index `(tenant_id, until)`.
- `Verdict = Literal["ok", "blocked", "muted", "capped"]`.
- `async def inbound_verdict(ctx, cfg, sender: str, now: datetime) -> Verdict`: in this order: a row with `until is None` → `blocked`; a row with `until > now` → `muted`; a row with `until <= now` is deleted and ignored; then count this sender's user messages on this tenant's `sms` conversations (`Conversation.tenant_id == cfg.id`, `Conversation.channel == "sms"`, `Conversation.caller == sender`, `Message.role == "user"`) in the last `burst_window_minutes` and since local midnight: if either count is at or above its limit, call `mute(...)` for `mute_hours` with reason `flood`, raise the alert, return `muted`; then count assistant messages on the tenant's `sms` conversations since local midnight: at or above `tenant_daily_replies` → `capped` (an alert once per local day). Staff numbers (`staff_numbers(cfg)`) never get a verdict other than `ok`.
- `async def mute(ctx, cfg, phone, until, reason, created_by) -> None` (upsert; a permanent block is never shortened by a mute); `async def block(ctx, cfg, phone, created_by) -> None`; `async def unblock(ctx, cfg, phone) -> bool`; `async def list_blocks(ctx, tenant_id) -> list[SmsBlock]`; `async def replies_today(ctx, cfg, now) -> int`.
- Alerts, through the existing `notify` with its dedup: key `sms.flood:{tenant}:{phone}` subject `"{name}: {phone} muted for {mute_hours}h after {n} texts"`; key `sms.daily_cap:{tenant}:{YYYY-MM-DD local}` subject `"{name}: assistant paused on SMS, {tenant_daily_replies} replies today"`.
- `TextConversationService.handle_inbound(..., suppressed_reason: str | None = None)`: when set, find or create the conversation, store the user message, meter nothing, schedule no follow-up, return `InboundResult(conversation_id, suppressed=True, reason=suppressed_reason)`.
- Route `POST /telnyx/sms`, after the staff check and before the customer path: `verdict = await inbound_verdict(ctx, cfg, sender, now)`; `blocked` and `muted` → `handle_inbound(..., suppressed_reason=verdict)`, response `{"ok": True, "suppressed": verdict}`; `capped` → store suppressed, and send `render_script("sms_paused", ...)` once per sender per local day, recorded through `already_alerted` with key `sms.paused_notice:{tenant}:{phone}:{date}` so the second text of the day gets nothing; response `{"ok": True, "suppressed": "capped"}`.

**Tests (through the real route with `MemorySms`, `FakeLLM`, a scratch database, the fixed clock):**
- The 12th text in 10 minutes is answered; the 13th is stored, unanswered, the number has a `flood` row with `until` 24 hours out, exactly one `sms.flood` alert exists, and the fake LLM recorded no call for it.
- 40 texts spread over a local day, each more than 10 minutes apart, trip the daily limit on the 41st; the 41st at 00:05 local the next day does not (the day rolled in tenant time; use a `now` that is 03:00 UTC to prove it is not UTC midnight).
- A muted number texting STOP gets the opt-out confirmation and is opted out; HELP gets the help text; a plain text gets nothing.
- A muted number texting after `until` is answered and its row is gone.
- A permanent block is never answered and never expires.
- Tenant cap: with `tenant_daily_replies: 3` and three assistant replies today, a new sender's text is stored, the paused script is sent once, a second text from the same sender gets nothing, a text from a third sender gets the script once; the alert exists once; tomorrow local the assistant answers again.
- Staff numbers are never muted or capped.
- Every suppressed text is visible as a user message on the conversation (assert through the service's `history`).
- Bundle round-trip with `sms_guard` set; validator rejects `burst_limit: 0`; `sms_paused` default contains no banned word and no `{confirm_by}`.

**Done when:** tests pass, migration applies and downgrades, suite green, ruff clean, reference docs updated. Commit `feat(sms): flood guard with timed mutes and a tenant daily ceiling`.

## Task F2: Block list management: CLI, internal API, portal

**Files:** `runtime/spatalk/cli.py`, `runtime/spatalk/http/internal.py` (delimited block `# --- sms blocks (plan F, F2) ---`), `portal/src/client/settings/NumbersTab.tsx`, `portal/src/client/ConversationsPage.tsx`, `portal/src/client/operations.ts`, the OpenAPI contract in `docs/contracts/` (regenerate), `docs/reference/api-surface.md`, tests `runtime/tests/test_sms_blocks_api.py`, portal unit tests, one Playwright spec `portal/e2e/sms-blocks.spec.ts`.

**Interfaces (produces):**
- CLI: `spatalk sms block <tenant> <number> [--reason manual]`, `spatalk sms unblock <tenant> <number>`, `spatalk sms blocks <tenant>` (table: number, permanent or until, reason, created by, created at). Numbers are validated as E.164; a staff number cannot be blocked (exit 1 with a message).
- `GET /internal/tenants/{tenant_id}/sms-blocks` → `SmsBlockOut[]`: `phone, until, reason, created_by, created_at`.
- `POST /internal/tenants/{tenant_id}/sms-blocks` body `{phone, actor}` → permanent block, reason `manual`, audit row `sms.block`; 409 if the number is staff.
- `DELETE /internal/tenants/{tenant_id}/sms-blocks/{phone}` body `{actor}` → removes a block or a mute, audit row `sms.unblock`; 404 when absent.
- `GET /internal/tenants/{tenant_id}/health` gains `sms_muted_numbers: int` (rows with `until` in the future), `sms_blocked_numbers: int`, `sms_replies_today: int`.
- Portal: NumbersTab shows a "Blocked and muted numbers" panel listing rows with an Unblock button and an "Add a number" form; ConversationsPage shows "Block this number" on an SMS conversation's header, which calls the POST and shows the row's state on the conversation ("Blocked since ..."). Copy above the panel: "Blocked numbers still reach the carrier, so their texts still cost the inbound fee. Their messages are kept in Conversations; nothing is answered."

**Tests:** runtime: list, add, remove, 409 for staff, 404 when absent, audit rows, health counts, `X-Internal-Key` enforced; CLI through Typer's runner with the scratch database; portal: operations unit tests for the three calls; Playwright: block from a seeded SMS conversation, see it in NumbersTab, unblock.

**Done when:** tests pass on both apps, `wasp build` succeeds, OpenAPI regenerated, `api-surface.md` updated. Commit `feat(portal): block and unblock sms numbers`.

## Task F3: The edge worker follows the same rules

**Files:** `edge/sms-worker/src/index.ts`, `edge/sms-worker/test/flood.test.ts`, `runtime/spatalk/cli.py` (`edge sync-texts`), the worker's `/admin/tenant-texts` handler, `docs/runbooks/accounts-and-env.md` (Telnyx blocklist check), `docs/runbooks/deploy.md` (sync step mentions blocks).

**Interfaces (produces):**
- Offline auto-reply: before sending, the worker reads `replied:sender:<E.164>` from `PENDING`; present → no reply; absent → put it with `expirationTtl: 3600`, then reply. The per-message `replied:<message_id>` key stays, so a redelivered message still gets nothing.
- Blocked numbers: `spatalk edge sync-texts` adds `blocked: ["+1..."]` (permanent blocks across all tenants) to the payload; the worker writes `blocked:<E.164>` keys into `TENANT_TEXTS` and deletes ones no longer listed; `maybeAutoReply` returns before replying when the key exists. Mutes are not synced (they expire on their own and only matter when the runtime is up).
- Forwarding to the runtime is unchanged: a blocked sender's text is still forwarded and stored when the runtime is up, and still kept in `PENDING` for replay when it is not.

**Tests (vitest + miniflare):** two texts from one sender within an hour during an outage produce one auto-reply; a second sender gets its own; a blocked sender gets none; the sync endpoint writes and prunes `blocked:` keys; the runtime's `sync-texts` dry run prints the block list.

**Done when:** `npm test` passes in `edge/sms-worker`, runtime CLI test passes, runbooks updated. Commit `feat(edge): one offline reply per sender per hour, none to blocked numbers`.

## Self-review against the spec

- §3 record: every suppressed text is stored on its conversation; nothing disappears.
- §5 honesty and fixed wording: the only text a capped sender gets is a script that promises no reply time; no model output is involved anywhere in this plan.
- §8 cost: the worst day from one number is bounded at 12 or 40 texts of replies, the worst day for a tenant at 400 replies, and the edge worker's outage reply at one per sender per hour.
- Business time: local day everywhere (F1 test with a 03:00 UTC `now`).
- Providers and secrets: nothing new; the carrier-side blocklist is a founder check, not code.
- Type consistency: `SmsGuard`, `SmsBlock`, `Verdict`, `inbound_verdict`, `mute`, `block`, `unblock`, `list_blocks`, `replies_today`, `suppressed_reason`, script `sms_paused`, alert keys `sms.flood`, `sms.daily_cap`, `sms.paused_notice`, KV keys `replied:sender:<number>` and `blocked:<number>` are used with the same names in every task.
