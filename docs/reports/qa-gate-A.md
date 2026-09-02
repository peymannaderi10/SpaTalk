# QA gate A

Verdict: pass with majors

Runtime gate A (after Task 16). QA agent, 2026-09-02. No product code was changed; only
tests and promptfoo cases were added. No provider API was called: no key exists in this
environment, and the single live test stays `skipif` on `GOOGLE_API_KEY`.

## Commands run and results

Run from `runtime/`, Docker Desktop up.

| Command | Result |
|---|---|
| `docker compose up -d db` | container `runtime-db-1` running; `spatalk` and `spatalk_test` present (created by `scripts/init-test-db.sql`) |
| `uv venv <throwaway> --python 3.12` + `uv pip install --python <throwaway> -e ".[dev]"` | exit 0, clean resolve into an empty venv |
| `python -m pytest -q -p no:cacheprovider` (clean venv, cold bytecode caches) | **184 passed, 1 skipped** in 16.9 s |
| `python -m ruff check spatalk tests scenarios` (clean venv) | All checks passed |
| `uv run pytest -q` (project venv) | 184 passed, 1 skipped in 11.5 s |
| `uv run ruff check spatalk tests scenarios` (project venv) | All checks passed |
| `python -m alembic upgrade head` against a throwaway `spatalk_qa_gate_a` database | exit 0; driven from `tests/test_qa_gate_a.py` |
| `promptfoo eval` | **not run**: no `GOOGLE_API_KEY` in this environment. 8 new cases added to the config, unexecuted. |

Baseline before QA's additions was 101 passed / 1 skipped; the 83 tests added here bring
it to 184. The one skip is `tests/test_driver.py::test_gemini_client_calls_a_tool`, which
is `skipif` on `GOOGLE_API_KEY` as required. Nothing is weakened, xfailed or deleted.

Secret sweep: `runtime/.env` is untracked and gitignored; the only tracked env file is
`runtime/.env.example` with empty values; `git grep` for API-key, Slack-token and private-key
shapes across all tracked files returns nothing; the Skincentrix bundle references
`SKINCENTRIX_SLACK_WEBHOOK` by name, never a value.

## Matrix: 16 / 16 rows proven; rows without proof: none

| Brief | Requirement | Proof |
|---|---|---|
| §7.2, S4 | No completion wording without a `Completed` outcome, text and voice | `test_driver.py::test_guard_blocks_hallucinated_completion_and_files_item`; `test_voice_processors.py::test_guard_replaces_completion_claim_and_drops_rest`; **new** `test_qa_gate_a.py::test_adversarial_demand_to_confirm_an_appointment_is_blocked_and_filed`, `::test_adversarial_staff_claim_with_a_hallucinated_booking_is_blocked` |
| §7.2 | A refusal never claims anything was filed | `test_renderer.py::test_refusals_never_claim_anything_was_filed`; **new** `::test_ledger_failure_refuses_with_the_clinic_phone_and_claims_nothing` and `::test_ledger_failure_on_the_voice_gate_refuses_instead_of_promising_a_callback` (ledger raises; the reply carries 905-703-7546 and none of "sent", "confirm with you", "passed it to the team") |
| §7.1, S5 | Clinical, complaint, payment, legal, explicit human request go to band 3 with fixed wording and no model call | `test_rules.py`, `test_driver.py::test_rules_gate_short_circuits_without_llm`; **new** 40 paraphrases (10 per category) in `::test_rules_gate_routes_each_paraphrase_to_its_own_band_3_reason`, the miss list pinned by `::test_the_recorded_gate_misses_are_exactly_the_known_backlog`, and the second net proved by `::test_the_model_escalate_tool_is_the_second_net_for_every_gate_miss` |
| §7.4 | No free text on items; health context is a flag | `test_structural_honesty.py::test_item_draft_has_no_free_text_field`, `test_tools_prompt.py::test_tools_have_no_free_text_parameters` |
| founder 2026-09-01 | Volunteered health context proceeds, flags, no advice | `test_rules.py::test_volunteered_health_context_is_flagged_not_gated`, `test_driver.py::test_volunteered_health_context_flags_item_and_proceeds`; **new** `::test_adversarial_pregnancy_context_proceeds_flags_and_gives_no_advice`; promptfoo `health_context_no_advice` and QA-A6 |
| §7.3 | Disclosure is uninterruptible | **new** `::test_disclosure_is_spoken_on_connect_and_cannot_be_interrupted` (asserts `user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()]` and the on-connect `render_script("disclosure"` in `voice/pipeline.py`, and that the pipecat symbol imports). Still owed: the manual barge-in test on a real call in the morning. |
| §7.3 | Human request after hours leads to a captured callback with a stated time | `test_tier_c.py::test_escalate_is_urgent`; **new** `::test_human_request_after_hours_captures_a_callback_with_a_stated_time` (Wed 00:00 Toronto, calendar closed, no model call, urgent item, reply says "within 15 minutes") |
| §4.3 | Due times respect business hours; breached items escalate once on every channel | `test_hours.py`, `test_scheduler.py::test_breached_item_is_escalated_once_on_all_channels` |
| §4.3 | Acknowledge and resolve without login; links do nothing on GET | `test_http_actions.py`; **new** `::test_get_never_changes_item_state_even_with_a_valid_token` (valid `ack` and `resolve` tokens; state stays `open`, `acknowledged_at` and `resolved_at` stay null) |
| §4.4 | Per-item email and Slack, digest once per local day | `test_delivery.py`, `test_scheduler.py::test_digest_sent_once_per_local_day_after_digest_time` |
| §4.7 | Usage events per conversation and channel; latency per call | `test_conversations.py`; **new** `::test_usage_observer_accumulates_llm_and_tts_metrics` (constructed `MetricsFrame` with `LLMUsageMetricsData` + `TTSUsageMetricsData`, accumulated over two frames) and `::test_turn_latency_observer_records_one_reading_per_turn` |
| §10 | Audit row on transcript read and on every action | **new** `::test_transcript_read_and_acknowledge_each_write_one_audit_row` (`GET /a/<transcript>` then `POST /a/<ack>` leaves exactly `read_transcript/conversation` by `link` and `ack/item` by the named actor) |
| §8.3 | Every provider swappable by env | **new** `::test_stt_and_tts_providers_are_chosen_by_environment_without_network` (`STT_PROVIDER=deepgram_flux` builds `DeepgramFluxSTTService`, `TTS_PROVIDER=deepgram_aura2` builds `DeepgramTTSService`, defaults build Soniox and Inworld, no socket opened) and `::test_no_provider_is_hard_wired_into_the_brain_or_the_ledger` over 15 modules |
| security | Slack signature verified; stream tokens expire; action tokens signed | `test_http_actions.py::test_slack_interaction_requires_valid_signature_and_resolves`, `test_voice_tokens.py`, `test_links.py` |
| §4.5 | Every fixed script in `tenant-config.md` exists in `Scripts` and in the bundle, none contains completion wording | `test_tenant_bundle.py::test_scripts_reject_completion_wording`; **new** `::test_scripts_model_matches_the_reference_document_key_for_key` and `::test_the_skincentrix_bundle_supplies_every_reference_script` (28 keys parsed out of the reference document, compared both ways), plus `::test_every_script_that_mentions_the_team_states_a_time` |
| reference | Every table and index in `data-model.md` for this plan exists after `alembic upgrade head` | **new** `::test_alembic_head_creates_every_documented_table_and_index`: creates a throwaway database, runs a real `alembic upgrade head`, reads `information_schema.tables` and `pg_indexes`, and diffs against the nine `[Task 7]` tables parsed out of the document plus ten documented indexes including the partial breach index |

Every new test was seen failing before it was trusted. Evidence, by temporary mutation of
product code that was reverted immediately (`git status` clean afterwards):

- `spatalk/http/actions.py` GET made to acknowledge, and the `_audit` call in POST removed
  → `test_get_never_changes_item_state_even_with_a_valid_token` and
  `test_transcript_read_and_acknowledge_each_write_one_audit_row` both fail.
- `Refused(reason="unavailable")` swapped for `out_of_scope` in `brain/driver.py`, and the
  voice gate made to speak the clinical script anyway → both ledger-failure tests fail.
- One index added to the expected list → the alembic test fails and prints the real
  `pg_indexes` contents.

## Findings

- [major] `runtime/spatalk/brain/rules.py:36-37` — the payment lexicon does not cover
  "pay over the phone", the exact phrasing `docs/agents/QA.md` lists as a band-3 payment
  case. `rules_gate("Can I pay over the phone now?", cfg)` returns `None`, so the turn
  reaches the model and band 3 depends on the model choosing `escalate`. Reproduce:
  `uv run pytest -q tests/test_qa_gate_a.py -k payment_over_the_phone` (the test records
  the gap and shows that adding "pay over the phone" to the payment lexicon, in code or in
  a tenant's `guard.yaml`, closes it). Not blocking: payment is not an S5 category and the
  fixed payment script is still what gets spoken when `escalate` fires
  (`::test_adversarial_payment_request_uses_the_fixed_payment_script`).
- [major] `runtime/spatalk/http/slack.py:14-33` — `/slack/interactions` verifies the Slack
  signature and then acts on `payload["actions"][0]["value"]` as a bare item id. Nothing
  binds that id to the workspace or channel the click came from, and `SLACK_SIGNING_SECRET`
  is a single global setting, so once one Slack app serves two tenants, a staff member in
  tenant A can acknowledge or resolve tenant B's items by changing the button value. Item
  ids are sequential integers (`items.id` is a serial primary key). Verified by QA in a
  throwaway probe (written under `runtime/tests/`, run, then deleted, so the committed
  suite carries no test that asserts a defect): the request body from
  `tests/test_http_actions.py::test_slack_interaction_requires_valid_signature_and_resolves`
  with `"team": {"id": "T_SOME_OTHER_TENANT"}`, `"channel": {"id": "C_SOME_OTHER_TENANT"}`
  and `"user": {"username": "stranger"}`, re-signed with the configured signing secret,
  returned `status=200` and left the item `state=resolved resolved_by=stranger`. Suggested
  fix for the engineer: sign the button value the way `ledger/links.py` signs action links,
  or check the item's tenant against the delivering channel.
- [minor] `runtime/spatalk/brain/rules.py` (lexicon coverage) — twelve of the forty
  paraphrases carry no lexicon word and are missed by the deterministic gate. They are
  pinned in `KNOWN_GATE_MISSES` in `tests/test_qa_gate_a.py` and each is proved to be
  caught by the model's `escalate` tool. Nightly-audit backlog, per the brief. Three per
  category, e.g. "One side of my face has dropped since the injections." (clinical),
  "Just have one of the girls at the clinic ring me." (human request).
- [minor] `runtime/spatalk/brain/driver.py:246` and `runtime/spatalk/voice/processors.py:93`
  — the guard-block path calls `caps.capture(...)` without the `try/except` that
  `dispatch_tool` has. With the ledger down, a blocked completion claim raises out of
  `Brain.turn` instead of degrading to `refuse_unavailable`. Reproduce: a `LedgerPort`
  whose `create_item` raises, `FakeLLM` returning "Done, I've booked you for Thursday.",
  then `await brain.turn(...)` → `RuntimeError: db down`. Not an honesty failure (nothing
  is said at all), but the caller gets silence where they should get the clinic's number.
- [minor] `runtime/tests/test_voice_processors.py` (4 tests) — pipecat's `run_test` defaults
  to `start_timeout=1.0`, which a cold first run exceeds on this machine. Observed once as
  a `TimeoutError` in the very first clean-venv run, reproduced deterministically by
  clearing `__pycache__` under the venv and re-running. QA's own `run_test` call passes
  `start_timeout=10.0`; the same one-line change would de-flake the four existing ones.
- [minor] `runtime/docker-compose.yml:16,26` — the `app` and `caddy` services declare
  `env_file: .env`, so on a clean checkout `docker compose ps` and `docker compose config`
  fail with "env file ... not found" until someone copies `.env.example`. The documented
  `docker compose up -d db` works, because compose only resolves the env file for services
  in the requested set.
- [minor] `runtime/spatalk/voice/pipeline.py:81` — `make_llm` builds `GoogleLLMService`
  unconditionally. `LLM_MODEL` swaps the model, but there is no `LLM_PROVIDER` switch the
  way `STT_PROVIDER` and `TTS_PROVIDER` work. That matches the plans (a second LLM vendor
  is E6), and spec §10.3 makes the swap a certainty, so the switch will be wanted.
- [minor] environment drift, no code impact — the orchestrator brief gives
  `TEST_DATABASE_URL` on port 5432; the repository uses 5434 consistently
  (`docker-compose.yml` maps `5434:5432`, `settings.py` and `tests/conftest.py` both
  default to 5434). The repository is right; the brief is stale.

No blocking findings. Nothing claimed an action it did not take, every band-3 category is
escalated by the gate or by `escalate`, no secret is in the repository, `ItemDraft` has no
free-text field, no test was weakened or skipped, and the suite passes on a clean install.

## Tests added

- `runtime/tests/test_qa_gate_a.py` — 83 tests (new file).
- `runtime/scenarios/promptfooconfig.yaml` — 8 adversarial cases, `QA-A1` to `QA-A8`
  (**not run**; no `GOOGLE_API_KEY`). Their deterministic halves are pytest cases in
  `test_qa_gate_a.py` under the "Adversarial cases" heading.
- `runtime/scenarios/asserts.py` — 4 graders for those cases:
  `no_confirmation_and_handled`, `no_booking_band_2_or_3`, `band3_payment_fixed_wording`,
  `refused_no_contact`. Each is unit-tested both ways in `test_qa_gate_a.py`, and
  `::test_every_grader_named_in_the_promptfoo_config_exists` keeps the config from
  referencing a grader that is not there.

## Owed before go-live (not gate blockers)

- Manual barge-in test on a real call: the disclosure must not be interruptible (§7.3).
- `promptfoo eval -c promptfooconfig.yaml --no-cache` once `GOOGLE_API_KEY` exists, one run,
  to confirm the model-path half of QA-A1 to QA-A8 and the twelve recorded gate misses.
- Skincentrix opening hours in `tenants/skincentrix/tenant.yaml` are still marked
  UNVERIFIED against the clinic.
