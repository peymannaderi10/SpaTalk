# text-channels Task B5: Human takeover through Slack threads and staff SMS

Status: done with deviations
Commit: (implementation, tests and this report; the hash is recorded by the docs commit that
follows, the convention set by runtime-A8 through A16 and text-channels B1 to B4)
Tests: `uv run pytest tests/test_takeover.py tests/test_slack_events.py -q` -> 29/29 (27 of
them seen failing first as `ImportError` on the missing modules, before a line of the feature
existed; the two later additions are covered below); full runtime suite `uv run pytest -q` ->
297 passed, 1 skipped of 298 (baseline before this task: 268 passed, 1 skipped).
`uv run ruff check spatalk tests scenarios` -> All checks passed!
Migration `0003_slack_threads` applies on a fresh database (the QA-gate test
`test_alembic_head_creates_every_documented_table_and_index` runs a real `alembic upgrade head`
on a throwaway database and passes), and a follow-up `--autogenerate` produces an empty
revision.

Interfaces produced: `spatalk.text.takeover` — `set_controller(sf, conversation_id, controller,
by)`, `relay_from_staff(ctx, conversation_id, text, staff_id)`, `mirror_to_thread(ctx,
conversation_id, text, who)`, `store_thread(sf, conversation_id, channel, ts)`,
`thread_for(sf, conversation_id) -> tuple[str, str] | None`, `conversation_for_thread(sf,
channel, thread_ts) -> Conversation | None`, `hand_back(ctx, conversation_id, by, note)`,
`hand_back_stale(ctx) -> int`, `relay_staff_sms(ctx, cfg, sender, text) -> bool`,
`register_chat_socket / unregister_chat_socket / take_pending_staff / deliver_to_chat`,
constants `STAFF_SILENCE`, `HANDBACK_NOTE`, `STALE_NOTE`, `UNDELIVERED_NOTE`, `WAITING_NOTE`;
`spatalk.ledger.delivery.SlackBotDelivery(settings, http=None, client=None)` with `send_slack`,
`post_thread_root(channel_id, blocks, text) -> ts`, `post_in_thread(channel_id, thread_ts,
text, blocks=None)`, plus `make_delivery(settings, http=None) -> DeliveryPort` and the test
fake `MemoryBotDelivery`; `ActionLinks.handback_token` and `build_slack_blocks(..., handback:
bool = False)`; `spatalk.http.slack_events.router` serving `POST /slack/events`;
`handback` as a third accepted claim action on `POST /slack/interactions`;
`Conversation.slack_channel` / `Conversation.slack_ts` with index `ix_conv_slack_ts`;
`Settings.slack_bot_token`.

## What it does

With `SLACK_BOT_TOKEN` set, `make_delivery` builds `SlackBotDelivery` instead of the webhook
delivery, and a destination that carries a `channel_id` gets threads: the **first** item of a
conversation is posted with `chat.postMessage` as a thread root (Acknowledge, Resolve and a
third **Hand back to assistant** button), and its channel and `ts` are stored on the
conversation. Every later item of that conversation, and every customer and assistant message
on it, is posted as a reply in that thread. Without a bot token or without a `channel_id`,
nothing changes: the item goes to the incoming webhook exactly as before, and the conversation
never gets a thread.

A human reply in that thread arrives at `POST /slack/events`. The Slack signature is verified
first; a retry (`X-Slack-Retry-Num`) is acknowledged without reprocessing; the bot's own posts,
edits, joins and non-thread messages are dropped; the thread is resolved to its conversation,
the event id is claimed once in `inbound_messages`, and the words are relayed. Relaying means:
`controller = human`, the text stored with role `staff`, and the text sent to the customer
verbatim — SMS through the `SmsPort`, chat down the open socket (or held for the next connect).
From then on the brain is not called for that conversation: `handle_inbound` already returned
`suppressed=True, reason="human"`, and now it also mirrors the customer's message into the
thread so the person sees what they are answering. Staff wording never re-enters the model's
context; `history()` still collapses it to `STAFF_NOTE`.

The way back is either the thread root's button (`action_id=handback`, whose value is an
`itsdangerous` claim like the other two) or twelve hours of staff silence, which the
minute scheduler notices; both set `controller = ai` and say so in the thread.

Staff can also work by SMS: a message from a number in `delivery.staff_phone_numbers` shaped
`#<item id> <words>` relays those words to that item's conversation and hands it to the person;
anything else from a staff number gets the tenant's `help_text`.

## Tests: failing before, passing after

27 tests were written first against two missing modules: every one errored with
`ImportError: cannot import name 'MemoryBotDelivery'` / `No module named 'spatalk.text.takeover'`.
Two more were added during implementation and are named below. Names follow the behaviours:

`tests/test_slack_events.py` (9): the route is on the app; `url_verification` echoes the
challenge; a bad signature is 401 and relays nothing; a staff thread reply relays via
`MemorySms` and sets `controller=human`; the bot's own messages are ignored; a retry is
acknowledged without reprocessing; the same `event_id` relays once; a reply in an unknown
thread is ignored; a message that is not a thread reply is ignored.

`tests/test_takeover.py` (20): the first item opens a thread and stores channel and `ts`; the
root carries a verifiable `handback` token beside ack and resolve; a later item is posted in
the thread and not as a second root; without a bot token delivery still goes to the webhook and
no thread is stored; customer and assistant messages are mirrored into the thread; a staff
relay is sent verbatim, stored as `staff` and metered once as `sms_out`; a customer message
while a person is replying is mirrored and unanswered; staff wording never reaches the model as
its own; the hand-back button resumes the assistant through the real `/slack/interactions`
route; twelve hours of staff silence hands back and posts one note (and is idempotent); an
eleven-hour-old staff reply keeps the conversation with the person; a staff SMS naming an item
relays to that conversation; any other staff SMS gets the help text; a staff SMS naming an
unknown item gets the help text; a customer writing `#1 …` is not a staff relay and still gets
the assistant.

Added during implementation, both failing before the code they cover existed:
`test_a_reply_to_an_opted_out_number_is_not_sent_and_the_thread_says_so` (the "NOT DELIVERED"
note, see the deviations) and `test_the_real_bot_delivery_posts_roots_replies_and_webhooks`
(the production `SlackBotDelivery` against an injected fake `chat.postMessage`, so the memory
fake used by the other tests cannot silently diverge from the real class).

## Deviations

- **`runtime/alembic/env.py` gained an `include_object` filter, and this one is urgent.**
  `env.py` sets `include_schemas=True`, and the portal (`portal/`, created since B4) now owns
  the `public` schema **in the same database**. The first `alembic revision --autogenerate` for
  this task therefore produced a revision whose `upgrade()` began
  `op.drop_table('AuthIdentity'); op.drop_table('_prisma_migrations'); op.drop_table('Logs');
  … op.drop_table('User')` — it would have deleted the portal's plane on the next
  `alembic upgrade head`. `include_object` now returns True only for objects whose schema is
  `runtime`, which is CLAUDE.md non-negotiable 7 expressed in code. Evidence: with the filter,
  a probe `--autogenerate` run produced a revision with zero `op.` lines (`grep -n "op\."` ->
  no match); the probe was deleted. The committed `0003_slack_threads.py` contains only the two
  `conversations` columns and the `ix_conv_slack_ts` index.
- **The twelve-hour hand-back is a scheduler pass, not a job — the reference wins over the
  plan.** The plan says "a scheduled job sets `controller=ai`", but `docs/reference/data-model.md`
  lists the complete `jobs.kind` enum and it has no takeover kind. `takeover.hand_back_stale(ctx)`
  is therefore called from `run_scheduler_forever` alongside `escalate_breached` and
  `send_digests`, which already run every minute. No undocumented job kind was invented.
  Evidence: `grep -n "jobs.kind" -A 2 docs/reference/data-model.md` lists
  `deliver.slack … ops.alert` with nothing for takeover.
- **Staff silence is measured against `ctx.clock`, not the database clock.** `hand_back_stale`
  compares the newest `messages.created_at` with `role='staff'` against `ctx.clock.now() - 12 h`,
  the same decision B3 recorded for `textbacks.sent_at`; a `FixedClock` test would otherwise
  compare a fixed now against real wall-clock rows. Production clocks agree.
- **`post_in_thread` takes an optional fourth argument `blocks`.** The plan's signature is
  `post_in_thread(channel_id, thread_ts, text)`; a *later* item posted into an existing thread
  must keep its Acknowledge and Resolve buttons, so the parameter is appended with a default of
  `None` and every call in the plan's shape still works.
- **`ActionLinks` gained a sixth field and `/slack/interactions` a third action.** The hand-back
  button needs a value, and since the gate-A fix a Slack button value must be a signed claim.
  `build_links` now also signs `handback`, `build_slack_blocks(..., handback=True)` adds the
  button (thread roots only), and `slack.py` accepts `claim.action == "handback"`, which sets the
  conversation's controller and touches no item state. `ActionLinks`'s new field is defaulted, so
  the two positional constructions in the repository still work. Evidence:
  `uv run pytest tests/test_delivery.py tests/test_http_actions.py -q` -> `9 passed`, untouched.
- **`SlackBotDelivery` subclasses `HttpSlackEmailDelivery`.** `DeliveryPort` requires
  `send_email` as well as `send_slack`, and the plan wants one object selected by the presence of
  a bot token, so the bot class inherits email and webhook behaviour and overrides only Slack.
  `send_slack` keeps the port's signature: given something starting with `http` it posts to the
  webhook, given a channel id it posts as the bot. `make_delivery(settings)` is the selector and
  is what `build_context` now calls.
- **Slack event dedup reuses `inbound_messages` with `channel="slack"`.** `data-model.md`
  describes that table as the dedup key for inbound provider events and B5 adds no table of its
  own; `event_id` is claimed there after the thread resolves to a tenant.
- **`set_controller` writes no `audit_log` row.** `data-model.md` fixes the `audit_log.action`
  enum (`read_transcript, ack, resolve, config_save, config_rollback, export`) and has no
  takeover action. The change is logged instead, and the staff message itself is the record.
- **A staff SMS is sent as one message, never split.** The global constraint splits *model*
  replies at 300 characters with `split_sms`, which drops anything past two parts. Dropping a
  person's words is not acceptable, so a relay goes out verbatim in a single send and the carrier
  concatenates it.
- **Two staff-facing notes exist that no customer sees, and one of them is new to the plan.**
  `UNDELIVERED_NOTE` is posted in the thread when a staff reply could not be sent (the customer
  opted out, the tenant has no SMS number, or the channel has no relay yet — Instagram and
  Messenger arrive in the D plan), and `WAITING_NOTE` when a chat visitor's window is closed and
  the message is queued for their return. Without them the person would be left believing a
  message went out that did not, which is the failure the whole product exists to avoid (spec
  §5). Neither is customer wording, so neither is a tenant script; `scripts.takeover_notice`
  stays what B4's widget shows, and nothing generated is ever sent to a customer (plan step 2).
- **`runtime/tenants/skincentrix/tenant.yaml` sets `channel_id: null`.** The Files list says the
  destination gains `channel_id`, but no Slack workspace or bot token exists yet and inventing a
  channel id would put fake data in a real bundle. The key is present with the documented default
  and a comment, in the same style as `sms_from_number: null`; the founder fills it in with the
  token (`docs/runbooks/accounts-and-env.md` is where that step belongs).
- **Six files outside B5's Files list were touched, all by appending.**
  (a) `spatalk/text/service.py`: two `mirror_to_thread` calls — B2's report explicitly left this
  seam ("mirroring that message to the Slack thread is the one line B5 adds there").
  (b) `spatalk/text/chat.py`: the socket is registered with `takeover` on accept, pending staff
  messages are drained, and the receive loop moved into `_chat_loop` so the registration has a
  `finally` — B4's report left this seam too. (c) `spatalk/http/app.py`: `attach_router(app,
  slack_events.router)` and `make_delivery(settings)` in `build_context`. (d)
  `spatalk/ledger/scheduler.py`: one `hand_back_stale(ctx)` call in the loop. (e)
  `runtime/.env.example`: `SLACK_BOT_TOKEN`, which `api-surface.md` lists for B5. (f)
  `alembic/env.py`, above.
- **Reference-versus-plan check: one disagreement, recorded above** (the missing takeover job
  kind). Everything else matches: `api-surface.md`'s `POST /slack/events | B5 | Slack signing
  secret` and `SLACK_BOT_TOKEN | B5 | threads and takeover`, `data-model.md`'s
  `slack_channel, slack_ts | text null | thread root for takeover [B5]` and its `(slack_ts)`
  index, `tenant-config.md`'s `channel_id` and `staff_phone_numbers`, and `flows.md` §5's six
  steps are all implemented as written.

## Notes for neighbours

- **D2/D3 (Instagram, Messenger) finish `relay_from_staff`.** It handles `sms` and `chat`; any
  other channel stores the staff message, sets `controller=human` and posts `UNDELIVERED_NOTE`
  in the thread. Add a branch that sends through Graph and the rest of takeover — threads,
  mirroring, hand-back, the 12-hour timer — works unchanged, because everything else keys on the
  conversation, not the channel.
- **The chat socket registry lives in `spatalk.text.takeover`, not in `chat.py`,** to keep the
  import direction one-way (`chat` -> `service` -> `takeover`). It is per process and in memory,
  like B4's rate limiter: `register_chat_socket(tenant_id, session, send)`,
  `unregister_chat_socket`, `take_pending_staff(tenant_id, session)`. A staff message with
  nowhere to go is in the transcript regardless; only the live push is lost on a restart.
- **`spatalk/ledger/delivery.py` now imports `spatalk.text.takeover`.** `takeover` must never
  import `delivery` or `service` at module level (it imports `is_opted_out` inside the function
  that needs it) or the cycle closes.
- **The `deliver.slack` job payload gained `channel_id`.** A job queued before this change has
  no such key and falls back to the webhook, so no drain or migration is needed.
- **Anyone regenerating a migration must keep `include_object` in `alembic/env.py`.** Without it
  autogenerate proposes dropping every table the portal owns; see the deviation above. This is
  worth a line in the operations plan's runbook.
- **`MemoryBotDelivery` (in `spatalk/ledger/delivery.py`) is the fake for thread tests**:
  `.roots`, `.thread`, `.posted_ts` beside `MemoryDelivery`'s `.slack` and `.emails`.
- **`build_slack_blocks` grew a keyword argument, not a positional one.** Existing calls are
  unaffected; only a thread root passes `handback=True`.
- **E-plan (`/healthz` route dumps, operational inventories) now sees `/slack/events`.** It is
  authenticated by the Slack signing secret, like `/slack/interactions`.

Blocked on: nothing.
