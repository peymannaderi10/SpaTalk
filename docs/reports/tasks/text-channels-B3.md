# text-channels Task B3: Missed-call text-back

Status: done with deviations
Commit: dc1ca3d (implementation, tests and this report; the hash is recorded by the docs commit
that follows, the convention set by runtime-A8 through A16 and text-channels B1/B2)
Tests: `uv run pytest tests/test_textback.py -q` -> 18/18 (17 seen failing first, the 18th
vacuously green before the module existed); full runtime suite `uv run pytest -q` -> 246 passed,
1 skipped of 247 (baseline before this task: 228 passed, 1 skipped).
`uv run ruff check spatalk tests scenarios` -> All checks passed!
Interfaces produced: `spatalk.text.textback.schedule_missed_call_textback(ctx, session,
had_user_speech, duration_s) -> bool`; job handler kind `sms.textback` with payload
`{tenant_id, to, conversation_id}`; module constants `TEXTBACK_WINDOW` (24 h) and
`SHORT_CALL_SECONDS` (20.0).

## What it does

`_finalize` in `spatalk/voice/pipeline.py` now ends every call by asking
`schedule_missed_call_textback` whether this caller is owed a text. It passes the wall-clock
duration it already computes for `telephony_seconds` and a `had_user_speech` flag derived from the
context transcript it already walks (any `user` message with text). Nothing else in the pipeline
changed.

The scheduler enqueues only when every one of the plan's conditions holds: a caller id is present;
the call was short (`duration_s < 20`) **or** carried no caller speech at all; the tenant has an
`sms_from_number`; the caller id is not one of our own numbers or the clinic's own line; the caller
is not opted out; there is no `textbacks` row for that (tenant, phone) inside 24 h; and no
`sms.textback` job for that pair is still queued.

The `sms.textback` handler re-checks the opt-out and the 24-hour window (the job can run minutes
after the call, and an opt-out in between must win), renders `scripts.missed_call_text` with the
tenant's name and `booking_url_default`, sends it through the `SmsPort`, then writes the assistant
message, the `sms_out` usage event and the `textbacks` row. The SMS conversation it finds or
creates is keyed on the caller's E.164 — the same key `TextConversationService` uses — and its
`external_session` is set to the voice conversation id, so the caller's reply joins that
conversation and staff can read it against the call it followed.

## Tests: failing before, passing after

Written first against a missing module: `17 failed, 1 passed` (the one that passed asserts *no*
job exists, which an absent feature satisfies by accident). After the implementation: `18 passed`.
Named after the behaviours the plan lists:

- sent once for a 5-second hang-up (asserting the exact from/to, the tenant's authored wording and
  the booking URL, and a single `textbacks` row);
- a long call the caller never spoke on is still texted back (the caller-id-lost / dead-air case);
- outbound SMS usage is metered exactly once as `sms_out` on channel `sms`;
- the text-back conversation is linked to the voice call (`external_session`, `external_ref`,
  `caller`, `last_message_at`, and a transcript holding only the assistant's fixed line);
- a reply to the text-back continues that same conversation through
  `TextConversationService.handle_inbound`;
- not sent after a full conversation; not sent twice within 24 h; sent again after 25 h; a second
  call before the job runs queues no second text; an opted-out caller is never texted; a caller who
  opts out between the call and the job is not texted; a caller id equal to the clinic's public
  phone is not texted; a caller id equal to one of our own numbers is not texted; a call with no
  caller id is not texted; a tenant with no SMS number never texts back;
- the end of a hang-up call schedules the job with the documented payload, and the end of a real
  conversation schedules nothing (both driving the real `_finalize`).

## Deviations

- **`runtime/tenants/skincentrix/scripts.yaml` is unchanged.** B3's Files list names it for
  `missed_call_text`, but the runtime plan already authored that string in both the bundle and the
  `Scripts` schema default. Evidence:
  `grep -n missed_call_text tenants/skincentrix/scripts.yaml` ->
  `missed_call_text: "Hi, this is Skincentrix's assistant. You just called us. Reply here and I can
  help, or book online: {booking_url}"`, and `tests/test_textback.py` asserts the sent text starts
  with exactly that sentence.
- **No model change and no migration.** `data-model.md` brackets `textbacks` `[B3]`, but Task B2
  created the table (its own Interfaces block listed it, and B3's Files list has neither
  `models.py` nor a migration), with the documented columns and the `(tenant_id, phone, sent_at)`
  index. `Conversation.external_session` likewise already exists. Evidence:
  `uv run pytest tests/test_qa_gate_a.py -q` -> `83 passed` untouched, and the new tests read and
  write both without a schema change.
- **`sent_at` is written from `ctx.clock`, not from the database's `now()`.** The column keeps its
  `server_default`, but the handler passes `sent_at=ctx.clock.now()` explicitly, because the
  24-hour window is decided against the application clock and a `FixedClock` test would otherwise
  compare a fixed `now()` against a real wall-clock row: the row's real timestamp sits inside
  `clock.now() + 25 h - 24 h`, so the day-later call reads as already texted. Evidence: with
  `s.add(Textback(tenant_id=tenant_id, phone=to))`, `uv run pytest tests/test_textback.py -q` -> `1 failed, 17 passed`,
  `FAILED test_a_missed_call_a_day_later_is_texted_back_again`, log line
  `caller +19055550101 was already texted back today`; with `sent_at=now`, `18 passed`.
- **"One of the tenant's own numbers" is checked four ways, and the comparison is on the national
  ten digits.** `cfg.public_phone` is authored as `905-703-7546` in the Skincentrix bundle while a
  carrier presents `+19057037546`, so `_same_number` strips non-digits and compares the last ten.
  The check covers `public_phone`, `sms_from_number`, `cfg.voice_numbers` and
  `registry.resolve_number(phone)` (the authoritative `tenant_numbers` table). The plan named only
  `public_phone` and "the tenant's own numbers"; `tenant_numbers` is what `data-model.md` calls
  authoritative, so it is included.
- **A queued-but-unsent `sms.textback` job blocks a second one.** The plan's guard is the
  `textbacks` row, which the handler writes; two missed calls a minute apart would both enqueue
  before either job ran. The scheduler therefore also looks for a queued job for the same
  (tenant, phone), the same way `TextConversationService.schedule_followup` guards the follow-up.
  Test: `test_a_second_call_before_the_job_runs_does_not_queue_a_second_text`.
- **The handler is registered by importing `spatalk.text.textback`, which
  `spatalk/voice/pipeline.py` imports**, which `spatalk/http/app.py` imports. Evidence:
  `uv run python -c "from spatalk.http.app import create_default_app; from spatalk import jobs;
  print(sorted(jobs._HANDLERS))"` -> `['deliver.email', 'deliver.slack', 'digest.email',
  'sms.textback', 'text.followup']`. There is no import cycle: `spatalk/voice/session.py` (which
  `textback.py` imports for the `VoiceSession` annotation) imports only `brain`, `clock` and
  `tenants.schema`.
- **Reference-versus-plan check: no disagreement found.** `data-model.md`'s `textbacks` columns and
  index, its `jobs.kind` enum (which lists `sms.textback`), its `conversations.external_session`
  meaning ("SMS text-back → voice id") and `flows.md` §1 step 11 ("Missed-call text-back decision
  (B3)") all match what is implemented.

## Notes for neighbours

- **B5 (takeover): the text-back creates a real SMS conversation before any customer message
  exists.** It holds one `assistant` message and `controller = "ai"`. If the caller never replies
  it simply ages out of the 24-hour window. Nothing schedules a follow-up for it — the follow-up is
  owed only after a model turn ends in a question — so a silent caller receives exactly one message.
- **B4 (chat) and D2 (social) share `find_or_create_conversation` with this handler.** SMS
  conversations are keyed on the caller's E.164 as `external_ref`; a text-back and a later inbound
  SMS from the same number inside 24 h are the same conversation row, by design.
- **The 20-second threshold and the 24-hour window are module constants**
  (`SHORT_CALL_SECONDS`, `TEXTBACK_WINDOW`), not tenant config. If the portal ever needs to expose
  them, they become `tenant.yaml` fields and `tenant-config.md` gains two rows; nothing in this
  task assumed they are fixed forever.
- **`_finalize` now has one more await after `end_conversation`.** Anything that stubs the voice
  pipeline's teardown (E5's stage-latency work is the next thing to touch `_finalize`) must keep
  the text-back call last, so a caller is only offered a text after the call is fully recorded.
