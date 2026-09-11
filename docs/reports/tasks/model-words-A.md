# Model words, runtime record — phase A
Status: done with deviations
Commits: `b91c25d`, `99e4ae0`, `d58a2b3`, `1cd9c50`, `2698e50`, `421276c`, `c42d1ad`, `017bf74`, `f499c0f`, plus the docs commit that carries this file
Branch: `model-words`, cut from `main` at `1493297` (the plan's own commit). Not merged; not pushed.

Tests: per task below. **Full suite -> 1 failed, 1423 passed, 2 skipped in 1722.73s**, against a measured baseline of **1 failed, 1375 passed, 2 skipped** at the branch point: 48 net new cases, the same one pre-existing failure, nothing deleted, skipped or xfailed. Lint: `ruff check spatalk tests scenarios` -> All checks passed.

Interfaces produced: `spatalk.brain.guard.DEFAULT_STALL_LEXICON`, `DEFAULT_RECEIPT_LEXICON`, `STALL_BEFORE_ACTION`, `STALL_DELEGATION`, `guard(text, has_completed, cfg, replacement, *, receipts=0)`, `GuardResult(text, blocked, matched, family)`; `VoiceSession.receipts`, `VoiceSession.remember_receipt`, `VoiceSession.signals`, `VoiceSession.record_signal`, `VoiceSession.runtime_asked_this_turn`; `OutputGuardProcessor._egress`, `._retract`, `._finish_turn`; `spatalk.ops.signals.{SIGNAL_KINDS, DETAIL_KEYS, CLOSED_VALUE, MAX_SIGNALS, Signal, SignalLog, signals_for}`; `spatalk.voice.observers.TurnSignalObserver`; `spatalk.voice.frames.ToolTurnDoneFrame`; `spatalk.brain.flow.{Slots.digression, pop_digression, Missing, Readiness, readiness, Rejection, rejection_text, tool_rejection, OpenQuestion, open_question}`; `spatalk.voice.steps.open_question_text`; `spatalk.voice.handlers.MAX_REJECTIONS_PER_TURN`; `"answer_question"` in `TOOL_NAMES`, `always_tools` and `slot_tool`; `Conversation.signals`; `end_conversation(..., signals=None, ...)`; `ConversationFull.signals`.

---

## The baseline, measured

The plan's 1367 predates the narrow voice fix, so it is a floor and not a number to match. The real baseline is **1,375 passed, 2 skipped, 1 pre-existing failure**, measured on this machine from a clean `git archive 1493297` of the whole repository, run against its own scratch database:

```
cd <scratch>/base/runtime
SPATALK_NO_ENV_FILE=1 PYTHONPATH=<scratch>/base/runtime \
TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_mw_base \
<main>/runtime/.venv/Scripts/python.exe -m pytest -q -p no:randomly -p no:cacheprovider

FAILED tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick
1 failed, 1375 passed, 2 skipped, 1 warning in 1722.87s (0:28:42)
```

Two notes on how it was taken, because the first attempt was wrong and the report should say so. The first run was started against the working tree before Task 1 and finished after Task 3, so it read three tasks' worth of edits from disk while it ran and is not a baseline; it is also what caught the QA-gate failure below. The second attempt archived only `runtime/`, so 48 tests that read files outside it (`docs/`, `edge/`, `portal/`, `.github/`) failed on the missing paths. The figure above is from the third: the whole tree at `1493297`, extracted to a scratch directory, `PYTHONPATH` pointed at it.

**The QA gate caught a comment of mine, exactly as it caught V1's.** `tests/test_qa_gate_a.py::test_no_provider_is_hard_wired_into_the_brain_or_the_ledger[brain/guard.py]` failed on the first run because the comment I had written above the stall pattern named the vendor whose clause it quotes. `brain/guard.py` is a vendor-free module and the gate reads comments too. The comment now says "the chat-supervisor filler clause quoted in OSS §8.2". The fix is folded into `2698e50` (Task 5) because that is where it was found; every one of the fifteen vendor-free modules was then scanned for all six vendor names and is clean.

**The one pre-existing failure is not ours.** `tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick` starts `run_scheduler_forever` and polls `alerts.last_scheduler_tick()` for three seconds. It fails identically in the clean `1493297` baseline above, with nothing of this plan present, which is the strongest form of the proof V1 and cost-gap-C1 gave by stashing. Nothing here goes near the scheduler, the job queue or the alert module. Left alone.

## The final run

```
cd <worktree>/runtime
SPATALK_NO_ENV_FILE=1 PYTHONPATH=<worktree>/runtime \
TEST_DATABASE_URL=postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test_mw_1120 \
<main>/runtime/.venv/Scripts/python.exe -m pytest -q -p no:randomly -p no:cacheprovider

FAILED tests/test_ops_alerts.py::test_one_pass_of_the_scheduler_loop_records_a_tick
1 failed, 1423 passed, 2 skipped, 1 warning in 1722.73s (0:28:42)

ruff check spatalk tests scenarios -> All checks passed!
```

1,423 against the baseline's 1,375 is **48 net new cases** — inside the plan's predicted 45 to 55 — against 53 added `def test_` lines, the difference being the five cases that were renamed rather than added. The same one failure, in the same place. Nothing was deleted, skipped, xfailed or loosened; the fifteen moved expectations are listed under their tasks with the sentence that authorises each.

Databases: `spatalk_test_mw_1120` (every task run and the final suite), `spatalk_test_mw_base` (the baseline archive), `spatalk_test_mw_mig` (migration 0015, both ways). `spatalk`, `portal` and `spatalk_test` were never touched, nor was the main checkout, `runtime/.env`, `portal/.env.server` or the runtime on port 8000. No paid API call, no push, no merge.

---

Every per-task count below is as measured when that task landed. Later tasks add cases to the same files, so re-running a task's set today gives a larger number; the suite as it stands is the figure above.

## Task 1 — the guard's two new lexicon families

`b91c25d`. Tests: `tests/test_guard.py` -> 11 passed (6 existing byte-identical, 5 new); with its neighbours `tests/test_guard.py tests/test_renderer.py tests/test_structural_honesty.py tests/test_driver.py tests/test_voice_processors.py` -> 60 passed, 2 skipped. Seen failing first: three on `TypeError: guard() got an unexpected keyword argument 'receipts'`, one on the stall family.

Two deviations, both forced by the plan's own Step 1 tests.

1. **A bare `i'?m` is not a stall marker.** The plan's `_STALL_MARKER` includes it, and with it `scripts.human_request` ("I'm sending a request to the team right now") and `scripts.complaint` ("I'm flagging it to the team as urgent") match `i'?m` + `sending`/`flagging`… — and a stall is blocked *even with a receipt*, so those two outcome scripts could never reach a caller again. The plan's own `test_the_receipt_lexicon_leaves_the_tenants_own_outcome_scripts_alone_once_an_item_exists` asserts both pass with `receipts=1`. Every one of the plan's six blocked examples still matches through `let me`, `i'?ll`, `i'?m going to` or the `one moment|hold on … while i` branch, so nothing was given up. A present progressive with a gerund is a *claim*, which the receipt lexicon judges and a receipt can release; a stall is a claim with a delay in front of it, which nothing can release.
2. **A delegation inside the matched span is not a stall** (`STALL_DELEGATION`). `scripts.link_captured` is "I'll have the team send you the booking link for {service}", and `I'll` + 15 characters + `send` is inside the plan's 24-character span. The plan's own test requires that sentence to pass. The actor there is the team, so the sentence is an offer; `_stall()` walks the matches and skips any whose span names the team, the clinic, someone, somebody, them or a member.

Deviation recorded from the memo itself: §3.3 says an utterance asserting an outcome "must name an item id the ledger issued this conversation". Read as *backed by*, not *literally spoken* — the caller never hears an item id. The mechanism is the receipt register of Task 2. And a stall stays blocked with a receipt and with `has_completed`, because "let me book that" is never true on this system.

## Task 2 — one egress to the wire, and the receipt register

`99e4ae0`. Tests: `tests/test_structural_honesty.py tests/test_voice_processors.py tests/test_voice_handlers.py tests/test_driver.py` -> 55 passed, 2 skipped; the wider voice and text set (`…test_guard test_renderer test_voice_steps test_voice_echo test_voice_filler test_voice_transfer test_driver_flow test_text_service test_text_scenarios test_tier_c`) -> 168 passed, 2 skipped. Seen failing first: `assert methods == ['_egress']` on `['_emit', '_speak', 'process_frame']`, `'VoiceSession' object has no attribute 'receipts'`, the paraphrased claim going out unretracted, and the same-turn restatement being retracted.

Tests added: `test_only_the_egress_function_can_speak_on_a_call`, `test_no_model_utterance_reaches_a_channel_without_the_guard` (structural honesty); `test_a_paraphrased_outcome_claim_is_retracted_when_nothing_was_filed`, `test_the_replacement_sentence_is_not_guarded_again`, `test_a_stall_that_implies_an_outcome_never_reaches_the_wire`, `test_a_fixed_script_from_upstream_goes_out_with_its_receipt_and_is_held_without_one` (voice processors); `test_the_receipt_is_recorded_before_the_outcome_is_spoken` (voice handlers); `test_a_text_reply_that_claims_a_filing_with_nothing_filed_is_retracted` and `test_a_reply_that_restates_the_filing_this_turn_made_is_not_retracted` (driver).

Deviations:

1. **`_retract` takes the frame kind of the sentence it is retracting** — `_retract(sentence, g, *, model_words, append_to_context=True)` rather than the plan's `_retract(sentence, g)`. The plan says the replacement should take "the same frame the blocked sentence would have taken" and then hard-codes `model_words=True`, which is only right on the model's path. Its own Step 1 test pushes a `TTSSpeakFrame` with no receipt and asserts the retraction comes back as a `TTSSpeakFrame`. Private method, no other task consumes it.
2. **The held question is released before the current sentence is guarded**, where the old `_emit` guarded first and dropped the held one on a block. The guard moved inside `_egress`, and the structural test allows exactly one `guard()` call site in the voice package. The consequence is narrow and not a honesty problem: on a turn where the model asks a question and then makes a false claim, the caller hears the question (which passed the guard on its own merits) and then the retraction, instead of the retraction alone.
3. **A `Refused` from the ledger earns no receipt and no claim.** `caps.capture` can return `Refused` rather than raise, and the plan's `_retract` reads `out.item_id` unconditionally. The item id is read with `getattr`; with none, the caller hears `refuse_unavailable` and the clinic's number. The existing dead-ledger test still passes through the same branch.
4. **The text driver's receipt count is this turn's, not the conversation's** — the plan's own deliberate deviation, recorded here as it asked. A text reply that restates a filing made on an *earlier* turn is retracted and files a second item. Not seen; the model is told "say nothing about the result"; the alternative is threading a conversation-wide count from `text/service.py`, a change to a second driver for a hazard nobody has hit. Phase B changes both drivers together. The same-turn case is now covered by a new test and is no longer retracted.
5. **`test_the_receipt_is_recorded_before_the_outcome_is_spoken` uses `test_voice_handlers.py`'s own `_world` helper** rather than the `_session`/`_Params`/`_LLM` trio the plan's snippet imports from `test_voice_steps.py`, so the file stays self-consistent.

## Task 3 — rung zero

`d58a2b3`. Tests: `tests/test_ops_signals.py` (new, 4 cases) + `tests/test_voice_processors.py` + `tests/test_structural_honesty.py` + `tests/test_voice_turns.py` + `tests/test_smoke_imports.py` -> 75 passed. Seen failing first: `ModuleNotFoundError: No module named 'spatalk.ops.signals'` (proved by moving the module aside and re-running: 5 failed), then `'VoiceSession' object has no attribute 'signals'` and `cannot import name 'TurnSignalObserver'`.

Tests added: the four in `tests/test_ops_signals.py`, `test_the_signal_log_is_a_second_place_free_text_cannot_reach` (structural honesty), `test_a_caller_who_repeats_himself_is_recorded` and `test_the_turn_analysers_verdict_is_recorded_and_so_is_its_absence` (voice processors).

Deviations:

1. **The caller-repeat comparison is `fuzz.partial_ratio`, not `fuzz.ratio`, floored at three words.** The plan's own test case scores 76.06 on the plain ratio — measured: `fuzz.ratio("can you book me that facial", "can you book me that facial, the mesojet one") == 76.06`, `partial_ratio == 100.0` — so at the plan's `CALLER_REPEAT = 0.80` the signal would never fire and the test could not pass. A caller who repeats himself usually adds to it, which is what `partial_ratio` measures. The floor of three words (`CALLER_REPEAT_MIN_WORDS`, the same floor the barge-in gate uses) stops a one-word answer matching every longer sentence that follows it.
2. **`Slots` is imported under `TYPE_CHECKING`** in `spatalk/ops/signals.py`, so the module stays a leaf: `signals_for` only reads attributes.
3. **`scenarios/voice/eval_bot.py` does not register `TurnSignalObserver`.** The plan says to register it in `pipeline.py` and puts simulations out of scope, and no test compares the two observer lists. Phase E's job.

## Task 4 — `answer_question`

`1cd9c50`. Tests: `tests/test_flow_apply.py tests/test_flow_order.py tests/test_flow_tools.py tests/test_flow_draft.py tests/test_tools_prompt.py tests/test_voice_steps.py tests/test_voice_handlers.py tests/test_structural_honesty.py tests/test_driver_flow.py tests/test_text_service.py tests/test_prompt_budget.py` -> 107 passed. Seen failing first: `'Slots' object has no attribute 'digression'`, `ValueError: answer_question` from `slot_tool`, and the QA tool-set list.

Tests added: `test_answer_question_writes_nothing_and_pushes_one_frame`, `test_the_frame_pops_when_the_record_is_still_at_the_same_step_and_is_dropped_when_it_moved`, `test_the_tool_is_offered_at_every_step_and_carries_no_argument` (flow apply); `test_a_side_question_hands_the_turn_over_and_says_nothing` (voice steps). Moved: `test_the_qa_tool_set_is_start_request_and_the_always_tools` gains `answer_question`; the free-text check under it is untouched and covers the new tool for nothing, because it has no arguments.

Deviations:

1. **The digression brief sits ahead of the step's own briefs**, not immediately before the general case. The plan's placement would have left a caller's side question at the OFFERS, PHONE-same, TEAM_NOTE and service-kind steps with a brief that never mentions it. Answering the caller is the turn's job; the step's disambiguation note is not. QA and COMPLETE keep their own briefs, which is where a digression description does not exist.
2. **The missing-datum descriptions land here as `_MISSING`** rather than as a private helper the plan says to delete in Task 6, because Task 5's `readiness()` is built over the same table. The SERVICE description is the string both tasks needed to agree on: "which treatment they want, from the SERVICES list above".
3. `_apply` refuses a second `answer_question` while one is open with a bare `ignored=True` in this commit; Task 5 replaces it with the `already_yours` rejection, as the plan says.

Prompt budget after the declaration: 21,935 characters, 5,928 estimated tokens, inside the band `5_000 < tokens < 6_500`.

## Task 5 — readable rejections

`2698e50`. Tests: `tests/test_flow_rejections.py` (new, 7 cases) + `tests/test_flow_apply.py tests/test_voice_steps.py tests/test_voice_handlers.py` -> 48 passed; neighbours (`test_flow_order test_flow_tools test_flow_draft test_voice_processors test_driver test_driver_flow test_lead_context_verification test_resolve test_real_model_findings test_qa_gate_a`) -> 198 passed, 2 skipped. Seen failing first: 12 cases, on `cannot import name 'tool_rejection'` and on the flat-string rejection.

Moved expectations, each strengthened, none removed:

| file | old name | now |
|---|---|---|
| `test_voice_steps.py` | `test_a_tool_the_step_did_not_offer_is_ignored_and_the_model_answers` | `…_is_refused_in_words_the_model_can_read`: every assertion of the old case (nothing written, nothing filed, nothing spoken, the turn handed back) plus the rejection's own words, repeated to the ceiling, plus the `tool_rejected` count |
| `test_voice_handlers.py` | `test_an_ignored_tool_hands_the_turn_back_to_the_model` | `…_is_refused_in_words_that_name_what_is_missing`: asserts the missing datum, the tool that takes it and the legal calls are in the payload |
| `test_voice_handlers.py` | `test_a_question_shaped_answer_hands_the_turn_back_with_a_reason` | extended with `"which treatment" in rejection`; nothing removed |
| `test_voice_handlers.py` | `test_a_tool_result_does_not_repeat_the_question_just_asked` | survives; the loop runs to the new ceiling |
| `test_flow_apply.py` | `test_a_question_shaped_answer_is_refused_with_a_reason` | reads the rejection through `rejection_text` and pins `reason`/`detail` as well |
| `test_flow_apply.py` | `test_change_answer_for_a_slot_that_holds_nothing_is_ignored` | extended with `reason="bad_value"`, `detail="empty_slot"` |

Authorising sentences: the plan's Task 5 preamble ("This task is an upgrade, not an introduction … `Applied.rejection` changes type … the handler's call site and the payload key `\"rejection\"` do not move") and its Verification table, which names each of these six.

Deviations:

1. **`ANSWER_THE_QUESTION` is deleted rather than kept unread.** The plan says to keep it; nothing outside `flow.py` referenced it (`grep -rn ANSWER_THE_QUESTION tests/ spatalk/ scenarios/` -> only `flow.py`), and an unread constant is dead code. Its five sentences live on in `_DETAIL_TEXT` and `rejection_text`, and the comment explaining why this wording is code and not `scripts.yaml` moved with them. The narrow fix's own assertions still find the word "question" in the refusal, because `_DETAIL_TEXT["question_shaped"]` is "what you passed was a question, not an answer".
2. **`_reject` does not take `step`.** `readiness()` derives it from the record, so the parameter would have been unused. Private helper.
3. **`readiness().tools` is built with the transfer off.** The function cannot know whether the clinic is staffed right now, and naming a tool that would ring an empty room is worse than under-naming one the model already holds in its own list. `_tool_allowed` still uses `transfer_enabled=True`, so a transfer is never refused as un-offered.
4. **Two fixtures in the plan's own test file were corrected.** `test_filing_before_the_slots_are_filled_is_premature_not_merely_un_offered` asserts `missing.datum == "name"` but its `Slots(flow="callback", returning_client=True)` opens at PRACTITIONER, because `callback` is in `BOOKING_LIKE`. The record now carries a practitioner and a treatment so the name really is what it is waiting on; the assertion is the plan's.
5. `resolve.is_question` was **not touched**. Its two call sites in `_apply` swapped `ANSWER_THE_QUESTION[...]` for `_reject(..., detail="question_shaped")`, and the refused `answer` value for `detail="not_a_choice"`. `tests/test_resolve.py` is untouched.
6. **The retry counter is retired as a strategy and kept as a ceiling** (`MAX_REJECTIONS_PER_TURN = 3`), against the scope's "replacing … the retry counter as a loop guard": every handed-back turn is a model call, and an unbounded loop spends the call while the caller hears nothing. `VoiceSession.ignored_tools` keeps its name and its reset site.
7. **A3's `Rejection` is produced for both channels but delivered only on voice.** `run_tool` logs the refusal's own words on text; a text turn is one completion with no tool-result round trip, so the model is not told. Phase B's driver change carries it.

## Task 6 — the model words the question

`421276c`. Tests: `tests/test_flow_brief.py` (new, 6 cases) + `test_flow_apply test_flow_order test_flow_tools test_flow_draft test_flow_rejections test_voice_steps test_voice_processors test_voice_handlers test_voice_turns test_prompt_budget test_prompt_booking_flow test_tools_prompt test_driver test_driver_flow test_text_scenarios test_structural_honesty test_guard test_renderer` -> 203 passed, 2 skipped. Seen failing first: `cannot import name 'open_question'` and the moved cases on the old behaviour.

**The cost line the amendment asked for: no second model run.** `run_llm` is `False` on every branch a slot tool can take, and `tests/test_voice_steps.py::test_a_slot_tool_never_triggers_a_second_model_run` walks `answer`, `choose_service`, `give_name` and `choose_practitioner` and asserts it. The one `run_llm=True` left in phase A is the rejection path and the `answer_question` path, both once per caller turn and both inherited from the narrow fix; the side question's `run_llm=True` *replaces* the one the first refused tool of a turn would have spent. So the plan's cost table collapses to its first row — **CA$0.0355 a call minute, 64.3% margin at the CA$0.0994 price** — and the perceived gap stays at V1's 1.31 s median. There is no `+0.0028` re-run row and no extra model round trip on a slot-filling turn.

How that was made to work, and the deviation it required. The amendment asks for the model's question from the tool-calling reply to be spoken *after* the runtime's fixed lines. Pipecat gives neither half of the turn a way to wait for the other: `pipecat/services/google/llm.py` calls `run_function_calls(function_calls)` and then pushes `LLMFullResponseEndFrame` in its `finally`, and `LLMService._run_sequential_function_calls` only puts the calls on a queue for a background task, so the end frame reaches the guard before the handler has run and the handler's own frames reach it afterwards. The trailing sentence of a completion, meanwhile, is only emitted at the end frame, so the handler can never see the model's question. **A new frame closes the gap**: `spatalk/voice/frames.py` defines `ToolTurnDoneFrame(handed_back: bool)`, the handler pushes exactly one, last, in a `finally`, and `OutputGuardProcessor._finish_turn` decides the question once it holds both halves. A handler that raises still releases the turn. This is machinery the plan did not name, and it is the price of the amendment's ordering guarantee.

What `_finish_turn` decides, in one place: the digression frame is popped if the model spoke; a turn handed back gets no question from the runtime at all; a `Pending` means the wording is law and the model's guess is dropped (the handler has already spoken the confirmation); otherwise the model's held question carries the turn; and a reply that asked nothing gets `next_question()`, subject to the never-twice-on-an-unchanged-record rule and its `repeat` signal. The runtime's own question is still pushed *after* the end frame, exactly as before, so the assistant aggregator keeps adding it as an utterance of its own; only the model's released words go out inside the completion.

Deviations:

1. **The amendment's slot-level check on the model's question is not implemented.** It asks the brief to name "the slot that follows" the open one and the runtime to compare the model's question against it. That slot is not single-valued: `next_step` branches at RETURNING on yes and no (returning clients are asked who, new clients are offered the offers), so the brief cannot name one and there is nothing to compare against. Any remaining check would be wording analysis, which the amendment explicitly says this is not. What is checked instead is act-level and well defined: a plain question must be open on the record, and the runtime must not have asked one already. A question about the wrong slot therefore reaches the caller; the caller answers it; the slot tool for it is not offered at that step, so it is refused in words and the model asks the right one — one extra model call on that turn, from the path the amendment allows, and `tool_rejected` counts it. Phase B's candidates-not-verdicts is where slot-level verification belongs.
2. **`VoiceSession.reran_this_turn` is not added.** The plan produces it to cap one re-run per caller turn; the amendment forbids the re-run, so there is nothing to cap. `runtime_asked_this_turn` takes its place and answers a different question — which of the two speakers asked.
3. **`test_flow_draft.py::test_step_message_names_what_is_known_and_the_tool_to_use`'s brevity budget moves from five sentences to six.** That is what a readiness report costs: what is known, what is still needed with its choices, the tool, the same-reply rule, the change path, the side-question path and the honesty rule. The tail was tightened once to keep it at six. `tests/test_prompt_budget.py` keeps the money honest and still passes inside its band.
4. **Three of the plan's own Task 6 cases were rewritten for the amendment, not for convenience.** `test_a_slot_tool_speaks_the_next_question_and_never_reruns_the_llm` became `test_a_slot_tool_says_nothing_and_never_reruns_the_llm` — the plan's replacement asserts `run_llm is True` and a `model_rerun` signal, which the amendment forbids; `test_a_tool_turn_never_lets_the_models_question_out` became `test_a_tool_turn_waits_for_the_handler_and_then_lets_the_models_question_out`, because the amendment's whole point is that it does go out; and `test_a_tool_the_step_does_offer_still_speaks_the_next_question` became `…_speaks_the_outcome_and_the_confirmation_only`, which is the plan's own description of it. No `model_rerun` signal is ever recorded, and the kind stays in `SIGNAL_KINDS` for phase B.
5. **`test_no_question_is_repeated_when_a_tool_ran_this_turn` now passes for a new reason**: it sends a tool frame and no done frame, so the turn is never decided and nothing is spoken. That is the real behaviour of a handler that never reported, which the `finally` makes unreachable in production. It is kept as-is and named here so nobody reads it as the tool-turn contract; `test_a_tool_turn_with_no_question_from_the_model_gets_the_step_script` is that contract.
6. **`_STEP_EXTRA` carries the anti-autocorrect rule** for the NAME and PHONE steps, keyed on the `step` argument. `step_message` now reads `_missing(step, …)` with its own argument rather than `readiness()`'s recomputed step, so a brief asked for a step is a brief for that step.

Surviving unchanged and run: `test_a_question_in_the_middle_of_an_answer_is_still_spoken`, `test_a_question_is_the_models_own_outside_a_flow`, `test_a_turn_that_is_only_a_question_is_not_left_silent`, `test_a_fragment_is_not_a_turn_and_its_words_are_kept`, `test_a_silent_model_turn_gets_the_question_unless_it_was_just_asked`, `test_the_step_question_comes_back_once_the_record_moves`, and all five of `tests/test_prompt_budget.py` including the byte-identical-prefix property.

## Task 7 — the signals reach the record and `/internal`

`c42d1ad`. Tests: `tests/test_conversations.py tests/test_internal_api.py tests/test_contract_snapshot.py tests/test_ops_retention.py tests/test_call_notes.py tests/test_voice_turns.py` -> 106 passed.

The code landed before the tests here, which is a departure from test-first and is recorded as such. The failure they would have produced is not in doubt and was verified against the branch point: `git show 1493297:runtime/spatalk/conversations.py` has no `signals` parameter on `end_conversation`, so every one of the three new cases fails with `TypeError`.

Tests added: `test_the_calls_signals_are_stored_with_it` (conversations), `test_the_conversation_endpoint_carries_the_signals` (internal API, which also pins that the list view does *not* carry them). Extended: the retention case now seeds `signals` and asserts it survives while `latency_ms`, `stage_ms` and `flow` are nulled.

Migration `0015_call_signals`, exercised both ways on `spatalk_test_mw_mig`:

```
alembic upgrade head     INFO Running upgrade 0014 -> 0015, call signals: the rung-0 trouble log on conversations
information_schema       signals | jsonb | YES
alembic downgrade -1     INFO Running downgrade 0015 -> 0014
information_schema       signals_columns = 0
alembic upgrade head     INFO Running upgrade 0014 -> 0015
information_schema       signals | jsonb | YES
alembic check            No new upgrade operations detected.
```

**Deviation recorded as the plan asked: `conversations.signals` survives the transcript purge**, unlike `latency_ms`, `stage_ms` and `flow`. It holds no caller data — `spatalk.ops.signals` refuses any value that could be a word somebody said, and a structural test keeps that true — and a trouble threshold cannot be set from thirty days of calls. The nulling line in `retention.py` carries that note.

Both snapshots are the generator's output, not hand-written: `spatalk openapi --internal --out ../docs/contracts/runtime-internal.openapi.json` (14 added lines, the `ConversationFull.signals` property and its required entry) and the repo's own `npx openapi-typescript@7.13.0` step for `portal/src/runtime/client.ts` (4 added lines, `signals: { [key: string]: unknown } | null`). **The portal was not run.** No `wasp`, no `npm test`, no `npm run e2e`: the orchestrator runs those.

## The one fix commit

`f499c0f`. `transfer_to_human` was the only tool handler that did not push a `ToolTurnDoneFrame`, so on the branch where the carrier refuses — the caller still on the line, a callback filed — the guard would have waited for a signal that never came and asked nothing until the "still there?" nudge. It now pushes it in a `finally` like every other tool. The same commit corrects `tests/test_voice_transfer.py`, which carried the QA tool list Task 4 widened and two assertions that compared every frame the handler pushed; the list gains `answer_question` and the frames are filtered by kind. Task 4's run did not include that file, which is how it was missed — recorded rather than folded away.

## Task 8 — reference docs

`017bf74`. `flows.md` §10 step 3 rewritten, step 4 extended, steps 7 and 8 added; `data-model.md` gains the `signals` column row and a retention row; `roadmap.md` records phase A as built and what phases B to E inherit. `tenant-config.md` and `api-surface.md` need no edit — phase A adds no `scripts.yaml` key, changes no wording and adds no environment variable, which is also why `tests/test_qa_gate_a.py`'s key-for-key comparison needed none.

## The promptfoo suite was read, not run

It needs `GOOGLE_API_KEY` and a paid Gemini call per case; the standing rule is one run per QA gate and that is the orchestrator's. Nothing in it is structurally stale. The case the plan flagged — an expectation that the runtime speaks its step question after a tool call — still holds, because `scenarios/provider.py` drives `Brain.turn` and A4 is voice-only: the text driver still appends the step question and still applies `drop_trailing_question`, so all twenty `asks_script` cases keep their contract.

One *behavioural* risk to watch on the paid run, which is not a stale expectation: `answer_question` is now offered on text too, so a model that reaches for it where a slot tool was expected will leave the slot empty and the expected script will be the same step's, not the next one's. If a case fails that way the refusal path is what to read, not the assertion.

## Notes for neighbours

- `Applied.rejection` is a `Rejection`, not a string. `tool_refusal` still returns `tuple[bool, str | None]` and `run_tool` still returns five values; `tests/test_lead_context_verification.py` unpacks them and is untouched.
- `VoiceSession` gained `receipts`, `signals`, `runtime_asked_this_turn` and the methods `remember_receipt` and `record_signal`. Anything constructing one gets the defaults.
- `spatalk/voice/frames.py` is new and holds one frame. Anything that builds a voice pipeline of its own must let `ToolTurnDoneFrame` reach `OutputGuardProcessor`, or a tool turn's question is never decided.
- `next_question` keeps its signature and is now the fallback only; `open_question_text` is the pair to reach for when the caller needs to know whose wording it is.
- `spatalk.ops.signals` is a leaf: it imports nothing at runtime from `spatalk.brain`.
- `end_conversation` gained a keyword-only-by-convention `signals` parameter before `call_notes`; both in-repo callers pass by keyword.

## What the founder's call test must confirm

The plan's four calls, with what phase A changed under each. Read `signals.counts` on every conversation afterwards (`GET /internal/conversations/<id>`) — this is the first release where the call reports on itself.

1. **A side question mid-step.** Start a booking, answer "no" to having been in before, then at the treatment question ask *"what was the facial one again?"* — the 01:40 call's exact shape. Expect an answer from the facts naming at most three treatments with prices, and then the treatment question again **in the model's own wording**. Expect *not* the words being filed as a treatment choice, and no "Did you mean Free virtual consultation?". Ask a second side question straight after ("does it hurt?") and check the same thing. In the record: `digression` >= 2, `repeat` = 0, `tool_rejected` = 0. A non-zero `repeat` means the fallback fired and the model went silent — say which turn.
2. **A mis-heard name.** At the name question say "Peyman" plainly. The call must **stay on the booking**: not a payment refusal, no hang-up. The stored name **may still be wrong** — STT confidence is phase B and V1's open item 2 is still open. Check the filed item's contact name in the portal and report what it holds. `caller_repeat` tells you whether you had to repeat yourself.
3. **A premature file attempt.** Say, early and firmly, *"just book me in, that's all you need"*. Expect no item filed, nothing claimed, and the assistant asking for what is actually missing in its own words; the words "sent", "filed", "passed on" and "booked" must not appear until the outcome script does. Then check the portal: **zero items** from that stretch. In the record: `tool_rejected` >= 1 with `reason` `premature` or `not_offered`. If it is 0 the model never tried and the test proved nothing.
4. **A paraphrased outcome claim.** A listening test across all four calls: any sentence of the shape *"I've passed that to the team"*, *"I've sent that over"*, *"let me book that in"* or *"one moment while I get that done"* **before** the runtime's own outcome line. Expect never. If one is attempted the caller hears `cannot_complete` and **an item exists** for it — check the portal. `guard_block` is the count and `family` names which lexicon fired; `guard_block > 0` with a matching item is the system working. If it never happens, the evidence is `tests/test_voice_processors.py::test_a_paraphrased_outcome_claim_is_retracted_when_nothing_was_filed` and `::test_a_stall_that_implies_an_outcome_never_reaches_the_wire` — say so rather than claiming the calls proved it.

Two things phase A changed that are worth listening for specifically, beyond the plan's list:

5. **Exactly one question a turn, on a turn that filled a slot.** This is the release's sharpest new behaviour and the one the plan could not test end to end: the model asks the next question in the same reply that calls the tool, and the runtime speaks its own script only if that reply asked nothing. Two questions in one breath is the V1 regression returning — name the turn. A question about a slot the record is not waiting on is the known limit of deviation 1 above; it should self-correct within one turn through a refusal, and `tool_rejected` will show it.
6. **A step where the runtime still owns the words.** When the resolver is unsure it reads the value back verbatim ("Did you mean Helen?") and the model's own question is dropped. Check the caller never hears both.

And, as numbers rather than adjectives: **the gap before the first word** (`latency_ms` on the conversation, against V1's 1.31 s median — phase A buys no second model round trip, so it should not move); **`turn_prediction` against `turn_no_prediction`**, the first real data on how often the 1.5 s silence fallback fires, and nobody touches `TURN_END_FALLBACK_SECS` until it exists; and the honest limit — LIT §6.4 needs more than 30 listeners for a stable naturalness verdict, and 10 to 30 paired calls can only detect a near-total preference. Four calls can tell the founder that phase A is not catastrophically worse and that the 01:40 failure is gone. They cannot tell him it sounds more human, and this report does not say they did.
