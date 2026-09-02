# instagram Task D3: Messenger (Facebook Page) adapter

Status: done with deviations
Commit: `feat(social): facebook page messenger and comment adapter` (hash recorded by the docs
commit that follows, the convention set by runtime-A8 onward)
Tests: `uv run pytest tests/test_social_messenger.py -q` -> 34/34 (33 were written first and
seen failing; the 34th, the messenger prompt rule, passed on the first run because D2 shipped
`CHANNEL_RULES["messenger"]` for this task); full runtime suite `uv run pytest -q` ->
451 passed, 13 failed, 1 skipped — **all 13 failures pre-date this task and none is in a file
it touches** (evidence below); `uv run ruff check spatalk tests scenarios` ->
"All checks passed!". No migration: D1 created `tenant_integrations`, `meta_events` and
`meta_windows`, and this task adds no column.

Interfaces produced: `spatalk.social.events.parse_messenger_payload`;
`spatalk.social.handlers.{FB_EVENT_JOB, GRAPH_BASE_FOR_CHANNEL, fb_event}` and the
channel-parameterised `send_message(ctx, integration, channel, recipient, text)` /
`send_public_reply(ctx, integration, channel, comment_id, text)`;
`spatalk.social.messenger.{router, PROVIDER, CONNECTED_BY, PENDING_TTL, PendingPages,
remember_pages, take_pending, offered_pages, select_page}` serving `GET /messenger/connect`,
`GET /messenger/callback`, `GET+POST /messenger/webhook`;
`spatalk.http.internal.{MessengerPageSelectIn, MessengerPageSelected}` serving
`POST /internal/tenants/{tenant_id}/integrations/messenger/select`; job kind
`social.fb_event`; `PROVIDER_FOR_CHANNEL` now maps `messenger` too, which is what makes
`relay_from_staff` work on a Page.

## What it does

`POST /messenger/webhook` is byte-for-byte the same door as Instagram's: HMAC-SHA256 over the
**raw** body, accepted if it matches either app secret in constant time, then parse, claim
each event id once in `meta_events`, and enqueue one `social.fb_event` job per event an
adapter answers. The route does nothing slow, because Meta retries a webhook that does not
answer quickly and a retry must never produce a second reply to a customer.

The job is D2's code. `_social_event` now takes the channel, so a Page message and an
Instagram DM run the same function: record the 24-hour window, find or create the
conversation for that sender, put the channel's one-sentence AI disclosure on the record, call
`TextConversationService.handle_inbound` (rules gate, guard, tools, ledger, usage metering and
human takeover all inherited), and send the reply through the Graph API. Only two things are
Page-specific and they live in one function each: `_reply_call` (a Page sends on
`graph.facebook.com`, adds `messaging_type: "RESPONSE"`, and answers a commenter on
`/{comment_id}/private_replies` instead of on the account's `messages` edge) and
`send_public_reply` (`/{comment_id}/comments` instead of `/{comment_id}/replies`).

A Page's `feed` field carries everything that happens on the Page's timeline — likes, shares,
edits, comments added, comments deleted — so `parse_messenger_payload` produces an event only
for `item == "comment"` and `verb == "add"`. Anything else is not even recorded: there is
nothing an adapter would ever do with it, and a `meta_events` row for a like is noise in the
one table that exists to prove we answered each customer once.

Outside Meta's 24-hour window nothing is sent, exactly as on Instagram: the customer's words
are stored, the conversation is closed, and one `callback` item is filed carrying the only
contact a Page gives us — the commenter's display name, or the PSID for a message. A second
stale message files no second item.

Connecting is the part that is genuinely different. A person may administer several Pages, and
the OAuth code that produced their user token is single use, so the flow cannot be restarted
after they choose. `GET /messenger/callback` with one Page subscribes it to `messages,feed`
and stores it; with several it holds the list under an opaque handle for fifteen minutes and
sends the browser back to the portal with the Page **names and ids only**. The portal posts
the handle and the chosen id to `POST /internal/tenants/{id}/integrations/messenger/select`,
which subscribes and stores that one Page. Page access tokens never travel through the
browser, and none is written to the database until a person has chosen one.

## Tests: failing before, passing after

All 33 behaviour tests were written first and run against a repository with no
`social/messenger.py`; every one failed on the missing route (a 404 where a 200 was asserted,
or the route-presence assertion). Names follow the behaviours the plan lists.

Routes and handshake: the three Page routes and the selection endpoint are on the app; the
handshake echoes `hub.challenge`; a wrong verify token is 403.
Signature: a bad signature is 401 and queues nothing; a signature made with the *Instagram*
app secret is accepted (one runtime, two apps).
Dedup and resolution: the same event id enqueues one job; an event for a Page no tenant has
connected is dropped.
Messages: a Page message reaches the brain and produces exactly one Graph send, to
`/v21.0/{page_id}/messages`, carrying `messaging_type: "RESPONSE"` and the greeting plus the
reply, with the disclosure on the transcript ahead of the customer's words; an echo of our own
send is ignored (no job, no conversation); a read receipt is stored in `meta_events` and
ignored; usage is metered as `fb_in` and `fb_out` on channel `messenger`.
Comments: a comment from the Page itself is ignored; a keyword comment gets a private reply on
`/{comment_id}/private_replies` and no public one; with `public_reply_enabled` it also gets
exactly the fixed sentence "Thanks! Check your DMs." on `/{comment_id}/comments`; a comment
with no keyword is ignored in `keyword` mode and answered in `all` mode; `off` answers
nothing; a feed change that is a like, or a comment being *removed*, produces no event, no job
and no row.
Window: an expired window sends nothing, closes the conversation, captures one `callback`
carrying only a name, and keeps the customer's words in the transcript; a second stale message
captures no second item; a stale comment captures the commenter's display name.
Failures: a Graph 429 requeues the job with the status in `last_error`; a Graph 400
dead-letters with the response body.
Takeover: a staff reply is relayed through Graph verbatim with `messaging_type: "RESPONSE"`,
stored as `staff`, and sets `controller=human`.
Connect and page selection: the connect link redirects to Facebook Login carrying a signed
state; a callback with one Page stores it (ciphertext, not the token), subscribes
`messages,feed`, and returns to the portal; a callback with two Pages stores nothing,
subscribes nothing, and hands back the two names with no `access_token` anywhere in the
redirect; selecting one stores and subscribes exactly that Page; the handle works once; an
unknown handle is 400; a page that was not offered is 400 and stores nothing; the selection
endpoint refuses a request without `X-Internal-Key`; a tampered callback state is 400.

## Deviations

- **The 13 failing tests in the full suite are pre-existing and unrelated.** They are
  `tests/test_widget.py` (11), `tests/test_takeover.py::test_a_staff_message_left_waiting_is_
  delivered_when_the_widget_reconnects` and
  `tests/test_text_sms.py::test_a_telnyx_signature_is_accepted_when_no_edge_key_is_configured`.
  Evidence: `git stash push -u -- runtime/spatalk runtime/tests docs/contracts` then
  `uv run pytest tests/test_widget.py -q` -> `11 failed, 11 passed` and
  `uv run pytest tests/test_takeover.py tests/test_text_sms.py -q` -> `2 failed, 32 passed`
  on the unmodified tree, the same two names. Two causes, neither in this task's scope:
  the Telnyx one signs `"{fixed_clock_timestamp}|{body}"` and the verifier compares it against
  the *wall* clock, so it began failing when the machine's date rolled over from 2026-09-01 to
  2026-09-02 (the `FixedClock` is pinned to 2026-09-01 18:00 UTC and the freshness window is
  300 s); the widget ones time out in the chat WebSocket with
  `turnstile verification failed` in the log, which is `verify_turnstile` reaching for
  `challenges.cloudflare.com` and hanging in this sandbox rather than refusing fast. **B2/B4's
  owner should pin the signing timestamp to the clock under test and inject the Turnstile
  verifier in every widget test, not only in the two that assert on it.** No test was skipped,
  weakened or touched here.
- **`spatalk/http/internal.py` and `docs/contracts/runtime-internal.openapi.json` were
  touched, and both are D4 files.** D3's Interfaces block names
  `POST /internal/tenants/{id}/integrations/messenger/select` as this task's endpoint, and
  the only home for an `/internal` route is `internal.py` (the contract is generated by path
  prefix, so putting the route in `messenger.py` would have changed the contract anyway while
  splitting the router in two). The route is appended in a delimited block
  `# --- social integrations (instagram plan, Task D3) ---`; nothing existing was reordered or
  reformatted. The contract was regenerated with `uv run spatalk openapi --internal` and
  normalised to LF; `uv run pytest tests/test_contract_snapshot.py -q` -> `5 passed`.
- **The pending Page choice is held in memory, not in the database.** The plan says the
  callback should "redirect to portal with the list to choose from" and the select endpoint
  should store the chosen Page, but does not say where the Page access tokens live in between,
  and D1's report flagged the problem (the OAuth code is single use, so the flow cannot be
  re-run). Every durable option was worse: a Page token in a redirect URL is a secret in
  browser history, and a half-written `tenant_integrations` row would make a tenant look
  connected to a Page nobody picked. `_PENDING` in `social/messenger.py` holds them for
  fifteen minutes under a `secrets.token_urlsafe(24)` handle, single use, scoped to the tenant
  in the path. The cost is that a runtime restart loses a selection in flight; the endpoint
  then answers 400 "this page selection has expired; start the connection again", which is
  true and recoverable. This is safe because the runtime is one uvicorn process
  (`spatalk/cli.py` runs `uvicorn.run(...)` with no worker count); **if a second worker or a
  second host is ever added, this needs a table.**
- **The webhook verify token is `settings.instagram_webhook_verify_token` for both doors.**
  `api-surface.md`'s environment table lists one `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` under plan D
  and no Facebook equivalent, and `settings.py` is not a D3 file. One value is typed into both
  Meta apps' webhook screens; a second variable would only be another secret to keep in step.
  Named `_verify_token(settings)` in `messenger.py` so the intent is not mistaken for a
  copy-paste.
- **`send_message` and `send_public_reply` in `social/handlers.py` gained a `channel`
  argument, and `answer_inbound`'s two callers now pass the channel through.** D2's report
  asked for exactly this ("Two things are Instagram-specific and D3 must parameterise them").
  Both functions are D2 interfaces; nothing outside `handlers.py`, `takeover.py`'s
  `relay_social` call and this task's tests consumes them, and the Instagram tests are
  unchanged and green (`tests/test_social_instagram.py` -> 35 passed inside the full run).
  `ig_event` and `fb_event` are now two one-line handlers over a shared `_social_event`.
- **`events.py`'s `_parse` takes the comment builder as an argument.** The `messaging` array
  is identical on both objects, so it is parsed by the same code; only the comment shape
  differs (`changes[].field == "feed"`, `value.comment_id`, `value.message`,
  `value.from.name`, `value.post_id`), which is `_page_comment_event`. Instagram's parser is
  otherwise untouched.
- **`SocialEvent.username` carries a Facebook *display name* on this channel**, where
  Instagram puts a username. It is the same field for the same purpose — the only contact the
  platform gives us for the expired-window callback item — and `data-model.md` has no column
  for it either way: it lands in `items.contact_name`.
- **A Page comment's timestamp is `value.created_time` where Meta sends one**, falling back to
  `entry.time`. Instagram sends no per-comment time and uses `entry.time` alone.
- **No `page_postback.json` fixture.** Postbacks and reads go through the shared
  `_messaging_event`, which D2 already covers for both kinds; `page_read.json` is here to
  prove the shared path also fires for `object: "page"`, and a second fixture would have
  tested the same three lines twice.
- **Fixture timestamps are at the test clock (2026-09-01 18:00 UTC, `1788285600`)**, not the
  `1756800000` printed in `api-surface.md`, for the reason D2 recorded: the reference
  documents the payload *shape*, which is reproduced exactly, but its epoch is a year before
  the suite's `FixedClock` and would make every replayed event look stale to the 24-hour
  window check. `page_message_expired.json` is deliberately two days old.
- **`docs/runbooks/meta-setup.md` was not written**; it is D5's file, and the plan assigns the
  runbook and the scenarios to that task.

## Notes for neighbours

- **D4 (portal)**: the Facebook card's Connect button opens
  `GET /messenger/connect?tenant=<id>&return_to=<portal url>`. When the owner administers more
  than one Page the runtime redirects back to `return_to` with two extra query parameters,
  `messenger_pending=<handle>` and `messenger_pages=<json list of {id, name}>`; render the
  choice and `POST /internal/tenants/{id}/integrations/messenger/select` with
  `{"pending": handle, "page_id": id}`, which answers `{tenant_id, provider, external_id,
  display_name}`. The handle is single use and expires after fifteen minutes; treat a 400 as
  "start the connection again", not as an error to retry. Status and Disconnect are still
  `integration_for` / `delete_integration` as D1 described.
- **D4 must regenerate the contract and the client anyway**, and should start from the
  snapshot as it stands after this commit: `uv run spatalk openapi --internal >
  docs/contracts/runtime-internal.openapi.json` (normalise to LF on Windows) and
  `npm --prefix portal run gen:client`. The portal's committed `src/runtime/client.ts` does
  not yet know about the selection endpoint; nothing breaks, it is simply untyped until then.
- **D5 (runbook)**: a tenant's Facebook app needs the webhook fields `messages` and `feed` on
  the Page and the same `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` value in both apps' webhook screens.
  The subscriber call the runtime makes is
  `POST /{page-id}/subscribed_apps?subscribed_fields=messages,feed`, and the connect flow does
  it automatically, so the runbook's manual step is only the app configuration and review.
- **Everyone**: `PROVIDER_FOR_CHANNEL` now contains `messenger`, so `relay_from_staff` and
  `relay_social` work on a Page with no further wiring; `USAGE_UNITS["messenger"]` was already
  `("fb_in", "fb_out", "meta")` from B2, and `CHANNEL_RULES["messenger"]`,
  `TEXT_CHANNELS` and `INLINE_LINK_CHANNELS` already listed the channel, so nothing in the
  brain changed for this task.
- **`jobs.DeadLetter` is used here too**, on any Graph 4xx that is not a 429, as D2 asked.

Blocked on: nothing.
