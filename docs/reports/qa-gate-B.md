# QA gate B

Verdict: pass with majors

Channels and portal (text-channels plan B1-B6, portal plan C1-C9, instagram plan D1-D5).
QA agent, 2026-09-02. No product code was changed: every mutation used to prove a test
fails was reverted in the same command and `git status` is clean for `runtime/spatalk` and
`portal/src`. No provider API was called: no key exists here, the one live pytest stays
`skipif` on `GOOGLE_API_KEY`, every Graph call goes through `FakeGraphClient`, every SMS
through `MemorySms`, and Stripe is a locally signed fixture event.

## Commands run and results

Runtime (from `runtime/`, Docker Desktop up, Compose Postgres on host port 5434):

| Command | Result |
|---|---|
| `docker compose up -d db` | `runtime-db-1` healthy, `5434->5432` |
| `uv run pytest -q` **with this machine's `runtime/.env` present** | **13 failed, 525 passed, 1 skipped** in 161 s — see finding 1 |
| `uv run pytest -q` **with `runtime/.env` moved aside** (a clean checkout) | **538 passed, 1 skipped** in 135 s; `.env` restored byte-identical afterwards |
| `uv run ruff check spatalk tests scenarios` | All checks passed |
| `uv run spatalk serve --host 0.0.0.0 --port 8001` | served the portal's end-to-end run; `/healthz` answered `{"ok":true,…}` |

Edge worker (from `edge/sms-worker/`, Node 22 on Windows):

| Command | Result |
|---|---|
| `npm ci` (from a deleted `node_modules`) | 87 packages, 0 vulnerabilities |
| `npm test` | **23 passed** (2 files) in 2.7 s |
| `npx tsc --noEmit` | exit 0 |
| `npx wrangler deploy --dry-run` | exit 0, "Total Upload: 10.54 KiB / gzip: 3.26 KiB", KV bindings and `RUNTIME_URL` resolved |

Portal (WSL, `@wasp.sh/wasp-cli` 0.25.0, Node v24.20.0, Chromium via Playwright 1.62.1):

| Command | Result |
|---|---|
| `wasp build` | "Your wasp project has been successfully built" |
| `npm run check:client` | no diff: the committed client and `docs/contracts/runtime-internal.openapi.json` agree |
| `npm run test:unit` | **108 passed** (6 files) |
| `wasp test client run` | **70 passed** (7 files) |
| `npx playwright test` against the live runtime | **77 passed** in 1.9 min (73 existing + the 4 added here) |

How the portal's suite reached the runtime on this machine: the runtime runs on Windows
(`:8001`), and WSL cannot open a Windows host port, so it was published back through
`docker run -d --name spatalk-qa-bridge -p 8011:8011 alpine/socat TCP-LISTEN:8011,fork,reuseaddr TCP:host.docker.internal:8001`
and the suite was run with `RUNTIME_INTERNAL_URL=http://localhost:8011
RUNTIME_INTERNAL_KEY=dummy-internal-key`. This is `portal/e2e-tests/README.md`'s documented
arrangement with different port numbers, because a runtime from an earlier session already
held `:8000`. Playwright's `globalSetup` seeded the Skincentrix bundle into that runtime
itself (`seed_runtime.py`, one tenant at config version 1, four conversations, four items,
a day of usage) and `client.spec.ts` then drove the version to 3 through the settings page
and the rollback.

Secret sweep: the only tracked env files are `runtime/.env.example`,
`portal/.env.server.example`, `portal/.env.client.example` and
`edge/sms-worker/.dev.vars.example`; `git grep` for Stripe, Slack, Google and private-key
shapes across all tracked files returns nothing; `.env`, `.env.server`, `.env.client`,
`.dev.vars`, `mail-sink.log` and `.seed.json` are all gitignored.

## Matrix: 17 / 17 rows proven; rows without proof: none

| Gate B row | Proof |
|---|---|
| Replay recorded Telnyx SMS webhooks, valid signature | **new** `test_qa_gate_b.py::test_the_recorded_telnyx_webhook_is_replayed_and_answered` — the payload is parsed out of `docs/reference/api-surface.md` itself, signed, posted, and the tenant's reply and the stored message are asserted; plus `test_text_sms.py::test_a_telnyx_signature_is_accepted_when_no_edge_key_is_configured` and the worker's `signature.test.ts` (7 cases) |
| …invalid signature | **new** `::test_the_recorded_telnyx_webhook_with_a_forged_signature_answers_nothing` (401, no SMS, no conversation, no message) and `::test_a_recorded_webhook_altered_after_it_was_signed_is_refused`; edge `index.test.ts::rejects an invalid signature with 401 and never reaches the runtime`; `test_text_sms.py::test_a_stale_telnyx_timestamp_is_rejected`. **new** `::test_the_edge_worker_reads_the_recorded_event_the_same_way_the_runtime_does` pins the worker and the runtime to the same field paths of that recorded body |
| STOP handling | `test_text_sms.py::test_stop_writes_an_optout_and_confirms`, `::test_an_opted_out_sender_gets_no_reply`, `::test_start_removes_the_optout_and_replies_with_help`, `::test_help_replies_with_the_help_script`; **new** `::test_a_stop_from_one_number_never_silences_another_number` (the opt-out is that person's, not the tenant's). See finding 2 for the wordings that are *not* honoured |
| One-follow-up rule | `test_text_service.py::test_a_followup_job_is_enqueued_exactly_once`, `::test_the_followup_is_not_sent_when_the_user_replied`; **new** `::test_only_one_followup_is_ever_sent_however_many_questions_follow` (follow-up sent, customer returns, the assistant asks again, three more hours: still exactly one, and no follow-up job left queued) |
| Missed-call text-back at most once per 24 h per number | `test_textback.py::test_a_second_missed_call_within_24_hours_is_not_texted_again`, `::test_a_missed_call_a_day_later_is_texted_back_again`, `::test_a_second_call_before_the_job_runs_does_not_queue_a_second_text`; **new** `::test_two_missed_callers_are_each_texted_once_on_the_same_day` (the window is per number, not per tenant) and `::test_the_missed_call_and_followup_windows_are_the_documented_ones` |
| Takeover pauses the bot, hand-back resumes it | `test_takeover.py::test_a_customer_message_while_a_person_is_replying_is_mirrored_and_unanswered`, `::test_the_hand_back_button_resumes_the_assistant`, `::test_twelve_hours_of_staff_silence_hands_back_and_says_so_in_the_thread`; **new** `::test_a_person_taking_over_pauses_the_bot_on_the_sms_route_and_hand_back_resumes_it` — the whole round trip through `POST /telnyx/sms`, which is where a customer actually meets the pause |
| Widget: WebSocket session with a Turnstile stub | `test_widget.py::test_a_good_turnstile_token_is_accepted`, `::test_a_bad_turnstile_token_closes_the_socket_with_4401`, `::test_a_chat_message_round_trips_through_the_socket`, plus the two rate-limit closes |
| Widget: degrade-to-form path | `test_widget.py::test_the_fallback_form_creates_a_conversation_a_message_and_a_callback_item`, `::test_the_fallback_item_never_carries_the_message_text`, `::test_a_runtime_with_no_model_configured_closes_the_socket_instead_of_erroring`; edge `index.test.ts::queues the form and answers 202 when the runtime is unreachable` |
| Portal: login | `auth.spec.ts` (signup → emailed verification link out of the Dummy-provider mail sink → login → `/app`, and the four signed-in/signed-out redirects) |
| Portal: org switch | **new** `qa-gate-b.spec.ts::the switcher offers exactly the organisations that person belongs to` and `::picking the other one lands on its pages` — a client invited into two of three organisations is offered exactly those two and lands on the second one's pages. Nothing tested `OrgSwitcher` before this |
| Portal: transcript view writes an audit row via the runtime | `client.spec.ts::opening a transcript writes an audit row naming the reader` (read straight out of `runtime.audit_log`) |
| Portal: settings save makes a new config version and the runtime hot-reloads | `client.spec.ts::saving hours writes a new configuration version the runtime serves` (`waitForConfigVersion` polls `/healthz`) |
| Portal: rollback works | `client.spec.ts::rolling back restores the previous configuration` (polls `/healthz` to version 3) |
| Portal: agency admin sees every tenant, a client sees only theirs (two users) | `admin.spec.ts::the agency queries refuse a user who is not an agency admin`, `::lists every organisation with its runtime usage, items and config version`; `orgs.spec.ts::someone who is not a member is refused the organisation`; **new** `qa-gate-b.spec.ts::the organisation it was never offered stays refused by the server` (403 from the server, not only a hidden link) |
| Contract: the portal's generated client matches the committed contract | `npm run check:client` (regenerates and diffs), `src/ci/workflow.server.test.ts` (offline, paths/operations/schemas); **new** `test_qa_gate_b.py::test_the_committed_contract_and_the_portal_client_declare_the_same_paths` proves the same 21 paths and 30 schemas from the runtime side, so a contract change that skips the portal fails pytest too |
| Contract: the runtime's snapshot test passes | `test_contract_snapshot.py` (5 tests) inside the 538 |
| Instagram: replay the fixtures (comment, DM, postback, read) with valid and invalid HMAC; comment-to-private-reply calls the expected Graph endpoints | **new** `::test_every_recorded_meta_payload_is_accepted_with_a_valid_signature` and `::test_every_recorded_meta_payload_is_refused_with_an_invalid_signature`, parametrised over all four Instagram fixtures **and** the three Messenger ones (14 cases), each asserting the `meta_events` row and the job count — a valid signature records every kind and queues only the actionable ones; an invalid one records nothing, queues nothing and calls no Graph endpoint. **new** `::test_a_recorded_meta_payload_altered_after_signing_is_refused`, `::test_the_comment_to_private_reply_path_calls_only_the_documented_graph_endpoint` (exactly one call, `POST /v21.0/<ig user>/messages`, recipient `{"comment_id": …}`) and `::test_the_graph_client_addresses_meta_at_the_documented_host_without_reaching_it` (the real `HttpGraphClient` over an httpx `MockTransport`: `https://graph.instagram.com/v21.0/…/messages` and a bearer header, no socket) |

Before the additions the two channel gaps were: an invalid HMAC was only ever replayed with
one Instagram fixture (`test_a_bad_signature_is_401_and_nothing_is_queued`, the DM), and the
URL the real Graph client builds was asserted nowhere, because every other test asserts
against `FakeGraphClient`'s recorded path.

Every new test was seen failing before it was trusted, by temporarily mutating product code
and reverting it in the same command (`git status` clean after each):

- `_authorized` in `http`/`text/sms.py` forced true → both forged-signature tests fail.
- `is_opted_out` made tenant-wide → `::test_a_stop_from_one_number_never_silences_another_number` fails.
- `Textback.phone == phone` dropped from the window query → `::test_two_missed_callers_are_each_texted_once_on_the_same_day` fails ("already texted today" for the second caller).
- both `followup_sent_at` guards removed → the one-follow-up test fails with 2 sends.
- `conv.controller == "human"` forced false → the takeover round trip fails.
- `verify_meta_signature` forced true → all 8 invalid-signature cases and both tampered-body cases fail.
- `listMyOrganizations`'s non-admin early return removed → the switcher test fails and prints the 50 organisations it was then offered.
- `OrgSwitcher`'s `navigate` removed → `::picking the other one lands on its pages` fails.

## Findings

- [major] **The runtime suite is not hermetic: it reads the developer's `runtime/.env`, and
  CI will go red the moment a Gemini key exists.** `Settings` is
  `SettingsConfigDict(env_file=".env")` (`runtime/spatalk/settings.py:7`) and the test
  helpers construct `Settings(secret_key="s3cret", …)` without disabling it
  (`tests/test_widget.py:50`, `tests/test_text_sms.py:54`, `tests/test_takeover.py:67`), so
  every field a test does not name is inherited from whatever the machine holds. On this
  machine `uv run pytest -q` is **13 failed, 525 passed, 1 skipped**; with `.env` moved
  aside it is **538 passed, 1 skipped**. Three separate inheritances:
  `TURNSTILE_SECRET_KEY` (11 widget/takeover tests: the socket now runs the *real* verifier,
  which `POST`s the tenant's live Turnstile secret to `https://challenges.cloudflare.com/turnstile/v0/siteverify`
  during `pytest` — `runtime/spatalk/text/chat.py:80-91`, reached because
  `chat_ws` only stubs through `app.state.turnstile_verifier`);
  `EDGE_SHARED_KEY` (`test_text_sms.py::test_a_telnyx_signature_is_accepted_when_no_edge_key_is_configured`
  gets 401, because `_authorized` prefers the edge key); and `GOOGLE_API_KEY`
  (`test_widget.py::test_a_runtime_with_no_model_configured_closes_the_socket_instead_of_erroring`
  gets an accepted socket, because `make_text_llm` builds a real client). That last one is
  the CI risk: `.github/workflows/ci.yml:17` puts `GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}`
  in the **runtime job's** environment so the promptfoo step can be gated on it, so as soon
  as the founder adds that secret — which the runbook and gate A both ask for — the runtime
  job fails on a test that has nothing to do with the model. Reproduce:
  `cd runtime && uv run pytest -q tests/test_widget.py` (11 of the 13 failures; the other
  two are in `test_text_sms.py` and `test_takeover.py`), then `GOOGLE_API_KEY= TURNSTILE_SECRET_KEY= EDGE_SHARED_KEY= uv run pytest -q tests/test_widget.py`
  → 22 passed. Suggested fix for the engineer, one line and no test weakened: build test
  settings with `Settings(_env_file=None, …)` (pydantic-settings honours the underscore
  argument), or add an autouse `conftest.py` fixture that clears the provider variables for
  the whole session. QA's own `tests/test_qa_gate_b.py` states every setting it depends on,
  including the empty ones, and therefore passes in both environments.
- [major] **SMS opt-out is an exact-match keyword list, so "STOP." is answered by the model
  instead of unsubscribing the sender.** `runtime/spatalk/text/sms.py:32-34` holds
  `STOP_WORDS = {"stop", "unsubscribe", "cancel", "end", "quit", "stopall"}` and line 138
  matches `text.strip().lower()` against it whole. Probed with a throwaway parametrised test
  (written under `runtime/tests/`, run, then deleted, so the committed suite carries no test
  that asserts a defect):
  `'STOP'` → opted out; `'stop'` → opted out; `' STOP '` → opted out; `'UNSUBSCRIBE'` →
  opted out; but **`'STOP.'`, `'STOP ALL'`, `'stop!'`, `'Please stop'` and `'unsubscribe me'`
  → not opted out**, and each was handed to the brain, which answered. `STOP ALL` is one of
  the CTIA standard opt-out keywords and a trailing full stop is what a phone keyboard
  produces on its own. Nothing in `docs/reference/` promises that Telnyx's own
  messaging-profile opt-out handling is enabled, so the runtime is the only net here.
  Reproduce: post `sms_event("STOP.", "m1")` through `POST /telnyx/sms` and query
  `sms_optouts`. Not an S4/S5 failure (nothing claims an action it did not take), but it is
  a compliance rule the tests do not cover. Suggested fix: strip trailing punctuation and
  match the first word, or fold the CTIA set (`STOP`, `STOPALL`, `STOP ALL`, `UNSUBSCRIBE`,
  `CANCEL`, `END`, `QUIT`) with a `startswith` on a normalised message.
- [minor] **The end-to-end suite leaves organisations behind, and the agency page pays for
  it every run.** Each Playwright run creates organisations that are never removed:
  `billing.spec.ts` one per run (`billing-test-<8 hex>`), `orgs.spec.ts` one
  (`skincentrix-<8 hex>`), `admin.spec.ts` one, and now `qa-gate-b.spec.ts` three. The
  portal database currently holds about fifty, most of whose runtime tenants do not exist,
  so `getAgencyTenants` fans out to the runtime for all of them and logs a 404 apiece; the
  observed call took **4136 ms**. Nothing fails yet, and the page is right to tolerate a
  missing tenant, but the run gets slower every time. Reproduce: run the suite twice and
  compare `select count(*) from public."Organization"`. Suggested fix: an `afterAll` that
  deletes the organisations a spec created, or a fixed slug per spec instead of a random one.
- [minor] **`runtime/.env.example` line 51 makes `/healthz` report a comment as the deployed
  commit.** `GIT_COMMIT=` followed by whitespace and `# set by the image build; reported by
  /healthz` parses, in python-dotenv, as the value `"# set by the image build; reported by
  /healthz"` — an inline comment is only stripped when the value is non-empty. Anyone who
  copies the example gets that string, and this machine's runtime does:
  `curl localhost:8001/healthz` → `"commit":"# set by the image build; reported by /healthz"`.
  Reproduce: `uv run python -c "from dotenv import dotenv_values; print(dotenv_values('.env.example')['GIT_COMMIT'])"`.
  Suggested fix: put the comment on its own line above the assignment. Worth checking the
  other empty-valued keys in that file the same way.
- [minor] `docs/reference/api-surface.md:135` lists the portal's server environment as
  `SMTP_*` and omits `PORTAL_EMAIL_PROVIDER`, which Wasp bakes in at compile time and which
  the end-to-end suite has to pin to `Dummy` (`portal/e2e-tests/playwright.config.ts`) while
  `wasp build` refuses that value. The variable exists only in `portal/.env.server.example`
  and in task reports C1 and C8. A founder reading the reference to fill in an environment
  will not know it is there.
- [minor] Gate A's two majors are both closed, verified here rather than assumed:
  `runtime/spatalk/brain/rules.py:37` now carries `"pay over the phone"` and `"pay by phone"`
  in the payment lexicon, and `runtime/spatalk/http/slack.py:31-40` now verifies a signed
  claim out of the button value (`verify_action`), refuses `BadSignature` with 401, and
  compares `item.tenant_id` with the claim's tenant, answering 403 on a mismatch. Recorded
  so gate C does not re-open them.

No blocking findings. Nothing claims an action it did not take on any of the three new
channels, every webhook verifies its signature and refuses a tampered body, the Meta tokens
are Fernet-encrypted and never reach the browser (`integrations.spec.ts`), no free-text field
was added to an item by the text, chat or social paths, no test was weakened, skipped or
deleted, and every suite passes on a clean checkout.

## Tests added

- `runtime/tests/test_qa_gate_b.py` — 28 tests (new file): the recorded-Telnyx replay set,
  the per-number STOP rule, the one-follow-up rule, the per-number text-back window, the
  takeover round trip through `POST /telnyx/sms`, the 14-case Meta HMAC matrix over every
  recorded fixture on both adapters, the tampered-body cases, the Graph endpoint and URL
  proofs, and the contract-to-portal-client check from the runtime side.
- `portal/e2e-tests/tests/qa-gate-b.spec.ts` — 4 Playwright tests (new file): the
  organisation switcher, which had no test anywhere, and the server-side refusal of an
  organisation it never offered.

## Owed before go-live (not gate blockers)

- The 13 ambient-`.env` failures (finding 1) should be fixed before `GOOGLE_API_KEY` is added
  to the repository secrets, or the runtime CI job will fail on the same push.
- `promptfoo eval` is still unrun for the text and social cases: no `GOOGLE_API_KEY` exists
  here, so `test_text_scenarios.py` and `test_social_scenarios.py` prove only the graders and
  the deterministic halves.
- Meta app review, the Telnyx messaging profile's own opt-out setting, and the manual
  barge-in call from gate A remain founder morning steps.
