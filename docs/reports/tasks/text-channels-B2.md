# text-channels Task B2: Text conversation service and the SMS adapter

Status: done with deviations
Commit: 2a305eb (implementation, tests and this report; the hash is recorded by the docs commit
that follows, the convention set by runtime-A8 through A16)
Tests: `uv run pytest tests/test_segments.py tests/test_text_service.py tests/test_text_sms.py -q`
-> 37/37 (all seen failing first); full runtime suite `uv run pytest -q` -> 228 passed, 1 skipped
of 229 (baseline before this task: 191 passed, 1 skipped). `uv run ruff check spatalk tests scenarios`
-> All checks passed! Migration verified on a fresh database: `alembic upgrade head` from empty
ran `-> 0001, initial` then `0001 -> 0002, text channels`.

Interfaces produced: `spatalk.text.segments.split_sms(text, limit=300) -> list[str]`;
`spatalk.text.service.TextConversationService(ctx, llm)` with `handle_inbound(tenant_id, channel,
external_id, sender, text, provider_message_id) -> InboundResult`, `find_or_create_conversation(
tenant_id, channel, external_id, sender) -> Conversation`, `history(conversation_id, limit=20) ->
list[dict]`, `schedule_followup(conversation) -> int | None`;
`spatalk.text.service.InboundResult(conversation_id, replies, turn, suppressed, reason)`;
`spatalk.text.service.record_inbound/is_opted_out/add_optout/remove_optout/make_text_llm`,
constant `STAFF_NOTE`; job handler kind `text.followup`; `spatalk.text.sms.router` serving
`POST /telnyx/sms`, plus `spatalk.text.sms.verify_telnyx_signature(raw_body, signature_b64,
timestamp, public_key_b64, tolerance_seconds=300) -> bool`;
`spatalk.models.InboundMessage`, `spatalk.models.SmsOptout`, `spatalk.models.Textback`, and
`Conversation.last_message_at / closed_at / followup_sent_at / external_session`;
`Settings.edge_shared_key`, `Settings.telnyx_public_key`; `jobs.JobContext.llm`.

## Deviations

- **Two shared files outside B2's Files list were touched, both by appending:
  `spatalk/jobs.py` and `spatalk/http/app.py`.** The plan gives B2 a router (`POST /telnyx/sms`)
  but no way to reach it or to give it a model. `JobContext` gained one defaulted field,
  `llm: Any = None` (appended after `sms`, so no positional construction changed), and
  `create_app` gained `attach_router(app, text_sms.router)` with `build_context` setting
  `llm=make_text_llm(settings)`. `make_text_llm` returns `None` when `GOOGLE_API_KEY` is unset, so
  `build_context` still constructs without a key (`GeminiClient` raises
  `ValueError: No API key was provided` at construction — runtime-A13 recorded the same fact); the
  router then builds the client on first use and answers 503 if there is still no key. Evidence:
  `uv run pytest tests/test_text_sms.py::test_the_sms_route_is_on_the_app -q` -> `1 passed`, and
  `uv run python -c "from spatalk.http.app import create_default_app; print(sorted({r.path for r in create_default_app().routes}))"`
  -> `['/a/{token}', '/docs', '/docs/oauth2-redirect', '/healthz', '/openapi.json', '/redoc', '/slack/interactions', '/telnyx/sms', '/telnyx/texml', '/ws/{token}']`.
  Routers are attached with `attach_router`, per runtime-A14; `text_sms.router` carries no prefix,
  tags or dependencies, so that helper is still equivalent to `include_router`.
- **`tests/test_qa_gate_a.py` needed two corrections, and they are corrections rather than
  loosenings.** (a) `test_alembic_head_creates_every_documented_table_and_index` asserted
  `tables - documented == {"alembic_version"}` where `documented` was only the tables tagged
  `Task 7` in `data-model.md`, so any later plan's table failed it. `_documented_tables` gained
  `only_task_7: bool = True` and the exactness check now runs against **every** table
  `data-model.md` documents; the schema still may not contain a table the reference does not name,
  which is the assertion's point. (b) `EXPECTED_INDEXES` carried
  `("conversations", ("tenant_id", "channel", "external_ref"), False)` under a comment saying
  "Columns added by later plans (last_message_at, slack_ts) are excluded"; `data-model.md`
  specifies `(tenant_id, channel, external_ref, last_message_at desc)` for find-or-create and this
  is the task that can create it, so the expectation moved to the documented four-column form.
  Evidence: before the edits `uv run pytest -q` -> `1 failed, 227 passed, 1 skipped`, with
  `AssertionError: ['alembic_version', 'inbound_messages', 'sms_optouts', 'textbacks']` and then
  `AssertionError: index ('conversations', ('tenant_id', 'channel', 'external_ref'), False) missing`;
  after them `uv run pytest tests/test_qa_gate_a.py -q` -> `83 passed`. No assertion was deleted or
  relaxed, and the index is created with the four columns in ascending order because a btree scans
  backwards for `ORDER BY last_message_at DESC` just as well, and a `DESC` term in `__table_args__`
  does not round-trip cleanly through autogenerate.
- **`spatalk/tenants/schema.py` and `runtime/tenants/skincentrix/scripts.yaml` are unchanged.**
  B2's Files list names both, but the runtime plan already shipped every field they were to gain:
  `Scripts` already carries `followup, missed_call_text, offline_reply, chat_greeting, link_shown,
  optout_confirm, help_text, takeover_notice`, `Destination.channel_id` exists, and
  `Delivery.staff_phone_numbers` exists; the Skincentrix bundle already authors all of those
  strings. Evidence: `grep -c "optout_confirm\|help_text\|takeover_notice" spatalk/tenants/schema.py`
  -> non-zero for each, and `uv run pytest tests/test_tenant_bundle.py -q` -> `4 passed` untouched.
- **`Textback` (table `textbacks`) is created here even though `data-model.md` brackets it
  `[B3]`.** B2's own Interfaces block lists it among the models B2 adds, and B3's Files list
  contains no `models.py` and no migration, so leaving it out would leave B3 with no table. Columns
  are exactly what `data-model.md` documents (`id` bigserial, `tenant_id`, `phone`, `sent_at`) with
  index `(tenant_id, phone, sent_at)`. B3 needs no schema work.
- **The follow-up's "the customer stayed silent" test is stricter than the plan's wording.** The
  plan says the handler sends "only if no user message arrived after the assistant's last
  message". Taken literally that fires: a customer who replies and gets answered leaves an
  *assistant* message last, so the stale follow-up would still go out two hours after a
  conversation that carried on. `schedule_followup` therefore stores `after_message_id` (the last
  `messages.id` at scheduling time) in the job payload and the handler skips when any newer message
  exists. Evidence: with the literal rule,
  `uv run pytest tests/test_text_service.py::test_the_followup_is_not_sent_when_the_user_replied`
  -> `1 failed`, `assert all("Just checking in" not in body ...)`; with `after_message_id`,
  `17 passed`. The "one follow-up per conversation, ever" constraint is still the
  `followup_sent_at` column, checked in both the scheduler and the handler.
- **Quiet hours use `BusinessCalendar.next_open`, which lands on the tenant's opening time, not
  literally 09:00.** The plan says "move to 09:00 next business day via `BusinessCalendar.next_open`";
  `next_open` returns the next time the clinic is actually open (10:00 or 12:00 for Skincentrix),
  which is never earlier than 09:00, so the guarantee the plan wants holds and no second concept of
  "09:00" is invented. The window checked is local `09:00 <= hour < 21:00`.
- **`cryptography>=42` added to `runtime/pyproject.toml`.** Telnyx signs webhooks with Ed25519 and
  the runtime now verifies them directly, so the package is imported rather than merely inherited
  from Pipecat. It was already installed transitively, so the lock moved by two lines. Evidence:
  `uv run python -c "import cryptography; print(cryptography.__version__)"` -> `50.0.1`;
  `git diff --stat -- runtime/uv.lock` -> `1 file changed, 2 insertions(+)`.
- **Opt-out enforcement lives in the service, not only in the router, and the three compliance
  keywords are answered even to an opted-out number.** STOP/START/HELP replies are the fixed
  carrier-required confirmations (plan step 4, which runs "before anything else"); every other send
  is blocked by `is_opted_out` checks in both `handle_inbound` and `_deliver`, so an adapter cannot
  forget the rule. An opted-out sender's message is still stored, as the plan requires, which is why
  the router hands it to the service rather than returning early.
- **`handle_inbound(provider_message_id=None)` means "the caller already claimed this id".** The
  SMS router must deduplicate before STOP is processed (otherwise a re-delivered STOP sends a second
  confirmation), so it calls `record_inbound` itself and passes `None`. Chat and the social adapters
  will pass the real id and let the service dedup.
- **`.env.example` documents `EDGE_SHARED_KEY` and `TELNYX_PUBLIC_KEY`**, which `api-surface.md`
  lists for plan B; `.env.example` is a Task-1 file but its stated job is "every environment
  variable, documented".
- The prompt gained `CHANNEL_RULES` (`sms` -> "Reply in under 300 characters, plain text, no
  lists.", `chat` -> "Reply in under 500 characters, plain text.") appended to the hard rules; the
  voice prompt is byte-identical to before, so `tests/test_tools_prompt.py` is untouched and passes.

## Notes for neighbours

- **B3 (missed-call text-back) needs no migration.** `textbacks` exists with
  `(tenant_id, phone, sent_at)` indexed, and `Conversation.external_session` exists for linking the
  text-back's SMS conversation to the voice conversation. Reuse `spatalk.text.service.is_opted_out`
  before sending, and note that `find_or_create_conversation` keys SMS conversations on the
  **sender's E.164** as `external_ref`, so the conversation B3 creates for the caller is the one the
  caller's reply will join — set its `last_message_at` when you create it or the window check
  (`last_message_at IS NOT NULL AND >= now - 24h`) will not match it.
- **B4 (web chat) gets the service for free.** Call
  `handle_inbound(channel="chat", external_id=<session uuid>, sender=None, provider_message_id=<id>)`.
  `_deliver` deliberately sends nothing for non-SMS channels — the socket is yours — but the usage
  units are already metered (`chat_in`, `chat_out`, provider `web`). `SEGMENT_LIMIT` has no entry
  for `chat`, so `replies` is a single whitespace-normalised string. Follow-ups are only scheduled
  for `channel == "sms"` with a caller phone, because there is no way to reach a chat visitor later;
  if B4 wants one, that is a new delivery route, not a change to `schedule_followup`'s guard.
- **B5 (takeover) has its seams already cut.** `handle_inbound` returns
  `InboundResult(suppressed=True, reason="human")` without calling the model whenever
  `conversations.controller == "human"`, and stores the customer message first — mirroring that
  message to the Slack thread is the one line B5 adds there. `history()` never puts staff wording in
  the model's context: a run of `role="staff"` messages collapses to the single constant
  `STAFF_NOTE`, so the model can neither repeat a person's promise nor treat it as its own. B5 still
  owns `slack_channel` / `slack_ts` on `conversations` and their migration (`0003`).
- **`JobContext` now has `llm`.** Any future text adapter should take the client from `ctx.llm`
  rather than constructing one; `make_text_llm(settings)` is the single production factory and
  returns `None` without `GOOGLE_API_KEY`, which is what keeps `build_context` importable on a
  machine with no keys.
- **`text.followup` is registered by importing `spatalk.text.service`**, which `spatalk.text.sms`
  imports, which `spatalk/http/app.py` imports. Anything that builds a `JobContext` and runs the
  worker without going through `app.py` (a standalone worker container, the scenario runner) must
  import one of those or the job dies with `no handler for text.followup` after five attempts.
- **Conversation band is now `greatest(coalesce(band, 0), turn.band)` on text channels**, so a
  later routine turn cannot erase the fact that an earlier one reached band 3. Voice still writes
  the band once at `_finalize`; if E5 or the audit ever reads band mid-conversation, this is the
  column's meaning on text.
- **Shared test database:** three unrelated tests (`test_app.py::test_healthz_and_routes_present`,
  `test_jobs.py::test_enqueue_run_retry_and_dead_letter`,
  `test_qa_gate_a.py::test_transcript_read_and_acknowledge_each_write_one_audit_row`) failed once in
  a full-suite run and passed both in isolation and on the two immediately following full runs. The
  `engine` fixture does `drop_all` + `create_all` on `spatalk_test` per test, so two agents running
  `pytest` at the same time on this machine will drop each other's schema mid-test. `edge/` and
  `portal/` appeared in the working tree during this task, so neighbours are active: run the suite
  when you have the database to yourself, and do not read a lone failure of those three as a
  regression. Final verified state: `228 passed, 1 skipped`, twice in a row.
