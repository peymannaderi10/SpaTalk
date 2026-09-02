# instagram Task D2: Instagram webhook, comments and DMs

Status: done with deviations
Commit: `<filled in by the docs commit that follows; a hash cannot be written into the commit
that carries it — the convention set by runtime-A8 onward>`
Tests: `uv run pytest tests/test_social_instagram.py -q` -> 35/35 (all 33 originally written
were seen failing first, the two later additions are named below); full runtime suite
`uv run pytest -q` -> 430 passed, 1 skipped (baseline after D1: 395 passed, 1 skipped);
`uv run ruff check spatalk tests scenarios` -> "All checks passed!". No migration: D1 created
`tenant_integrations`, `meta_events` and `meta_windows`, and this task adds no column.

Interfaces produced: `spatalk.social.events.{SocialEvent, EventKind, ACTIONABLE,
SIGNATURE_HEADER, verify_meta_signature, parse_instagram_payload}`;
`spatalk.social.handlers.{IG_EVENT_JOB, MESSAGING_WINDOW, PROVIDER_FOR_CHANNEL, claim_event,
ingest_events, record_window, window_open, send_message, send_public_reply, matches_keyword,
open_greeting, greeting_due, close_and_capture, answer_inbound, ig_event, relay_social}`;
`spatalk.social.instagram.{router, parse_signed_request, CONNECTED_BY}` serving
`GET /instagram/connect`, `GET /instagram/callback`, `GET+POST /instagram/webhook`,
`POST /instagram/deauthorize`, `GET+POST /instagram/delete`; job kind `social.ig_event`;
`spatalk.jobs.DeadLetter`; `CHANNEL_RULES["instagram"]` and `CHANNEL_RULES["messenger"]` in
`spatalk.brain.prompt`; `relay_from_staff` now sends on `instagram` and `messenger`.

## What it does

`POST /instagram/webhook` proves the request came from Meta (HMAC-SHA256 over the **raw**
body, accepted if it matches either app secret, compared in constant time), parses the
payload into flat `SocialEvent`s, claims each `event_id` once in `meta_events`, and enqueues
one `social.ig_event` job per event that an adapter actually answers. Nothing slow happens in
the route: Meta retries a webhook that does not answer quickly, and a retry must never produce
a second reply to a customer.

The job is where the work is. A direct message and a keyword-matched comment take the same
path (`answer_inbound`): record the 24-hour window, find or create the conversation for that
IG sender id, put the channel's one-sentence AI disclosure on the record, run
`TextConversationService.handle_inbound` (so the rules gate, the guard, the tools, the ledger,
the usage metering and human takeover are all inherited unchanged), and send the reply through
the Graph API — `{"recipient": {"id": …}}` for a DM, `{"recipient": {"comment_id": …}}` for a
private reply to a comment. When `public_reply_enabled`, the comment also gets the tenant's
fixed `comment_public_reply` sentence, never a generated one.

Outside Meta's 24-hour window nothing is sent at all. The customer's words are still stored,
the conversation is closed, and one `callback` item is filed carrying the commenter's username
— the only contact Instagram gives us — so a person answers from the Instagram inbox. A second
stale message does not file a second item.

Takeover works because `relay_from_staff` now has an `instagram`/`messenger` branch that calls
`relay_social`; if the window has closed or no account is connected, it returns the reason and
B5 posts `UNDELIVERED_NOTE` in the Slack thread, so the team is never left believing a message
went out that did not.

## Tests: failing before, passing after

All 33 tests were written first and run against a repository with no `social/instagram.py`:
every one failed (`assert response.status_code == 200` on a 404 from the missing route, or the
route-presence assertion). Names follow the behaviours the plan lists.

Routes and handshake: the five routes are on the app; the handshake echoes `hub.challenge`; a
wrong verify token is 403; a wrong `hub.mode` is 403.
Signature: a bad signature is 401 and queues nothing; a missing signature is 401; a signature
made with the *Facebook* app secret is accepted.
Dedup and resolution: the same event id enqueues one job; an event for an account no tenant
has connected is dropped.
DMs: a DM reaches the brain and produces exactly one Graph send whose text is the greeting
plus the reply, with the disclosure on the transcript ahead of the customer's message; the
second reply in the same conversation is not prefixed; an echo is ignored (no job, no
conversation); a postback and a read are stored in `meta_events` and ignored; usage is metered
as `ig_in` and `ig_out` on channel `instagram`.
Comments: a comment from the account itself is ignored; a keyword comment gets a private
reply and no public one; with `public_reply_enabled` it also gets exactly the fixed sentence
"Thanks! Check your DMs."; a comment with no keyword is ignored in `keyword` mode and answered
in `all` mode; `off` answers nothing.
Window: an expired window sends nothing, closes the conversation, captures one `callback`
carrying only a name, and keeps the customer's words in the transcript; a second stale message
captures no second item; a stale comment captures the commenter's username.
Failures: a Graph 429 requeues the job with the status in `last_error`; a Graph 400
dead-letters with the response body.
Takeover: a staff reply is relayed through Graph verbatim, stored as `staff`, and sets
`controller=human`.
Prompt: the `instagram` channel rule caps the reply at 500 characters and forbids unprompted
emoji.
Connect and platform requirements: the connect link redirects to Instagram carrying a signed
state; the callback stores the integration (ciphertext, not the token) and redirects to the
portal; a tampered state is 400; deauthorize removes the integration; a deauthorize with a bad
signature is 401 and removes nothing; the data-deletion callback returns a URL and a
confirmation code.

Two tests were added during implementation, each failing before the code it covers existed:
`test_a_failed_public_reply_does_not_retry_the_private_one` and
`test_the_requeued_job_sends_the_reply_it_already_wrote_without_asking_again`.

## Deviations

- **`spatalk/jobs.py` gained `DeadLetter` and one line inside `run_once`.** The plan's
  behaviour 7 requires a non-429 4xx to dead-letter immediately, but the jobs mechanism only
  marks a job dead at `max_attempts`, so a handler had no way to say "another attempt will
  fail the same way". `DeadLetter` is a new exception class (appended in a delimited block)
  and the existing branch condition became
  `if job.attempts >= job.max_attempts or isinstance(e, DeadLetter):`. Nothing else in the
  file changed and every existing job behaves exactly as before. Evidence: before the change
  `uv run pytest tests/test_social_instagram.py -k dead_letters` -> `assert 'queued' == 'dead'`;
  after it, and with the whole suite, `430 passed, 1 skipped`. **D3 and the operations plan
  should use `DeadLetter` for the same shape of permanent failure.**
- **`verify_meta_signature` lives in `social/events.py`, not in `instagram.py`.** The plan's
  File Structure describes `events.py` as the parsers only, but D3's `messenger.py` needs
  byte-identical signature verification and neither router should import the other. `events.py`
  is the module both webhook doors already share.
- **`SocialEvent` has a tenth field, `username`, after the nine the plan lists.** Behaviour 6
  requires the callback item to carry "the sender's IG username", and a comment payload is the
  only place Meta puts one (`value.from.username`); a DM payload has no username at all. The
  field is defaulted to `""` and a DM falls back to the sender id, which is what the test
  asserts. Adding a Graph lookup per DM to fetch a username was rejected: it is one more paid
  call per message for a field only the expired-window path uses.
- **Only `message` and `comment` events become jobs; `echo`, `postback` and `read` are
  recorded in `meta_events` and stopped at the webhook.** Behaviour 2 says "enqueue one job
  per new event" and behaviour 7 says postbacks and reads are "stored as `MetaEvent` and
  ignored"; a job that exists only to do nothing would be five retries of nothing when a
  handler is missing. Self-authored events (sender id equal to the integration's own id) are
  dropped in the same place, for the same reason.
- **`record_inbound` (the `inbound_messages` dedup) is used in addition to `meta_events`, and
  a job retried after a failed send re-sends the reply it already wrote instead of asking the
  model again.** The plan says to pass `provider_message_id=mid` to `handle_inbound`, which
  means a retried job is deduplicated and produces no replies — so a 429 would requeue a job
  that can never deliver anything, which is exactly the silent drop this product exists to
  avoid. `_replies_to_send` therefore reads the trailing run of assistant messages off the
  conversation when the turn was deduplicated. Evidence:
  `test_the_requeued_job_sends_the_reply_it_already_wrote_without_asking_again` asserts two
  identical sends and `len(ctx.llm.calls) == 1`.
- **The `dm_greeting` disclosure is stored as the conversation's first assistant message and
  prefixed onto the first outgoing reply, and "is this the first reply" is read from the
  transcript rather than from a flag.** One Graph send carries greeting plus reply, as the
  plan's test requires; storing it too means an audited transcript shows the AI disclosure was
  given. `greeting_due` compares the count of our messages against the replies about to go
  out, so a retry after a failed send still carries the disclosure and a second turn does not
  repeat it.
- **A failed *public* comment reply is logged and swallowed rather than failing the job.** The
  private reply has already reached the customer at that point; retrying the job would send
  them a second copy of it to recover a cosmetic public sentence.
- **`spatalk/tenants/schema.py`, `runtime/tenants/skincentrix/tenant.yaml` and
  `scripts.yaml` are unchanged.** D2's Files list names all three, but `SocialSettings`
  (`comment_mode`, `comment_keywords`, `public_reply_enabled`) and the `comment_public_reply`
  and `dm_greeting` scripts already exist with the reference's wording, and the Skincentrix
  bundle already authors a `social:` block (`keyword`, five keywords, public reply off).
  Evidence: `grep -n "comment_public_reply\|dm_greeting\|class SocialSettings"
  spatalk/tenants/schema.py` and `grep -n "social:" -A 3 tenants/skincentrix/tenant.yaml` both
  hit; `uv run pytest tests/test_tenant_bundle.py -q` -> `4 passed`, untouched.
- **`CHANNEL_RULES` gained `messenger` as well as `instagram`.** The wording is a Global
  Constraint of this plan ("Instagram and Messenger prompts add: …") and `prompt.py` is a D2
  file, so both entries ship here and D3 does not have to reopen it.
- **Three shared files outside the Files list were touched, all by appending.**
  `spatalk/http/app.py`: one import and `attach_router(app, social_instagram.router)` (the
  helper runtime-A14 requires, because FastAPI 0.141 made `include_router` lazy).
  `spatalk/text/takeover.py`: one `elif` branch for `instagram`/`messenger` delegating to
  `relay_social`, which is the seam B5's report explicitly left for this task; the import is
  inside the function so `social` may import `text` and not the other way round.
  `spatalk/jobs.py`: `DeadLetter`, above.
- **The recorded fixtures carry timestamps at the test clock (2026-09-01 18:00 UTC,
  `1788285600`), not the `1756800000` printed in `api-surface.md`.** The reference documents
  the *shape* of a Meta payload, and the shape is reproduced exactly; the epoch value in the
  document is a year before the suite's `FixedClock`, which would have made every replayed
  event look 12 months stale to the 24-hour window check. `dm_expired.json` deliberately
  carries a timestamp two days old, which is how the window tests are built.
- **The data-deletion status URL is a `GET` on `/instagram/delete`,** the same path as the
  callback Meta posts to, so no route outside the plan's list was invented. Meta requires the
  `url` it is handed to be reachable; it answers in plain words that the connection and its
  token were deleted.
- **Reference-versus-plan check.** `api-surface.md` puts `GET /instagram/connect`,
  `/callback`, `POST /instagram/deauthorize` and `/delete` under **D1**, while the plan's File
  Structure puts them in `social/instagram.py`, a D2 file. D1 reported the same conflict and
  resolved it in favour of the plan; those four routes exist as of this commit, one task later
  than the reference says. Everything else matches: `GET, POST /instagram/webhook | D2 |
  verify token; HMAC-SHA256`, the `meta_events` and `meta_windows` columns, the `ig_in`/`ig_out`
  usage units, the `social.ig_event` job kind, the `callback` item type, and `flows.md` §6's
  four steps.

## Notes for neighbours

- **D3 (Messenger) should reuse this task's machinery rather than copy it.**
  `ingest_events(ctx, "messenger", parse_messenger_payload(body), FB_EVENT_JOB)` is the whole
  webhook body after the signature check; `claim_event`, `record_window`, `window_open`,
  `close_and_capture`, `open_greeting`, `greeting_due`, `_replies_to_send` and `matches_keyword`
  are all channel-agnostic and already take the channel as an argument. Two things are
  Instagram-specific and D3 must parameterise them: `send_message` hard-codes
  `graph.instagram.com` and the `/{ig_user_id}/messages` body (a Page needs
  `graph.facebook.com`, `messaging_type: "RESPONSE"`, and `/{comment_id}/private_replies` for a
  comment), and `answer_inbound` calls `send_message` directly. Add `"messenger": "messenger"`
  to `PROVIDER_FOR_CHANNEL` and `relay_social` starts working for Pages too — the takeover
  branch in `takeover.py` already routes both channels there.
- **`verify_meta_signature(raw, header, (instagram_app_secret, facebook_app_secret))` is the
  check for both webhooks** and must run against the **raw** body bytes, before any JSON
  parsing.
- **D4 (portal)**: the connect URL the Settings page should open is
  `GET /instagram/connect?tenant=<id>&return_to=<portal url>`; the runtime signs the state
  itself and redirects the browser back to `return_to` when the flow finishes. Disconnect
  still goes through `delete_integration` on the internal API, as D1 described.
- **`jobs.DeadLetter` exists now.** Raise it from any handler that has learned another attempt
  would fail the same way; the worker marks the job `dead` immediately and keeps the message
  in `last_error`.
- **`conversations.external_ref` on Instagram is the IG sender id**, and a comment and a DM
  from the same person share it, so a comment-triggered thread and their later DMs are one
  conversation. `conversations.caller` stays null on this channel, as `data-model.md` says.
- **`meta_windows` is now written on every inbound social event** and is what any later
  "can we still message this person" question should read (`window_open`). It never moves
  backwards: a stale replayed event cannot shrink a live window.
- The suite is 430 passed, 1 skipped after this task. The portal's working tree had
  uncommitted changes from a neighbouring task throughout; only this task's files were
  committed, with explicit pathspecs.

Blocked on: nothing.
